"""Notifikasi sinyal dan news ke iPhone: ntfy (disarankan, tanpa daftar akun) dan/atau Telegram.

Pengaturan lewat Environment Variables di Vercel:
  NTFY_TOPIC            nama topik ntfy (acak dan panjang, anggap sebagai kata sandi)
  NTFY_SERVER           bawaan https://ntfy.sh
  NTFY_TOKEN            opsional, bila topik dilindungi
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID    alternatif/tambahan
  OFFSET_XAUUSD, OFFSET_NASDAQ            selisih harga broker minus data aplikasi (poin)
  UPSTASH_REDIS_REST_URL/TOKEN (atau KV_REST_API_URL/TOKEN)   opsional: cegah notifikasi dobel
"""
import json
import os
import time
from datetime import datetime, timedelta

import requests

TIMEOUT = 10
_mem = {}              # cadangan anti-dobel bila Redis tidak ada: key -> waktu kedaluwarsa
DAYS = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]


def _scrub(msg):
    import data
    return data.scrub(msg)


def channels():
    ch = []
    if os.getenv("NTFY_TOPIC", "").strip():
        ch.append("ntfy")
    if os.getenv("TELEGRAM_BOT_TOKEN", "").strip() and os.getenv("TELEGRAM_CHAT_ID", "").strip():
        ch.append("telegram")
    return ch


_off_cache = {}       # sym -> (waktu baca, rekaman)


def offset_record(sym):
    """Penyesuaian harga yang diatur dari dasbor (tombol Samakan), disimpan di Redis: {"v", "t"} atau None."""
    if not _redis():
        return None
    hit = _off_cache.get(sym)
    if hit and time.time() - hit[0] < 30:
        return hit[1]
    rec = None
    try:
        raw = _rcall(["GET", "sinyal:offset:" + sym])
        if raw:
            j = json.loads(raw)
            rec = {"v": None if j.get("v") is None else float(j["v"]), "t": int(j.get("t") or 0)}
    except Exception:  # noqa: BLE001
        rec = hit[1] if hit else None
    _off_cache[sym] = (time.time(), rec)
    return rec


def set_offset(sym, v, t):
    """Simpan penyesuaian dari dasbor. v=None berarti dimatikan. True bila tersimpan bersama."""
    if not _redis():
        return False
    rec = {"v": None if v is None else round(float(v), 2), "t": int(t)}
    try:
        _rcall(["SET", "sinyal:offset:" + sym, json.dumps(rec)])
    except Exception:  # noqa: BLE001
        return False
    _off_cache[sym] = (time.time(), rec)
    return True


def offset(sym):
    """Dipakai di pesan notifikasi. Utamakan nilai dari dasbor, lalu OFFSET_<SYM> di Vercel."""
    rec = offset_record(sym)
    if rec and rec["v"] is not None:
        return rec["v"]
    if rec and rec["v"] is None and rec["t"]:
        return 0.0                                  # sengaja dimatikan dari dasbor
    try:
        return float(os.getenv(f"OFFSET_{sym}", "0") or 0)
    except ValueError:
        return 0.0


# ---------------------------------------------------------------- anti-dobel
def _redis():
    url = (os.getenv("UPSTASH_REDIS_REST_URL") or os.getenv("KV_REST_API_URL") or "").strip()
    tok = (os.getenv("UPSTASH_REDIS_REST_TOKEN") or os.getenv("KV_REST_API_TOKEN") or "").strip()
    return (url, tok) if url and tok else None


def _rcall(cmd):
    url, tok = _redis()
    r = requests.post(url, headers={"Authorization": f"Bearer {tok}"}, json=cmd, timeout=TIMEOUT)
    j = r.json()
    if "result" not in j:
        raise ValueError(str(j.get("error", "respons Redis tidak dikenal")))
    return j["result"]


def seen(key):
    """Sudah pernah dikirim? (baca saja, tidak menandai)"""
    if _redis():
        try:
            return _rcall(["EXISTS", "sinyal:" + key]) == 1
        except Exception:  # noqa: BLE001
            pass
    return _mem.get(key, 0) > time.time()


def once(key, ttl=172800):
    """True hanya pada pemanggilan pertama untuk key ini (atomik di Redis bila tersedia)."""
    if _redis():
        try:
            return _rcall(["SET", "sinyal:" + key, "1", "NX", "EX", int(ttl)]) == "OK"
        except Exception:  # noqa: BLE001
            pass                                   # Redis bermasalah: jatuh ke memori
    t = time.time()
    for k in [k for k, v in _mem.items() if v <= t]:
        del _mem[k]
    if key in _mem:
        return False
    _mem[key] = t + ttl
    return True


def kv_set(key, value, ttl=172800):
    """Simpan nilai kecil bersama (mis. waktu putaran cron terakhir) agar terbaca lintas instance."""
    if _redis():
        try:
            _rcall(["SET", "sinyal:" + key, str(value), "EX", int(ttl)])
        except Exception:  # noqa: BLE001
            pass


def kv_mget(keys):
    """Baca beberapa nilai sekaligus (1 perintah Redis). Kembalikan list sepanjang keys."""
    if not keys or not _redis():
        return [None] * len(keys)
    try:
        out = _rcall(["MGET", *["sinyal:" + k for k in keys]])
        return list(out) if isinstance(out, list) else [None] * len(keys)
    except Exception:  # noqa: BLE001
        return [None] * len(keys)


def kv_get(key):
    if _redis():
        try:
            return _rcall(["GET", "sinyal:" + key])
        except Exception:  # noqa: BLE001
            return None
    return None


def forget(key):
    """Lepas tanda (dipakai bila pengiriman gagal di semua kanal, supaya dicoba lagi)."""
    _mem.pop(key, None)
    if _redis():
        try:
            _rcall(["DEL", "sinyal:" + key])
        except Exception:  # noqa: BLE001
            pass


def deliver(key, title, message, priority=3, tags=(), click=None):
    """once() + send() + coba lagi pada tick berikutnya bila semua kanal gagal. None = sudah pernah/dilewati."""
    if not channels() or not once(key):
        return None
    res = send(title, message, priority, tags, click)
    if res and not any(r["ok"] for r in res):
        forget(key)
    return res


# -------------------------------------------------------------------- kirim
_cool = {"ntfy": 0.0}      # waktu (epoch) sampai kapan ntfy sedang membatasi kita (HTTP 429)
_log = []                  # riwayat pengiriman terakhir (memori)
LOG_MAX = 20


def _log_add(title, results):
    """Catat hasil kirim (berhasil/gagal + alasan) supaya bisa dilihat di /api/notif."""
    row = {"t": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S") + " UTC", "judul": str(title)[:70],
           "hasil": [{"kanal": r["channel"], "ok": r["ok"], "galat": r.get("error")} for r in results]}
    _log.append(row)
    del _log[:-LOG_MAX]
    if _redis():
        try:
            _rcall(["SET", "sinyal:sendlog", json.dumps(_log[-LOG_MAX:]), "EX", 7 * 86400])
        except Exception:  # noqa: BLE001
            pass


def recent_log():
    """Riwayat pengiriman terakhir. Bila memori kosong (instance serverless baru), baca dari Redis."""
    if _log:
        return list(_log)
    if _redis():
        try:
            raw = _rcall(["GET", "sinyal:sendlog"])
            return json.loads(raw) if raw else []
        except Exception:  # noqa: BLE001
            return []
    return []


def _ntfy_send(title, message, priority, tags, click):
    """Kirim ke ntfy. Galat dilaporkan lengkap (kode HTTP + isi respons), 429/5xx dicoba ulang sekali."""
    if time.time() < _cool["ntfy"]:
        return {"channel": "ntfy", "ok": False,
                "error": f"ntfy membatasi pengiriman (HTTP 429), dicoba lagi {int(_cool['ntfy'] - time.time())} dtk lagi"}
    topic = os.getenv("NTFY_TOPIC", "").strip()
    server = (os.getenv("NTFY_SERVER", "") or "https://ntfy.sh").strip().rstrip("/")
    body = {"topic": topic, "title": title, "message": message, "priority": int(priority), "tags": list(tags)}
    if click:
        body["click"] = click
    headers = {"Content-Type": "application/json"}
    auth = None
    if os.getenv("NTFY_TOKEN", "").strip():
        headers["Authorization"] = "Bearer " + os.getenv("NTFY_TOKEN").strip()
    elif os.getenv("NTFY_USER", "").strip():
        auth = (os.getenv("NTFY_USER").strip(), os.getenv("NTFY_PASS", ""))
    last = None
    for attempt in (1, 2):
        try:
            r = requests.post(server, json=body, headers=headers, auth=auth, timeout=TIMEOUT)
        except Exception as e:  # noqa: BLE001
            last = {"channel": "ntfy", "ok": False, "error": _scrub(f"{type(e).__name__}: {e}")[:160]}
        else:
            if r.status_code == 200:
                return {"channel": "ntfy", "ok": True, "error": None}
            detail = ""
            try:
                detail = (r.json().get("error") or "")[:100]
            except Exception:  # noqa: BLE001
                detail = (r.text or "")[:100]
            last = {"channel": "ntfy", "ok": False, "error": _scrub(f"HTTP {r.status_code} {detail}".strip())}
            if r.status_code == 429:
                try:
                    wait = int(float(r.headers.get("Retry-After", "") or 60))
                except ValueError:
                    wait = 60
                _cool["ntfy"] = time.time() + min(max(wait, 10), 300)
                return last                                    # jangan menghajar server saat dibatasi
            if r.status_code not in (500, 502, 503, 504):
                return last                                    # 401/403/404 dst: bukan masalah sementara
        if attempt == 1:
            time.sleep(1.5)
    return last


def send(title, message, priority=3, tags=(), click=None):
    """Kirim ke semua kanal yang aktif. Kembalikan hasil per kanal (galat sudah disamarkan)."""
    out = []
    if os.getenv("NTFY_TOPIC", "").strip():
        out.append(_ntfy_send(title, message, priority, tags, click))
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN", "").strip(), os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if tok and chat:
        try:
            r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                              json={"chat_id": chat, "text": f"{title}\n{message}",
                                    "disable_web_page_preview": True}, timeout=TIMEOUT)
            out.append({"channel": "telegram", "ok": r.status_code == 200,
                        "error": None if r.status_code == 200 else f"HTTP {r.status_code}"})
        except Exception as e:  # noqa: BLE001
            out.append({"channel": "telegram", "ok": False, "error": _scrub(e)})
    try:
        _log_add(title, out)
    except Exception:  # noqa: BLE001  - pencatatan tidak boleh menggagalkan notifikasi
        pass
    return out


# ------------------------------------------------------------------- pesan
def fp(x, off=0.0):
    return f"{x + off:,.2f}"


def hm(iso):
    return f"{(datetime.fromisoformat(iso) + timedelta(hours=7)):%H:%M} WIB"


def wib(iso):
    t = datetime.fromisoformat(iso) + timedelta(hours=7)
    return f"{DAYS[t.weekday()]} {t.day} {MONTHS[t.month - 1]} {t:%H:%M} WIB"


def signal_message(label, tf, a, off=0.0, sniper=False, until=None):
    """Sinyal baru. sniper=True (REQUIRE_M1=0): tanpa menunggu konfirmasi M1; until = batas waktu entry (ISO UTC)."""
    lv = a["levels"]
    tps = " | ".join(f"TP{i + 1} {fp(x, off)}" for i, x in enumerate(lv["tp"]))
    if not sniper:
        return (f"{label} {tf} · {a['direction']}",
                f"Sinyal baru (keyakinan {a['confidence']}%) · candle {tf} ditutup {hm(a['time_close'])}\n"
                f"Entry {fp(lv['entry'], off)} | SL {fp(lv['stop_loss'], off)}\n{tps}\n"
                "Tunggu konfirmasi M1 sebelum masuk. Bukan saran investasi.")
    order = "BUY" if a["direction"] == "BUY" else "SELL"
    valid = f"\nBerlaku sampai {hm(until)}; lewat itu lewati setup ini." if until else ""
    return (f"{label} {tf} · {order} SNIPER",
            f"SNIPER (tanpa menunggu M1) · candle {tf} ditutup {hm(a['time_close'])}\n"
            f"Entry {fp(lv['entry'], off)} (limit di harga ini, atau market bila harga masih dekat) | SL {fp(lv['stop_loss'], off)}\n{tps}"
            f"{valid}\nBatal bila harga menyentuh SL. Jangan mengejar harga yang sudah menjauh. Bukan saran investasi.")


def confirm_message(label, tf, a, c, off=0.0, warn=None, info_only=False):
    """ENTRY SIAP setelah M1 terkonfirmasi. info_only=True (mode SNIPER): hanya informasi, sinyal SNIPER sudah dikirim."""
    lv = c.get("live_levels") or a["levels"]
    since = f"\nPertama terkonfirmasi {c['first_time'][11:16]} UTC di sekitar {fp(c['first_price'], off)}." if c.get("first_time") else ""
    tps = " | ".join(f"TP{i + 1} {fp(x, off)}" for i, x in enumerate(lv["tp"]))
    left = f"\nBatas waktu entry sisa {c['minutes_left']:.0f} menit." if c.get("minutes_left") is not None else ""
    title = (f"{label} {tf} · {a['direction']} M1 terkonfirmasi (info)" if info_only
             else f"{label} {tf} · {a['direction']} ENTRY SIAP (M1 terkonfirmasi)")
    note = "Hanya informasi: sinyal SNIPER sudah dikirim, jangan entri dua kali.\n" if info_only else ""
    return (title,
            note + f"Harga M1 {fp(c['price'], off)} (di zona entry, {c.get('chase_r', 0):+.2f}R dari entry sinyal).\n"
            f"Entry {fp(lv['entry'], off)} | SL {fp(lv['stop_loss'], off)} | risiko {lv['risk_points']:.2f}\n{tps}{left}{since}\n"
            + (f"⚠ {warn}\n" if warn else "") + "Jangan mengejar jika harga sudah menjauh. Bukan saran investasi.")


def momentum_message(label, res, off=0.0, in_zone=False):
    """NEWS MOMENTUM: rencana LIMIT di pullback setelah gerakan mendadak (eksperimental)."""
    lv, imp, ev = res["levels"], res["impulse"], res.get("evidence") or {}
    d = res["plan_direction"]
    order = "BUY LIMIT" if d == "BUY" else "SELL LIMIT"
    tps = " | ".join(f"TP{i + 1} {fp(x, off)}" for i, x in enumerate(lv["tp"]))
    z = res["zone"]
    why = "; ".join(res.get("reasons") or [])
    warn = "".join(f"\n⚠ {w}" for w in (res.get("warnings") or [])[:2])
    head = "HARGA DI ZONA ENTRY" if in_zone else "rencana baru"
    return (f"{label} · NEWS MOMENTUM {d} ({'zona' if in_zone else 'eksperimental'})",
            f"{head}: impuls {imp['direction']} {imp['ratio']}x ATR M5 ({imp['pct']}% dalam {imp['bars'] * 5} menit).\n"
            f"{order} {fp(lv['entry'], off)} (zona {fp(z[0], off)}-{fp(z[1], off)}) | SL {fp(lv['stop_loss'], off)} | risiko {lv['risk_points']:.2f}\n"
            f"{tps}\nBukti {ev.get('n', 0)}/{ev.get('of', 3)} ({ev.get('label', '-')}): {why}{warn}\n"
            "Berita terbit setelah harga bergerak: jangan mengejar, batal bila harga menembus awal impuls. Bukan saran investasi.")


def momentum_cancel_message(label, res):
    imp = res.get("impulse") or {}
    return (f"{label} · NEWS MOMENTUM BATAL",
            f"{res.get('label', 'rencana batal')}. Pullback menembus batas atau harga kembali ke awal impuls "
            f"({imp.get('origin')}). Hapus order limit yang belum terisi.")


NOW_MIN = 10          # menit: pada jendela ini sinyal pra-news bertuliskan BUY NOW / SELL NOW


def pre_now():
    """NEWS_PRE_NOW=0 mematikan tahap 10 menit dan tulisan NOW (pra-news kembali seperti v19.30)."""
    return os.getenv("NEWS_PRE_NOW", "1").strip().lower() not in ("0", "off", "false", "no")


def news_pre_message(ev, sig, minutes_left, off=0.0, analysis=None):
    head = f"{ev['short']} {minutes_left:.0f} menit lagi · {wib(ev['t0'])}"
    lines = []
    now_win = sig["direction"] in ("BUY", "SELL") and 0 < minutes_left <= NOW_MIN and pre_now()
    if now_win:
        head += f" · {sig['direction']} NOW"
        lines.append("Arah ini taruhan pada angka rilis, bukan konfirmasi harga.")
    if sig["direction"] in ("BUY", "SELL"):
        lv = sig.get("levels")
        lines.append(f"Sinyal pra-news: {sig['direction']} ({(sig.get('strength') or '').lower()}, kekuatan bukti {sig['confidence']}%)")
        if lv:
            lines.append(f"Entry {fp(lv['entry'], off)} | SL {fp(lv['stop_loss'], off)} | TP1 {fp(lv['tp1'], off)} | TP2 {fp(lv['tp2'], off)}")
    else:
        lines.append("Tidak ada prediksi arah. Tunggu angka rilis dan reaksi harga.")
    if analysis:
        fu = analysis["fusion"]
        txt = f"bias {fu['bias']} {fu['confidence']}%" if fu["bias"] in ("BUY", "SELL") else "belum ada bias"
        lines.append(f"Analisis lengkap: {txt} ({fu['available']} aspek terkumpul). Hanya bias; entry baru setelah rilis dan harga bereaksi.")
    st = sig.get("straddle")
    if st:
        lines.append(f"Zona breakout: di atas {fp(st['buy_above'], off)} atau di bawah {fp(st['sell_below'], off)} "
                     f"(gerak umum 60 menit ±{st['typical_move_60m']:.0f} poin).")
    lines.append("Arah sebelum rilis sering berbalik oleh angka berita. Spread melebar saat rilis. Bukan saran investasi.")
    return head, "\n".join(lines)


def news_post_message(ev, sig, off=0.0):
    lv = sig.get("levels")
    mv = sig["reaction"]["move"]
    lines = [f"Gerak sejak rilis {mv:+.2f} poin (kekuatan bukti {sig['confidence']}%)."]
    if lv:
        lines.append(f"Entry {fp(lv['entry'], off)} | SL {fp(lv['stop_loss'], off)} | TP1 {fp(lv['tp1'], off)} | TP2 {fp(lv['tp2'], off)}")
    lines.append("Bukan saran investasi.")
    return f"{ev['short']} · reaksi {sig['direction']}", "\n".join(lines)


def news_result_message(row, off=0.0):
    """Pemberitahuan bahwa sinyal news yang pernah diterbitkan ternyata SALAH."""
    mv = row.get("move")
    lines = [f"Sinyal {row['direction']} di {fp(row['entry'], off)} dinilai SALAH: {row.get('why') or 'hasil berlawanan'}."]
    if mv is not None:
        lines.append(f"Gerak akhir {mv:+.2f} poin terhadap arah sinyal.")
    lines.append("Tercatat di tab NEWS (riwayat sinyal). Bukan saran investasi.")
    return f"Sinyal {row['short']} {row['direction']} SALAH", "\n".join(lines)


EXIT_REASON = {
    "REVERSED": "Sinyal berbalik arah",
    "SL": "Stop loss tersentuh",
    "TP3": "TP3 tercapai",
    "EXPIRED": "Sinyal kedaluwarsa (lewat batas waktu)",
}


def exit_message(label, tf, r, new_dir=None, off=0.0):
    """Sinyal aktif selesai: berbalik, SL, TP3, atau kedaluwarsa."""
    sg = 1 if r["direction"] == "BUY" else -1
    pts = (r["exit_price"] - r["entry"]) * sg
    why = EXIT_REASON.get(r["outcome"], r["outcome"])
    if r["outcome"] == "REVERSED" and new_dir:
        why += f" ke {new_dir}"
    act = {"TP3": "Ambil profit / tutup posisi.",
           "SL": "Posisi seharusnya sudah tertutup oleh SL."}.get(r["outcome"], "Pertimbangkan tutup posisi.")
    tp = f" · TP tersentuh: {r['tp_hit']} dari 3" if r.get("tp_hit") else ""
    return (f"{label} {tf} · KELUAR {r['direction']}",
            f"{why}.\nEntry {fp(r['entry'], off)} → harga {fp(r['exit_price'], off)} ({pts:+.2f} poin){tp}\n"
            f"Sinyal terbit {hm(r['time'])}, berakhir {hm(r['end_time'])}.\n{act} Bukan saran investasi.")


def weak_message(label, tf, a, score, max_score, price, off=0.0):
    """Sinyal masih aktif, tetapi indikator sudah tidak mendukung arahnya."""
    lv = a["levels"]
    sg = 1 if a["direction"] == "BUY" else -1
    pts = (price - lv["entry"]) * sg
    state = "netral" if score == 0 else "berlawanan"
    return (f"{label} {tf} · {a['direction']} MELEMAH",
            f"Skor indikator sekarang {score:+d} dari ±{max_score} ({state}), tidak lagi mendukung {a['direction']}.\n"
            f"Entry {fp(lv['entry'], off)} → harga {fp(price, off)} ({pts:+.2f} poin) · SL {fp(lv['stop_loss'], off)}\n"
            "Pertimbangkan keluar lebih awal atau geser SL ke titik impas. Bukan saran investasi.")


def renew_message(label, tf, r, a, off=0.0):
    """Sinyal lama kedaluwarsa, tetapi pada candle yang sama terbit sinyal baru searah."""
    sg = 1 if r["direction"] == "BUY" else -1
    pts = (r["exit_price"] - r["entry"]) * sg
    lv = a["levels"]
    tps = " | ".join(f"TP{i + 1} {fp(x, off)}" for i, x in enumerate(lv["tp"]))
    return (f"{label} {tf} · {a['direction']} DIPERBARUI",
            f"Sinyal {r['direction']} lama ({hm(r['time'])}) kedaluwarsa, tetapi indikator masih mendukung {a['direction']}: "
            f"sinyal baru terbit {hm(a['time_close'])}.\n"
            f"Entry lama {fp(r['entry'], off)} → harga {fp(r['exit_price'], off)} ({pts:+.2f} poin)\n"
            f"Level baru: SL {fp(lv['stop_loss'], off)} | {tps}\n"
            "Posisi boleh ditahan dengan SL/TP baru, atau tutup bila ingin aman. Bukan saran investasi.")


def _fib_order_lines(fs, off):
    """Baris rencana order limit (dari Order Block bila ada) untuk notifikasi Fib."""
    od, ob = fs.get("order"), fs.get("ob")
    if not od:
        return ""
    side = "BUY LIMIT" if od["side"] == "BUY_LIMIT" else "SELL LIMIT"
    rr = "/".join(f"{x:g}" for x in od["rr"])
    tps = " | ".join(f"TP{i + 1} {fp(x, off)}" for i, x in enumerate(od["tp"]))
    if ob:
        src = f"OB {'demand' if ob['type'] == 'demand' else 'supply'} {fp(ob['bottom'], off)} - {fp(ob['top'], off)}"
    else:
        src = "OB tidak ditemukan di zona, pakai level entry Fib"
    note = "" if od.get("limit_ok", True) else "\nHarga sudah di dalam OB: limit tidak bisa dipasang, tunggu atau pakai market."
    return (f"{side} {fp(od['entry'], off)} | SL {fp(od['sl'], off)} | risiko {od['risk_points']:.2f}\n"
            f"{src}\n{tps} (RR 1:{rr}){note}\n")


def _fib_quality_line(fs):
    """Satu baris kualitas setup: struktur (BOS) dan divergensi RSI bila ada."""
    bits = []
    st, dv = fs.get("struct"), fs.get("div")
    if st:
        bits.append("struktur valid (BOS)" if st["ok"] else "struktur lemah (belum BOS)")
    if dv:
        bits.append(f"RSI {dv['type']} {dv['side']} divergence")
    return ("Kualitas: " + ", ".join(bits) + "\n") if bits else ""


def fib_message(label, tf, fs, off=0.0, invalid=False, plan=False):
    """Notifikasi setup Fib: rencana order limit (plan, langsung saat setup muncul), harga masuk zona entry,
    atau setup batal setelah sempat diberitahukan."""
    d, lg = fs["direction"], fs["leg"]
    draw = lg.get("draw_label") or lg["draw"]
    if invalid:
        return (f"{label} {tf} · FIB {d} BATAL",
                f"Harga melewati level 0.99 ({fp(fs['stop_loss'], off)}). Setup Fib {d} (tarik {draw}) tidak berlaku lagi.\n"
                "Batalkan limit yang belum terisi dan jangan menambah posisi; tunggu garis Fib baru. Bukan saran investasi.")
    od = fs.get("order")
    lines = _fib_order_lines(fs, off)
    if plan and od:
        side = "BUY LIMIT" if od["side"] == "BUY_LIMIT" else "SELL LIMIT"
        live = fs.get("live_price")
        return (f"{label} {tf} · FIB {side} {fp(od['entry'], off)}",
                f"{lines}{_fib_quality_line(fs)}Zona {fp(fs['zone']['from'], off)} - {fp(fs['zone']['to'], off)} (tarik {draw}: "
                f"{fp(lg['start'], off)} -> {fp(lg['end'], off)})"
                + (f"\nHarga sudah bergerak {max(fs.get('progress') or 0, 0) * 100:.0f}% dari titik balik menuju zona entry (posisi di fib {fs['ratio']:.2f}, harga {fp(live, off)})." if live is not None and fs.get("ratio") is not None else "") +
                "\nPasang limit sekarang; batalkan bila ada kabar BATAL. Bukan saran investasi.")
    tps = " | ".join(f"TP{i + 1} {fp(x, off)}" for i, x in enumerate(fs["tp"]))
    rz = fs.get("rr_zone") or [fs["rr"], fs["rr"]]
    rr = "/".join(f"{a:g}-{b:g}" if a != b else f"{a:g}" for a, b in zip(rz[0], rz[1]) if a is not None and b is not None)
    body = (f"Zona {fp(fs['zone']['from'], off)} - {fp(fs['zone']['to'], off)} (tarik {draw}: "
            f"{fp(lg['start'], off)} -> {fp(lg['end'], off)})\n")
    body += _fib_quality_line(fs)
    body += lines if od else f"Area entry {fp(fs['zone']['from'], off)} - {fp(fs['zone']['to'], off)} | SL {fp(fs['stop_loss'], off)}\n{tps} (RR 1:{rr})\n"
    return (f"{label} {tf} · FIB {d} DI ZONA ENTRY",
            body + "Jika SL kena, hitung dulu risikonya terhadap saldo. Bukan saran investasi.")
