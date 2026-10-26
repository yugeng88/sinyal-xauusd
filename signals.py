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


def split_closed(df, now):
    """Pisahkan candle yang sudah tertutup dari candle H1 yang masih berjalan."""
    last = df.iloc[-1]
    if last["time"] + pd.Timedelta(hours=1) > now:
        return df.iloc[:-1], last
    return df, None


def analyze(df, source="", symbol="XAUUSD", label=None, note=None,
            chart_bars=48, now=None, closed_only=True):
    now = now or pd.Timestamp.now(tz="UTC")
    full = df
    live_price = float(full["close"].iloc[-1])
    if closed_only:
        df, _ = split_closed(full, now)   # indikator hanya dari candle tertutup
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

    age_h = (now - full.iloc[-1]["time"]).total_seconds() / 3600
    market_closed = age_h > STALE_HOURS
    if market_closed:
        direction, conf = "WAIT", 0
        warnings.clear()
        warnings.append( f"Pasar tampaknya tutup: candle terakhir {age_h:.0f} jam lalu "
                           f"({full.iloc[-1]['time'].strftime('%Y-%m-%d %H:%M')} UTC). "
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
        "live_price": round(live_price, 2),
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


# ---------------------------------------------------------------------------
# Pelacakan sinyal: sekali terbit, sinyal TIDAK hilang hanya karena indikator
# berubah. Level dikunci saat terbit dan sinyal berakhir bila: SL tersentuh,
# TP3 tercapai, lewat EXPIRY_HOURS, atau muncul sinyal arah berlawanan.
# Semua dihitung ulang dari data candle nyata, tanpa penyimpanan di server.
# ---------------------------------------------------------------------------
EXPIRY_HOURS = float(os.getenv("EXPIRY_HOURS", "12"))
TRACK_BARS = int(os.getenv("TRACK_BARS", "48"))


def _issue_at(df, i):
    s = analyze(df.iloc[:i + 1], now=df.iloc[i]["time"], closed_only=False)
    return s["direction"], s["levels"], s["confidence"]


def _hits(direction, lv, high, low):
    """(SL tersentuh?, jumlah TP tersentuh) pada satu candle."""
    if direction == "BUY":
        return low <= lv["stop_loss"], sum(1 for t in lv["tp"] if high >= t)
    return high >= lv["stop_loss"], sum(1 for t in lv["tp"] if low <= t)


def track(df, window=TRACK_BARS, expiry_hours=EXPIRY_HOURS, now=None, issue_fn=None):
    """Kembalikan {"active": sinyal berjalan atau None, "recent": riwayat terbaru}.

    Sinyal hanya diterbitkan dari candle TERTUTUP. Candle yang masih berjalan
    dipakai hanya untuk mengecek apakah SL/TP sudah tersentuh.
    Bila SL dan TP tersentuh dalam candle yang sama, SL dianggap lebih dulu
    (asumsi konservatif karena urutan di dalam candle tidak diketahui).
    """
    now = now or pd.Timestamp.now(tz="UTC")
    closed, forming = split_closed(df, now)
    issue_fn = issue_fn or (lambda i: _issue_at(closed, i))
    n = len(closed)
    start = max(119, n - window)
    cur, done = None, []

    def finish(outcome):
        nonlocal cur
        done.append({**{k: cur[k] for k in ("direction", "time", "levels", "confidence", "tp_hit")},
                     "outcome": outcome})
        cur = None

    for i in range(start, n):
        row = closed.iloc[i]
        d, lv, conf = issue_fn(i)
        if cur is not None and i > cur["idx"]:
            sl, tps = _hits(cur["direction"], cur["levels"], row["high"], row["low"])
            if sl:
                finish("SL")
            else:
                cur["tp_hit"] = max(cur["tp_hit"], tps)
                if cur["tp_hit"] >= 3:
                    finish("TP3")
                elif (row["time"] - cur["time"]).total_seconds() / 3600 >= expiry_hours:
                    finish("EXPIRED")
                elif d in ("BUY", "SELL") and d != cur["direction"]:
                    finish("REVERSED")
        if cur is None and d in ("BUY", "SELL") and lv:
            cur = {"idx": i, "time": row["time"], "direction": d, "levels": lv,
                   "confidence": conf, "tp_hit": 0}

    if cur is not None and forming is not None:        # cek SL/TP pada candle berjalan
        sl, tps = _hits(cur["direction"], cur["levels"], forming["high"], forming["low"])
        if sl:
            finish("SL")
        else:
            cur["tp_hit"] = max(cur["tp_hit"], tps)
            if cur["tp_hit"] >= 3:
                finish("TP3")

    last_time = df.iloc[-1]["time"]
    market_closed = (now - last_time).total_seconds() / 3600 > STALE_HOURS
    live = float(df["close"].iloc[-1])
    active = None
    if cur is not None:
        age_h = (now - cur["time"]).total_seconds() / 3600
        if age_h >= expiry_hours:
            finish("EXPIRED")
        elif market_closed:
            done.append({**{k: cur[k] for k in ("direction", "time", "levels", "confidence", "tp_hit")},
                         "outcome": "OPEN"})
        else:
            sign = 1 if cur["direction"] == "BUY" else -1
            active = {"direction": cur["direction"], "time": cur["time"].isoformat(),
                      "levels": cur["levels"], "confidence": cur["confidence"],
                      "tp_hit": cur["tp_hit"], "age_hours": round(age_h, 1),
                      "expires_in_hours": round(expiry_hours - age_h, 1),
                      "live_price": round(live, 2),
                      "move_points": round((live - cur["levels"]["entry"]) * sign, 2)}
    recent = [{"time": r["time"].isoformat(), "direction": r["direction"],
               "entry": r["levels"]["entry"], "stop_loss": r["levels"]["stop_loss"],
               "tp": r["levels"]["tp"], "confidence": r["confidence"],
               "tp_hit": r["tp_hit"], "outcome": r["outcome"]} for r in done][::-1][:10]
    return {"active": active, "recent": recent, "expiry_hours": expiry_hours}
