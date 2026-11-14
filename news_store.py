"""Penyimpanan permanen hasil ukur reaksi harga per kejadian (Redis lewat notify.kv_*).

Tanpa ini, jendela candle riwayat hanya hidup di memori satu instance dan diambil ulang setiap kali instance baru
menyala, sehingga kuota Twelve Data/OANDA habis dan riwayat panjang mustahil. Dengan ini setiap kejadian hanya
diambil SEKALI. Tanggal yang tidak tersedia di penyedia data ditandai {"na": waktu} dan dilewati 14 hari.
"""
from __future__ import annotations

import json
import time

import notify

PREFIX = "nwreact:"
TTL = 400 * 86400
NA_DAYS = 14
_CACHE_S = 60
_mem = {}                         # jenis -> (waktu baca, dict tanggal -> baris atau {"na": ts})


def reset():
    _mem.clear()


def _load(typ, force=False):
    t = time.time()
    c = _mem.get(typ)
    if c and not force and t - c[0] < _CACHE_S:
        return c[1]
    cur = None
    raw = notify.kv_get(PREFIX + typ)
    if raw:
        try:
            v = json.loads(raw)
            cur = v if isinstance(v, dict) else None
        except (TypeError, ValueError):
            cur = None
    if cur is None:
        cur = dict(c[1]) if c else {}
    _mem[typ] = (t, cur)
    return cur


def rows(typ):
    """Baris reaksi yang sudah tersimpan: tanggal -> dict."""
    return {d: v for d, v in _load(typ).items() if isinstance(v, dict) and "na" not in v}


def skip_dates(typ, now_ts=None):
    """Tanggal yang tidak perlu diambil lagi: sudah tersimpan, atau ditandai tidak tersedia dalam 14 hari terakhir."""
    t = time.time() if now_ts is None else now_ts
    out = set()
    for d, v in _load(typ).items():
        if not isinstance(v, dict):
            continue
        if "na" not in v or t - float(v["na"]) < NA_DAYS * 86400:
            out.add(d)
    return out


def put(typ, new=None, dead=(), now_ts=None):
    """Simpan baris baru dan tandai tanggal tidak tersedia. Kembalikan True bila ada perubahan."""
    t = time.time() if now_ts is None else now_ts
    if not new and not dead:
        return False
    cur = dict(_load(typ, force=True))
    for d, r in (new or {}).items():
        cur[d] = r
    for d in dead:
        if d not in cur or ("na" in (cur[d] or {})):
            cur[d] = {"na": t}
    _mem[typ] = (time.time(), cur)
    notify.kv_set(PREFIX + typ, json.dumps(cur), ttl=TTL)
    return True
