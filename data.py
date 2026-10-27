"""Pengambil data candle dari sumber nyata untuk beberapa instrumen dan timeframe.

Aturan: tidak pernah membuat data palsu. Jika semua sumber gagal,
get_candles() melempar DataError dan aplikasi menampilkan pesan galat.
Bila yang terpakai adalah pengganti (proxy) dari instrumen asli, catatannya
dikembalikan dan ditampilkan di dasbor.
"""
import os
import re
import time

import pandas as pd
import requests

UA = {"User-Agent": "Mozilla/5.0 (compatible; sinyal-trading/3.0)"}
TIMEOUT = 8        # detik per permintaan
BUDGET = 25        # detik total per siklus pengambilan data

# Pengaturan per timeframe.
#   minutes : panjang candle        expiry_h : umur maksimum sebuah sinyal
#   stale_h : candle terakhir lebih tua dari ini = pasar dianggap tutup
#   ttl     : jeda minimum (detik) antar pengambilan data
#   size    : jumlah candle yang diminta (lebih banyak = statistik lebih berarti)
TF = {
    "M1":  dict(minutes=1,  td="1min",  yahoo=("1m", "5d"),   size=300,  expiry_h=0.0,  stale_h=0.15, chart=60, ttl=60),
    "M5":  dict(minutes=5,  td="5min",  yahoo=("5m", "60d"),  size=1500, expiry_h=1.0,  stale_h=0.35, chart=60, ttl=120),
    "M15": dict(minutes=15, td="15min", yahoo=("15m", "60d"), size=1500, expiry_h=3.0,  stale_h=0.75, chart=60, ttl=300),
    "M30": dict(minutes=30, td="30min", yahoo=("30m", "60d"), size=1500, expiry_h=6.0,  stale_h=1.5,  chart=60, ttl=600),
    "H1":  dict(minutes=60, td="1h",    yahoo=("60m", "60d"), size=500,  expiry_h=12.0, stale_h=3.0,  chart=48, ttl=900),
}
SIGNAL_TFS = ["M5", "M15", "M30", "H1"]      # yang bisa dipilih di dasbor (M1 khusus konfirmasi)

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


def scrub(msg):
    """Hapus kunci API/token dari teks galat sebelum ditampilkan di dasbor."""
    msg = re.sub(r"(apikey=)[^&\s)\"']+", r"\1***", str(msg), flags=re.I)
    msg = re.sub(r"(Bearer\s+)[A-Za-z0-9._\-]+", r"\1***", msg, flags=re.I)
    return msg


OANDA_INST = {"XAUUSD": "XAU_USD", "NASDAQ": "NAS100_USD"}
OANDA_GRAN = {"M1": "M1", "M5": "M5", "M15": "M15", "M30": "M30", "H1": "H1"}


def fetch_oanda(token, instrument, gran, count, env="practice"):
    """Candle CFD dari OANDA (akun demo gratis). Jalan hampir 24 jam, tanpa kuota harian ketat."""
    host = "api-fxtrade.oanda.com" if env == "live" else "api-fxpractice.oanda.com"
    r = requests.get(f"https://{host}/v3/instruments/{instrument}/candles",
                     params={"granularity": gran, "count": min(int(count), 5000), "price": "M"},
                     headers={**UA, "Authorization": f"Bearer {token}"}, timeout=TIMEOUT)
    try:
        j = r.json()
    except ValueError:
        raise DataError(f"OANDA {instrument}: HTTP {r.status_code}, respons bukan JSON")
    if r.status_code != 200 or "candles" not in j:
        raise DataError(f"OANDA {instrument}: {j.get('errorMessage', 'HTTP ' + str(r.status_code))}")
    rows = [(c["time"], c["mid"]["o"], c["mid"]["h"], c["mid"]["l"], c["mid"]["c"])
            for c in j["candles"] if "mid" in c]
    return _frame(rows), f"OANDA {instrument}"


def candidates_for(key):
    """Urutan sumber. NASDAQ_SOURCE=futures: utamakan futures NQ=F (hampir 24 jam,
    lebih mirip CFD NAS100 di broker daripada indeks tunai yang hanya jam bursa AS)."""
    cands = list(SYMBOLS[key]["candidates"])
    if key == "NASDAQ" and os.getenv("NASDAQ_SOURCE", "").strip().lower() == "futures":
        cands.sort(key=lambda c: 0 if c[1] == "NQ=F" else 1)
    if os.getenv("OANDA_TOKEN", "").strip() and key in OANDA_INST:
        cands.insert(0, ("oanda", OANDA_INST[key], None))
    return cands


def fetch_one(provider, sym, tf):
    """Ambil satu sumber. Dipakai get_candles() dan diagnosis."""
    t = TF[tf]
    if provider == "oanda":
        tok = os.getenv("OANDA_TOKEN", "").strip()
        if not tok:
            raise DataError("OANDA: OANDA_TOKEN belum diisi")
        return fetch_oanda(tok, sym, OANDA_GRAN[tf], t["size"], os.getenv("OANDA_ENV", "practice").strip().lower())
    if provider == "td":
        k = os.getenv("TWELVEDATA_API_KEY", "").strip()
        if not k:
            raise DataError("Twelve Data: TWELVEDATA_API_KEY belum diisi")
        return fetch_twelvedata(k, sym, t["td"], t["size"])
    return fetch_yahoo(sym, *t["yahoo"])


def diagnose(key, tf):
    """Coba SEMUA sumber untuk satu instrumen/timeframe dan laporkan hasilnya (untuk pemecahan masalah)."""
    out = []
    for provider, sym, note in candidates_for(key):
        t0 = time.monotonic()
        row = {"provider": provider, "symbol": sym, "proxy": bool(note)}
        try:
            df, src = fetch_one(provider, sym, tf)
            last = df.iloc[-1]["time"]
            age = (pd.Timestamp.now(tz="UTC") - last).total_seconds() / 60
            row.update(ok=True, rows=len(df), last_candle=last.isoformat(), age_minutes=round(age, 1),
                       last_close=round(float(df.iloc[-1]["close"]), 2))
        except Exception as e:  # noqa: BLE001
            row.update(ok=False, error=scrub(e))
        row["ms"] = round((time.monotonic() - t0) * 1000)
        out.append(row)
    return out


def _frame(rows):
    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close"])
    df["time"] = pd.to_datetime(df["time"], utc=True)
    for c in ("open", "high", "low", "close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna().drop_duplicates("time").sort_values("time")
    return df.reset_index(drop=True)


def fetch_twelvedata(api_key, symbol, interval, size):
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


def fetch_yahoo(symbol, interval, rng):
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


def get_candles(key, tf="H1"):
    """Kembalikan (DataFrame candle, nama sumber, catatan atau None)."""
    if key not in SYMBOLS:
        raise DataError(f"Instrumen tidak dikenal: {key}")
    if tf not in TF:
        raise DataError(f"Timeframe tidak dikenal: {tf}")
    start = time.monotonic()
    errors = []
    min_rows = 150 if tf != "M1" else 60
    has_td = bool(os.getenv("TWELVEDATA_API_KEY", "").strip())
    for provider, sym, note in candidates_for(key):
        if time.monotonic() - start > BUDGET:
            errors.append("waktu habis, sumber berikutnya dilewati")
            break
        if provider == "td" and not has_td:
            continue
        try:
            df, src = fetch_one(provider, sym, tf)
            if len(df) >= min_rows:
                return df, src, note
            errors.append(f"{src}: candle terlalu sedikit ({len(df)})")
        except Exception as e:  # noqa: BLE001
            errors.append(scrub(e))
    raise DataError(" | ".join(errors) or "Semua sumber data gagal")
