"""Pengambil data harga candle H1 dari sumber nyata untuk beberapa instrumen.

Aturan: tidak pernah membuat data palsu. Jika semua sumber gagal,
get_candles() melempar DataError dan aplikasi menampilkan pesan galat.
Bila yang terpakai adalah pengganti (proxy) dari instrumen asli, catatannya
dikembalikan dan ditampilkan di dasbor.
"""
import os
import time

import pandas as pd
import requests

UA = {"User-Agent": "Mozilla/5.0 (compatible; sinyal-trading/2.0)"}
TIMEOUT = 8        # detik per permintaan
BUDGET = 25        # detik total per siklus pengambilan data

NOTE_GC = "Futures emas (GC=F): harga bisa berbeda dari spot XAUUSD."
NOTE_QQQ = ("Memakai ETF QQQ (pelacak Nasdaq-100): harga dalam USD per unit ETF, "
            "BUKAN poin indeks NAS100/US100. Jangan pakai level ini langsung untuk CFD.")
NOTE_NQ = ("Memakai futures Nasdaq-100 (NQ=F): harga bisa berbeda dari "
           "indeks atau CFD NAS100/US100.")

# (penyedia, simbol, catatan bila ini pengganti). Dicoba berurutan.
SYMBOLS = {
    "XAUUSD": {
        "label": "XAUUSD",
        "candidates": [
            ("td", "XAU/USD", None),
            ("yahoo", "XAUUSD=X", None),
            ("yahoo", "GC=F", NOTE_GC),
        ],
    },
    "NASDAQ": {
        "label": "NASDAQ 100",
        "candidates": [
            ("td", "NDX", None),
            ("yahoo", "^NDX", None),
            ("td", "QQQ", NOTE_QQQ),
            ("yahoo", "NQ=F", NOTE_NQ),
        ],
    },
}


class DataError(Exception):
    pass


def _frame(rows):
    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close"])
    df["time"] = pd.to_datetime(df["time"], utc=True)
    for c in ("open", "high", "low", "close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna().drop_duplicates("time").sort_values("time")
    return df.reset_index(drop=True)


def fetch_twelvedata(api_key, symbol, interval="1h", size=500):
    r = requests.get(
        "https://api.twelvedata.com/time_series",
        params={"symbol": symbol, "interval": interval, "outputsize": size,
                "timezone": "UTC", "apikey": api_key},
        headers=UA, timeout=TIMEOUT,
    )
    j = r.json()
    if j.get("status") == "error" or "values" not in j:
        raise DataError(f"Twelve Data {symbol}: {j.get('message', 'respons tidak valid')}")
    rows = [(v["datetime"], v["open"], v["high"], v["low"], v["close"])
            for v in j["values"]]
    return _frame(rows), f"Twelve Data {symbol}"


def fetch_yahoo(symbol, interval="60m", rng="60d"):
    r = requests.get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
        params={"interval": interval, "range": rng},
        headers=UA, timeout=TIMEOUT,
    )
    if r.status_code != 200:
        raise DataError(f"Yahoo {symbol}: HTTP {r.status_code}")
    j = r.json()
    res = (j.get("chart") or {}).get("result")
    if not res:
        err = (j.get("chart") or {}).get("error")
        raise DataError(f"Yahoo {symbol}: {err or 'tidak ada hasil'}")
    res = res[0]
    q = res["indicators"]["quote"][0]
    ts = res.get("timestamp") or []
    rows = list(zip(pd.to_datetime(ts, unit="s", utc=True),
                    q["open"], q["high"], q["low"], q["close"]))
    return _frame(rows), f"Yahoo Finance {symbol}"


def get_candles(key):
    """Kembalikan (DataFrame candle H1, nama sumber, catatan atau None)."""
    cfg = SYMBOLS.get(key)
    if cfg is None:
        raise DataError(f"Instrumen tidak dikenal: {key}")
    td_key = os.getenv("TWELVEDATA_API_KEY", "").strip()
    start = time.monotonic()
    errors = []
    for provider, sym, note in cfg["candidates"]:
        if time.monotonic() - start > BUDGET:
            errors.append("waktu habis, sumber berikutnya dilewati")
            break
        try:
            if provider == "td":
                if not td_key:
                    continue
                df, src = fetch_twelvedata(td_key, sym)
            else:
                df, src = fetch_yahoo(sym)
            if len(df) >= 150:
                return df, src, note
            errors.append(f"{src}: candle terlalu sedikit ({len(df)})")
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))
    raise DataError(" | ".join(errors) or "Semua sumber data gagal")
