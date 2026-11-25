"""Seed riwayat harga M5 dari MT5 untuk studi reaksi berita (v19.36).

Masalah: studi reaksi tab NEWS mengambil candle M5 di sekitar tiap rilis lampau dari Twelve Data. Untuk tanggal lama
Twelve Data menjawab "No data is available", sehingga progres macet (mis. 31 dari 60). Data M5 dari MT5 Anda sendiri
(broker yang dipakai trading) bisa mengisi jendela itu tanpa kuota dan tanpa internet.

Cara pakai:
  1) Ekspor M5 dari MT5 (Ctrl+U > Bars > pilih simbol, M5, rentang tanggal > Request > Export Bars).
  2) python mt5_seed.py build XAUUSD-STDc_M5.csv --utc-offset ny      (membuat mt5_seed_xauusd_m5.csv.gz, waktu UTC)
  3) Deploy. history_sync() memakai seed untuk tanggal yang jendelanya tercakup penuh; sisanya tetap dari penyedia data.

Aturan: seed tidak menimpa hasil ukur yang sudah tersimpan; tanggal di luar cakupan seed tidak disentuh (tidak ditandai gagal).
NEWS_SEED=0 mematikan; NEWS_SEED_FILE mengganti jalur file.
"""
from __future__ import annotations

import argparse
import os

import pandas as pd

import news

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mt5_seed_xauusd_m5.csv.gz")
_cache = {"key": None, "df": None}


def enabled():
    return os.getenv("NEWS_SEED", "1").strip().lower() not in ("0", "off", "false", "no")


def path():
    return os.getenv("NEWS_SEED_FILE", "").strip() or DEFAULT_PATH


def build(csv_path, out_path=DEFAULT_PATH, utc_offset="ny"):
    """CSV ekspor MT5 -> file seed ringkas (time ISO UTC, open, high, low, close)."""
    import backtest                                   # impor malas: hanya dibutuhkan saat membuat seed
    df = backtest.load_candles(csv_path, utc_offset)
    out = df[["time", "open", "high", "low", "close"]].copy()
    out["time"] = out["time"].dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    out.to_csv(out_path, index=False, compression="gzip", float_format="%.2f")
    _cache["key"] = None
    return len(out), df["time"].iloc[0], df["time"].iloc[-1]


def load():
    """Candle seed (UTC) atau None bila dimatikan atau file tidak ada. Di-cache per file dan waktu ubah."""
    if not enabled():
        return None
    p = path()
    if not os.path.isfile(p):
        return None
    key = (p, os.path.getmtime(p))
    if _cache["key"] != key:
        df = pd.read_csv(p)
        df["time"] = pd.to_datetime(df["time"], utc=True)
        _cache.update(key=key, df=df.sort_values("time").reset_index(drop=True))
    return _cache["df"]


def inject(family, dates):
    """Isi news._win dengan jendela dari seed untuk tanggal yang TERCAKUP PENUH. Kembalikan jumlah yang diisi."""
    try:
        seed = load()
        if seed is None or seed.empty:
            return 0
        lo, hi = seed["time"].iloc[0], seed["time"].iloc[-1]
        n = 0
        for d in dates:
            if (family, d) in news._win:
                continue
            a, b = news._family_bounds(family, d)
            a, b = pd.Timestamp(a), pd.Timestamp(b)
            if a.tzinfo is None:
                a, b = a.tz_localize("UTC"), b.tz_localize("UTC")
            if a < lo or b > hi:
                continue                              # di luar cakupan seed: biarkan penyedia data lain
            w = seed[(seed["time"] >= a) & (seed["time"] <= b)]
            if len(w) >= 20:                          # libur atau pasar tutup: serahkan ke penyedia lain
                news._win[(family, d)] = w.reset_index(drop=True)
                n += 1
        return n
    except Exception:  # noqa: BLE001  - seed tidak boleh menggagalkan halaman NEWS
        return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="buat file seed dari CSV ekspor MT5")
    b.add_argument("csv")
    b.add_argument("--utc-offset", default="ny", help="'ny' (server tutup New York, GMT+2/+3) atau selisih jam, mis. 2")
    b.add_argument("--out", default=DEFAULT_PATH)
    a = ap.parse_args(argv)
    n, t0, t1 = build(a.csv, a.out, a.utc_offset)
    print(f"{n} candle M5 ({t0} -> {t1}) ditulis ke {a.out}")


if __name__ == "__main__":
    main()
