"""Setup Fib Retracement sesuai pengaturan TradingView pengguna.

Level yang dipakai (dari layar pengaturan): -0.99, -0.66, -0.33, 0.03, 0.63, 0.78, 0.99.
(0.786 dan 2.618 pada pengaturan itu tidak dicentang, jadi tidak dipakai.)

Cara menggambar (sama dengan TradingView): garis ditarik dari awal kaki ayunan (swing) ke ujungnya.
Level 0 ada di ujung kaki, level 1 di awal kaki, level negatif adalah perpanjangan melewati ujung.
    harga(L) = ujung + L x (awal - ujung)

Dua gambar dari pasangan titik yang sama (mis. LL dan LH): LL -> LH (low -> high) = setup BUY, LH -> LL (high -> low) = setup SELL.
Kaki NAIK  (low -> high): setup BUY.  Area entry 0.63-0.78, SL di 0.99, TP1/TP2/TP3 di -0.33 / -0.66 / -0.99.
                          Level 0.03 = titik balik (ujung kaki): area tempat pullback atau balik arah dimulai, bukan TP.
Kaki TURUN (high -> low): setup SELL, cerminannya.

Ini kecenderungan dari struktur harga, bukan prediksi atau jaminan. Modul ini hanya menambah blok `fib`
pada hasil analyze(); arah sinyal utama (mesin 3 keluarga strategi) tidak diubah.
Semua deterministik dari candle tertutup; tidak ada data buatan.
"""
import os

import numpy as np
import pandas as pd

# Level persis seperti di pengaturan pengguna (urutan tampil dari target jauh ke SL).
LEVELS = (-0.99, -0.66, -0.33, 0.03, 0.63, 0.78, 0.99)
LEVEL_ROLES = {-0.99: "TP3", -0.66: "TP2", -0.33: "TP1", 0.03: "titik balik / pullback (ujung kaki)",
               0.63: "area entry (tepi atas)", 0.78: "area entry (tepi dalam)", 0.99: "stop loss"}


def _floats(raw, default):
    try:
        v = tuple(float(x) for x in str(raw).split(","))
        return v if v else default
    except ValueError:
        return default


def config():
    """Dibaca tiap panggilan agar env bisa diubah tanpa deploy ulang kode."""
    zone = sorted(_floats(os.getenv("FIB_ZONE", "0.63,0.78"), (0.63, 0.78)))
    tp = _floats(os.getenv("FIB_TP", "-0.33,-0.66,-0.99"), (-0.33, -0.66, -0.99))
    try:
        entry = float(os.getenv("FIB_ENTRY", "0.78"))
        turn = float(os.getenv("FIB_TURN", "0.03"))
        sl = float(os.getenv("FIB_SL", "0.99"))
        buf = float(os.getenv("FIB_SL_BUFFER_ATR", "0"))
        pivot = int(float(os.getenv("FIB_PIVOT", "10")))
        min_atr = float(os.getenv("FIB_MIN_ATR", "3"))
        max_age = int(float(os.getenv("FIB_MAX_AGE_BARS", "80")))
    except ValueError:
        entry, sl, buf, pivot, min_atr, max_age, turn = 0.78, 0.99, 0.0, 10, 3.0, 80, 0.03
    if len(tp) != 3 or list(tp) != sorted(tp, reverse=True):   # harus 3 TP, makin jauh makin kecil (negatif)
        tp = (-0.33, -0.66, -0.99)
    return {"enabled": os.getenv("FIB_ENABLED", "1").lower() not in ("0", "off", "false", "no"),
            "zone": (zone[0], zone[-1]), "entry": entry, "turn": turn, "sl": sl, "sl_buffer_atr": buf, "tp": tp,
            "pivot": max(1, pivot), "min_atr": min_atr, "max_age": max_age}


def _price(L, start, end):
    return end + L * (start - end)


def _pivots(h, l, k):
    """Pivot terkonfirmasi (k candle di kiri dan kanan), lalu digabung jadi zigzag bergantian high/low."""
    n = len(h)
    raw = []
    for i in range(k, n - k):
        if h[i] >= h[i - k:i + k + 1].max():
            raw.append((i, "H", float(h[i])))
        if l[i] <= l[i - k:i + k + 1].min():
            raw.append((i, "L", float(l[i])))
    raw.sort(key=lambda p: p[0])
    zz = []
    for p in raw:
        if zz and zz[-1][1] == p[1]:                 # dua pivot sejenis berurutan: ambil yang lebih ekstrem
            if (p[1] == "H" and p[2] >= zz[-1][2]) or (p[1] == "L" and p[2] <= zz[-1][2]):
                zz[-1] = p
        else:
            zz.append(p)
    return zz


def _struct_label(kind, value, prev_value):
    """Label struktur pasar: high dibanding high sebelumnya (HH/LH), low dibanding low sebelumnya (HL/LL)."""
    if prev_value is None:
        return "High" if kind == "H" else "Low"
    if kind == "H":
        return "HH" if value > prev_value else "LH"
    return "LL" if value < prev_value else "HL"


def find_leg(df, atr_v, cfg=None):
    """Kaki ayunan terakhir yang valid: (arah, awal, ujung, idx_awal, idx_ujung, label_awal, label_ujung) atau None.
    Label = struktur pasar kedua titik (LL/LH/HL/HH), mis. kaki turun dari LH ke LL."""
    cfg = cfg or config()
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    n = len(df)
    zz = _pivots(h, l, cfg["pivot"])
    # Dari belakang: cari pasangan pivot bergantian yang jaraknya cukup besar.
    for j in range(len(zz) - 1, 0, -1):
        a, b = zz[j - 1], zz[j]
        rng = abs(b[2] - a[2])
        if rng < cfg["min_atr"] * atr_v:
            continue
        up = a[1] == "L" and b[1] == "H"
        # Ujung kaki dapat bertambah panjang bila setelah pivot terkonfirmasi harga mencetak ekstrem baru.
        tail_h, tail_l = h[b[0]:], l[b[0]:]
        end_i = b[0] + int(np.argmax(tail_h)) if up else b[0] + int(np.argmin(tail_l))
        end_v = float(h[end_i]) if up else float(l[end_i])
        if (n - 1 - end_i) > cfg["max_age"]:
            return None
        prev_a = zz[j - 3][2] if j >= 3 else None            # pivot sejenis sebelum titik awal
        prev_b = zz[j - 2][2] if j >= 2 else None            # pivot sejenis sebelum titik ujung
        lab_a = _struct_label(a[1], float(a[2]), prev_a)
        lab_b = _struct_label(b[1], end_v, prev_b)
        return ("BUY" if up else "SELL"), float(a[2]), end_v, int(a[0]), int(end_i), lab_a, lab_b
    return None


def _build(direction, lo, hi, i_lo, i_hi, df, atr_v, live_price, engine_direction, cfg, labels=None):
    """Satu setup dari dua titik jangkar. BUY: tarik low -> high. SELL: tarik high -> low."""
    if direction == "BUY":
        start, end, i0, i1 = lo, hi, i_lo, i_hi
    else:
        start, end, i0, i1 = hi, lo, i_hi, i_lo
    rng = abs(end - start)
    lo_lab, hi_lab = labels or ("Low", "High")
    draw_label = f"{lo_lab} → {hi_lab}" if direction == "BUY" else f"{hi_lab} → {lo_lab}"
    times = df["time"]
    closes = df["close"].to_numpy(dtype=float)[max(i0, i1) + 1:]   # setelah titik jangkar yang terakhir

    def px(L):
        return round(_price(L, start, end), 2)

    # Rasio harga sekarang pada garis fib (0 = ujung kaki, 1 = awal kaki, >1 = lewat SL).
    ratio = round(float((end - live_price) / (end - start)), 3)
    sl_L = cfg["sl"]
    beyond = lambda x: (x - end) / (start - end) >= sl_L     # noqa: E731
    broke = bool(len(closes) and any(beyond(x) for x in closes)) or beyond(live_price)
    z_lo, z_hi = cfg["zone"]
    word = "naik" if direction == "BUY" else "turun"
    if broke:
        status, note = "INVALID", (f"Harga sudah melewati level {sl_L:g} ({px(sl_L):,.2f}). Setup {direction} "
                                   "batal; tunggu kaki ayunan baru, jangan menambah posisi.")
    elif ratio < cfg["turn"]:
        status, note = "EXTENDED", (f"Harga sudah melewati titik balik {cfg['turn']:g} ({px(cfg['turn']):,.2f}) tanpa pullback ke zona entry. "
                                    "Jangan mengejar harga.")
    elif ratio < z_lo:
        status, note = "WAIT_PULLBACK", (f"Garis {'low -> high' if direction == 'BUY' else 'high -> low'} valid. "
                                         f"Tunggu harga ke zona {px(z_lo):,.2f} - {px(z_hi):,.2f}.")
    elif ratio <= z_hi:
        status, note = "IN_ZONE", (f"Harga di zona entry ({px(z_lo):,.2f} - {px(z_hi):,.2f}). "
                                   "Tunggu candle konfirmasi, bukan masuk membabi buta.")
    else:
        status, note = "DEEP", (f"Harga sudah lewat level entry {z_hi:g}, mendekati SL ({px(sl_L):,.2f}). "
                                "Risiko lebih tinggi; setup melemah.")
    buf = cfg["sl_buffer_atr"] * float(atr_v)
    sign = 1 if direction == "BUY" else -1
    entry = px(cfg["entry"])
    sl_price = round(_price(sl_L, start, end) - sign * buf, 2)
    tps = [px(L) for L in cfg["tp"]]
    risk = abs(entry - sl_price)
    rr = [round(abs(t - entry) / risk, 2) if risk > 0 else None for t in tps]
    # Entry berupa AREA (zona): RR dihitung dari kedua tepinya. Tepi dekat (0.63) = RR terkecil.
    def _rr_from(L):
        e = px(L)
        rk = abs(e - sl_price)
        return [round(abs(t - e) / rk, 2) if rk > 0 else None for t in tps]
    rr_near, rr_far = _rr_from(z_lo), _rr_from(z_hi)
    aligned = None if engine_direction in (None, "WAIT") else engine_direction == direction
    return {
        "enabled": True, "status": status, "direction": direction, "note": note,
        "leg": {"start": round(start, 2), "end": round(end, 2), "range": round(rng, 2),
                "start_time": times.iloc[i0].isoformat(), "end_time": times.iloc[i1].isoformat(),
                "type": word, "draw": "low -> high" if direction == "BUY" else "high -> low", "draw_label": draw_label,
                "start_label": hi_lab if direction == "SELL" else lo_lab, "end_label": lo_lab if direction == "SELL" else hi_lab},
        "ratio": ratio, "zone": {"from": px(z_lo), "to": px(z_hi)},
        "entry": entry, "stop_loss": sl_price, "tp": tps, "rr": rr, "rr_zone": [rr_near, rr_far],
        "turn": px(cfg["turn"]), "risk_points": round(risk, 2),
        "levels": [{"level": L, "price": px(L), "role": LEVEL_ROLES.get(L, "")} for L in LEVELS],
        "aligned_with_engine": aligned,
    }


def resample(df, minutes, target_minutes=240):
    """Gabungkan candle kecil jadi candle besar (mis. H1 -> H4, batas jam UTC). Candle besar yang belum
    lengkap dibuang supaya ujung kaki tidak berubah-ubah. None bila datanya kurang."""
    try:
        if df is None or len(df) < 20 or minutes >= target_minutes:
            return None
        d = df.set_index("time")
        rule = f"{target_minutes}min"
        o = d["open"].resample(rule).first()
        h = d["high"].resample(rule).max()
        l = d["low"].resample(rule).min()
        c = d["close"].resample(rule).last()
        n = d["close"].resample(rule).count()
        out = pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "n": n}).dropna()
        last_end = d.index[-1] + pd.Timedelta(minutes=minutes)
        out = out[(out.index + pd.Timedelta(minutes=target_minutes)) <= last_end]   # hanya yang sudah lengkap
        out = out.drop(columns="n").reset_index().rename(columns={"index": "time"})
        if "time" not in out.columns:
            out = out.rename(columns={out.columns[0]: "time"})
        out["volume"] = 1
        return out.reset_index(drop=True)
    except Exception:  # noqa: BLE001
        return None


def compute_htf(df, minutes, live_price, engine_direction=None, target_minutes=240):
    """Fib di timeframe besar (bawaan H4) dari candle yang sudah ada. None bila data tidak cukup."""
    big = resample(df, minutes, target_minutes)
    if big is None or len(big) < 25:
        return None
    hh, ll, cc = big["high"], big["low"], big["close"]
    tr = pd.concat([hh - ll, (hh - cc.shift()).abs(), (ll - cc.shift()).abs()], axis=1).max(axis=1)
    atr_b = float(tr.rolling(14).mean().iloc[-1])
    if not atr_b or atr_b != atr_b:
        return None
    f = compute(big, atr_b, live_price, engine_direction, overrides={"pivot": 3, "max_age": 30})
    f["tf"] = "H4" if target_minutes == 240 else f"{target_minutes}m"
    return f


def compute(df, atr_v, live_price, engine_direction=None, overrides=None):
    """Blok `fib`. df = candle TERTUTUP. Tidak pernah melempar galat ke luar.

    Dua titik jangkar (swing low dan swing high terakhir) dipakai untuk DUA gambar, seperti cara pengguna
    menarik garis: low -> high (BUY) dan high -> low (SELL). `fib` = yang searah kaki terakhir,
    `fib["alt"]` = gambar sebaliknya dari titik yang sama.
    """
    cfg = config()
    if overrides:
        cfg = {**cfg, **overrides}
    if not cfg["enabled"]:
        return {"enabled": False, "status": "OFF"}
    base = {"enabled": True, "status": "NO_SETUP", "direction": None,
            "level_set": list(LEVELS), "note": "Belum ada kaki ayunan yang cukup besar dan masih segar."}
    try:
        leg = find_leg(df, float(atr_v), cfg)
        if leg is None:
            return base
        d0, start, end, i0, i1, lab_s, lab_e = leg
        lo, hi = min(start, end), max(start, end)
        i_lo, i_hi = (i0, i1) if d0 == "BUY" else (i1, i0)
        labels = (lab_s, lab_e) if d0 == "BUY" else (lab_e, lab_s)      # (label titik low, label titik high)
        args = (lo, hi, i_lo, i_hi, df, atr_v, live_price, engine_direction, cfg)
        main = _build(d0, *args, labels=labels)
        main["alt"] = _build("SELL" if d0 == "BUY" else "BUY", *args, labels=labels)
        return main
    except Exception as e:  # noqa: BLE001  fib tidak boleh merusak sinyal utama
        base["note"] = f"Fib gagal dihitung: {type(e).__name__}"
        return base
