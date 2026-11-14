"""Tanggal rilis resmi sejak tahun lampau (mis. 2007) dari FRED (Federal Reserve Bank of St. Louis).

Butuh env FRED_API_KEY (gratis: fred.stlouisfed.org -> My Account -> API Keys). Tanpa kunci modul ini diam
dan aplikasi memakai jadwal bawaan di news.py. Mencakup CPI, PPI, NFP, PCE. FOMC tidak tersedia dari FRED.
Semua rilis ini terbit pukul 08:30 waktu New York, sama dengan aturan di news.TYPES.
"""
from __future__ import annotations

import os
import time
from datetime import date, datetime

import requests

FRED_URL = "https://api.stlouisfed.org/fred/release/dates"
RELEASES = {"CPI": 10, "PPI": 46, "NFP": 50, "PCE": 54}     # id rilis FRED
TTL, FAIL_TTL = 7 * 86400, 3600
_cache = {}                                                    # (jenis, tahun) -> (waktu, daftar, galat)


def reset():
    _cache.clear()


def status():
    return {k[0]: {"n": len(v[1]), "error": v[2]} for k, v in _cache.items()}


def fred_dates(typ, since_year, now_ts=None, fetch=None):
    """Daftar tanggal ISO (hari kerja, sampai hari ini) rilis `typ` sejak `since_year`. Tidak pernah melempar error."""
    rid = RELEASES.get(typ)
    key = os.getenv("FRED_API_KEY", "").strip()
    if not rid or (not key and fetch is None):
        return []
    t = time.time() if now_ts is None else now_ts
    ck = (typ, since_year)
    c = _cache.get(ck)
    if c and t - c[0] < (TTL if not c[2] else FAIL_TTL):
        return c[1]
    try:
        if fetch is not None:
            rows = fetch(rid)
        else:
            r = requests.get(FRED_URL, timeout=6, params={
                "release_id": rid, "api_key": key, "file_type": "json", "sort_order": "asc",
                "realtime_start": "1776-07-04", "realtime_end": "9999-12-31", "limit": 10000,
                "include_release_dates_with_no_data": "false"})
            if r.status_code != 200:
                raise ValueError(f"HTTP {r.status_code}")
            rows = r.json().get("release_dates", [])
        today = datetime.fromtimestamp(t).date() if now_ts is not None else date.today()
        out = set()
        for x in rows:
            try:
                d = date.fromisoformat(str(x["date"])[:10])
            except (KeyError, ValueError):
                continue
            if d.year >= since_year and d.weekday() < 5 and d < today:
                out.add(d.isoformat())
        res = sorted(out)
        _cache[ck] = (t, res, None)
        return res
    except Exception as e:  # noqa: BLE001  jangan bocorkan URL/kunci ke pesan galat
        msg = f"{type(e).__name__}" + (f": {e}" if isinstance(e, ValueError) else "")
        old = c[1] if c else []
        _cache[ck] = (t, old, msg[:80])
        return old
