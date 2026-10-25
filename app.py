"""Aplikasi sinyal XAUUSD harian: berjalan terus dan memperbarui diri.

Jalankan:  python app.py   ->  http://localhost:8000
"""
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import requests
from flask import Flask, jsonify, send_from_directory

import data
import signals

UPDATE_MINUTES = max(int(os.getenv("UPDATE_MINUTES", "15")), 1)
HISTORY_FILE = os.getenv("HISTORY_FILE", "history.jsonl")
PORT = int(os.getenv("PORT", "8000"))

BASE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=None)
state = {"signal": None, "summary": None, "updated_at": None,
         "error": None, "last_attempt": None}
lock = threading.Lock()
narrative_cache = {}


def now():
    return datetime.now(timezone.utc)


def claude_narrative(sig):
    """Opsional: Claude menulis ulang angka yang SUDAH dihitung. Gagal -> None."""
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return None
    ck = (sig["candle_time"], sig["direction"])
    if ck in narrative_cache:
        return narrative_cache[ck]
    facts = json.dumps({k: sig[k] for k in
                        ("direction", "score", "confidence", "price",
                         "indicators", "levels", "reasons", "warnings")},
                       ensure_ascii=False)
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5"),
                  "max_tokens": 400,
                  "system": ("Kamu menulis ringkasan teknikal XAUUSD H1 dalam Bahasa "
                             "Indonesia, 3-4 kalimat. Pakai HANYA angka pada data yang "
                             "diberikan. Dilarang menambah angka, berita, atau prediksi "
                             "baru. Jangan menjanjikan profit."),
                  "messages": [{"role": "user", "content": facts}]},
            timeout=40)
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json()["content"]).strip()
        narrative_cache.clear()
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
    row = {k: sig[k] for k in ("candle_time", "direction", "score",
                               "confidence", "price", "levels")}
    row["logged_at"] = now().isoformat()
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def refresh():
    """Satu siklus: ambil data nyata -> hitung -> simpan. Galat disimpan apa adanya."""
    with lock:
        state["last_attempt"] = now().isoformat()
    try:
        df, source = data.get_candles()
        sig = signals.analyze(df, source)
    except Exception as e:  # noqa: BLE001
        with lock:
            state["error"] = f"{type(e).__name__}: {e}"
        return
    summary = claude_narrative(sig) or signals.summary_text(sig)
    with lock:
        prev = state["signal"]
        new_candle = prev is None or prev["candle_time"] != sig["candle_time"]
        changed = prev is not None and prev["direction"] != sig["direction"]
        state.update(signal=sig, summary=summary, error=None,
                     updated_at=now().isoformat())
    if new_candle:
        log_history(sig)
    if changed:
        lv = sig["levels"]
        extra = (f"\nEntry {lv['entry']} | SL {lv['stop_loss']} | TP {lv['tp']}"
                 if lv else "")
        telegram(f"XAUUSD H1: {prev['direction']} -> {sig['direction']} "
                 f"(keyakinan {sig['confidence']}%){extra}\nBukan saran investasi.")


def loop():
    while True:
        try:
            refresh()
        except Exception as e:  # noqa: BLE001  - loop tidak boleh mati
            with lock:
                state["error"] = f"Loop: {e}"
        time.sleep(UPDATE_MINUTES * 60)


@app.get("/api/signal")
def api_signal():
    with lock:
        s = dict(state)
    nxt = None
    if s["last_attempt"]:
        nxt = (datetime.fromisoformat(s["last_attempt"])
               + timedelta(minutes=UPDATE_MINUTES)).isoformat()
    s.update(update_minutes=UPDATE_MINUTES, next_update=nxt, now=now().isoformat())
    return jsonify(s)


@app.get("/api/history")
def api_history():
    rows = []
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, encoding="utf-8") as f:
            rows = [json.loads(x) for x in f if x.strip()][-50:]
    return jsonify(rows[::-1])


@app.get("/healthz")
def healthz():
    return jsonify(ok=True, has_signal=state["signal"] is not None)


@app.get("/")
def index():
    return send_from_directory(BASE, "index.html")


def start_background():
    threading.Thread(target=loop, daemon=True, name="updater").start()


if __name__ == "__main__":
    start_background()
    app.run(host="0.0.0.0", port=PORT, threaded=True)
