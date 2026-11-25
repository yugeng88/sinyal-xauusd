"""Backtest mesin sinyal aplikasi pada candle MT5 sungguhan, dengan pembanding sinyal ACAK.

Pakai:  python backtest.py XAUUSD_M15.csv --tf M15 [--symbol XAUUSD] [--utc-offset 2|ny] [--spread 0.3]

Isi CSV: ekspor MT5 (View > Symbols / Ctrl+U > tab Bars > pilih simbol, timeframe, rentang tanggal > Request > Export Bars) atau CSV umum
dengan kolom waktu, open, high, low, close (volume boleh ada).

Cara kerja:
- Mesin sinyal yang diuji adalah kode aplikasi sendiri (signals.issue_arrays / strategy_arrays / make_levels),
  dengan aturan pelacakan yang sama (SL dicek lebih dulu dalam satu candle, TP3 mengakhiri, kedaluwarsa,
  jeda setelah SL).
- Setiap skenario dibandingkan dengan sinyal ACAK berjumlah, berjarak SL, dan berproporsi BUY/SELL sama pada candle yang
  sama (proporsi arah dijaga agar tren pasar yang kuat tidak dianggap keahlian).
  p-value = seberapa sering sinyal acak menyamai atau mengalahkan hasil skenario. Nilai kecil berarti
  hasilnya sulit dijelaskan kebetulan.
- Data dibagi dua menurut waktu: bagian awal dan bagian akhir dilaporkan terpisah. Skenario yang hanya
  bagus di salah satu bagian kemungkinan kebetulan (overfitting).
- R = hasil dalam kelipatan risiko (SL = -1R). Keluar di TP1 = +RR1. Sinyal yang kedaluwarsa atau
  berbalik dihitung harga pasar saat berakhir (bukan nol seperti ringkasan di dasbor).

Batasan: spread dan slippage hanya didekati lewat --spread; tidak ada data tick; hasil masa lalu bukan jaminan.
"""
from __future__ import annotations

import argparse
import io
import re
import sys

import numpy as np
import pandas as pd

import signals

START = 119          # sama dengan signals.track: sinyal pertama dinilai dari candle ke-120 (indeks 119)
EXPIRY_BARS = 12     # semua timeframe bawaan aplikasi = 12 candle (M5 1 jam, M15 3 jam, M30 6 jam, H1 12 jam)


# ------------------------------------------------------------------ memuat data
def load_candles(src, utc_offset=0.0):
    """Baca CSV (jalur file atau teks). Mengenali ekspor MT5 (tab/koma/titik koma; header <DATE> <TIME> ...)."""
    text = src if "\n" in str(src) else open(src, encoding="utf-8-sig", errors="replace").read()
    text = text.lstrip("\ufeff").strip()
    first = text.splitlines()[0]
    sep = max(("\t", ";", ","), key=first.count)
    has_header = bool(re.search(r"[A-Za-z]{3,}", first))
    df = pd.read_csv(io.StringIO(text), sep=sep, header=0 if has_header else None, engine="python")
    if has_header:
        df.columns = [re.sub(r"[<>\s]", "", str(c)).lower() for c in df.columns]
    else:
        names = ["date", "time", "open", "high", "low", "close", "tickvol", "vol", "spread"]
        if re.match(r"^\d{4}[./-]\d{2}[./-]\d{2}$", str(df.iloc[0, 0]).strip()) and ":" in str(df.iloc[0, 1]):
            df.columns = names[:df.shape[1]]
        else:
            df.columns = ["time", "open", "high", "low", "close", "volume"][:df.shape[1]]
    cols = set(df.columns)
    if {"date", "time"} <= cols:
        t = pd.to_datetime(df["date"].astype(str).str.replace(".", "-", regex=False) + " " + df["time"].astype(str), errors="coerce")
    elif "time" in cols and pd.api.types.is_numeric_dtype(df["time"]):
        t = pd.to_datetime(df["time"], unit="s", errors="coerce")
    elif "time" in cols:
        t = pd.to_datetime(df["time"].astype(str).str.replace(".", "-", regex=False), errors="coerce")
    else:
        raise ValueError("kolom waktu tidak ditemukan")
    vol_col = next((c for c in ("tickvol", "volume", "vol") if c in cols), None)
    out = pd.DataFrame({"time": t, **{k: pd.to_numeric(df[k], errors="coerce") for k in ("open", "high", "low", "close")}})
    out["volume"] = pd.to_numeric(df[vol_col], errors="coerce").fillna(1) if vol_col else 1
    out = out.dropna().drop_duplicates("time").sort_values("time").reset_index(drop=True)
    if str(utc_offset).lower() == "ny":
        # Server "NY-close": 17:00 New York = 00:00 server, jadi waktu NY = server - 7 jam (GMT+2 / GMT+3 saat DST AS).
        ny = (out["time"] - pd.Timedelta(hours=7)).dt.tz_localize("America/New_York", ambiguous="NaT", nonexistent="NaT")
        out["time"] = ny.dt.tz_convert("UTC")
        out = out.dropna(subset=["time"]).reset_index(drop=True)
    else:
        out["time"] = (out["time"] - pd.Timedelta(hours=float(utc_offset))).dt.tz_localize("UTC")
    return out


# ------------------------------------------------------------------ simulasi
def _hits(d, sl, tps, hi, lo):
    if d == 1:
        return lo <= sl, sum(1 for t in tps if hi >= t)
    return hi >= sl, sum(1 for t in tps if lo <= t)


def _trade_r(d, entry, risk, rr, outcome, tp_hit, px, cost):
    if outcome == "SL" and tp_hit == 0:
        r = -1.0
    elif tp_hit >= 1:
        r = rr[0]
    else:
        r = d * (px - entry) / risk
    return r - cost / risk


def _mins(df):
    """Waktu candle dalam menit (bilangan bulat, UTC) untuk hitung kedaluwarsa menurut jam berlalu."""
    return df["time"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy().astype("datetime64[m]").astype("int64")


def tf_minutes(df):
    return float(np.median(np.diff(_mins(df))))


def eval_one(c, hi, lo, mins, i, d, risk, rr, expiry_min, cost=0.0, pb=0.0, pb_bars=0):
    """Satu sinyal pada candle i (tanpa sinyal berlawanan): (R, label), atau None bila limit pullback tidak terisi.
    pb > 0: limit di pb poin melawan arah dari penutupan candle i, berlaku pb_bars candle; SL dan TP mengikuti harga isi."""
    e, start = c[i], i
    if pb > 0:
        e = c[i] - d * pb
        filled = None
        for j in range(i + 1, min(i + 1 + pb_bars, len(c))):
            if (d == 1 and lo[j] <= e) or (d == -1 and hi[j] >= e):
                filled = j
                break
        if filled is None:
            return None
        start = filled
        if (d == 1 and lo[start] <= e - risk) or (d == -1 and hi[start] >= e + risk):   # SL di candle isi: konservatif
            return _trade_r(d, e, risk, rr, "SL", 0, e - d * risk, cost), "SL"
    sl = e - d * risk
    tps = [e + d * risk * x for x in rr]
    hit, j = 0, start
    for j in range(start + 1, len(c)):
        s_, t_ = _hits(d, sl, tps, hi[j], lo[j])
        if s_:
            return _trade_r(d, e, risk, rr, "SL", hit, sl, cost), "SL" if hit == 0 else "TP1+"
        hit = max(hit, t_)
        if hit >= 3 or mins[j] - mins[start] >= expiry_min:
            break
    label = "TP1+" if hit >= 1 else "NONE"
    return _trade_r(d, e, risk, rr, "EXP", hit, c[j], cost), label


def simulate(df, ar, symbol, rr=None, expiry=EXPIRY_BARS, cooldown=signals.COOLDOWN_BARS, cost=0.0, lo_i=START, hi_i=None,
             pullback=None):
    """Urutan sinyal seperti signals.track: satu sinyal aktif sekali waktu. ar = dict direction/price/atr/stop."""
    c, hi, lo = df["close"].to_numpy(float), df["high"].to_numpy(float), df["low"].to_numpy(float)
    mins = _mins(df)
    expiry_min = expiry * tf_minutes(df)
    n = len(df)
    hi_i = n if hi_i is None else hi_i
    rr = rr or signals.profile(symbol)["rr"]
    blocked = {1: -10 ** 9, -1: -10 ** 9}
    cur, pend, trades = None, None, []
    pb_mult, pb_bars = pullback if pullback else (0.0, 0)

    def finish(outcome, i, px):
        nonlocal cur
        r = _trade_r(cur["d"], cur["e"], cur["risk"], rr, outcome, cur["hit"], px, cost)
        label = ("SL" if cur["hit"] == 0 else "TP1+") if outcome == "SL" else ("TP1+" if cur["hit"] >= 1 else "NONE")
        trades.append({"i": cur["i"], "d": cur["d"], "risk": cur["risk"], "risk_atr": cur["risk_atr"], "r": r, "label": label,
                       "pb": cur.get("pb", 0.0), "sig": cur.get("sig", cur["i"])})
        if outcome == "SL":
            blocked[cur["d"]] = i
        cur = None

    for i in range(START, hi_i):
        dstr = str(ar["direction"][i])
        d = 1 if dstr == "BUY" else -1 if dstr == "SELL" else 0
        if pend is not None and cur is None and i > pend["i"]:        # limit pullback menunggu terisi
            if i - pend["i"] > pb_bars:
                pend = None
            else:
                fill = (pend["d"] == 1 and lo[i] <= pend["e"]) or (pend["d"] == -1 and hi[i] >= pend["e"])
                if fill:
                    cur = {"i": i, "sig": pend["i"], "d": pend["d"], "e": pend["e"], "risk": pend["risk"], "risk_atr": pend["risk_atr"],
                           "hit": 0, "pb": pend["pb"], "sl": pend["e"] - pend["d"] * pend["risk"],
                           "tps": [pend["e"] + pend["d"] * pend["risk"] * x for x in rr]}
                    pend = None
                    if (cur["d"] == 1 and lo[i] <= cur["sl"]) or (cur["d"] == -1 and hi[i] >= cur["sl"]):
                        finish("SL", i, cur["sl"])                    # SL di candle isi: konservatif
        if cur is not None and i > cur["i"]:
            s, t = _hits(cur["d"], cur["sl"], cur["tps"], hi[i], lo[i])
            if s:
                finish("SL", i, cur["sl"])
            else:
                cur["hit"] = max(cur["hit"], t)
                if cur["hit"] >= 3:
                    finish("TP3", i, cur["tps"][2])
                elif mins[i] - mins[cur["i"]] >= expiry_min:
                    finish("EXP", i, c[i])
                elif d != 0 and d != cur["d"]:
                    finish("REV", i, c[i])
        if cur is None and pend is None and d != 0 and i >= lo_i and i > blocked[d] + cooldown:
            entry = float(ar["price"][i])
            lv = signals.make_levels(dstr, entry, float(ar["atr"][i]), symbol, float(ar["stop"][i]))
            risk = lv["risk_points"]
            if risk <= 0:
                continue
            if pb_mult > 0:
                pb = pb_mult * float(ar["atr"][i])
                pend = {"i": i, "d": d, "e": entry - d * pb, "risk": risk, "risk_atr": lv["risk_atr"], "pb": pb}
                continue
            cur = {"i": i, "d": d, "e": entry, "risk": risk, "risk_atr": lv["risk_atr"], "hit": 0,
                   "sl": lv["stop_loss"], "tps": [entry + d * risk * x for x in rr]}
    return trades


def summarize(trades):
    n = len(trades)
    if not n:
        return {"n": 0, "sl": 0.0, "tp": 0.0, "none": 0.0, "r": float("nan")}
    lab = [t["label"] for t in trades]
    return {"n": n, "sl": 100 * lab.count("SL") / n, "tp": 100 * lab.count("TP1+") / n,
            "none": 100 * lab.count("NONE") / n, "r": float(np.mean([t["r"] for t in trades]))}


def random_baseline(df, trades, rr, expiry, cost, draws=300, seed=11, lo_i=START, hi_i=None, pullback=None):
    """Sinyal acak: jumlah dan jarak SL sama, waktu dan arah acak. Mengembalikan (rata-rata R acak, p-value)."""
    if not trades:
        return float("nan"), float("nan")
    c, hi, lo = df["close"].to_numpy(float), df["high"].to_numpy(float), df["low"].to_numpy(float)
    mins = _mins(df)
    expiry_min = expiry * tf_minutes(df)
    hi_i = len(df) if hi_i is None else hi_i
    rng = np.random.default_rng(seed)
    draws = int(min(draws, max(40, 1_500_000 // len(trades))))      # batasi kerja pada data besar (ribuan sinyal)
    risks = np.array([t["risk"] for t in trades])
    dirs_real = np.array([t["d"] for t in trades])
    obs = float(np.mean([t["r"] for t in trades]))
    means = []
    atr_v = signals.atr(df).to_numpy(float)
    pb_mult, pb_bars = pullback if pullback else (0.0, 0)
    for _ in range(draws):
        dirs = rng.permutation(dirs_real)             # proporsi BUY/SELL sama dengan skenario: kendalikan tren pasar
        if pb_mult > 0:                               # limit pullback: tolak yang tidak terisi sampai jumlah sama
            res, k = [], 0
            cand = rng.integers(lo_i, max(lo_i + 1, hi_i - expiry - 1), len(trades) * 6)
            for i in cand:
                if len(res) == len(trades):
                    break
                out = eval_one(c, hi, lo, mins, int(i), int(dirs[len(res)]), float(risks[len(res)]), rr, expiry_min, cost,
                               pb=pb_mult * atr_v[int(i)], pb_bars=pb_bars)
                if out is not None:
                    res.append(out[0])
            means.append(np.mean(res) if res else np.nan)
        else:
            idx = rng.integers(lo_i, max(lo_i + 1, hi_i - expiry - 1), len(trades))
            means.append(np.mean([eval_one(c, hi, lo, mins, int(i), int(d), float(rk), rr, expiry_min, cost)[0]
                                  for i, d, rk in zip(idx, dirs, risks)]))
    means = np.array(means)
    means = means[~np.isnan(means)]
    return float(means.mean()), float((1 + np.sum(means >= obs)) / (len(means) + 1))


# ------------------------------------------------------------------ skenario
def build_scenarios(df, symbol):
    """Skenario = (nama, arrays arah/harga/ATR/stop, RR, kedaluwarsa). Semua memakai detektor aplikasi."""
    ar = signals.issue_arrays(df, symbol=symbol)
    st = signals.strategy_arrays(df)
    c = df["close"].astype(float)
    h, l = df["high"].astype(float), df["low"].astype(float)
    ctx = st["context"]
    context_ok = (ctx["adx"] >= 10) & ctx["volatility_expansion"]
    swing_lo, swing_hi = l.rolling(8, min_periods=1).min(), h.rolling(8, min_periods=1).max()
    ema200 = signals.ema(c, 200).to_numpy()
    cv = c.to_numpy()
    hour = df["time"].dt.hour.to_numpy()

    def fam_arrays(name):
        d = np.where(context_ok, st["families"][name], "WAIT")
        stop = np.where(d == "BUY", (c - swing_lo).to_numpy(), np.where(d == "SELL", (swing_hi - c).to_numpy(), np.nan))
        return {**ar, "direction": d, "stop": stop.astype(float)}

    def filt(mask_ok):
        return {**ar, "direction": np.where(mask_ok, ar["direction"], "WAIT")}

    base_rr = signals.profile(symbol)["rr"]
    trend_ok = ((ar["direction"] == "BUY") & (cv > ema200)) | ((ar["direction"] == "SELL") & (cv < ema200))
    sess_ok = (hour >= 7) & (hour < 20)
    return [
        ("Bawaan aplikasi", ar, base_rr, EXPIRY_BARS),
        ("3 dari 3 keluarga setuju", filt(st["votes"] >= 3), base_rr, EXPIRY_BARS),
        ("Satu keluarga: reversal saja", fam_arrays("reversal"), base_rr, EXPIRY_BARS),
        ("Satu keluarga: continuation saja", fam_arrays("continuation"), base_rr, EXPIRY_BARS),
        ("Satu keluarga: breakout saja", fam_arrays("breakout"), base_rr, EXPIRY_BARS),
        ("Bawaan + searah EMA200", filt(trend_ok), base_rr, EXPIRY_BARS),
        ("Bawaan + ADX >= 20", filt(np.asarray(ctx["adx"] >= 20)), base_rr, EXPIRY_BARS),
        ("Bawaan + sesi 07-20 UTC", filt(sess_ok), base_rr, EXPIRY_BARS),
        ("Bawaan, RR 1 / 1.5 / 2", ar, (1.0, 1.5, 2.0), EXPIRY_BARS),
        ("Bawaan, kedaluwarsa 24 candle", ar, base_rr, 24),
    ]


def run(df, symbol, cost=0.0, split=0.5, draws=300, scenarios=None):
    """Kembalikan baris hasil per skenario: seluruh data, bagian awal, bagian akhir.
    scenarios: daftar (nama, arrays, rr, kedaluwarsa[, pullback]); bawaan = build_scenarios."""
    n = len(df)
    cut = int(n * split)
    rows = []
    for sc in (scenarios or build_scenarios(df, symbol)):
        name, ar, rr, expiry = sc[:4]
        pb = sc[4] if len(sc) > 4 else None
        res = {"name": name}
        for key, (a, b) in {"all": (START, n), "first": (START, cut), "last": (cut, n)}.items():
            tr = simulate(df, ar, symbol, rr=rr, expiry=expiry, cost=cost, lo_i=a, hi_i=b, pullback=pb)
            res[key] = summarize(tr)
            if key == "all":
                res["rand_r"], res["p"] = random_baseline(df, tr, rr, expiry, cost, draws=draws, pullback=pb)
        rows.append(res)
    return rows


def build_ideas(df, symbol):
    """Tiga ide perbaikan yang ditetapkan SEBELUM melihat hasil data nyata (bukan hasil memilih-milih):
    A) buang sinyal saat ATR melonjak > 1,5x median 96 candle (berita, gap),
    B) entry limit di pullback 0,5 ATR berlaku 4 candle (mengatasi 'sinyal terlambat'),
    C) hanya searah tren H1 (EMA20 > EMA50 pada candle H1 yang sudah tertutup)."""
    ar = signals.issue_arrays(df, symbol=symbol)
    a = signals.atr(df)
    calm = (a <= 1.5 * a.rolling(96, min_periods=48).median()).to_numpy()
    t_utc = df["time"].dt.tz_convert("UTC")
    h1 = df.set_index(t_utc)["close"].resample("1h").last().dropna()
    h1_dir = np.where(signals.ema(h1, 20) > signals.ema(h1, 50), 1, -1)
    h1_done = (h1.index + pd.Timedelta(hours=1)).tz_localize(None).to_numpy().astype("datetime64[ns]")
    close_t = (t_utc + pd.Timedelta(minutes=tf_minutes(df))).dt.tz_localize(None).to_numpy().astype("datetime64[ns]")
    pos = np.searchsorted(h1_done, close_t, side="right") - 1       # H1 terakhir yang sudah tertutup pada saat sinyal
    trend = np.where(pos >= 0, h1_dir[np.clip(pos, 0, None)], 0)
    sig = ar["direction"]
    aligned = ((sig == "BUY") & (trend == 1)) | ((sig == "SELL") & (trend == -1))
    base_rr = signals.profile(symbol)["rr"]
    return [
        ("Bawaan aplikasi (acuan)", ar, base_rr, EXPIRY_BARS),
        ("Ide A: tanpa lonjakan volatilitas", {**ar, "direction": np.where(calm, sig, "WAIT")}, base_rr, EXPIRY_BARS),
        ("Ide B: entry limit pullback 0,5 ATR", ar, base_rr, EXPIRY_BARS, (0.5, 4)),
        ("Ide C: searah tren H1", {**ar, "direction": np.where(aligned, sig, "WAIT")}, base_rr, EXPIRY_BARS),
    ]


def walk_forward(df, symbol, scenarios, cost=0.0, blocks=6, min_trades=30):
    """Pilih skenario terbaik dari data SEBELUMNYA, lalu nilai pada blok berikutnya yang belum terlihat.
    Menjawab: 'adakah cara memilih strategi yang untung di data baru?' Mengembalikan ringkasan keluar-sampel."""
    n = len(df)
    edges = np.linspace(START, n, blocks + 1).astype(int)
    per = {}
    for sc in scenarios:
        name, ar, rr, expiry = sc[:4]
        pb = sc[4] if len(sc) > 4 else None
        tr = simulate(df, ar, symbol, rr=rr, expiry=expiry, cost=cost, pullback=pb)
        per[name] = np.array([(t["i"], t["r"]) for t in tr]).reshape(-1, 2)

    def window(name, a, b):
        x = per[name]
        return x[(x[:, 0] >= a) & (x[:, 0] < b), 1]

    rows, oos, ref_all, ref_base = [], [], [], []
    base_name = next(iter(per))
    for b in range(1, blocks):
        train = {k: window(k, edges[0], edges[b]) for k in per}
        ok = {k: v.mean() for k, v in train.items() if len(v) >= min_trades}
        if not ok:
            continue
        pick = max(ok, key=ok.get)
        test = window(pick, edges[b], edges[b + 1])
        oos.extend(test.tolist())
        ref_base.extend(window(base_name, edges[b], edges[b + 1]).tolist())
        ref_all.append(np.mean([window(k, edges[b], edges[b + 1]).mean() for k in per if len(window(k, edges[b], edges[b + 1]))]))
        rows.append({"block": b, "pick": pick, "train_r": float(ok[pick]), "oos_n": len(test),
                     "oos_r": float(test.mean()) if len(test) else float("nan")})
    oos = np.array(oos)
    se = float(oos.std(ddof=1) / np.sqrt(len(oos))) if len(oos) > 1 else float("nan")
    return {"rows": rows, "oos_n": len(oos), "oos_r": float(oos.mean()) if len(oos) else float("nan"), "se": se,
            "t": float(oos.mean() / se) if se and se == se else float("nan"),
            "base_r": float(np.mean(ref_base)) if ref_base else float("nan"),
            "avg_scenario_r": float(np.mean(ref_all)) if ref_all else float("nan")}


def report_wf(res, tf, symbol, cost):
    lines = [f"WALK-FORWARD {symbol} {tf} (biaya {cost} poin): pilih skenario terbaik dari data sebelumnya, nilai pada blok berikutnya.",
             f"{'Blok':>4} {'Skenario terpilih':36} {'R latih':>8} {'n uji':>6} {'R uji':>7}"]
    for r in res["rows"]:
        lines.append(f"{r['block']:>4} {r['pick']:36} {r['train_r']:>8.3f} {r['oos_n']:>6} {r['oos_r']:>7.3f}")
    lines.append(f"Keluar-sampel gabungan: n={res['oos_n']}, R rata-rata {res['oos_r']:+.3f} (SE {res['se']:.3f}, t={res['t']:.1f}). "
                 f"Pembanding: bawaan aplikasi {res['base_r']:+.3f}, rata-rata semua skenario {res['avg_scenario_r']:+.3f}.")
    lines.append("t di bawah 2 berarti tidak bisa dibedakan dari nol. Hasil positif yang nyata biasanya t di atas 3 setelah banyak pilihan.")
    return "\n".join(lines)


def report(rows, n_candles, tf, symbol, cost):
    k = len(rows)
    lines = [f"{symbol} {tf}: {n_candles} candle, spread/biaya {cost} poin, {k} skenario dibandingkan dengan sinyal acak.",
             f"{'Skenario':34} {'n':>4} {'SL%':>5} {'TP1+%':>6} {'tanpa%':>6} {'R rata2':>8} {'R acak':>7} {'p':>6} {'R awal':>7} {'R akhir':>7}"]
    for r in rows:
        a = r["all"]
        lines.append(f"{r['name']:34} {a['n']:>4} {a['sl']:>5.0f} {a['tp']:>6.0f} {a['none']:>6.0f} {a['r']:>8.3f} "
                     f"{r['rand_r']:>7.3f} {r['p']:>6.3f} {r['first']['r']:>7.3f} {r['last']['r']:>7.3f}")
    k = max(k - 1, 1) if rows and rows[0]["name"].startswith("Bawaan aplikasi (acuan)") else k
    lines.append(f"Ambang p setelah koreksi {k} perbandingan: {0.05 / k:.4f}. Skenario layak dipertimbangkan hanya bila "
                 "R rata-rata positif di bagian awal DAN akhir serta p di bawah ambang.")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv")
    ap.add_argument("--tf", default="M15")
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--utc-offset", default="0", help="selisih jam server broker terhadap UTC (mis. 2), atau 'ny' bila server mengikuti jam tutup New York (GMT+2/+3)")
    ap.add_argument("--spread", type=float, default=0.0, help="biaya per trade dalam poin harga (spread + slippage)")
    ap.add_argument("--split", type=float, default=0.5)
    ap.add_argument("--draws", type=int, default=300)
    ap.add_argument("--walkforward", action="store_true", help="pilih skenario dari data sebelumnya, uji pada blok berikutnya")
    ap.add_argument("--ideas", action="store_true", help="uji 3 ide perbaikan (A volatilitas, B pullback, C tren H1) saja")
    a = ap.parse_args(argv)
    df = load_candles(a.csv, a.utc_offset)
    if len(df) < 600:
        sys.exit(f"Candle terlalu sedikit ({len(df)}); butuh minimal 600, idealnya beberapa ribu.")
    if a.walkforward:
        sc = build_scenarios(df, a.symbol) + [x for x in build_ideas(df, a.symbol) if not x[0].startswith("Bawaan")]
        print(report_wf(walk_forward(df, a.symbol, sc, a.spread), a.tf, a.symbol, a.spread))
        return
    scen = build_ideas(df, a.symbol) if a.ideas else None
    print(report(run(df, a.symbol, a.spread, a.split, a.draws, scen), len(df), a.tf, a.symbol, a.spread))


if __name__ == "__main__":
    main()
