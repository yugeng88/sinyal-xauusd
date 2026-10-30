"""Radar news XAUUSD: jadwal rilis penting, studi reaksi harga historis, dan sinyal.

Prinsip:
- Jadwal berasal dari sumber resmi (Fed, BLS, BEA). Tidak ada tanggal karangan.
- Reaksi harga dihitung dari candle M5 XAUUSD nyata di sekitar waktu rilis.
- Sinyal = ringkasan statistik riwayat + konteks harga sekarang. Sampel kecil (n < MIN_N)
  tidak pernah dijadikan sinyal arah. Ini bukan jaminan dan bukan saran investasi.
"""
import json
import math
import os
import re
import statistics
import time
from datetime import date, datetime, timedelta, timezone

import pandas as pd

MIN_N = 6                  # minimum kejadian historis agar statistik dipakai
HISTORY_N = 8              # jumlah kejadian terakhir yang dipelajari per jenis berita
WIN_BEFORE = 125           # menit sebelum rilis (candle M5)
WIN_AFTER = 125            # menit sesudah rilis
SETTLE_MIN = 5             # menit pertama setelah rilis: jangan entry
DONE_MIN = 150             # setelah ini berita dianggap selesai

TYPES = {
    "FOMC":    {"label": "FOMC: keputusan suku bunga", "short": "FOMC",       "et": (14, 0),  "family": "FOMC"},
    "FOMC_PC": {"label": "FOMC: konferensi pers",      "short": "FOMC Pers",  "et": (14, 30), "family": "FOMC"},
    "NFP":     {"label": "Non-Farm Payrolls (NFP)",    "short": "NFP",        "et": (8, 30),  "family": "NFP"},
    "CPI":     {"label": "CPI (inflasi)",              "short": "CPI",        "et": (8, 30),  "family": "CPI"},
    "PCE":     {"label": "PCE (Personal Income & Outlays)", "short": "PCE",   "et": (8, 30),  "family": "PCE"},
}

# Tanggal rilis (waktu AS). Sumber: Federal Reserve (kalender FOMC), BLS (jadwal rilis 2026),
# BEA (jadwal rilis 2026). Tanggal bertanda ESTIMATED adalah perkiraan (belum terkonfirmasi).
SCHEDULE = {
    "FOMC": ["2025-12-10", "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
             "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09"],
    "NFP":  ["2026-05-08", "2026-06-05", "2026-07-02", "2026-08-07", "2026-09-04",
             "2026-10-02", "2026-11-06", "2026-12-04"],
    "CPI":  ["2026-05-12", "2026-06-10", "2026-07-14", "2026-08-12", "2026-09-11",
             "2026-10-14", "2026-11-10", "2026-12-10"],
    "PCE":  ["2026-07-30", "2026-08-26", "2026-09-30", "2026-10-29", "2026-11-25", "2026-12-23"],
}
ESTIMATED = {("PCE", "2026-11-25"), ("PCE", "2026-12-23")}
SCHEDULE["FOMC_PC"] = SCHEDULE["FOMC"]


# ------------------------------------------------------------------ waktu
def et_offset(d):
    """Selisih waktu New York terhadap UTC (jam): -4 saat DST (EDT), -5 saat standar (EST)."""
    mar1 = date(d.year, 3, 1)
    dst_start = mar1 + timedelta(days=(6 - mar1.weekday()) % 7) + timedelta(days=7)   # Minggu ke-2 Maret
    nov1 = date(d.year, 11, 1)
    dst_end = nov1 + timedelta(days=(6 - nov1.weekday()) % 7)                         # Minggu ke-1 November
    return -4 if dst_start <= d < dst_end else -5


def event_utc(typ, d):
    h, m = TYPES[typ]["et"]
    return datetime(d.year, d.month, d.day, h, m, tzinfo=timezone.utc) - timedelta(hours=et_offset(d))


def parse_extra(raw):
    """EXTRA_EVENTS (JSON): tambah/koreksi jadwal tanpa mengubah kode. Contoh:
    [{"type":"NFP","date":"2027-01-08"},{"type":"CPI","date":"2027-01-13"}]"""
    out = []
    try:
        for e in json.loads(raw or "[]"):
            if e.get("type") in TYPES and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(e.get("date", ""))):
                out.append((e["type"], e["date"]))
    except (ValueError, TypeError, AttributeError):
        pass
    return out


def parse_bls_ics(text):
    """Ambil tanggal NFP dan CPI dari kalender BLS (iCal). Hasil: [(type, 'YYYY-MM-DD')]."""
    out = []
    for blk in text.split("BEGIN:VEVENT")[1:]:
        s = re.search(r"SUMMARY[^:]*:(.+)", blk)
        d = re.search(r"DTSTART[^:]*:(\d{8})", blk)
        if not (s and d):
            continue
        summ = s.group(1).strip()
        typ = ("NFP" if summ.startswith("Employment Situation") else
               "CPI" if summ.startswith("Consumer Price Index") else None)
        if typ:
            x = d.group(1)
            out.append((typ, f"{x[:4]}-{x[4:6]}-{x[6:]}"))
    return out


def build_events(now, extra=()):
    """Semua kejadian (lampau dan mendatang) beserta status relatif terhadap `now`."""
    seen, evs = set(), []
    pairs = [(t, d) for t, ds in SCHEDULE.items() for d in ds] + list(extra)
    for typ, ds in pairs:
        if typ not in TYPES:
            continue
        pair = [(typ, ds)] + ([("FOMC_PC", ds)] if typ == "FOMC" and (typ, ds) in set(extra) else [])
        for t_, d_ in pair:
            if (t_, d_) in seen:
                continue
            seen.add((t_, d_))
            dd = date.fromisoformat(d_)
            t0 = event_utc(t_, dd)
            evs.append({"id": f"{t_}@{d_}", "type": t_, "date": d_, "label": TYPES[t_]["label"],
                        "short": TYPES[t_]["short"], "t0": t0.isoformat(),
                        "confirmed": (t_, d_) not in ESTIMATED})
    evs.sort(key=lambda e: e["t0"])
    for e in evs:
        e["status"], e["minutes"] = status_of(datetime.fromisoformat(e["t0"]), now)
    return evs


def status_of(t0, now):
    now = now.to_pydatetime() if hasattr(now, "to_pydatetime") else now
    m = (now - t0).total_seconds() / 60
    if m < 0:
        return "PRA", round(m, 1)
    if m < SETTLE_MIN:
        return "RILIS", round(m, 1)
    if m < DONE_MIN:
        return "PASCA", round(m, 1)
    return "SELESAI", round(m, 1)


def pick_focus(evs):
    """Berita yang paling relevan sekarang: yang sedang berjalan atau berikutnya."""
    live = [e for e in evs if e["status"] in ("RILIS", "PASCA")]
    if live:
        return live[-1]
    nxt = [e for e in evs if e["status"] == "PRA"]
    return nxt[0] if nxt else evs[-1]


def past_dates(typ, now, n=HISTORY_N):
    """Tanggal kejadian lampau (sudah selesai) untuk studi, terbaru dulu."""
    out = []
    for d in SCHEDULE.get(typ, []):
        t0 = event_utc(typ, date.fromisoformat(d))
        if (now - t0).total_seconds() / 60 >= DONE_MIN and (typ, d) not in ESTIMATED:
            out.append(d)
    return sorted(out, reverse=True)[:n]


# ------------------------------------------------------------ metrik reaksi
def reaction(df, t0):
    """Ukur reaksi harga di sekitar rilis dari candle M5. None bila data tidak lengkap."""
    t0 = pd.Timestamp(t0)
    if t0.tzinfo is None:
        t0 = t0.tz_localize("UTC")
    idx = df.set_index("time")

    def bar(ts):
        return idx.loc[ts] if ts in idx.index else None

    b0 = bar(t0)
    if b0 is None:
        return None
    p0 = float(b0["open"])

    def r(min_after):
        b = bar(t0 + pd.Timedelta(minutes=min_after - 5))
        return None if b is None else float(b["close"]) - p0

    r5, r15, r30, r60 = r(5), r(15), r(30), r(60)
    post = df[(df["time"] >= t0) & (df["time"] < t0 + pd.Timedelta(minutes=60))]
    pre = df[(df["time"] >= t0 - pd.Timedelta(minutes=60)) & (df["time"] < t0)]
    if None in (r5, r15, r60) or len(post) < 10 or len(pre) < 8:
        return None
    b_start = bar(t0 - pd.Timedelta(minutes=120))
    return {
        "t0": t0.isoformat(), "p0": round(p0, 2),
        "r5": round(r5, 2), "r15": round(r15, 2), "r30": None if r30 is None else round(r30, 2),
        "r60": round(r60, 2),
        "up60": round(float(post["high"].max()) - p0, 2), "dn60": round(p0 - float(post["low"].min()), 2),
        "pre_hi": round(float(pre["high"].max()), 2), "pre_lo": round(float(pre["low"].min()), 2),
        "pre_drift": None if b_start is None else round(p0 - float(b_start["open"]), 2),
    }


def wilson(k, n, z=1.96):
    if n == 0:
        return 0.0, 1.0
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centre - half), min(1.0, centre + half)


def pct(vals, q):
    if not vals:
        return None
    s = sorted(vals)
    k = (len(s) - 1) * q
    f, c = math.floor(k), math.ceil(k)
    return s[f] if f == c else s[f] + (s[c] - s[f]) * (k - f)


def _rate(k, n):
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "rate": round(k / n, 3) if n else None, "lo": round(lo, 3), "hi": round(hi, 3)}


def summarize(rows):
    n = len(rows)
    if n == 0:
        return {"n": 0, "enough": False}
    med15 = statistics.median(abs(r["r15"]) for r in rows)
    strong = [r for r in rows if abs(r["r15"]) >= med15 and r["r15"] != 0]
    cont_k = sum(1 for r in strong if r["r60"] * r["r15"] > 0)
    fade = [r for r in rows if r["r5"] != 0 and r["r60"] != 0]
    ext = [(r["r60"] - r["r15"]) * (1 if r["r15"] > 0 else -1) for r in strong]
    rng = [r["up60"] + r["dn60"] for r in rows]
    return {
        "n": n, "enough": n >= MIN_N,
        "up60": _rate(sum(1 for r in rows if r["r60"] > 0), n),
        "up15": _rate(sum(1 for r in rows if r["r15"] > 0), n),
        "med_abs_r15": round(med15, 2),
        "med_abs_r60": round(statistics.median(abs(r["r60"]) for r in rows), 2),
        "med_range60": round(statistics.median(rng), 2),
        "cont": _rate(cont_k, len(strong)),
        "fade5": _rate(sum(1 for r in fade if r["r5"] * r["r60"] < 0), len(fade)),
        "ext": {"p25": pct(ext, .25), "p50": pct(ext, .5), "p75": pct(ext, .75)} if ext else None,
        "adv_long": {"p50": pct([r["dn60"] for r in rows], .5), "p75": pct([r["dn60"] for r in rows], .75)},
        "fav_long": {"p50": pct([r["up60"] for r in rows], .5), "p75": pct([r["up60"] for r in rows], .75)},
        "rows": sorted(rows, key=lambda r: r["t0"], reverse=True),
    }


# ------------------------------------------------------------------ sinyal
def _r2(x):
    return None if x is None else round(float(x), 2)


def pre_signal(summary, ctx_dir, live, pre_hi=None, pre_lo=None):
    """Sinyal SEBELUM rilis. Arah hanya bila statistik riwayat cukup kuat; selain itu WAIT + zona breakout."""
    out = {"kind": "PRA", "direction": "WAIT", "strength": None, "confidence": 0,
           "reasons": [], "levels": None, "straddle": None}
    n = summary.get("n", 0)
    if n < MIN_N:
        out["reasons"].append(f"Riwayat hanya {n} kejadian (minimal {MIN_N}). Tidak ada bias statistik, jadi tidak ada sinyal arah.")
    else:
        u = summary["up60"]
        bias = "BUY" if u["lo"] > 0.5 else "SELL" if u["hi"] < 0.5 else None
        out["reasons"].append(f"Dalam {n} kejadian terakhir, harga naik pada menit ke-60 sebanyak {u['k']} kali ({round(u['rate']*100)}%).")
        if bias is None:
            out["reasons"].append("Selisih naik/turun belum cukup jelas secara statistik (interval kepercayaan 95% masih mencakup 50%). Tidak ada bias arah.")
        elif ctx_dir not in ("WAIT", None, bias):
            out["reasons"].append(f"Bias riwayat {bias}, tetapi tren H1 sekarang berlawanan ({ctx_dir}). Dibatalkan, tunggu reaksi.")
        else:
            out["direction"] = bias
            out["strength"] = "SEDANG" if ctx_dir == bias else "LEMAH"
            lo = u["lo"] if bias == "BUY" else 1 - u["hi"]
            out["confidence"] = min(60, round(lo * 100))
            out["reasons"].append(f"Bias {bias} lolos uji statistik; tren H1 {'searah' if ctx_dir == bias else 'netral'}.")
            if live is not None:
                sg = 1 if bias == "BUY" else -1
                sl_d = summary["adv_long"]["p75"] if bias == "BUY" else summary["fav_long"]["p75"]
                tp1 = summary["fav_long"]["p50"] if bias == "BUY" else summary["adv_long"]["p50"]
                tp2 = summary["fav_long"]["p75"] if bias == "BUY" else summary["adv_long"]["p75"]
                out["levels"] = {"entry": _r2(live), "stop_loss": _r2(live - sg * sl_d),
                                 "tp1": _r2(live + sg * tp1), "tp2": _r2(live + sg * tp2),
                                 "risk_points": _r2(sl_d), "rr1": _r2(tp1 / sl_d) if sl_d else None}
                out["reasons"].append("SL, TP1, TP2 diambil dari sebaran pergerakan 60 menit pada kejadian lalu (SL = persentil 75 gerak melawan arah).")
    if n >= 3 and pre_hi is not None and pre_lo is not None:
        mr = summary.get("med_range60") or 0
        buf = 0.15 * mr
        out["straddle"] = {"buy_above": _r2(pre_hi + buf), "sell_below": _r2(pre_lo - buf),
                           "typical_move_60m": _r2(mr),
                           "note": "Tunggu rilis. Masuk hanya setelah candle M5 menutup di luar zona ini, jangan menebak arah."}
    return out


def post_signal(summary, p0, last_close, minutes_since):
    """Sinyal SESUDAH rilis berdasarkan reaksi harga sejauh ini dibanding riwayat."""
    out = {"kind": "PASCA", "direction": "WAIT", "confidence": 0, "reasons": [], "levels": None}
    if minutes_since < SETTLE_MIN:
        out["kind"] = "RILIS"
        out["reasons"].append("Rilis baru keluar. Spread lebar dan harga acak. Tunggu minimal 5 menit, jangan entry sekarang.")
        return out
    r_now = last_close - p0
    out["reaction"] = {"p0": _r2(p0), "move": _r2(r_now), "minutes": round(minutes_since)}
    if summary.get("n", 0) < MIN_N:
        out["reasons"].append(f"Riwayat hanya {summary.get('n', 0)} kejadian: reaksi tidak bisa dinilai secara statistik.")
        return out
    thr = summary["med_abs_r15"]
    cont = summary["cont"]
    big = abs(r_now) >= thr
    out["reasons"].append(f"Gerak sejak rilis {r_now:+.2f} poin; gerak 15 menit yang biasa (median) {thr:.2f} poin.")
    if not big:
        out["reasons"].append("Reaksi belum sebesar biasanya. Belum ada sinyal.")
        return out
    if cont["n"] < 3 or cont["rate"] is None or cont["rate"] < 0.6:
        out["reasons"].append(f"Pada reaksi sebesar ini, harga hanya lanjut searah {cont['k']} dari {cont['n']} kali. Tidak cukup meyakinkan.")
        return out
    d = "BUY" if r_now > 0 else "SELL"
    sg = 1 if d == "BUY" else -1
    buf = 0.1 * summary["med_range60"]
    sl = p0 - sg * buf
    ext = summary.get("ext") or {}
    tp1, tp2 = max(ext.get("p50") or 0, 0), max(ext.get("p75") or 0, 0)
    out["direction"] = d
    out["confidence"] = min(60, round(cont["lo"] * 100))
    out["levels"] = {"entry": _r2(last_close), "stop_loss": _r2(sl),
                     "tp1": _r2(last_close + sg * tp1), "tp2": _r2(last_close + sg * tp2),
                     "risk_points": _r2(abs(last_close - sl))}
    out["reasons"].append(f"Reaksi besar dan historis lanjut searah {cont['k']} dari {cont['n']} kali. SL di sisi harga sebelum rilis ({p0:.2f}), karena kembali ke sana berarti reaksi gagal.")
    return out


# ----------------------------------------------------- pengambilan riwayat
_win = {}        # (family, tanggal) -> DataFrame M5
_calls = []      # waktu panggilan API (detik) untuk pembatas per menit


def window_bounds(typ, d):
    t0 = event_utc(typ, date.fromisoformat(d))
    return t0 - timedelta(minutes=WIN_BEFORE), t0 + timedelta(minutes=WIN_AFTER)


def _family_bounds(family, d):
    types = [t for t, v in TYPES.items() if v["family"] == family]
    a = [window_bounds(t, d) for t in types]
    return min(x[0] for x in a), max(x[1] for x in a)


def ensure_windows(family, dates, fetch_fn, per_minute=7, max_per_call=4, clock=time.monotonic):
    """Ambil jendela candle yang belum ada, dengan pembatas kuota. Kembalikan status kemajuan."""
    missing = [d for d in dates if (family, d) not in _win]
    done_now, err, wait = 0, None, 0
    for d in missing:
        if done_now >= max_per_call:
            break
        t = clock()
        _calls[:] = [c for c in _calls if t - c < 60]
        if len(_calls) >= per_minute:
            wait = int(60 - (t - _calls[0])) + 1
            break
        _calls.append(t)
        try:
            a, b = _family_bounds(family, d)
            df = fetch_fn(a, b)
            if df is None or len(df) < 20:
                raise ValueError("data terlalu sedikit pada rentang itu")
            _win[(family, d)] = df
            done_now += 1
        except Exception as e:  # noqa: BLE001
            err = str(e)
            if "minute" in err.lower() or "credit" in err.lower() or "429" in err:
                wait = 30
            break
    left = [d for d in dates if (family, d) not in _win]
    return {"total": len(dates), "done": len(dates) - len(left), "wait_seconds": wait, "error": err}


def study(typ, dates):
    fam = TYPES[typ]["family"]
    rows = []
    for d in dates:
        df = _win.get((fam, d))
        if df is None:
            continue
        r = reaction(df, event_utc(typ, date.fromisoformat(d)))
        if r:
            r["date"] = d
            rows.append(r)
    return summarize(rows)
