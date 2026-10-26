"""Aplikasi sinyal H1 untuk XAUUSD dan NASDAQ: satu aplikasi, dua tab.

Dua mode, kode sama:
- Server biasa:  python app.py  -> thread latar belakang memperbarui tiap UPDATE_MINUTES
- Serverless (Vercel): data dihitung saat halaman meminta, dengan cache UPDATE_MINUTES
"""
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import requests
from flask import Flask, Response, jsonify, request

import data
import page
import signals

UPDATE_MINUTES = max(int(os.getenv("UPDATE_MINUTES", "15")), 1)
HISTORY_FILE = os.getenv("HISTORY_FILE",
                         "/tmp/history.jsonl" if os.getenv("VERCEL") else "history.jsonl")
PORT = int(os.getenv("PORT", "8000"))
SYMS = list(data.SYMBOLS)

app = Flask(__name__, static_folder=None)
lock = threading.Lock()
busy = {s: threading.Lock() for s in SYMS}
narrative_cache = {}


def new_state():
    return {"signal": None, "summary": None, "updated_at": None,
            "error": None, "last_attempt": None}


states = {s: new_state() for s in SYMS}


def now():
    return datetime.now(timezone.utc)


def claude_narrative(sig):
    """Opsional: Claude menulis ulang angka yang SUDAH dihitung. Gagal -> None."""
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return None
    ck = (sig["symbol"], sig["candle_time"], sig["direction"])
    if ck in narrative_cache:
        return narrative_cache[ck]
    facts = json.dumps({k: sig[k] for k in
                        ("label", "direction", "score", "confidence", "price",
                         "indicators", "levels", "reasons", "warnings", "market_closed")},
                       ensure_ascii=False)
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5"),
                  "max_tokens": 400,
                  "system": ("Kamu menulis ringkasan teknikal H1 dalam Bahasa Indonesia, "
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


def telegram(msg):
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        return
    try:
        requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                      json={"chat_id": chat, "text": msg}, timeout=15)
    except Exception:  # noqa: BLE001
        pass


def log_history(sig):
    row = {k: sig[k] for k in ("symbol", "candle_time", "direction", "score",
                               "confidence", "price", "levels")}
    row["logged_at"] = now().isoformat()
    try:
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass  # penyimpanan tidak tersedia: abaikan, sinyal tetap tampil


def refresh(sym):
    """Satu siklus untuk satu instrumen: ambil data nyata -> hitung -> simpan."""
    if not busy[sym].acquire(blocking=False):
        return  # siklus lain untuk instrumen ini sedang berjalan
    try:
        _refresh(sym)
    finally:
        busy[sym].release()


def _refresh(sym):
    st = states[sym]
    with lock:
        st["last_attempt"] = now().isoformat()
    try:
        df, source, note = data.get_candles(sym)
        sig = signals.analyze(df, source, symbol=sym,
                              label=data.SYMBOLS[sym]["label"], note=note)
        sig["tracking"] = signals.track(df)
    except Exception as e:  # noqa: BLE001
        with lock:
            st["error"] = f"{type(e).__name__}: {e}"
        return
    summary = claude_narrative(sig) or signals.summary_text(sig)
    with lock:
        prev = st["signal"]
        new_candle = prev is None or prev["candle_time"] != sig["candle_time"]
        changed = prev is not None and prev["direction"] != sig["direction"]
        st.update(signal=sig, summary=summary, error=None, updated_at=now().isoformat())
    if new_candle:
        log_history(sig)
    if changed and sig["direction"] != "WAIT":
        lv = sig["levels"]
        extra = f"\nEntry {lv['entry']} | SL {lv['stop_loss']} | TP {lv['tp']}" if lv else ""
        telegram(f"{sig['label']} H1: {prev['direction']} -> {sig['direction']} "
                 f"(keyakinan {sig['confidence']}%){extra}\nBukan saran investasi.")


def ensure_fresh(sym):
    """Hitung ulang hanya bila data lebih tua dari interval (galat dicoba lagi 1 menit)."""
    with lock:
        la, err = states[sym]["last_attempt"], states[sym]["error"]
    gap = timedelta(minutes=1 if err else UPDATE_MINUTES)
    if la is None or now() - datetime.fromisoformat(la) > gap:
        refresh(sym)


def loop():
    while True:
        for sym in SYMS:
            try:
                refresh(sym)
            except Exception as e:  # noqa: BLE001  - loop tidak boleh mati
                with lock:
                    states[sym]["error"] = f"Loop: {e}"
        time.sleep(UPDATE_MINUTES * 60)


def pick_symbol():
    sym = (request.args.get("symbol") or SYMS[0]).upper()
    return sym if sym in states else None


@app.get("/api/signal")
def api_signal():
    sym = pick_symbol()
    if sym is None:
        return jsonify(error="Instrumen tidak dikenal", symbols=SYMS), 404
    ensure_fresh(sym)
    with lock:
        s = dict(states[sym])
    nxt = None
    if s["last_attempt"]:
        nxt = (datetime.fromisoformat(s["last_attempt"])
               + timedelta(minutes=UPDATE_MINUTES)).isoformat()
    s.update(symbol=sym, update_minutes=UPDATE_MINUTES, next_update=nxt,
             now=now().isoformat())
    return jsonify(s)


@app.get("/api/history")
def api_history():
    sym = pick_symbol()
    if sym is None:
        return jsonify([]), 404
    rows = []
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, encoding="utf-8") as f:
            for x in f:
                if x.strip():
                    r = json.loads(x)
                    if r.get("symbol", "XAUUSD") == sym:
                        rows.append(r)
    return jsonify(rows[-50:][::-1])


@app.get("/healthz")
def healthz():
    return jsonify(ok=True, has_signal={s: states[s]["signal"] is not None for s in SYMS})


@app.get("/")
def index():
    return Response(page.HTML, mimetype="text/html")


def start_background():
    threading.Thread(target=loop, daemon=True, name="updater").start()


if __name__ == "__main__":
    start_background()
    app.run(host="0.0.0.0", port=PORT, threaded=True)
