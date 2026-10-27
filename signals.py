"""Indikator, sinyal, pelacakan sinyal, statistik, dan konfirmasi entri M1.

Semua deterministik dan dihitung dari data candle nyata. Tidak ada data buatan.
"""
import os

import numpy as np
import pandas as pd

import data as D

ATR_MULT = float(os.getenv("ATR_MULT", "1.5"))     # jarak SL = ATR14 x ini
RR_LEVELS = (2.0, 3.0, 4.0)                         # TP1, TP2, TP3
MAX_SCORE = 5
SPIKE_PCT = float(os.getenv("SPIKE_PCT", "2.0"))    # per candle H1; diskalakan untuk TF lain
COOLDOWN_BARS = int(os.getenv("COOLDOWN_BARS", "4"))  # jeda setelah SL sebelum sinyal arah sama
ZONE_R = float(os.getenv("ZONE_R", "0.5"))          # batas "mengejar" harga: 0,5 x jarak SL


# ---------------------------------------------------------------- indikator
def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    out = 100 - 100 / (1 + up / dn)
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
    return (last["close"] / ref.iloc[-1]["close"] - 1) * 100


def split_closed(df, now, minutes=60):
    """Pisahkan candle yang sudah tertutup dari candle yang masih berjalan."""
    last = df.iloc[-1]
    if last["time"] + pd.Timedelta(minutes=minutes) > now:
        return df.iloc[:-1], last
    return df, None


def make_levels(direction, price, atr_v):
    sign = 1 if direction == "BUY" else -1
    risk = ATR_MULT * atr_v
    return {
        "entry": round(price, 2),
        "stop_loss": round(price - sign * risk, 2),
        "tp": [round(price + sign * risk * k, 2) for k in RR_LEVELS],
        "rr": list(RR_LEVELS),
        "risk_points": round(risk, 2),
    }


def max_move_pct(df, minutes, bars):
    """Pergerakan terbesar antar candle berurutan (celah antar sesi diabaikan)."""
    t = df.tail(bars + 1)
    chg = t["close"].pct_change().abs() * 100
    contiguous = t["time"].diff() <= pd.Timedelta(minutes=2 * minutes)
    vals = chg[contiguous]
    return float(vals.max()) if len(vals) else 0.0


# ------------------------------------------------------------------ analisis
def analyze(df, source="", symbol="XAUUSD", label=None, note=None, tf="H1",
            chart_bars=None, now=None, closed_only=True):
    cfg = D.TF[tf]
    minutes = cfg["minutes"]
    chart_bars = chart_bars or cfg["chart"]
    now = now or pd.Timestamp.now(tz="UTC")
    full = df
    live_price = float(full["close"].iloc[-1])
    if closed_only:
        df, _ = split_closed(full, now, minutes)   # indikator hanya dari candle tertutup
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
        reasons.append(f"EMA20 ({v20:,.2f}) di atas EMA50 ({v50:,.2f}): tren {tf} naik (skor +2)")
    else:
        score -= 2
        reasons.append(f"EMA20 ({v20:,.2f}) di bawah EMA50 ({v50:,.2f}): tren {tf} turun (skor -2)")
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

    direction = "BUY" if score >= 3 else "SELL" if score <= -3 else "WAIT"

    warnings = []
    conf = round(abs(score) / MAX_SCORE * 100)
    if direction == "BUY" and rsi_v >= 75:
        conf = max(conf - 10, 0)
        warnings.append("RSI overbought: risiko koreksi, pertimbangkan entry bertahap")
    if direction == "SELL" and rsi_v <= 25:
        conf = max(conf - 10, 0)
        warnings.append("RSI oversold: risiko pantulan, pertimbangkan entry bertahap")

    age_h = (now - full.iloc[-1]["time"]).total_seconds() / 3600
    market_closed = age_h > cfg["stale_h"]
    if market_closed:
        direction, conf = "WAIT", 0
        warnings.clear()
        age_txt = f"{age_h * 60:.0f} menit" if age_h < 2 else f"{age_h:.0f} jam"
        warnings.append(f"Pasar tampaknya tutup: candle terakhir {age_txt} lalu "
                        f"({full.iloc[-1]['time'].strftime('%Y-%m-%d %H:%M')} UTC). "
                        "Tidak ada level entry sampai ada candle baru.")
    spike_limit = SPIKE_PCT * (minutes / 60) ** 0.5
    spike = max_move_pct(df, minutes, chart_bars)
    if spike > spike_limit:
        warnings.append(f"Ada lonjakan {spike:.2f}% dalam satu candle {tf} pada {chart_bars} candle terakhir. "
                        "Periksa apakah datanya benar sebelum memakai sinyal.")

    levels = make_levels(direction, price, atr_v) if direction != "WAIT" else None

    tail = df.tail(chart_bars)
    return {
        "symbol": symbol,
        "label": label or symbol,
        "timeframe": tf,
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


# ------------------------------------------------- sinyal untuk semua candle
def issue_arrays(df):
    """Arah, keyakinan, harga, dan ATR untuk SETIAP candle sekaligus.

    EMA/RSI/ATR bersifat kausal (adjust=False), jadi nilainya di candle i sama
    persis dengan hasil analyze() pada potongan df[:i+1]. Ini diuji.
    """
    c = df["close"].astype(float)
    e20, e50, e100 = ema(c, 20).to_numpy(), ema(c, 50).to_numpy(), ema(c, 100).to_numpy()
    r, a = rsi(c).to_numpy(), atr(df).to_numpy()
    t = df["time"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy()
    ref = np.searchsorted(t, t - np.timedelta64(24, "h"), side="right") - 1
    cv = c.to_numpy()
    with np.errstate(invalid="ignore"):
        chg = np.where(ref >= 0, (cv / cv[np.clip(ref, 0, None)] - 1) * 100, np.nan)
        score = (np.where(e20 > e50, 2, -2) + np.where(cv > e100, 1, -1)
                 + np.where(r > 55, 1, np.where(r < 45, -1, 0))
                 + np.where(chg > 0.5, 1, np.where(chg < -0.5, -1, 0)))
    direction = np.where(score >= 3, "BUY", np.where(score <= -3, "SELL", "WAIT"))
    conf = np.round(np.abs(score) / MAX_SCORE * 100)
    pen = ((direction == "BUY") & (r >= 75)) | ((direction == "SELL") & (r <= 25))
    conf = np.maximum(conf - 10 * pen, 0).astype(int)
    return {"direction": direction, "conf": conf, "price": cv, "atr": a}


def _issue_from_arrays(closed):
    ar = issue_arrays(closed)

    def fn(i):
        d = str(ar["direction"][i])
        if d == "WAIT":
            return "WAIT", None, 0
        return d, make_levels(d, float(ar["price"][i]), float(ar["atr"][i])), int(ar["conf"][i])
    return fn


def _issue_at(df, i):
    """Versi lambat (analyze pada potongan). Dipakai untuk menguji issue_arrays."""
    s = analyze(df.iloc[:i + 1], now=df.iloc[i]["time"], closed_only=False)
    return s["direction"], s["levels"], s["confidence"]


# ------------------------------------------------------- pelacakan sinyal
def _hits(direction, lv, high, low):
    """(SL tersentuh?, jumlah TP tersentuh) pada satu candle."""
    if direction == "BUY":
        return low <= lv["stop_loss"], sum(1 for t in lv["tp"] if high >= t)
    return high >= lv["stop_loss"], sum(1 for t in lv["tp"] if low <= t)


def track(df, tf="H1", expiry_hours=None, now=None, issue_fn=None, cooldown_bars=None):
    """Kembalikan {"active", "recent", "stats", "expiry_hours"}.

    - Sinyal hanya diterbitkan dari candle TERTUTUP; candle berjalan hanya dipakai
      untuk mengecek SL/TP.
    - Level dikunci saat terbit. Sinyal berakhir: SL tersentuh, TP3 tercapai,
      lewat expiry_hours, atau muncul sinyal arah berlawanan.
    - Bila SL dan TP tersentuh dalam satu candle, SL dianggap lebih dulu.
    - Setelah SL, sinyal arah sama diblokir selama `cooldown_bars` candle.
    """
    cfg = D.TF[tf]
    minutes = cfg["minutes"]
    expiry_hours = cfg["expiry_h"] if expiry_hours is None else expiry_hours
    cooldown = COOLDOWN_BARS if cooldown_bars is None else cooldown_bars
    now = now or pd.Timestamp.now(tz="UTC")
    closed, forming = split_closed(df, now, minutes)
    issue_fn = issue_fn or _issue_from_arrays(closed)
    n = len(closed)
    start = min(119, max(n - 1, 0))
    blocked = {"BUY": -10 ** 9, "SELL": -10 ** 9}
    cur, done = None, []

    def finish(outcome, i):
        nonlocal cur
        done.append({**{k: cur[k] for k in ("direction", "time", "levels", "confidence", "tp_hit")},
                     "outcome": outcome})
        if outcome == "SL":
            blocked[cur["direction"]] = i
        cur = None

    for i in range(start, n):
        row = closed.iloc[i]
        d, lv, conf = issue_fn(i)
        if cur is not None and i > cur["idx"]:
            sl, tps = _hits(cur["direction"], cur["levels"], row["high"], row["low"])
            if sl:
                finish("SL", i)
            else:
                cur["tp_hit"] = max(cur["tp_hit"], tps)
                if cur["tp_hit"] >= 3:
                    finish("TP3", i)
                elif (row["time"] - cur["time"]).total_seconds() / 3600 >= expiry_hours:
                    finish("EXPIRED", i)
                elif d in ("BUY", "SELL") and d != cur["direction"]:
                    finish("REVERSED", i)
        if cur is None and d in ("BUY", "SELL") and lv and i > blocked[d] + cooldown:
            cur = {"idx": i, "time": row["time"], "direction": d, "levels": lv,
                   "confidence": conf, "tp_hit": 0}

    if cur is not None and forming is not None:        # candle berjalan: hanya cek SL/TP
        sl, tps = _hits(cur["direction"], cur["levels"], forming["high"], forming["low"])
        if sl:
            finish("SL", n)
        else:
            cur["tp_hit"] = max(cur["tp_hit"], tps)
            if cur["tp_hit"] >= 3:
                finish("TP3", n)

    last_time = df.iloc[-1]["time"]
    market_closed = (now - last_time).total_seconds() / 3600 > cfg["stale_h"]
    live = float(df["close"].iloc[-1])
    active = None
    if cur is not None:
        age_h = (now - cur["time"]).total_seconds() / 3600
        if age_h >= expiry_hours:
            finish("EXPIRED", n)
        elif market_closed:
            done.append({**{k: cur[k] for k in ("direction", "time", "levels", "confidence", "tp_hit")},
                         "outcome": "OPEN"})
        else:
            sign = 1 if cur["direction"] == "BUY" else -1
            active = {"direction": cur["direction"], "time": cur["time"].isoformat(),
                      "time_close": (cur["time"] + pd.Timedelta(minutes=minutes)).isoformat(),
                      "levels": cur["levels"], "confidence": cur["confidence"],
                      "tp_hit": cur["tp_hit"], "age_hours": round(age_h, 2),
                      "expires_in_hours": round(expiry_hours - age_h, 2),
                      "live_price": round(live, 2),
                      "move_points": round((live - cur["levels"]["entry"]) * sign, 2)}

    fin = [r for r in done if r["outcome"] != "OPEN"]
    stats = {
        "total": len(fin),
        "tp1plus": sum(1 for r in fin if r["tp_hit"] >= 1),
        "tp3": sum(1 for r in fin if r["outcome"] == "TP3"),
        "sl_after_tp": sum(1 for r in fin if r["outcome"] == "SL" and r["tp_hit"] >= 1),
        "sl_first": sum(1 for r in fin if r["outcome"] == "SL" and r["tp_hit"] == 0),
        "no_result": sum(1 for r in fin if r["outcome"] in ("EXPIRED", "REVERSED") and r["tp_hit"] == 0),
        "from": closed.iloc[start]["time"].isoformat() if n else None,
        "to": closed.iloc[-1]["time"].isoformat() if n else None,
        "days": round((closed.iloc[-1]["time"] - closed.iloc[start]["time"]).total_seconds() / 86400, 1) if n else 0,
        "cooldown_bars": cooldown,
    }
    recent = [{"time": r["time"].isoformat(), "direction": r["direction"],
               "entry": r["levels"]["entry"], "stop_loss": r["levels"]["stop_loss"],
               "tp": r["levels"]["tp"], "confidence": r["confidence"],
               "tp_hit": r["tp_hit"], "outcome": r["outcome"]} for r in done][::-1][:10]
    return {"active": active, "recent": recent, "stats": stats,
            "expiry_hours": expiry_hours, "tf": tf}


# --------------------------------------------------------- konfirmasi M1
def confirm_m1(m1, direction, levels, issued_close, now=None):
    """Konfirmasi entri di M1 untuk sinyal dari timeframe lebih besar.

    TERKONFIRMASI bila pada candle M1 tertutup terakhir SEMUA benar:
      1) EMA9 berada di sisi arah terhadap EMA21
      2) close berada di sisi arah terhadap EMA9
      3) RSI(14) di sisi arah terhadap 50 (>50 untuk BUY, <50 untuk SELL)
      4) harga belum menyentuh SL dan belum "mengejar" lebih dari ZONE_R x jarak SL
         dari entry sinyal
    Aturan ini heuristik; belum divalidasi sebagai peningkat hasil.
    """
    now = now or pd.Timestamp.now(tz="UTC")
    closed, _ = split_closed(m1, now, 1)
    last_time = m1.iloc[-1]["time"]
    age_min = (now - last_time).total_seconds() / 60
    if len(closed) < 40:
        return {"state": "NODATA", "message": "Candle M1 terlalu sedikit untuk konfirmasi."}
    if age_min > D.TF["M1"]["stale_h"] * 60:
        return {"state": "STALE",
                "message": f"Candle M1 terakhir {age_min:.0f} menit lalu (pasar tutup atau data tertunda)."}
    sign = 1 if direction == "BUY" else -1
    entry, sl, risk = levels["entry"], levels["stop_loss"], levels["risk_points"]
    c = closed["close"]
    e9, e21, r = ema(c, 9), ema(c, 21), rsi(c)
    trend = ((e9 - e21) * sign > 0)
    side = ((c - e9) * sign > 0)
    mom = ((r - 50) * sign > 0)
    if direction == "BUY":
        zone = (c > sl) & (c <= entry + ZONE_R * risk)
    else:
        zone = (c < sl) & (c >= entry - ZONE_R * risk)
    flag = trend & side & mom & zone
    after = (closed["time"] >= issued_close).to_numpy()
    hit = np.where(flag.to_numpy() & after)[0]
    first = None if len(hit) == 0 else int(hit[0])
    now_ok = bool(flag.iloc[-1]) and bool(after[-1])
    px = float(c.iloc[-1])
    up = "atas" if direction == "BUY" else "bawah"
    checks = [
        {"name": f"EMA9 di {up} EMA21", "ok": bool(trend.iloc[-1]),
         "detail": f"{float(e9.iloc[-1]):.2f} vs {float(e21.iloc[-1]):.2f}"},
        {"name": f"Close M1 di {up} EMA9", "ok": bool(side.iloc[-1]),
         "detail": f"{px:.2f} vs {float(e9.iloc[-1]):.2f}"},
        {"name": f"RSI M1 {'>' if direction == 'BUY' else '<'} 50", "ok": bool(mom.iloc[-1]),
         "detail": f"{float(r.iloc[-1]):.0f}"},
        {"name": "Harga di zona entry (belum kena SL, tidak mengejar)", "ok": bool(zone.iloc[-1]),
         "detail": f"{px:.2f}; SL {sl:.2f}; batas kejar "
                   f"{(entry + sign * ZONE_R * risk):.2f}"},
    ]
    out = {"state": "CONFIRMED" if now_ok else "WAIT", "checks": checks,
           "m1_time": closed.iloc[-1]["time"].isoformat(), "price": round(px, 2),
           "first_time": None, "first_price": None}
    if first is not None:
        out["first_time"] = closed.iloc[first]["time"].isoformat()
        out["first_price"] = round(float(c.iloc[first]), 2)
    return out
