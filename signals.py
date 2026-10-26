"""Hitung indikator dan sinyal dari candle H1. Murni deterministik."""
import os
import pandas as pd

ATR_MULT = float(os.getenv("ATR_MULT", "1.5"))   # jarak SL = ATR x ini
RR_LEVELS = (2.0, 3.0, 4.0)                       # TP1, TP2, TP3
MAX_SCORE = 5
STALE_HOURS = float(os.getenv("STALE_HOURS", "3"))   # lebih tua dari ini = pasar dianggap tutup
SPIKE_PCT = float(os.getenv("SPIKE_PCT", "2.0"))      # lonjakan 1 candle H1 yang dianggap mencurigakan


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn
    out = 100 - 100 / (1 + rs)
    return out.where(dn != 0, 100.0)


def atr(df, n=14):
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - pc).abs(),
                    (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def change_24h(df):
    last = df.iloc[-1]
    ref = df[df["time"] <= last["time"] - pd.Timedelta(hours=24)]
    if ref.empty:
        return None
    base = ref.iloc[-1]["close"]
    return (last["close"] / base - 1) * 100


def max_hourly_move_pct(df, bars=48):
    """Pergerakan terbesar antar candle berurutan (celah antar sesi diabaikan)."""
    t = df.tail(bars + 1)
    chg = t["close"].pct_change().abs() * 100
    contiguous = t["time"].diff() <= pd.Timedelta(hours=2)
    vals = chg[contiguous]
    return float(vals.max()) if len(vals) else 0.0


def analyze(df, source="", symbol="XAUUSD", label=None, note=None,
            chart_bars=48, now=None):
    if len(df) < 120:
        raise ValueError(f"Candle kurang ({len(df)}); butuh minimal 120")
    c = df["close"]
    e20, e50, e100 = ema(c, 20), ema(c, 50), ema(c, 100)
    r, a = rsi(c), atr(df)
    price = float(c.iloc[-1])
    v20, v50, v100 = float(e20.iloc[-1]), float(e50.iloc[-1]), float(e100.iloc[-1])
    rsi_v, atr_v = float(r.iloc[-1]), float(a.iloc[-1])
    chg = change_24h(df)

    reasons, score = [], 0
    if v20 > v50:
        score += 2
        reasons.append(f"EMA20 ({v20:,.2f}) di atas EMA50 ({v50:,.2f}): tren H1 naik (skor +2)")
    else:
        score -= 2
        reasons.append(f"EMA20 ({v20:,.2f}) di bawah EMA50 ({v50:,.2f}): tren H1 turun (skor -2)")
    if price > v100:
        score += 1
        reasons.append(f"Harga {price:,.2f} di atas EMA100 ({v100:,.2f}): tren panjang bullish (skor +1)")
    else:
        score -= 1
        reasons.append(f"Harga {price:,.2f} di bawah EMA100 ({v100:,.2f}): tren panjang bearish (skor -1)")
    if rsi_v > 55:
        score += 1
        reasons.append(f"RSI {rsi_v:.1f}: momentum bullish (skor +1)")
    elif rsi_v < 45:
        score -= 1
        reasons.append(f"RSI {rsi_v:.1f}: momentum bearish (skor -1)")
    else:
        reasons.append(f"RSI {rsi_v:.1f}: netral (skor 0)")
    if chg is not None:
        if chg > 0.5:
            score += 1
            reasons.append(f"Perubahan 24 jam {chg:+.2f}%: naik (skor +1)")
        elif chg < -0.5:
            score -= 1
            reasons.append(f"Perubahan 24 jam {chg:+.2f}%: turun (skor -1)")
        else:
            reasons.append(f"Perubahan 24 jam {chg:+.2f}%: datar (skor 0)")

    if score >= 3:
        direction = "BUY"
    elif score <= -3:
        direction = "SELL"
    else:
        direction = "WAIT"

    warnings = []
    conf = round(abs(score) / MAX_SCORE * 100)
    if direction == "BUY" and rsi_v >= 75:
        conf = max(conf - 10, 0)
        warnings.append("RSI overbought: risiko koreksi, pertimbangkan entry bertahap")
    if direction == "SELL" and rsi_v <= 25:
        conf = max(conf - 10, 0)
        warnings.append("RSI oversold: risiko pantulan, pertimbangkan entry bertahap")

    now = now or pd.Timestamp.now(tz="UTC")
    age_h = (now - df.iloc[-1]["time"]).total_seconds() / 3600
    market_closed = age_h > STALE_HOURS
    if market_closed:
        direction, conf = "WAIT", 0
        warnings.clear()
        warnings.append( f"Pasar tampaknya tutup: candle terakhir {age_h:.0f} jam lalu "
                           f"({df.iloc[-1]['time'].strftime('%Y-%m-%d %H:%M')} UTC). "
                           "Tidak ada level entry sampai ada candle baru.")
    spike = max_hourly_move_pct(df)
    if spike > SPIKE_PCT:
        warnings.append(f"Ada lonjakan {spike:.1f}% dalam satu candle H1 pada 48 candle terakhir. "
                        "Periksa apakah datanya benar sebelum memakai sinyal.")

    levels = None
    if direction != "WAIT":
        sign = 1 if direction == "BUY" else -1
        risk = ATR_MULT * atr_v
        levels = {
            "entry": round(price, 2),
            "stop_loss": round(price - sign * risk, 2),
            "tp": [round(price + sign * risk * k, 2) for k in RR_LEVELS],
            "rr": list(RR_LEVELS),
            "risk_points": round(risk, 2),
        }
        # catatan: TP/SL dihitung dari ATR, bukan prediksi harga

    tail = df.tail(chart_bars)
    return {
        "symbol": symbol,
        "label": label or symbol,
        "timeframe": "H1",
        "source": source,
        "note": note,
        "market_closed": market_closed,
        "candle_time": df.iloc[-1]["time"].isoformat(),
        "direction": direction,
        "score": score,
        "max_score": MAX_SCORE,
        "confidence": conf,
        "price": round(price, 2),
        "indicators": {
            "ema20": round(v20, 2), "ema50": round(v50, 2), "ema100": round(v100, 2),
            "rsi14": round(rsi_v, 1), "atr14": round(atr_v, 2),
            "change_24h_pct": None if chg is None else round(chg, 2),
        },
        "levels": levels,
        "reasons": reasons,
        "warnings": warnings,
        "chart": [{"t": t.isoformat(), "c": round(float(x), 2)}
                  for t, x in zip(tail["time"], tail["close"])],
    }


def summary_text(sig):
    """Ringkasan Bahasa Indonesia dari angka yang sudah dihitung (tanpa data baru)."""
    d = sig["direction"]
    head = {"BUY": "Sinyal BUY.", "SELL": "Sinyal SELL.",
            "WAIT": "Belum ada setup jelas, sebaiknya menunggu."}[d]
    if sig.get("market_closed"):
        head = "Pasar tampaknya tutup, tidak ada sinyal baru."
    body = " ".join(r.split(" (skor")[0] + "." for r in sig["reasons"])
    tail = f" Skor indikator {sig['score']:+d} dari ±{sig['max_score']}."
    return f"{head} {body}{tail}"
