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
def send(title, message, priority=3, tags=(), click=None):
    """Kirim ke semua kanal yang aktif. Kembalikan hasil per kanal (galat sudah disamarkan)."""
    out = []
    topic = os.getenv("NTFY_TOPIC", "").strip()
    if topic:
        try:
            server = (os.getenv("NTFY_SERVER", "") or "https://ntfy.sh").strip().rstrip("/")
            body = {"topic": topic, "title": title, "message": message,
                    "priority": int(priority), "tags": list(tags)}
            if click:
                body["click"] = click
            headers = {"Content-Type": "application/json"}
            if os.getenv("NTFY_TOKEN", "").strip():
                headers["Authorization"] = "Bearer " + os.getenv("NTFY_TOKEN").strip()
            r = requests.post(server, json=body, headers=headers, timeout=TIMEOUT)
            out.append({"channel": "ntfy", "ok": r.status_code == 200,
                        "error": None if r.status_code == 200 else f"HTTP {r.status_code}"})
        except Exception as e:  # noqa: BLE001
            out.append({"channel": "ntfy", "ok": False, "error": _scrub(e)})
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
    return out


# ------------------------------------------------------------------- pesan
def fp(x, off=0.0):
    return f"{x + off:,.2f}"


def hm(iso):
    return f"{(datetime.fromisoformat(iso) + timedelta(hours=7)):%H:%M} WIB"


def wib(iso):
    t = datetime.fromisoformat(iso) + timedelta(hours=7)
    return f"{DAYS[t.weekday()]} {t.day} {MONTHS[t.month - 1]} {t:%H:%M} WIB"


def signal_message(label, tf, a, off=0.0):
    lv = a["levels"]
    tps = " | ".join(f"TP{i + 1} {fp(x, off)}" for i, x in enumerate(lv["tp"]))
    return (f"{label} {tf} · {a['direction']}",
            f"Sinyal baru (keyakinan {a['confidence']}%) · candle {tf} ditutup {hm(a['time_close'])}\n"
            f"Entry {fp(lv['entry'], off)} | SL {fp(lv['stop_loss'], off)}\n{tps}\n"
            "Tunggu konfirmasi M1 sebelum masuk. Bukan saran investasi.")


def confirm_message(label, tf, a, c, off=0.0):
    lv = a["levels"]
    since = f"\nPertama terkonfirmasi {c['first_time'][11:16]} UTC di sekitar {fp(c['first_price'], off)}." if c.get("first_time") else ""
    return (f"{label} {tf} · {a['direction']} TERKONFIRMASI M1",
            f"Harga M1 {fp(c['price'], off)} (di zona entry).\n"
            f"Entry {fp(lv['entry'], off)} | SL {fp(lv['stop_loss'], off)} | TP1 {fp(lv['tp'][0], off)}{since}\n"
            "Bukan saran investasi.")


def news_pre_message(ev, sig, minutes_left, off=0.0):
    head = f"{ev['short']} {minutes_left:.0f} menit lagi · {wib(ev['t0'])}"
    lines = []
    if sig["direction"] in ("BUY", "SELL"):
        lv = sig["levels"]
        lines.append(f"Sinyal pra-news: {sig['direction']} ({(sig.get('strength') or '').lower()}, keyakinan {sig['confidence']}%)")
        if lv:
            lines.append(f"Entry {fp(lv['entry'], off)} | SL {fp(lv['stop_loss'], off)} | TP1 {fp(lv['tp1'], off)} | TP2 {fp(lv['tp2'], off)}")
    else:
        lines.append("Belum ada bias arah: TUNGGU reaksi.")
    st = sig.get("straddle")
    if st:
        lines.append(f"Zona breakout: di atas {fp(st['buy_above'], off)} atau di bawah {fp(st['sell_below'], off)} "
                     f"(gerak umum 60 menit ±{st['typical_move_60m']:.0f} poin).")
    lines.append("Spread melebar saat rilis. Bukan saran investasi.")
    return head, "\n".join(lines)


def news_post_message(ev, sig, off=0.0):
    lv = sig["levels"]
    mv = sig["reaction"]["move"]
    return (f"{ev['short']} · reaksi {sig['direction']}",
            f"Gerak sejak rilis {mv:+.2f} poin, searah pola riwayat (keyakinan {sig['confidence']}%).\n"
            f"Entry {fp(lv['entry'], off)} | SL {fp(lv['stop_loss'], off)} | TP1 {fp(lv['tp1'], off)} | TP2 {fp(lv['tp2'], off)}\n"
            "Bukan saran investasi.")


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
