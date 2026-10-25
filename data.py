"""Pengambil data harga XAUUSD (candle H1) dari sumber nyata.

Aturan: tidak pernah membuat data palsu. Jika semua sumber gagal,
fungsi melempar DataError dan aplikasi menampilkan pesan galat.
"""
import os
import pandas as pd
import requests

UA = {"User-Agent": "Mozilla/5.0 (compatible; sinyal-xauusd/1.0)"}
TIMEOUT = 8


class DataError(Exception):
    pass


def _frame(rows):
    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close"])
    df["time"] = pd.to_datetime(df["time"], utc=True)
    for c in ("open", "high", "low", "close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna().drop_duplicates("time").sort_values("time")
    return df.reset_index(drop=True)


def fetch_twelvedata(api_key, symbol="XAU/USD", interval="1h", size=500):
    r = requests.get(
        "https://api.twelvedata.com/time_series",
        params={"symbol": symbol, "interval": interval, "outputsize": size,
                "timezone": "UTC", "apikey": api_key},
        headers=UA, timeout=TIMEOUT,
    )
    j = r.json()
    if j.get("status") == "error" or "values" not in j:
        raise DataError(f"Twelve Data: {j.get('message', 'respons tidak valid')}")
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


def get_candles():
    """Kembalikan (DataFrame candle H1, nama sumber). Urutan coba:
    1) Twelve Data bila TWELVEDATA_API_KEY diisi (disarankan, spot XAU/USD)
    2) Yahoo XAUUSD=X, lalu GC=F (futures emas; harganya bisa beda dari spot)
    """
    errors = []
    key = os.getenv("TWELVEDATA_API_KEY", "").strip()
    if key:
        try:
            return fetch_twelvedata(key)
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))
    for sym in os.getenv("YAHOO_SYMBOLS", "XAUUSD=X,GC=F").split(","):
        sym = sym.strip()
        if not sym:
            continue
        try:
            df, src = fetch_yahoo(sym)
            if len(df) >= 150:
                return df, src
            errors.append(f"Yahoo {sym}: candle terlalu sedikit ({len(df)})")
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))
    raise DataError(" | ".join(errors) or "Semua sumber data gagal")
