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
CONSENSUS_SYMBOLS = ("XAUUSD", "NASDAQ")            # instrumen yang memakai mesin 3-strategi


# ------------------------------------------------ profil risiko per instrumen (v18)
# Nilai awal (bisa diubah lewat env, mis. ATR_MULT_NASDAQ=2.0). Env khusus instrumen menang atas env umum
# (ATR_MULT), lalu default di bawah. Default NASDAQ lebih lebar karena indeks lebih berisik dan sering gap;
# itu asumsi awal untuk diamati di akun demo, bukan hasil backtest.
_PROFILE_DEFAULTS = {
    "XAUUSD": dict(atr_mult=1.5, sl_min=1.0, sl_max=2.5, sl_buffer=0.1, rr="2,3,4",
                   zone_r=0.5, max_age_bars=2, risk_pct=1.0, point_value=100.0),
    "NASDAQ": dict(atr_mult=1.8, sl_min=1.2, sl_max=3.0, sl_buffer=0.1, rr="2,3,4",
                   zone_r=0.4, max_age_bars=2, risk_pct=0.5, point_value=1.0),
}


def _envf(name, sym, default):
    raw = os.getenv(f"{name}_{sym}") or os.getenv(name)
    try:
        return float(raw) if raw not in (None, "") else float(default)
    except ValueError:
        return float(default)


def _parse_rr(raw, default):
    try:
        v = tuple(float(x) for x in str(raw).split(","))
        if len(v) == 3 and all(x > 0 for x in v) and list(v) == sorted(v):
            return v
    except ValueError:
        pass
    return tuple(float(x) for x in default.split(","))


def profile(symbol):
    """Pengaturan risiko aktif untuk satu instrumen (env dibaca tiap panggilan)."""
    sym = symbol if symbol in _PROFILE_DEFAULTS else "XAUUSD"
    d = _PROFILE_DEFAULTS[sym]
    rr_raw = os.getenv(f"RR_{sym}") or os.getenv("RR_LEVELS") or d["rr"]
    return {
        "symbol": sym,
        "atr_mult": _envf("ATR_MULT", sym, d["atr_mult"]),
        "sl_min": _envf("SL_MIN_ATR", sym, d["sl_min"]),
        "sl_max": _envf("SL_MAX_ATR", sym, d["sl_max"]),
        "sl_buffer": _envf("SL_BUFFER_ATR", sym, d["sl_buffer"]),
        "rr": _parse_rr(rr_raw, d["rr"]),
        "zone_r": _envf("ZONE_R", sym, d["zone_r"]),
        "max_age_bars": int(_envf("ENTRY_MAX_BARS", sym, d["max_age_bars"])),
        "risk_pct": _envf("RISK_PCT", sym, d["risk_pct"]),
        "point_value": _envf("POINT_VALUE", sym, d["point_value"]),
    }


def public_profile(symbol):
    p = profile(symbol)
    p["rr"] = list(p["rr"])
    return p


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
    feed = df.attrs.get("data_time")              # waktu transaksi terakhir di sumber data (Yahoo telat ~10 menit untuk futures)
    if feed is not None and pd.Timestamp(feed) < now:
        now = pd.Timestamp(feed)
    if last["time"] + pd.Timedelta(minutes=minutes) > now:
        return df.iloc[:-1], last
    return df, None


def make_levels(direction, price, atr_v, symbol="XAUUSD", struct=None):
    """SL/TP dinamis per instrumen.

    SL = jarak ke ekstrem struktur terakhir (`struct`) + buffer, dibatasi antara sl_min dan sl_max x ATR.
    Tanpa struktur, SL = atr_mult x ATR. TP = risiko x RR instrumen (skala mengikuti jarak SL nyata).
    """
    p = profile(symbol)
    sign = 1 if direction == "BUY" else -1
    risk, mode = p["atr_mult"] * atr_v, "atr"
    if struct is not None and np.isfinite(struct) and struct > 0:
        raw = float(struct) + p["sl_buffer"] * atr_v
        risk = min(max(raw, p["sl_min"] * atr_v), p["sl_max"] * atr_v)
        mode = "structure"
    return {
        "entry": round(price, 2),
        "stop_loss": round(price - sign * risk, 2),
        "tp": [round(price + sign * risk * k, 2) for k in p["rr"]],
        "rr": list(p["rr"]),
        "risk_points": round(risk, 2),
        "sl_mode": mode,
        "risk_atr": round(risk / atr_v, 2) if atr_v > 0 else None,
    }


def max_move_pct(df, minutes, bars):
    """Pergerakan terbesar antar candle berurutan (celah antar sesi diabaikan)."""
    t = df.tail(bars + 1)
    chg = t["close"].pct_change().abs() * 100
    contiguous = t["time"].diff() <= pd.Timedelta(minutes=2 * minutes)
    vals = chg[contiguous]
    return float(vals.max()) if len(vals) else 0.0


def strategy_arrays(df):
    """Tiga setup kausal berbasis candle tertutup; tidak memakai candle masa depan.

    Strategi: liquidity sweep reversal, trend-pullback, dan momentum breakout.
    Konsensus BUY/SELL hanya muncul bila sedikitnya dua strategi searah.
    Ini adalah aturan awal untuk diuji, bukan edge/profit yang sudah terbukti.
    """
    c = df["close"].astype(float)
    o = df["open"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    a = atr(df)
    e20, e50 = ema(c, 20), ema(c, 50)
    rv = rsi(c)

    prior_low = l.shift(1).rolling(12, min_periods=12).min()
    prior_high = h.shift(1).rolling(12, min_periods=12).max()
    body = (c - o).abs()
    lower_wick = pd.concat([o, c], axis=1).min(axis=1) - l
    upper_wick = h - pd.concat([o, c], axis=1).max(axis=1)

    # 1) Sweep: harga menembus swing 12 candle lalu close kembali di dalam range.
    sweep_buy = (l < prior_low) & (c > prior_low) & (c > o) & (lower_wick >= body * 0.5)
    sweep_sell = (h > prior_high) & (c < prior_high) & (c < o) & (upper_wick >= body * 0.5)

    # 2) Pullback: tren EMA20/50, sentuh area EMA20 dalam toleransi 0.35 ATR,
    # lalu candle tutup kembali searah tren dengan RSI di sisi 50.
    tol = a * 0.35
    pull_buy = (e20 > e50) & (l <= e20 + tol) & (c > e20) & (c > o) & (rv > 50)
    pull_sell = (e20 < e50) & (h >= e20 - tol) & (c < e20) & (c < o) & (rv < 50)

    # 3) Breakout: close melewati high/low 20 candle sebelumnya dengan body >= 0.5 ATR.
    range_high = h.shift(1).rolling(20, min_periods=20).max()
    range_low = l.shift(1).rolling(20, min_periods=20).min()
    break_buy = (c > range_high) & (c > o) & (body >= a * 0.5)
    break_sell = (c < range_low) & (c < o) & (body >= a * 0.5)

    names = ("liquidity_sweep", "trend_pullback", "momentum_breakout")
    buy = np.column_stack([sweep_buy, pull_buy, break_buy]).astype(bool)
    sell = np.column_stack([sweep_sell, pull_sell, break_sell]).astype(bool)
    buy_n, sell_n = buy.sum(axis=1), sell.sum(axis=1)
    direction = np.where(buy_n >= 2, "BUY", np.where(sell_n >= 2, "SELL", "WAIT"))
    count = np.where(direction == "BUY", buy_n, np.where(direction == "SELL", sell_n, 0))
    # Jarak close ke ekstrem struktur 8 candle (termasuk candle ini): dasar SL dinamis.
    swing_lo, swing_hi = l.rolling(8, min_periods=1).min(), h.rolling(8, min_periods=1).max()
    stop_dist = np.where(direction == "BUY", (c - swing_lo).to_numpy(),
                         np.where(direction == "SELL", (swing_hi - c).to_numpy(), np.nan)).astype(float)
    return {
        "direction": direction,
        "stop_dist": stop_dist,
        "confidence": np.where(count == 3, 90, np.where(count == 2, 70, 0)).astype(int),
        "votes": count.astype(int),
        "strategies": {name: np.where(buy[:, i], "BUY", np.where(sell[:, i], "SELL", "WAIT"))
                       for i, name in enumerate(names)},
    }


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

    legacy_direction = "BUY" if score >= 3 else "SELL" if score <= -3 else "WAIT"
    warnings = []
    strategy_engine = None
    struct = None
    if symbol in CONSENSUS_SYMBOLS:
        strat = strategy_arrays(df)
        struct = float(strat["stop_dist"][-1])
        direction = str(strat["direction"][-1])
        conf = int(strat["confidence"][-1])
        votes = int(strat["votes"][-1])
        strategy_labels = {
            "liquidity_sweep": "Liquidity Sweep Reversal",
            "trend_pullback": "Trend Pullback",
            "momentum_breakout": "Momentum Breakout",
        }
        strategy_status = {strategy_labels[k]: str(v[-1]) for k, v in strat["strategies"].items()}
        strategy_engine = {"name": "3-Strategy Consensus", "minimum_votes": 2,
                           "votes": votes, "strategies": strategy_status,
                           "status": "CONFIRMED" if direction != "WAIT" else "WAIT"}
        if direction == "WAIT":
            reasons.append("Konfirmasi strategi belum mencapai minimal 2 dari 3 strategi yang searah.")
        else:
            agreeing = [name for name, side in strategy_status.items() if side == direction]
            reasons.append(f"Konsensus {votes}/3 strategi untuk {direction}: " + ", ".join(agreeing) + ".")
        reasons.append(f"Arah indikator lama: {legacy_direction} (dipertahankan sebagai informasi pembanding).")
    else:
        direction = legacy_direction
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

    levels = make_levels(direction, price, atr_v, symbol, struct) if direction != "WAIT" else None

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
        "legacy_direction": legacy_direction,
        "strategy_engine": strategy_engine,
        "risk_profile": public_profile(symbol),
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
    body = " ".join(r.split(" (skor")[0].rstrip(".") + "." for r in sig["reasons"])
    tail = f" Skor indikator {sig['score']:+d} dari ±{sig['max_score']}."
    return f"{head} {body}{tail}"


# ------------------------------------------------- sinyal untuk semua candle
def issue_arrays(df, symbol="XAUUSD"):
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
    stop = np.full(len(cv), np.nan)
    if symbol in CONSENSUS_SYMBOLS:
        strat = strategy_arrays(df)
        direction, conf, stop = strat["direction"], strat["confidence"], strat["stop_dist"]
    else:
        direction = np.where(score >= 3, "BUY", np.where(score <= -3, "SELL", "WAIT"))
        conf = np.round(np.abs(score) / MAX_SCORE * 100)
        pen = ((direction == "BUY") & (r >= 75)) | ((direction == "SELL") & (r <= 25))
        conf = np.maximum(conf - 10 * pen, 0).astype(int)
    return {"direction": direction, "conf": conf, "price": cv, "atr": a, "stop": stop}


def _issue_from_arrays(closed, symbol="XAUUSD"):
    ar = issue_arrays(closed, symbol=symbol)

    def fn(i):
        d = str(ar["direction"][i])
        if d == "WAIT":
            return "WAIT", None, 0
        return (d, make_levels(d, float(ar["price"][i]), float(ar["atr"][i]), symbol, float(ar["stop"][i])),
                int(ar["conf"][i]))
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


def track(df, tf="H1", expiry_hours=None, now=None, issue_fn=None, cooldown_bars=None, symbol="XAUUSD"):
    """Kembalikan {"active", "recent", "stats", "expiry_hours"}.

    - Sinyal hanya diterbitkan dari candle TERTUTUP; candle berjalan hanya dipakai
      untuk mengecek SL/TP.
    - Level dikunci saat terbit. Sinyal berakhir: SL tersentuh, TP3 tercapai,
      lewat expiry_hours, atau muncul sinyal arah berlawanan.
    - Bila SL dan TP tersentuh dalam satu candle, SL dianggap lebih dulu.
    - Setelah SL, sinyal arah sama diblokir selama `cooldown_bars` candle.
    - Sinyal yang berakhir mencatat end_time dan exit_price (untuk notifikasi KELUAR).
    """
    cfg = D.TF[tf]
    minutes = cfg["minutes"]
    expiry_hours = cfg["expiry_h"] if expiry_hours is None else expiry_hours
    cooldown = COOLDOWN_BARS if cooldown_bars is None else cooldown_bars
    now = now or pd.Timestamp.now(tz="UTC")
    closed, forming = split_closed(df, now, minutes)
    issue_fn = issue_fn or _issue_from_arrays(closed, symbol=symbol)
    n = len(closed)
    start = min(119, max(n - 1, 0))
    blocked = {"BUY": -10 ** 9, "SELL": -10 ** 9}
    cur, done = None, []

    live = float(df["close"].iloc[-1])

    def finish(outcome, i):
        nonlocal cur
        # Kapan dan di harga berapa sinyal berakhir (dipakai notifikasi KELUAR).
        lv = cur["levels"]
        if i < n:
            end_t = closed.iloc[i]["time"] + pd.Timedelta(minutes=minutes)
            px = float(closed.iloc[i]["close"])
        else:                                          # candle berjalan / kedaluwarsa sekarang
            end_t, px = now, live
        if outcome == "SL":
            px = lv["stop_loss"]
        elif outcome == "TP3":
            px = lv["tp"][2]
        done.append({**{k: cur[k] for k in ("direction", "time", "levels", "confidence", "tp_hit")},
                     "outcome": outcome, "end_time": min(end_t, now).isoformat(), "exit_price": round(float(px), 2)})
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
               "tp_hit": r["tp_hit"], "outcome": r["outcome"],
               "end_time": r.get("end_time"), "exit_price": r.get("exit_price")} for r in done][::-1][:10]
    return {"active": active, "recent": recent, "stats": stats,
            "expiry_hours": expiry_hours, "tf": tf}


# --------------------------------------------------------- konfirmasi M1
def entry_deadline(issued_close, tf, symbol="XAUUSD"):
    """Batas waktu entry: sinyal hanya boleh dieksekusi dalam max_age_bars candle TF setelah terbit."""
    if not tf or tf not in D.TF:
        return None
    return pd.Timestamp(issued_close) + pd.Timedelta(minutes=profile(symbol)["max_age_bars"] * D.TF[tf]["minutes"])


def confirm_m1(m1, direction, levels, issued_close, now=None, symbol="XAUUSD", tf=None):
    """Konfirmasi entri M1 (WAJIB sebelum entry) + proteksi entry terlambat.

    CONFIRMED bila pada candle M1 tertutup terakhir SEMUA benar:
      1) EMA9 berada di sisi arah terhadap EMA21
      2) close berada di sisi arah terhadap EMA9
      3) RSI(14) di sisi arah terhadap 50 (>50 untuk BUY, <50 untuk SELL)
      4) harga belum menyentuh SL dan belum "mengejar" lebih dari zone_r x jarak SL dari entry sinyal
      5) masih dalam batas waktu entry (max_age_bars candle TF sejak sinyal terbit)
    Status lain: WAIT (belum), CHASED (harga sudah mengejar), LATE (batas waktu lewat), INVALID (SL tersentuh).
    Saat CONFIRMED, `live_levels` memberi Entry/TP dari harga M1 sekarang dengan SL sinyal yang sama.
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
    prof = profile(symbol)
    zone_r = prof["zone_r"]
    sign = 1 if direction == "BUY" else -1
    entry, sl, risk = levels["entry"], levels["stop_loss"], levels["risk_points"]
    dl = entry_deadline(issued_close, tf, symbol)
    late = dl is not None and pd.Timestamp(now) > dl
    c = closed["close"]
    e9, e21, r = ema(c, 9), ema(c, 21), rsi(c)
    trend = ((e9 - e21) * sign > 0)
    side = ((c - e9) * sign > 0)
    mom = ((r - 50) * sign > 0)
    if direction == "BUY":
        zone = (c > sl) & (c <= entry + zone_r * risk)
    else:
        zone = (c < sl) & (c >= entry - zone_r * risk)
    flag = trend & side & mom & zone
    after = (closed["time"] >= issued_close).to_numpy()
    in_win = np.ones(len(closed), bool) if dl is None else ((closed["time"] + pd.Timedelta(minutes=1)) <= dl).to_numpy()
    hit = np.where(flag.to_numpy() & after & in_win)[0]
    first = None if len(hit) == 0 else int(hit[0])
    now_ok = bool(flag.iloc[-1]) and bool(after[-1]) and not late
    px = float(c.iloc[-1])
    chase_r = (px - entry) * sign / risk if risk else 0.0
    broken = (px - sl) * sign <= 0
    state = ("CONFIRMED" if now_ok else "INVALID" if broken else "LATE" if late
             else "CHASED" if chase_r > zone_r else "WAIT")
    up = "atas" if direction == "BUY" else "bawah"
    e9v, e21v, rv = float(e9.iloc[-1]), float(e21.iloc[-1]), float(r.iloc[-1])
    limit = entry + sign * zone_r * risk
    checks = [
        {"name": f"EMA9 di {up} EMA21", "ok": bool(trend.iloc[-1]),
         "detail": f"{e9v:.2f} vs {e21v:.2f}",
         "parts": [{"label": "EMA9", "v": e9v, "price": True}, {"label": "EMA21", "v": e21v, "price": True}]},
        {"name": f"Close M1 di {up} EMA9", "ok": bool(side.iloc[-1]),
         "detail": f"{px:.2f} vs {e9v:.2f}",
         "parts": [{"label": "Close", "v": px, "price": True}, {"label": "EMA9", "v": e9v, "price": True}]},
        {"name": f"RSI M1 {'>' if direction == 'BUY' else '<'} 50", "ok": bool(mom.iloc[-1]),
         "detail": f"{rv:.0f}", "parts": [{"label": "RSI", "v": rv, "price": False, "d": 0}]},
        {"name": "Harga di zona entry (belum kena SL, tidak mengejar)", "ok": bool(zone.iloc[-1]),
         "detail": f"{px:.2f}; SL {sl:.2f}; batas kejar {limit:.2f}",
         "parts": [{"label": "Harga", "v": px, "price": True}, {"label": "SL", "v": sl, "price": True},
                   {"label": "Batas kejar", "v": limit, "price": True}]},
    ]
    if dl is not None:
        checks.append({"name": f"Masih dalam batas waktu entry ({prof['max_age_bars']} candle {tf})",
                       "ok": not late, "detail": f"sampai {dl.strftime('%H:%M')} UTC"})
    reasons = {
        "INVALID": "Harga sudah menyentuh stop loss sinyal. Setup batal, jangan entry.",
        "LATE": "Batas waktu entry sudah lewat. Lewati setup ini dan tunggu sinyal baru.",
        "CHASED": f"Harga sudah bergerak {chase_r:.2f}R dari entry sinyal (batas {zone_r:g}R). Jangan mengejar.",
    }
    if state == "WAIT" and not bool(after[-1]):
        reasons["WAIT"] = "Menunggu candle M1 pertama setelah candle sinyal tertutup."
    out = {"state": state, "checks": checks,
           "m1_time": closed.iloc[-1]["time"].isoformat(), "price": round(px, 2),
           "first_time": None, "first_price": None, "chase_r": round(chase_r, 2) + 0.0,
           "zone_r": zone_r, "deadline": None if dl is None else dl.isoformat(),
           "minutes_left": None if dl is None else round(max(0.0, (dl - pd.Timestamp(now)).total_seconds() / 60), 1),
           "reason": reasons.get(state)}
    if first is not None:
        out["first_time"] = closed.iloc[first]["time"].isoformat()
        out["first_price"] = round(float(c.iloc[first]), 2)
    if state == "CONFIRMED":
        risk_now = abs(px - sl)
        rr = levels.get("rr") or list(profile(symbol)["rr"])
        out["live_levels"] = {"entry": round(px, 2), "stop_loss": sl,
                              "tp": [round(px + sign * risk_now * k, 2) for k in rr],
                              "rr": rr, "risk_points": round(risk_now, 2)}
    return out
