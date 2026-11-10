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

VERSION = "18"
# v18: entry hanya diumumkan setelah konfirmasi M1. REQUIRE_M1=0 mengembalikan notifikasi "sinyal baru" lama;
# SETUP_ALERT=1 tetap mengirim peringatan setup saat candle TF tutup (sebelum M1).
REQUIRE_M1 = os.getenv("REQUIRE_M1", "1").strip() != "0"
SETUP_ALERT = os.getenv("SETUP_ALERT", "0").strip() == "1"
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
        sig["tracking"] = signals.track(df, tf=tf, symbol=sym)
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


def _was_notified(sym, tf, t):
    """Entry sudah dikabarkan (peringatan setup lama `sig:` atau ENTRY SIAP `cfm:`)."""
    return notify.seen(f"sig:{sym}:{tf}:{t}") or notify.seen(f"cfm:{sym}:{tf}:{t}")


EXIT_FRESH_MIN = 30            # menit: sinyal yang berakhir lebih lama dari ini tidak dikabarkan lagi


def maybe_notify_exit(sym, tf, sig, click=None):
    """Notifikasi KELUAR (v15), hanya untuk sinyal yang dulu dikirim lewat notifikasi:
    - sinyal berakhir: berbalik arah, SL, TP3, atau kedaluwarsa;
    - sinyal masih aktif tetapi skor indikator sudah netral/berlawanan (MELEMAH)."""
    tr = sig.get("tracking") or {}
    if sig.get("market_closed") or not tr:
        return
    off = 0.0 if sig.get("broker_native") else notify.offset(sym)
    click = click or app_url()
    a = tr.get("active")
    limit = max(3 * tf_minutes(tf), EXIT_FRESH_MIN) * 60
    t_now = pd.Timestamp.now(tz="UTC")
    for r in tr.get("recent") or []:
        if r.get("outcome") not in notify.EXIT_REASON or not r.get("end_time"):
            continue
        if (t_now - pd.Timestamp(r["end_time"])).total_seconds() > limit:
            continue                                   # sudah lama berakhir: jangan kirim kabar basi
        if not _was_notified(sym, tf, r["time"]):
            continue                                   # sinyal ini dulu tidak dikabarkan: tidak perlu KELUAR
        new_dir = a["direction"] if (r["outcome"] == "REVERSED" and a) else None
        renewed = (r["outcome"] == "EXPIRED" and a and a["direction"] == r["direction"]
                   and pd.Timestamp(a["time"]) >= pd.Timestamp(r["end_time"]) - pd.Timedelta(minutes=tf_minutes(tf)))
        if renewed:                                    # kedaluwarsa tapi langsung terbit sinyal baru searah
            title, msg = notify.renew_message(sig["label"], tf, r, a, off)
            tag = "arrows_counterclockwise"
        else:
            title, msg = notify.exit_message(sig["label"], tf, r, new_dir, off)
            tag = {"TP3": "money_with_wings", "SL": "x"}.get(r["outcome"], "door")
        res = notify.deliver(f"exit:{sym}:{tf}:{r['time']}", title, msg, 4, [tag], click)
        if res is not None:
            _sent_log.append({"jenis": "keluar_" + r["outcome"].lower(), "target": f"{sym}:{tf}", "hasil": res})
    if a and sig.get("score") is not None:
        sg = 1 if a["direction"] == "BUY" else -1
        if sg * sig["score"] <= 0 and _was_notified(sym, tf, a["time"]):
            price = sig.get("live_price") or sig["price"]
            title, msg = notify.weak_message(sig["label"], tf, a, sig["score"], sig["max_score"], price, off)
            res = notify.deliver(f"weak:{sym}:{tf}:{a['time']}", title, msg, 4, ["warning"], click)
            if res is not None:
                _sent_log.append({"jenis": "melemah", "target": f"{sym}:{tf}", "hasil": res})


def maybe_notify_signal(sym, tf, sig, click=None):
    """Notifikasi sinyal baru: sekali per sinyal, hanya bila masih segar dan pasar buka.
    Juga memeriksa notifikasi KELUAR / MELEMAH untuk sinyal sebelumnya."""
    try:
        maybe_notify_exit(sym, tf, sig, click)
    except Exception:  # noqa: BLE001  - kabar keluar tidak boleh menggagalkan sinyal baru
        pass
    if REQUIRE_M1 and not SETUP_ALERT:
        return None                                    # v18: entry baru diumumkan setelah M1 terkonfirmasi (cron/MT5)
    a = sig["tracking"]["active"] if sig.get("tracking") else None
    if not a or sig.get("market_closed") or a["age_hours"] * 60 > max(3 * tf_minutes(tf), 15):
        return None
    off = 0.0 if sig.get("broker_native") else notify.offset(sym)       # harga MT5 sudah harga broker
    title, msg = notify.signal_message(sig["label"], tf, a, off)
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
    native = mt5_signal(sym, tf)
    if native:
        s = {"signal": native["signal"], "summary": native.get("summary"), "updated_at": native.get("updated_at"),
             "error": None, "last_attempt": native.get("updated_at")}
        s.update(notify={"channels": notify.channels(), "last_cron": last_cron(),
                         "shared": bool(notify._redis()), "offset": notify.offset_record(sym)},
                 symbol=sym, tf=tf, update_seconds=60, next_update=None, now=now().isoformat(), mt5=True)
        return jsonify(s)
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
    native = mt5_signal(sym, tf)
    if native:
        a = native["signal"]["tracking"]["active"] if native["signal"].get("tracking") else None
        if not a:
            return jsonify(confirm=None, symbol=sym, tf=tf)
        c = mt5_confirm_get(sym, tf)
        if not c or c.get("signal_time") != a["time"]:
            c = {"state": "NODATA", "message": "Menunggu kiriman M1 berikutnya dari MT5 (paling lama 1 menit)."}
        return jsonify(confirm=c, symbol=sym, tf=tf, signal_time=a["time"])
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
                                 pd.Timestamp(a["time_close"]), now=pd.Timestamp.now(tz="UTC"),
                                 symbol=sym, tf=tf)
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
    feed = c["df"].attrs.get("data_time")                                # jam transaksi terakhir di sumber (Yahoo)
    ref = min(pd.Timestamp(feed), t_now) if feed is not None else min(last["time"] + pd.Timedelta(minutes=1), t_now)
    fetched = (now() - c["at"]).total_seconds() if c["at"] else 0.0       # umur cache server
    age = max(0.0, (t_now - ref).total_seconds())
    closed, _ = signals.split_closed(c["df"], t_now, 1)                 # candle M1 terakhir yang sudah tutup penuh
    cl = closed.iloc[-1] if len(closed) else None
    try:
        boff = float(os.getenv("BROKER_UTC_OFFSET", "2"))               # jam server broker MT5 (musim dingin biasanya UTC+2)
    except ValueError:
        boff = 2.0
    return jsonify(price=round(float(last["close"]), 2), time=last["time"].isoformat(),
                   price_time=ref.isoformat(), source=c["source"], age_seconds=round(age + fetched),
                   closed_price=None if cl is None else round(float(cl["close"]), 2),
                   closed_time=None if cl is None else cl["time"].isoformat(),
                   broker_utc_offset=boff, error=c["error"])


def news_inputs(focus, manual=None):
    """Forecast/Previous/Actual untuk berita fokus. Urutan: input manual > kalender Forex Factory > kosong."""
    cfg = news.SURPRISE_CFG.get(focus["type"])
    out = {"supported": bool(cfg), "metric": cfg["metric"] if cfg else None,
           "forecast": None, "previous": None, "actual": None, "source": None, "feed_error": None}
    if not cfg:
        return out
    near = -8 * 24 * 60 <= focus["minutes"] <= 24 * 60            # feed hanya memuat pekan berjalan
    try:
        fv = news.feed_values(focus) if near else None
    except Exception:  # noqa: BLE001
        fv = None
    if fv:
        out.update(metric=fv["title"], forecast=fv["forecast"], previous=fv["previous"], actual=fv["actual"],
                   source="Forex Factory (otomatis)")
    elif near:
        st = news.feed_status()
        out["feed_error"] = None if st["ok"] else (st["error"] or "kalender Forex Factory belum terbaca")
    for k in ("forecast", "previous", "actual"):
        v = (manual or {}).get(k)
        if v:
            out[k] = v
            out["source"] = "input manual" if not fv else "Forex Factory + input manual"
    return out


def news_view(ev_id=None, now=None, manual=None):
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
    usable_h1 = bool(h1) and not h1.get("market_closed")
    ctx = h1["direction"] if usable_h1 else None
    h1_score = h1["score"] if usable_h1 else None
    # Angka berita: Forecast/Previous dari kalender Forex Factory (bila terbaca), lalu ditimpa input manual.
    inputs = news_inputs(focus, manual)
    sur = news.surprise(typ, inputs["forecast"], inputs["previous"], inputs["actual"])
    out_focus = {**focus, "study": summ, "progress": prog, "live_price": live, "ctx_h1": ctx,
                 "h1_label": None if not h1 else f"{h1['direction']} (skor {h1['score']:+d})",
                 "inputs": inputs, "surprise": sur}
    if focus["status"] == "PRA":
        pre = m5[(m5["time"] >= t0 - pd.Timedelta(minutes=60)) & (m5["time"] < t0)] if m5 is not None else None
        hi = None if pre is None or len(pre) < 6 else float(pre["high"].max())
        lo = None if pre is None or len(pre) < 6 else float(pre["low"].min())
        out_focus["signal"] = news.pre_signal(summ, ctx, live, hi, lo, h1_score=h1_score, sur=sur)
    elif focus["status"] in ("RILIS", "PASCA"):
        bar = None if m5 is None else m5[m5["time"] == t0]
        if bar is None or len(bar) == 0 or live is None:
            out_focus["signal"] = {"kind": "PASCA", "direction": "WAIT", "factors": [],
                                   "reasons": ["Candle M5 saat rilis belum tersedia di sumber data."]}
        else:
            out_focus["signal"] = news.post_signal(summ, float(bar["open"].iloc[0]), live, focus["minutes"], sur=sur)
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
        manual = {k: (request.args.get(q) or "").strip()[:12] for k, q in (("forecast", "f"), ("previous", "p"), ("actual", "a"))}
        return jsonify(news_view(request.args.get("id"), manual=manual))
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


def compute_confirm(sym, tf, a):
    c = get_m1(sym)
    if c["df"] is None:
        return None
    return signals.confirm_m1(c["df"], a["direction"], a["levels"], pd.Timestamp(a["time_close"]),
                              now=pd.Timestamp.now(tz="UTC"), symbol=sym, tf=tf)


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
    live_mt5 = mt5_alive_map(force=True)
    for sym, tf in parse_targets(os.getenv("NOTIFY_TARGETS")):
        if sym in live_mt5:
            status.append({"target": f"{sym}:{tf}", "mt5": True,
                           "note": "data langsung dari MT5: sinyal & notifikasi diurus /api/mt5"})
            continue
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
            c = compute_confirm(sym, tf, a)
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
    if time.time() - _cron_seen.get("w", 0) > 300:          # terbaca juga oleh instance lain; hemat kuota Redis
        notify.kv_set("last_cron", ts.isoformat())
        _cron_seen["w"] = time.time()
    return {"ran": ts.isoformat(), "channels": notify.channels(), "targets": [f"{s}:{t}" for s, t in parse_targets(os.getenv("NOTIFY_TARGETS"))],
            "refreshed": refreshed, "sent": sent, "notes": notes, "status": status,
            "credits_today": data.credits_used(), "credit_cap": data.credit_cap()}


_cron_seen = {"at": None, "v": None, "w": 0}


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


# ------------------------------------------------------------------ MT5 (EA)
MT5_FRESH = 180               # detik: kiriman EA lebih tua dari ini = MT5 dianggap mati, kembali ke sumber lama
_mt5 = {"alive": {}, "alive_read": 0.0, "sig": {}, "cfm": {}, "cfm_state": {}}


def mt5_alive_map(force=False):
    """{simbol: waktu kiriman terakhir} untuk simbol yang MT5-nya masih mengirim data."""
    t = time.time()
    if force or t - _mt5["alive_read"] > 30:
        raw_v = notify.kv_get("mt5:alive")
        if raw_v:
            try:
                for k, v in json.loads(raw_v).items():
                    _mt5["alive"][k] = max(float(v), _mt5["alive"].get(k, 0))
            except (ValueError, TypeError, AttributeError):
                pass
        _mt5["alive_read"] = t
    return {k: v for k, v in _mt5["alive"].items() if t - v < MT5_FRESH}


def _mt5_frame(rows, data_time=None):
    df = pd.DataFrame([r[:5] for r in rows], columns=["time", "open", "high", "low", "close"])
    df["time"] = pd.to_datetime(df["time"].astype("int64"), unit="s", utc=True)
    for c in ("open", "high", "low", "close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna().drop_duplicates("time").sort_values("time").reset_index(drop=True)
    if data_time is not None:
        df.attrs["data_time"] = data_time
    return df


def _fresh_native(rec, tf):
    if not rec or not rec.get("signal"):
        return None
    ct = pd.Timestamp(rec["signal"]["candle_time"])
    return rec if pd.Timestamp.now(tz="UTC") - ct <= pd.Timedelta(minutes=3 * tf_minutes(tf) + 5) else None


def mt5_signal(sym, tf):
    """Sinyal yang dihitung dari candle MT5 (harga broker), atau None bila MT5 tidak aktif."""
    if sym not in mt5_alive_map():
        return None
    rec = _mt5["sig"].get((sym, tf))
    if rec and time.time() - rec.get("_read", 0) < 20:
        return _fresh_native(rec, tf)
    raw_v = notify.kv_get(f"mt5sig:{sym}:{tf}")
    if raw_v:
        try:
            got = json.loads(raw_v)
            if not rec or got.get("updated_at", "") >= rec.get("updated_at", ""):
                rec = got
        except ValueError:
            pass
    if rec:
        rec["_read"] = time.time()
        _mt5["sig"][(sym, tf)] = rec
    return _fresh_native(rec, tf)


def mt5_confirm_get(sym, tf):
    c = _mt5["cfm"].get((sym, tf))
    if c and time.time() - c.get("_read", 0) < 20:
        return c
    raw_v = notify.kv_get(f"mt5cfm:{sym}:{tf}")
    if raw_v:
        try:
            c = json.loads(raw_v)
            c["_read"] = time.time()
            _mt5["cfm"][(sym, tf)] = c
        except ValueError:
            pass
    return c


def _jsonable(x):
    return json.loads(json.dumps(x, default=str))


@app.post("/api/mt5")
def api_mt5():
    """Diterima dari EA di MT5 (PC atau VPS). Sinyal dan notifikasi dihitung dari harga broker."""
    secret = os.getenv("CRON_SECRET", "").strip()
    j = request.get_json(silent=True, force=True) or {}
    if not secret:
        return jsonify(ok=False, error="CRON_SECRET belum diisi di Vercel"), 403
    if not hmac.compare_digest(str(j.get("key") or "").encode(), secret.encode()):
        return jsonify(ok=False, error="kunci salah (isi input Kunci di EA dengan CRON_SECRET)"), 403
    try:
        return jsonify(mt5_ingest(j))
    except Exception as e:  # noqa: BLE001
        return jsonify(ok=False, error=data.scrub(f"{type(e).__name__}: {e}")), 500


def mt5_ingest(j):
    t_now = time.time()
    sent = float(j.get("sent") or t_now)
    if abs(sent - t_now) > 600:
        sent = t_now                                   # jam PC/VPS ngaco: pakai jam server
    feed_time = pd.Timestamp(sent, unit="s", tz="UTC")
    out = {"ok": True, "computed": [], "sent": [], "notes": []}
    m1s, alive, fresh = {}, {}, {}
    for sym_in, blk in (j.get("symbols") or {}).items():
        sym = str(sym_in).upper()
        if sym not in SYMS or not isinstance(blk, dict):
            out["notes"].append(f"{sym_in}: simbol tidak dikenal (pakai XAUUSD atau NASDAQ)")
            continue
        broker = str(blk.get("broker") or sym)[:40]
        tfs = blk.get("tf") or {}
        if not tfs:
            continue
        alive[sym] = sent
        if tfs.get("M1"):
            m1 = _mt5_frame(tfs["M1"], feed_time)
            if len(m1):
                m1s[sym] = m1
        for tf in TFS:
            rows = tfs.get(tf)
            if not rows:
                continue
            df = _mt5_frame(rows, feed_time)
            if len(df) < 130:
                out["notes"].append(f"{sym} {tf}: candle hanya {len(df)}, butuh minimal 130 (naikkan JumlahBar di EA)")
                continue
            sig = signals.analyze(df, f"MT5 {broker}", symbol=sym, label=data.SYMBOLS[sym]["label"], tf=tf)
            sig["tracking"] = signals.track(df, tf=tf, symbol=sym)
            sig.update(broker_native=True, broker_symbol=broker)
            sig = _jsonable(sig)
            rec = {"signal": sig, "summary": signals.summary_text(sig), "updated_at": now().isoformat()}
            with lock:
                states[(sym, tf)].update(signal=sig, summary=rec["summary"], error=None,
                                         updated_at=rec["updated_at"], last_attempt=rec["updated_at"])
            raw[(sym, tf)] = df.tail(400)
            _mt5["sig"][(sym, tf)] = {**rec, "_read": time.time()}
            notify.kv_set(f"mt5sig:{sym}:{tf}", json.dumps(rec), ttl=6 * 3600)
            fresh[(sym, tf)] = rec
            act = (sig.get("tracking") or {}).get("active")
            out["computed"].append(f"{sym}:{tf} " + (f"{act['direction']} aktif" if act else sig["direction"]))
    if alive:
        _mt5["alive"].update(alive)
        merged = {k: v for k, v in _mt5["alive"].items() if t_now - v < MT5_FRESH}
        notify.kv_set("mt5:alive", json.dumps(merged), ttl=MT5_FRESH)
    # notifikasi & konfirmasi M1 untuk target yang simbolnya dikirim EA
    targets = [(s, t) for s, t in parse_targets(os.getenv("NOTIFY_TARGETS")) if s in alive]
    need = [(s, t) for s, t in targets if (s, t) not in fresh and not _fresh_native(_mt5["sig"].get((s, t)), t)]
    for (s, t), raw_v in zip(need, notify.kv_mget([f"mt5sig:{s}:{t}" for s, t in need])):
        if raw_v:
            try:
                _mt5["sig"][(s, t)] = {**json.loads(raw_v), "_read": time.time()}
            except ValueError:
                pass
    _drain()
    for sym, tf in targets:
        rec = fresh.get((sym, tf)) or _fresh_native(_mt5["sig"].get((sym, tf)), tf)
        if not rec:
            continue
        sig = rec["signal"]
        maybe_notify_signal(sym, tf, sig, app_url())
        out["sent"].extend(_drain())
        a = sig["tracking"]["active"] if sig.get("tracking") else None
        if not a or sig.get("market_closed") or sym not in m1s:
            continue
        ck = f"cfm:{sym}:{tf}:{a['time']}"
        c = signals.confirm_m1(m1s[sym], a["direction"], a["levels"], pd.Timestamp(a["time_close"]), now=feed_time,
                               symbol=sym, tf=tf)
        c = _jsonable({**c, "source": f"MT5 {sig.get('broker_symbol', sym)}", "signal_time": a["time"]})
        st_key = (c.get("state"), c.get("m1_time"))
        if _mt5["cfm_state"].get((sym, tf)) != st_key:
            _mt5["cfm_state"][(sym, tf)] = st_key
            _mt5["cfm"][(sym, tf)] = {**c, "_read": time.time()}
            notify.kv_set(f"mt5cfm:{sym}:{tf}", json.dumps(c), ttl=6 * 3600)
        if c.get("state") == "CONFIRMED" and not notify.seen(ck):
            title, msg = notify.confirm_message(sig["label"], tf, a, c, 0.0)
            r = notify.deliver(ck, title, msg, 5, ["white_check_mark"], app_url())
            if r is not None:
                out["sent"].append({"jenis": "konfirmasi_m1", "target": f"{sym}:{tf}", "hasil": r})
    out["alive"] = sorted(alive)
    return out


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


@app.get("/api/risk")
def api_risk():
    """Profil risiko aktif per instrumen (SL/TP dinamis, batas mengejar, batas waktu entry, ukuran lot)."""
    return jsonify(version=VERSION, require_m1=REQUIRE_M1, setup_alert=SETUP_ALERT,
                   profiles={s: signals.public_profile(s) for s in SYMS})


@app.get("/healthz")
def healthz():
    return jsonify(ok=True, version=VERSION, has_signal={f"{s}/{t}": states[(s, t)]["signal"] is not None
                                        for s in SYMS for t in TFS})


@app.get("/")
def index():
    return Response(page.HTML, mimetype="text/html")


def internal_cron_loop():
    """Opsional untuk VPS (INTERNAL_CRON=1): menjalankan cron_run tiap menit tanpa crontab luar."""
    while True:
        try:
            cron_run(click=app_url())
        except Exception:  # noqa: BLE001  - loop tidak boleh mati
            pass
        time.sleep(60)


def start_background():
    threading.Thread(target=loop, daemon=True, name="updater").start()
    if os.getenv("INTERNAL_CRON", "").strip() == "1":
        threading.Thread(target=internal_cron_loop, daemon=True, name="cron").start()


if __name__ == "__main__":
    start_background()
    app.run(host="0.0.0.0", port=PORT, threaded=True)
