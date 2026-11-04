"""Aplikasi sinyal untuk XAUUSD dan NASDAQ: timeframe M5, M15, M30, H1 + konfirmasi M1.

Dua mode, kode sama:
- Server biasa:  python app.py  -> thread latar belakang memperbarui H1 tiap UPDATE_MINUTES
- Serverless (Vercel): data dihitung saat halaman meminta, dengan cache per timeframe
"""
import hmac
import json
import math
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests
from flask import Flask, Response, jsonify, request

import data
import news
import notify
import page
import signals

UPDATE_MINUTES = max(int(os.getenv("UPDATE_MINUTES", "15")), 1)   # khusus H1
PORT = int(os.getenv("PORT", "8000"))
SYMS = list(data.SYMBOLS)
TFS = data.SIGNAL_TFS

app = Flask(__name__, static_folder=None)
lock = threading.Lock()
busy = {(s, t): threading.Lock() for s in SYMS for t in TFS}
narrative_cache = {}
raw = {}            # (instrumen, tf) -> candle terbaru (untuk modul news)


def new_state():
    return {"signal": None, "summary": None, "updated_at": None,
            "error": None, "last_attempt": None}


states = {(s, t): new_state() for s in SYMS for t in TFS}
m1 = {s: {"df": None, "source": None, "at": None, "error": None} for s in SYMS}
m1_busy = {s: threading.Lock() for s in SYMS}


def now():
    return datetime.now(timezone.utc)


def ttl_seconds(tf):
    return UPDATE_MINUTES * 60 if tf == "H1" else data.TF[tf]["ttl"]


def claude_narrative(sig):
    """Opsional: Claude menulis ulang angka yang SUDAH dihitung. Gagal -> None."""
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return None
    ck = (sig["symbol"], sig["timeframe"], sig["candle_time"], sig["direction"])
    if ck in narrative_cache:
        return narrative_cache[ck]
    facts = json.dumps({k: sig[k] for k in
                        ("label", "timeframe", "direction", "score", "confidence", "price",
                         "indicators", "levels", "reasons", "warnings", "market_closed")},
                       ensure_ascii=False)
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5"),
                  "max_tokens": 400,
                  "system": ("Kamu menulis ringkasan teknikal dalam Bahasa Indonesia, "
                             "3-4 kalimat. Pakai HANYA angka pada data yang diberikan. "
                             "Dilarang menambah angka, berita, atau prediksi baru. "
                             "Jangan menjanjikan profit."),
                  "messages": [{"role": "user", "content": facts}]},
            timeout=40)
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json()["content"]).strip()
        narrative_cache[ck] = text or None
        return narrative_cache[ck]
    except Exception:  # noqa: BLE001
        return None


def refresh(sym, tf):
    """Satu siklus untuk satu instrumen dan timeframe."""
    if not busy[(sym, tf)].acquire(blocking=False):
        return  # siklus lain sedang berjalan
    try:
        _refresh(sym, tf)
    finally:
        busy[(sym, tf)].release()


def _refresh(sym, tf):
    st = states[(sym, tf)]
    with lock:
        st["last_attempt"] = now().isoformat()
    try:
        df, source, note = data.get_candles(sym, tf)
        sig = signals.analyze(df, source, symbol=sym, label=data.SYMBOLS[sym]["label"],
                              note=note, tf=tf)
        sig["tracking"] = signals.track(df, tf=tf)
        raw[(sym, tf)] = df.tail(400)
    except Exception as e:  # noqa: BLE001
        with lock:
            st["error"] = data.scrub(f"{type(e).__name__}: {e}")
        return
    summary = claude_narrative(sig) or signals.summary_text(sig)
    with lock:
        prev = st["signal"]
        st.update(signal=sig, summary=summary, error=None, updated_at=now().isoformat())
    maybe_notify_signal(sym, tf, sig)


def tf_minutes(tf):
    return data.TF[tf]["minutes"]


_sent_log = []                 # notifikasi yang terkirim sejak putaran cron terakhir (untuk ringkasan)
_app_url = {"v": ""}


@app.before_request
def _remember_host():
    if not _app_url["v"] and request.host_url:
        _app_url["v"] = request.host_url.rstrip("/")


def app_url():
    return (os.getenv("APP_URL", "").strip() or _app_url["v"]).rstrip("/") or None


def _drain():
    out = list(_sent_log)
    _sent_log.clear()
    return out


def maybe_notify_signal(sym, tf, sig, click=None):
    """Notifikasi sinyal baru: sekali per sinyal, hanya bila masih segar dan pasar buka."""
    a = sig["tracking"]["active"] if sig.get("tracking") else None
    if not a or sig.get("market_closed") or a["age_hours"] * 60 > max(3 * tf_minutes(tf), 15):
        return None
    title, msg = notify.signal_message(sig["label"], tf, a, notify.offset(sym))
    tag = "chart_with_upwards_trend" if a["direction"] == "BUY" else "chart_with_downwards_trend"
    r = notify.deliver(f"sig:{sym}:{tf}:{a['time']}", title, msg, 4, [tag], click or app_url())
    if r is not None:
        _sent_log.append({"jenis": "sinyal", "target": f"{sym}:{tf}", "hasil": r})
    return r


def ensure_fresh(sym, tf):
    """Hitung ulang hanya bila data lebih tua dari TTL (galat dicoba lagi 1 menit)."""
    with lock:
        la, err = states[(sym, tf)]["last_attempt"], states[(sym, tf)]["error"]
    gap = timedelta(seconds=60 if err else ttl_seconds(tf))
    if la is None or now() - datetime.fromisoformat(la) > gap:
        refresh(sym, tf)


def get_m1(sym):
    """Candle M1 untuk konfirmasi; diambil ulang paling cepat tiap TTL M1."""
    c = m1[sym]
    ttl = timedelta(seconds=data.TF["M1"]["ttl"])
    if (c["at"] is None or now() - c["at"] > ttl) and m1_busy[sym].acquire(blocking=False):
        try:
            df, src, _ = data.get_candles(sym, "M1")
            c.update(df=df, source=src, at=now(), error=None)
        except Exception as e:  # noqa: BLE001
            c.update(at=now(), error=data.scrub(f"{type(e).__name__}: {e}"))
        finally:
            m1_busy[sym].release()
    return c


def loop():
    while True:
        for sym in SYMS:
            try:
                refresh(sym, "H1")
            except Exception as e:  # noqa: BLE001  - loop tidak boleh mati
                with lock:
                    states[(sym, "H1")]["error"] = f"Loop: {e}"
        time.sleep(UPDATE_MINUTES * 60)


def pick():
    sym = (request.args.get("symbol") or SYMS[0]).upper()
    tf = (request.args.get("tf") or "H1").upper()
    return (sym, tf) if sym in SYMS and tf in TFS else (None, None)


@app.get("/api/signal")
def api_signal():
    sym, tf = pick()
    if sym is None:
        return jsonify(error="Instrumen atau timeframe tidak dikenal",
                       symbols=SYMS, timeframes=TFS), 404
    if request.args.get("force") == "1":
        with lock:
            la = states[(sym, tf)]["last_attempt"]
        if la is None or (now() - datetime.fromisoformat(la)).total_seconds() > 45:
            refresh(sym, tf)
    else:
        ensure_fresh(sym, tf)
    with lock:
        s = dict(states[(sym, tf)])
    nxt = None
    if s["last_attempt"]:
        nxt = (datetime.fromisoformat(s["last_attempt"])
               + timedelta(seconds=ttl_seconds(tf))).isoformat()
    s.update(notify={"channels": notify.channels(), "last_cron": last_cron(),
                     "shared": bool(notify._redis()), "offset": notify.offset_record(sym)},
             symbol=sym, tf=tf, update_seconds=ttl_seconds(tf), next_update=nxt,
             now=now().isoformat())
    return jsonify(s)


@app.post("/api/offset")
def api_offset():
    """Simpan penyesuaian harga dari dasbor supaya notifikasi ntfy memakai angka yang sama."""
    j = request.get_json(silent=True) or {}
    sym = str(j.get("symbol") or "").upper()
    if sym not in SYMS:
        return jsonify(saved=False, error="Instrumen tidak dikenal"), 404
    v, t = j.get("v"), j.get("t") or time.time() * 1000
    try:
        t = int(float(t))
        if v is not None:
            v = float(v)
            if not math.isfinite(v):
                raise ValueError
    except (TypeError, ValueError):
        return jsonify(saved=False, error="Angka tidak valid"), 400
    if v is not None:
        with lock:
            ref = next((st["signal"]["price"] for (s, _), st in states.items()
                        if s == sym and st["signal"] and st["signal"].get("price")), None)
        if abs(v) > (0.03 * ref if ref else 3000):
            return jsonify(saved=False, error="Selisih terlalu besar (lebih dari 3%)"), 400
    ok = notify.set_offset(sym, v, t)
    return jsonify(saved=ok, shared=bool(notify._redis()), offset=notify.offset_record(sym))


@app.get("/api/confirm")
def api_confirm():
    """Konfirmasi M1 untuk sinyal aktif. Dipisah agar halaman utama tidak menunggu data M1."""
    sym, tf = pick()
    if sym is None:
        return jsonify(error="Instrumen atau timeframe tidak dikenal"), 404
    with lock:
        sig = states[(sym, tf)]["signal"]
    a = sig["tracking"]["active"] if sig and sig.get("tracking") else None
    if not a:
        return jsonify(confirm=None, symbol=sym, tf=tf)
    c = get_m1(sym)
    if c["df"] is None:
        return jsonify(confirm={"state": "ERROR",
                                "message": "Data M1 belum bisa diambil: " + (c["error"] or "belum ada data")},
                       symbol=sym, tf=tf, signal_time=a["time"])
    try:
        out = signals.confirm_m1(c["df"], a["direction"], a["levels"],
                                 pd.Timestamp(a["time_close"]), now=pd.Timestamp.now(tz="UTC"))
    except Exception as e:  # noqa: BLE001
        out = {"state": "ERROR", "message": f"{type(e).__name__}: {e}"}
    out["source"] = c["source"]
    if c["error"]:
        out["warning"] = "Pembaruan M1 terakhir gagal: " + c["error"]
    return jsonify(confirm=out, symbol=sym, tf=tf, signal_time=a["time"])


@app.get("/api/quote")
def api_quote():
    """Harga M1 terbaru, dipakai untuk menyelaraskan harga dengan broker/TradingView."""
    sym = (request.args.get("symbol") or SYMS[0]).upper()
    if sym not in SYMS:
        return jsonify(price=None, message="Instrumen tidak dikenal"), 404
    c = get_m1(sym)
    if c["df"] is None:
        return jsonify(price=None, message="Data M1 belum bisa diambil: " + (c["error"] or "belum ada data"))
    last = c["df"].iloc[-1]
    t_now = pd.Timestamp.now(tz="UTC")
    lag = max(0.0, (t_now - last["time"]).total_seconds() - 60)          # keterlambatan penyedia data
    fetched = (now() - c["at"]).total_seconds() if c["at"] else 0.0       # umur cache server
    return jsonify(price=round(float(last["close"]), 2), time=last["time"].isoformat(),
                   source=c["source"], age_seconds=round(lag + fetched), error=c["error"])


def news_view(ev_id=None, now=None):
    """Susun data halaman NEWS: daftar berita, studi riwayat jenis berita terpilih, dan sinyal."""
    ts = now or pd.Timestamp.now(tz="UTC")
    extra = news.parse_extra(os.getenv("EXTRA_EVENTS", ""))
    evs = news.build_events(ts.to_pydatetime(), extra)
    focus = next((e for e in evs if e["id"] == ev_id), None) or news.pick_focus(evs)
    ensure_fresh("XAUUSD", "M5")
    ensure_fresh("XAUUSD", "H1")
    m5 = raw.get(("XAUUSD", "M5"))
    h1 = states[("XAUUSD", "H1")]["signal"]
    typ = focus["type"]
    dates = news.past_dates(typ, ts.to_pydatetime())
    fam = news.TYPES[typ]["family"]
    per_min = 60 if os.getenv("OANDA_TOKEN", "").strip() else int(os.getenv("NEWS_CALLS_PER_MIN", "7"))
    prog = news.ensure_windows(fam, dates, lambda a, b: data.get_range("XAUUSD", "M5", a, b), per_minute=per_min)
    if prog.get("error"):
        prog["error"] = data.scrub(prog["error"])
    summ = news.study(typ, dates)
    t0 = pd.Timestamp(focus["t0"])
    live = None if m5 is None else float(m5["close"].iloc[-1])
    ctx = h1["direction"] if h1 and not h1.get("market_closed") else None
    out_focus = {**focus, "study": summ, "progress": prog, "live_price": live, "ctx_h1": ctx,
                 "h1_label": None if not h1 else f"{h1['direction']} (skor {h1['score']:+d})"}
    if focus["status"] == "PRA":
        pre = m5[(m5["time"] >= t0 - pd.Timedelta(minutes=60)) & (m5["time"] < t0)] if m5 is not None else None
        hi = None if pre is None or len(pre) < 6 else float(pre["high"].max())
        lo = None if pre is None or len(pre) < 6 else float(pre["low"].min())
        out_focus["signal"] = news.pre_signal(summ, ctx, live, hi, lo)
    elif focus["status"] in ("RILIS", "PASCA"):
        bar = None if m5 is None else m5[m5["time"] == t0]
        if bar is None or len(bar) == 0:
            out_focus["signal"] = {"kind": "PASCA", "direction": "WAIT", "reasons": ["Candle M5 saat rilis belum tersedia di sumber data."]}
        else:
            out_focus["signal"] = news.post_signal(summ, float(bar["open"].iloc[0]), live, focus["minutes"])
    else:
        out_focus["signal"] = {"kind": "SELESAI", "direction": "WAIT", "reasons": ["Berita ini sudah selesai. Pilih berita berikutnya."]}
    shown = [e for e in evs if e["status"] != "SELESAI"][:6] + [e for e in evs if e["status"] == "SELESAI"][-2:]
    shown.sort(key=lambda e: e["t0"])
    return {"now": ts.isoformat(), "events": shown, "focus": out_focus,
            "source": None if m5 is None else (states[("XAUUSD", "M5")]["signal"] or {}).get("source"),
            "error": states[("XAUUSD", "M5")]["error"]}


@app.get("/api/news/events")
def api_news_events():
    ts = pd.Timestamp.now(tz="UTC")
    extra = news.parse_extra(os.getenv("EXTRA_EVENTS", ""))
    return jsonify(now=ts.isoformat(), events=news.build_events(ts.to_pydatetime(), extra))


@app.get("/api/news")
def api_news():
    try:
        return jsonify(news_view(request.args.get("id")))
    except Exception as e:  # noqa: BLE001
        return jsonify(error=data.scrub(f"{type(e).__name__}: {e}")), 500


_last_cron = {"at": None}


_tries = {}                    # (sym, tf) -> (batas candle, jumlah percobaan ambil data)
NEW_CANDLE_DELAY = 8           # detik menunggu penyedia data memuat candle yang baru tertutup
NEW_CANDLE_RETRY = 30          # detik antar percobaan ulang
NEW_CANDLE_MAX_TRIES = 6       # percobaan cepat per batas candle
NEW_CANDLE_SLOW = 90           # setelah itu tetap dicoba, tapi tiap 90 detik (dulu: berhenti total)


def new_candle_due(sym, tf, ts, now_dt):
    """True bila sudah ada candle tertutup baru yang belum terambil. Selaras dengan batas candle,
    jadi sinyal terdeteksi beberapa detik setelah candle tutup (bukan menunggu jeda tetap)."""
    st = states[(sym, tf)]
    sig, la = st["signal"], st["last_attempt"]
    if sig is None or la is None:
        return True
    have = sig.get("candle_time")
    if not have:
        return False
    m = tf_minutes(tf)
    boundary = ts.floor(f"{m}min")
    if pd.Timestamp(have) >= boundary - pd.Timedelta(minutes=m):
        return False                                   # candle tertutup terakhir sudah terambil
    if (ts - boundary).total_seconds() < NEW_CANDLE_DELAY:
        return False
    if (now_dt - datetime.fromisoformat(la)).total_seconds() < NEW_CANDLE_RETRY:
        return False
    b, n = _tries.get((sym, tf), (None, 0))
    n = n + 1 if b == boundary.isoformat() else 1
    if n > NEW_CANDLE_MAX_TRIES and (now_dt - datetime.fromisoformat(la)).total_seconds() < NEW_CANDLE_SLOW:
        return False                                   # penyedia data telat: coba lagi lebih jarang, jangan menyerah
    _tries[(sym, tf)] = (boundary.isoformat(), n)
    return True


def parse_targets(raw):
    out = []
    for part in (raw or "XAUUSD:M15,NASDAQ:M15").split(","):
        s, _, t = part.strip().upper().partition(":")
        if s in SYMS and t in TFS and (s, t) not in out:
            out.append((s, t))
    return out


def compute_confirm(sym, a):
    c = get_m1(sym)
    if c["df"] is None:
        return None
    return signals.confirm_m1(c["df"], a["direction"], a["levels"], pd.Timestamp(a["time_close"]),
                              now=pd.Timestamp.now(tz="UTC"))


def cron_run(ts=None, click=None):
    """Satu putaran pemeriksaan (dipanggil tiap menit oleh penjadwal luar). Idempotent."""
    ts = ts or pd.Timestamp.now(tz="UTC")
    if not notify.channels():
        return {"error": "Belum ada kanal notifikasi. Isi NTFY_TOPIC (atau token Telegram) di Vercel."}
    _drain()
    sent, notes, refreshed, status = [], [], [], []
    if data.td_over_cap():
        # Dulu: seluruh putaran cron berhenti (sinyal baru hanya muncul saat dasbor dibuka).
        # Sekarang: Twelve Data saja yang dilewati di data.get_candles, sumber cadangan tetap dipakai.
        notes.append(f"kuota Twelve Data hari ini tercapai ({data.credits_used()}/{data.credit_cap()}): memakai sumber cadangan")
    for sym, tf in parse_targets(os.getenv("NOTIFY_TARGETS")):
        st = states[(sym, tf)]
        closed = bool(st["signal"] and st["signal"].get("market_closed"))
        la = st["last_attempt"]
        age = None if la is None else (now() - datetime.fromisoformat(la)).total_seconds()
        if closed:
            due = age is None or age > 1800                      # pasar tutup: cek jarang
        elif st["error"]:
            due = age is None or age >= 60                       # galat: coba lagi tiap menit
        else:
            # normal: tepat setelah candle tutup; jaring pengaman: paling lambat 1 candle + 1 menit
            due = new_candle_due(sym, tf, ts, now()) or age is None or age > tf_minutes(tf) * 60 + 60
        if due:
            refresh(sym, tf)
            refreshed.append(f"{sym}:{tf}")
        sig = st["signal"]
        if sig:
            maybe_notify_signal(sym, tf, sig, click)
        sent.extend(_drain())
        a = sig["tracking"]["active"] if sig and sig.get("tracking") else None
        status.append({"target": f"{sym}:{tf}", "candle": sig and sig.get("candle_time"),
                       "source": sig and sig.get("source"), "market_closed": bool(sig and sig.get("market_closed")),
                       "active": a and f"{a['direction']} {a['time']} (umur {a['age_hours'] * 60:.0f} mnt)",
                       "error": st["error"]})
        if not sig:
            continue
        ck = f"cfm:{sym}:{tf}:{a['time']}" if a else None
        if a and not sig.get("market_closed") and not notify.seen(ck):
            c = compute_confirm(sym, a)
            if c and c.get("state") == "CONFIRMED":
                title, msg = notify.confirm_message(sig["label"], tf, a, c, notify.offset(sym))
                r = notify.deliver(ck, title, msg, 5, ["white_check_mark"], click)
                if r is not None:
                    sent.append({"jenis": "konfirmasi_m1", "target": f"{sym}:{tf}", "hasil": r})
    extra = news.parse_extra(os.getenv("EXTRA_EVENTS", ""))
    evs = news.build_events(ts.to_pydatetime(), extra)
    pre_min = int(os.getenv("NEWS_PRE_MIN", "30"))
    off = notify.offset("XAUUSD")
    nxt = [e for e in evs if e["status"] == "PRA"][:1]
    if nxt and -nxt[0]["minutes"] <= 36 * 60:       # hangatkan riwayat sebelum rilis
        typ = nxt[0]["type"]
        per_min = 60 if os.getenv("OANDA_TOKEN", "").strip() else int(os.getenv("NEWS_CALLS_PER_MIN", "7"))
        news.ensure_windows(news.TYPES[typ]["family"], news.past_dates(typ, ts.to_pydatetime()),
                            lambda x, y: data.get_range("XAUUSD", "M5", x, y), per_minute=per_min)
    for ev in evs:
        if ev["status"] not in ("PRA", "PASCA"):
            continue
        left = -ev["minutes"]
        if ev["status"] == "PRA" and left <= pre_min:
            k30, k5, ksig = f"nwr30:{ev['id']}", f"nwr5:{ev['id']}", f"nwp:{ev['id']}"
            stage = "5" if left <= 5 else "30"
            if notify.seen(k5 if stage == "5" else k30):
                continue
            v = news_view(ev["id"], now=ts)["focus"]
            if stage == "30" and v["progress"]["done"] < v["progress"]["total"] and left > 6:
                notes.append(f"{ev['short']}: riwayat belum lengkap ({v['progress']['done']}/{v['progress']['total']}), menunggu")
                continue
            s = v["signal"]
            directional = s["direction"] in ("BUY", "SELL")
            title, msg = notify.news_pre_message(ev, s, left, off)
            claim = k5 if stage == "5" else k30
            r = notify.deliver(claim, title, msg, 4 if directional else 3,
                               ["chart_with_upwards_trend" if directional else "bell"], click)
            if r is not None:
                if directional:
                    notify.once(ksig)
                sent.append({"jenis": f"news_pra_{stage}", "target": ev["id"], "hasil": r})
        elif ev["status"] == "PASCA":
            key = f"nwq:{ev['id']}"
            if notify.seen(key):
                continue
            v = news_view(ev["id"], now=ts)["focus"]
            s = v["signal"]
            if s.get("direction") in ("BUY", "SELL"):
                title, msg = notify.news_post_message(ev, s, off)
                r = notify.deliver(key, title, msg, 5, ["rotating_light"], click)
                if r is not None:
                    sent.append({"jenis": "news_pasca", "target": ev["id"], "hasil": r})
    _last_cron["at"] = ts.isoformat()
    notify.kv_set("last_cron", ts.isoformat())             # terbaca juga oleh instance serverless lain
    return {"ran": ts.isoformat(), "channels": notify.channels(), "targets": [f"{s}:{t}" for s, t in parse_targets(os.getenv("NOTIFY_TARGETS"))],
            "refreshed": refreshed, "sent": sent, "notes": notes, "status": status,
            "credits_today": data.credits_used(), "credit_cap": data.credit_cap()}


_cron_seen = {"at": None, "v": None}


def last_cron():
    """Waktu putaran cron terakhir. Di serverless, cron dan dasbor bisa jatuh ke instance berbeda,
    jadi baca dari Redis bila ada (disimpan 30 detik agar tidak memanggil Redis tiap permintaan)."""
    if _last_cron["at"]:
        return _last_cron["at"]
    t = time.time()
    if _cron_seen["at"] is None or t - _cron_seen["at"] > 30:
        _cron_seen.update(at=t, v=notify.kv_get("last_cron"))
    return _cron_seen["v"]


@app.get("/api/cron")
def api_cron():
    secret = os.getenv("CRON_SECRET", "").strip()
    if not secret:
        return jsonify(error="CRON_SECRET belum diisi di Vercel"), 403
    if not hmac.compare_digest((request.args.get("key") or "").encode(), secret.encode()):
        return jsonify(error="kunci salah"), 403
    click = (os.getenv("APP_URL", "").strip() or request.host_url).rstrip("/")
    try:
        if request.args.get("test"):
            res = notify.send("Tes notifikasi sinyal", "Jika pesan ini muncul di iPhone Anda, notifikasi sudah aktif.",
                              3, ["white_check_mark"], click)
            return jsonify(test=True, channels=notify.channels(), results=res)
        return jsonify(cron_run(click=click))
    except Exception as e:  # noqa: BLE001
        return jsonify(error=data.scrub(f"{type(e).__name__}: {e}")), 500


_diag_cache = {}


@app.get("/api/diag")
def api_diag():
    """Diagnosis sumber data: sumber mana yang berhasil/gagal, jumlah candle, dan umur candle terakhir."""
    sym, tf = (request.args.get("symbol") or "NASDAQ").upper(), (request.args.get("tf") or "M1").upper()
    if sym not in SYMS or tf not in data.TF:
        return jsonify(error="Instrumen atau timeframe tidak dikenal"), 404
    k = (sym, tf)
    hit = _diag_cache.get(k)
    if hit and (now() - hit[0]).total_seconds() < 60:      # cegah penyalahgunaan: maksimal 1 kali/menit
        return jsonify(symbol=sym, tf=tf, cached=True, sources=hit[1])
    rows = data.diagnose(sym, tf)
    _diag_cache[k] = (now(), rows)
    return jsonify(symbol=sym, tf=tf, cached=False, sources=rows)


@app.get("/healthz")
def healthz():
    return jsonify(ok=True, has_signal={f"{s}/{t}": states[(s, t)]["signal"] is not None
                                        for s in SYMS for t in TFS})


@app.get("/")
def index():
    return Response(page.HTML, mimetype="text/html")


def start_background():
    threading.Thread(target=loop, daemon=True, name="updater").start()


if __name__ == "__main__":
    start_background()
    app.run(host="0.0.0.0", port=PORT, threaded=True)
