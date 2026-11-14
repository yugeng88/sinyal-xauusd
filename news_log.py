"""Catatan sinyal NEWS yang benar-benar diterbitkan, lalu dinilai BENAR atau SALAH dari candle M5 sesudahnya.

Penilaian transparan dan tidak bisa diubah belakangan:
  BENAR  = TP1 tersentuh lebih dulu dalam 60 menit sejak terbit.
  SALAH  = SL tersentuh lebih dulu (bila SL dan TP1 satu candle: dihitung SALAH, sisi paling hati-hati).
  NETRAL = 60 menit berlalu tanpa TP1 maupun SL.
  Sinyal tanpa level SL/TP dinilai dari arah harga 30 menit sesudah terbit (gerak < 0,5 poin = NETRAL).
Disimpan di Redis (kunci "newslog") bila tersedia; tanpa Redis hanya bertahan di memori instance.
"""
from __future__ import annotations

import json
import time

import pandas as pd

import notify

KEY = "newslog"
CAP = 40                         # jumlah catatan maksimum
TTL = 30 * 86400                 # simpan 30 hari
WINDOW_MIN = 60                  # batas waktu penilaian sinyal berlevel
QUICK_MIN = 30                   # batas penilaian sinyal tanpa level
FLAT_MOVE = 0.5                  # gerak kurang dari ini (poin) = netral
GIVE_UP_HOURS = 6                # data candle tidak mencakup sinyal setelah ini -> TIDAK TERUKUR
_CACHE_S = 45                    # hemat perintah Redis: baca ulang paling cepat tiap 45 detik

_mem = {"rows": None, "at": 0.0}


def _load(force=False):
    t = time.time()
    if not force and _mem["rows"] is not None and t - _mem["at"] < _CACHE_S:
        return _mem["rows"]
    rows = None
    raw = notify.kv_get(KEY)
    if raw:
        try:
            v = json.loads(raw)
            rows = v if isinstance(v, list) else None
        except (TypeError, ValueError):
            rows = None
    if rows is None:
        rows = list(_mem["rows"] or [])
    _mem.update(rows=rows, at=t)
    return rows


def _save(rows):
    rows = rows[-CAP:]
    _mem.update(rows=rows, at=time.time())
    notify.kv_set(KEY, json.dumps(rows), ttl=TTL)


def reset():
    """Dipakai tes."""
    _mem.update(rows=None, at=0.0)


def record(ev, sig, now=None):
    """Catat sinyal BUY/SELL yang diterbitkan untuk berita `ev`. Satu catatan per berita per jenis. Kembalikan baris baru atau None."""
    if not sig or sig.get("direction") not in ("BUY", "SELL"):
        return None
    lv = sig.get("levels") or {}
    entry = lv.get("entry")
    if entry is None:
        r = sig.get("reaction") or {}
        if r.get("p0") is None:
            return None
        entry = round(float(r["p0"]) + float(r.get("move") or 0.0), 2)
    kind = sig.get("kind") or "PASCA"
    rid = f"{ev['id']}:{kind}"
    rows = _load(force=True)
    if any(r["id"] == rid for r in rows):
        return None
    ts = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    row = {"id": rid, "ev": ev["id"], "type": ev["type"], "short": ev["short"], "kind": kind,
           "direction": sig["direction"], "issued": ts.isoformat(), "entry": float(entry),
           "sl": lv.get("stop_loss"), "tp1": lv.get("tp1"), "conf": sig.get("confidence"),
           "result": None, "why": None, "move": None, "closed": None, "notified": False}
    rows.append(row)
    _save(rows)
    return row


def evaluate(row, m5, now):
    """Nilai satu catatan. Kembalikan dict {result, why, move, closed} bila sudah bisa dinilai, selain itu None."""
    now = pd.Timestamp(now)
    t0 = pd.Timestamp(row["issued"])
    sg = 1 if row["direction"] == "BUY" else -1
    has_levels = row.get("sl") is not None and row.get("tp1") is not None
    horizon = t0 + pd.Timedelta(minutes=WINDOW_MIN if has_levels else QUICK_MIN)
    start = t0.ceil("5min")
    bars = pd.DataFrame()
    if m5 is not None and len(m5):
        t = pd.to_datetime(m5["time"], utc=True)
        bars = m5[(t >= start) & (t + pd.Timedelta(minutes=5) <= min(now, horizon))].sort_values("time")

    def done(result, why, last_close):
        mv = round(sg * (float(last_close) - row["entry"]), 2) if last_close is not None else None
        return {"result": result, "why": why, "move": mv, "closed": now.isoformat()}

    last = float(bars["close"].iloc[-1]) if len(bars) else None
    if has_levels:
        sl, tp = float(row["sl"]), float(row["tp1"])
        for _, b in bars.iterrows():
            hit_sl = b["low"] <= sl if sg > 0 else b["high"] >= sl
            hit_tp = b["high"] >= tp if sg > 0 else b["low"] <= tp
            if hit_sl:
                return done("SALAH", "SL tersentuh" + (" (TP1 di candle yang sama, dihitung salah)" if hit_tp else ""), b["close"])
            if hit_tp:
                return done("BENAR", "TP1 tercapai", b["close"])
        if now >= horizon:
            if last is None:
                return done("TIDAK TERUKUR", "data candle tidak tersedia", None)
            return done("NETRAL", f"{WINDOW_MIN} menit tanpa TP1 maupun SL", last)
    else:
        if now >= horizon:
            if last is None:
                return done("TIDAK TERUKUR", "data candle tidak tersedia", None)
            mv = sg * (last - row["entry"])
            if abs(mv) < FLAT_MOVE:
                return done("NETRAL", f"{QUICK_MIN} menit: harga nyaris tidak bergerak", last)
            return done("BENAR" if mv > 0 else "SALAH",
                        f"{QUICK_MIN} menit: harga {'searah' if mv > 0 else 'berlawanan'} dengan sinyal (tanpa level SL/TP)", last)
    if now >= t0 + pd.Timedelta(hours=GIVE_UP_HOURS) and not len(bars):
        return done("TIDAK TERUKUR", "data candle tidak tersedia", None)
    return None


def stats(rows):
    res = [r.get("result") for r in rows]
    benar, salah = res.count("BENAR"), res.count("SALAH")
    netral = res.count("NETRAL")
    resolved = benar + salah
    return {"total": len(rows), "benar": benar, "salah": salah, "netral": netral,
            "berjalan": sum(1 for r in res if r is None), "resolved": resolved,
            "acc": round(benar / resolved * 100) if resolved else None}


def refresh(m5, now=None):
    """Nilai semua catatan yang masih berjalan, simpan bila ada perubahan. Kembalikan tampilan untuk UI."""
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    rows = _load()
    changed = False
    for r in rows:
        if r.get("result") is None:
            try:
                out = evaluate(r, m5, now)
            except Exception:  # noqa: BLE001  penilaian tidak boleh merusak halaman
                out = None
            if out:
                r.update(out)
                changed = True
    if changed:
        _save(rows)
    return {"entries": list(reversed(rows[-12:])), "stats": stats(rows)}


def pending_wrong():
    """Catatan SALAH yang belum diberi tahu lewat notifikasi."""
    return [r for r in _load(force=True) if r.get("result") == "SALAH" and not r.get("notified")]


def mark_notified(rid):
    rows = _load(force=True)
    for r in rows:
        if r["id"] == rid:
            r["notified"] = True
    _save(rows)
