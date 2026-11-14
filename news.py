"""Radar news XAUUSD: jadwal rilis penting, studi reaksi harga historis, angka berita, dan sinyal.

Prinsip:
- Jadwal berasal dari sumber resmi (Fed, BLS, BEA). Tidak ada tanggal karangan.
- Reaksi harga dihitung dari candle M5 XAUUSD nyata di sekitar waktu rilis.
- Forecast/Previous dibaca dari kalender Forex Factory (feed publik) atau diketik manual. Actual diketik manual.
- Sinyal = skor dari beberapa faktor (tren H1, kecenderungan riwayat, angka berita, reaksi harga).
  Selalu menunjuk BUY atau SELL bila ada data, tetapi KEKUATAN BUKTI ditampilkan jujur: sampel kecil =
  bukti lemah. Ini bukan prediksi dan bukan jaminan.
"""
import json
import math
import os
import re
import statistics
import time
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import requests

MIN_N = 6                  # minimum kejadian historis agar statistik dipakai
HISTORY_N = 8              # jumlah kejadian terakhir yang dipelajari per jenis berita
WIN_BEFORE = 125           # menit sebelum rilis (candle M5)
WIN_AFTER = 125            # menit sesudah rilis
SETTLE_MIN = 5             # menit pertama setelah rilis: jangan entry
SETTLE_NOACT_MIN = 10      # tanpa angka Actual: tunggu lebih lama sebelum percaya pada harga saja
CONF_CAP, CONF_CAP_NOACT = 80, 50   # batas atas kekuatan bukti (tidak pernah 100%)
DONE_MIN = 150             # setelah ini berita dianggap selesai

TYPES = {
    "FOMC":    {"label": "FOMC: keputusan suku bunga", "short": "FOMC",       "et": (14, 0),  "family": "FOMC"},
    "FOMC_PC": {"label": "FOMC: konferensi pers",      "short": "FOMC Pers",  "et": (14, 30), "family": "FOMC"},
    "NFP":     {"label": "Non-Farm Payrolls (NFP)",    "short": "NFP",        "et": (8, 30),  "family": "NFP"},
    "CPI":     {"label": "CPI (inflasi)",              "short": "CPI",        "et": (8, 30),  "family": "CPI"},
    "PPI":     {"label": "PPI (harga produsen)",       "short": "PPI",        "et": (8, 30),  "family": "PPI"},
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
    # PPI: jadwal resmi BLS (termasuk jadwal revisi setelah penutupan pemerintah di awal 2026)
    "PPI":  ["2026-02-27", "2026-03-18", "2026-04-14", "2026-05-13", "2026-06-11", "2026-07-15",
             "2026-08-13", "2026-09-10", "2026-10-15", "2026-11-13", "2026-12-15"],
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
    """Ambil tanggal NFP, CPI, dan PPI dari kalender BLS (iCal). Hasil: [(type, 'YYYY-MM-DD')]."""
    out = []
    for blk in text.split("BEGIN:VEVENT")[1:]:
        s = re.search(r"SUMMARY[^:]*:(.+)", blk)
        d = re.search(r"DTSTART[^:]*:(\d{8})", blk)
        if not (s and d):
            continue
        summ = s.group(1).strip()
        typ = ("NFP" if summ.startswith("Employment Situation") else
               "CPI" if summ.startswith("Consumer Price Index") else
               "PPI" if summ.startswith("Producer Price Index") else None)
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


# ------------------------------------------------ cara membaca angka berita
# Aturan baku untuk emas (XAUUSD) terhadap berita AS (diambil dari video referensi dan praktik umum):
#   angka LEBIH PANAS dari Forecast (inflasi lebih tinggi, pekerjaan lebih banyak, suku bunga lebih tinggi)
#   -> dolar cenderung menguat -> emas cenderung TURUN (SELL)
#   angka LEBIH DINGIN dari Forecast -> dolar cenderung melemah -> emas cenderung NAIK (BUY)
# Ini kecenderungan, bukan kepastian. Pasar sering bereaksi pada hal lain (misalnya angka inti,
# revisi, nada pidato), jadi reaksi harga tetap diberi bobot terbesar.
# "unit" = ukuran satu kejutan yang dianggap bermakna (aturan praktis, boleh diubah di sini).
SURPRISE_CFG = {
    "CPI":  {"metric": "Core CPI m/m", "feed": ["Core CPI m/m", "CPI m/m"], "unit": 0.1},
    "PPI":  {"metric": "Core PPI m/m", "feed": ["Core PPI m/m", "PPI m/m"], "unit": 0.1},
    "PCE":  {"metric": "Core PCE Price Index m/m", "feed": ["Core PCE Price Index m/m", "PCE Price Index m/m"], "unit": 0.1},
    "NFP":  {"metric": "Non-Farm Employment Change", "feed": ["Non-Farm Employment Change"], "unit": 50000.0},
    "FOMC": {"metric": "Federal Funds Rate", "feed": ["Federal Funds Rate"], "unit": 0.25},
}
W_TREND, W_HIST, W_FCST = 0.40, 0.35, 0.25     # bobot sinyal SEBELUM rilis
W_PRICE, W_SURP, W_CONT = 0.50, 0.40, 0.10     # bobot sinyal SESUDAH rilis
FLOOR_PRE, FLOOR_POST = 0.05, 0.12             # skor minimum agar arah dikeluarkan
PRE_SIGNAL_HOURS = 24.0                        # sinyal arah sebelum rilis baru terbit sejak sekian jam sebelum rilis


def pre_signal_hours():
    """Ambang jam (env NEWS_PRE_SIGNAL_HOURS, bawaan 24). Nilai tidak valid -> bawaan."""
    try:
        v = float(os.getenv("NEWS_PRE_SIGNAL_HOURS", "") or PRE_SIGNAL_HOURS)
    except ValueError:
        return PRE_SIGNAL_HOURS
    return v if v > 0 else PRE_SIGNAL_HOURS


def far_signal(minutes_before, limit_hours=None):
    """Berita masih jauh: jangan beri arah. Skor sebelum rilis yang jauh hanya mengulang tren H1 saat ini
    (sama untuk semua berita) dan tidak ada Forecast, jadi menyesatkan."""
    lim = limit_hours if limit_hours is not None else pre_signal_hours()
    hrs = abs(minutes_before) / 60.0
    jauh = f"{round(hrs / 24)} hari" if hrs >= 48 else f"{round(hrs)} jam"
    batas = f"{lim:g} jam"
    return {"kind": "PRA", "direction": "WAIT", "strength": None, "confidence": 0, "score": None,
            "levels": None, "straddle": None, "factors": [], "too_far": True,
            "reasons": [f"Rilis masih sekitar {jauh} lagi. Sinyal arah baru diterbitkan {batas} sebelum rilis.",
                        "Alasannya: untuk berita yang jauh, skor hanya mengulang tren H1 emas saat ini (sama untuk semua berita) "
                        "dan Forecast belum tersedia. Tren itu bisa berubah total sebelum hari rilis.",
                        "Riwayat reaksi di bawah tetap bisa dipakai sebagai bahan persiapan."]}

_NUM = re.compile(r"^\s*[<>\u2264\u2265~]?\s*(-?\d+(?:\.\d+)?)\s*([KMBT%]?)\s*$", re.I)
_MULT = {"": 1.0, "%": 1.0, "K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}


def _clamp(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))


def parse_num(s):
    """'0.3%' -> 0.3 ; '145K' -> 145000 ; '0,3' -> 0.3 ; '1,234K' -> 1234000. None bila tidak terbaca."""
    if s is None:
        return None
    t = str(s).strip().replace(" ", "")
    if not t:
        return None
    if "," in t and "." in t:
        t = t.replace(",", "")                                   # 1,234.5 -> 1234.5
    elif "," in t:
        t = t.replace(",", "") if re.fullmatch(r"-?\d{1,3}(,\d{3})+[KMBT%]?", t, re.I) else t.replace(",", ".")
    m = _NUM.match(t)
    if not m:
        return None
    return float(m.group(1)) * _MULT[m.group(2).upper()]


def surprise(typ, forecast=None, previous=None, actual=None):
    """Baca angka berita seperti di Forex Factory: Actual dibanding Forecast (dan Forecast dibanding Previous).
    v dalam [-1, +1]: positif condong BUY emas, negatif condong SELL emas."""
    cfg = SURPRISE_CFG.get(typ)
    if not cfg:
        return None
    f, p, a = parse_num(forecast), parse_num(previous), parse_num(actual)
    unit = cfg["unit"]
    out = {"metric": cfg["metric"], "forecast": (str(forecast).strip() or None) if forecast is not None else None,
           "previous": (str(previous).strip() or None) if previous is not None else None,
           "actual": (str(actual).strip() or None) if actual is not None else None,
           "stage": None, "v": 0.0, "bias": None, "size": None, "text": None}

    def ratio(d):
        return round(abs(d) / unit, 6)             # bulatkan: 0.3 - 0.2 = 0.0999999... harus terbaca 1 unit

    def mag(d):
        return _clamp(-math.copysign(min(1.0, ratio(d) / 2.0), d))

    def size(d):
        r = ratio(d)
        return "kecil" if r < 1 else "sedang" if r < 2 else "besar"

    if f is not None and a is not None:
        d = round(a - f, 9)
        out["stage"] = "actual"
        if abs(d) < 1e-9:
            out["text"] = f"Angka sesuai perkiraan ({out['actual']} = {out['forecast']}). Tidak ada kejutan, arah ditentukan oleh reaksi harga."
        else:
            hot = d > 0
            out.update(v=round(mag(d), 3), bias="SELL" if hot else "BUY", size=size(d),
                       text=(f"Angka {out['actual']} {'di atas' if hot else 'di bawah'} perkiraan {out['forecast']} (kejutan {size(d)}): "
                             f"dolar cenderung {'menguat' if hot else 'melemah'}, emas cenderung {'turun' if hot else 'naik'}."))
    elif f is not None and p is not None:
        d = round(f - p, 9)
        out["stage"] = "forecast"
        if abs(d) < 1e-9:
            out["text"] = f"Perkiraan sama dengan angka sebelumnya ({out['forecast']}). Belum ada kecondongan dari angka."
        else:
            hot = d > 0
            out.update(v=round(0.5 * mag(d), 3), bias="SELL" if hot else "BUY", size=size(d),
                       text=(f"Pasar memperkirakan angka {'lebih tinggi' if hot else 'lebih rendah'} dari sebelumnya "
                             f"({out['forecast']} vs {out['previous']}): condong ke {'dolar kuat, emas tertekan' if hot else 'dolar lemah, emas terbantu'}. "
                             "Perkiraan sudah banyak masuk harga, jadi bobotnya kecil."))
    return out


# ---------------------------------------------- kalender Forex Factory (Forecast & Previous)
FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
_feed = {"at": 0.0, "rows": None, "ok": False, "err": None, "retry_until": 0.0}
FEED_TTL, FEED_FAIL_TTL = 20 * 60, 10 * 60
FEED_HOT_TTL, FEED_HOT_FAIL_TTL = 90, 45       # sekitar jam rilis angka Actual muncul: baca lebih sering
HOT_BEFORE_MIN, HOT_AFTER_MIN = 3, 45


def is_hot(ev, now_ts=None):
    """True bila berita `ev` sedang di sekitar jam rilis (3 menit sebelum sampai 45 menit sesudah)."""
    try:
        t0 = datetime.fromisoformat(ev["t0"]).timestamp()
    except (KeyError, ValueError, TypeError):
        return False
    now = time.time() if now_ts is None else now_ts
    return -HOT_BEFORE_MIN * 60 <= now - t0 <= HOT_AFTER_MIN * 60


def _feed_rows(now_ts=None, fetch=None, hot=False):
    """Baca feed mingguan (di-cache). Kembalikan list baris atau None. Tidak pernah melempar error.
    Saat `hot` (jam rilis) cache hanya 90 detik supaya angka Actual cepat terbaca; bila server membatasi (429)
    atau gagal, baris terakhir yang berhasil tetap dipakai dan permintaan ditunda."""
    t = time.time() if now_ts is None else now_ts
    if os.getenv("NEWS_FEED", "").strip().lower() in ("off", "0", "no"):
        return None
    if _feed["ok"]:
        ttl = FEED_HOT_TTL if hot else FEED_TTL
    else:
        ttl = FEED_HOT_FAIL_TTL if hot else FEED_FAIL_TTL
    if _feed["at"] and t - _feed["at"] < ttl:
        return _feed["rows"]
    if t < _feed["retry_until"]:
        return _feed["rows"]
    _feed["at"] = t
    try:
        if fetch is not None:
            rows = fetch()
        else:
            r = requests.get(os.getenv("NEWS_FEED_URL", FEED_URL), timeout=6,
                             headers={"User-Agent": "Mozilla/5.0 (sinyal-xauusd)"})
            if r.status_code == 429:
                try:
                    wait = float(r.headers.get("Retry-After", "") or 0)
                except ValueError:
                    wait = 0.0
                _feed["retry_until"] = t + max(wait, 120.0)
                raise ValueError("kalender membatasi permintaan (429), ditunda")
            r.raise_for_status()
            rows = r.json()
        if not isinstance(rows, list):
            raise ValueError("format feed tidak dikenal")
        _feed.update(rows=rows, ok=True, err=None, retry_until=0.0)
    except Exception as e:  # noqa: BLE001
        _feed.update(ok=False, err=f"{type(e).__name__}: {e}"[:160])
    return _feed["rows"]


def _row_utc_date(row):
    s = str(row.get("date") or row.get("dateRaw") or "")
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).date()


def feed_values(ev, rows=None):
    """Forecast/Previous/Actual berita `ev` dari feed, atau None bila tidak ada/tidak cocok."""
    cfg = SURPRISE_CFG.get(ev["type"])
    if not cfg:
        return None
    rows = rows if rows is not None else _feed_rows(hot=is_hot(ev))
    if not rows:
        return None
    day = datetime.fromisoformat(ev["t0"]).astimezone(timezone.utc).date()
    for title in cfg["feed"]:                      # urutan = prioritas (mis. Core CPI dulu)
        for r in rows:
            if str(r.get("country", "")).upper() != "USD" or str(r.get("title", "")).strip() != title:
                continue
            d = _row_utc_date(r)
            if d is None or abs((d - day).days) > 1:
                continue
            return {"title": title, "forecast": r.get("forecast") or None,
                    "previous": r.get("previous") or None, "actual": r.get("actual") or None}
    return None


def feed_status():
    return {"ok": _feed["ok"], "error": _feed["err"]}


# ------------------------------------------------------------------ sinyal
def _r2(x):
    return None if x is None else round(float(x), 2)


def _strength(s):
    a = abs(s)
    return "SEDANG" if a >= 0.45 else "LEMAH" if a >= 0.2 else "SANGAT LEMAH"


def _fac(key, name, v, w, note, additive=False):
    """additive=True: faktor pendukung kecil. Menggeser skor tanpa ikut menjadi pembagi rata-rata,
    sehingga faktor lemah yang searah tidak malah menurunkan kekuatan bukti."""
    return {"key": key, "name": name, "value": round(v, 2), "weight": w, "note": note, "additive": additive}


def _combine(factors):
    main = [f for f in factors if not f.get("additive")]
    wsum = sum(f["weight"] for f in main)
    base = 0.0 if wsum == 0 else sum(f["weight"] * f["value"] for f in main) / wsum
    extra = sum(f["weight"] * f["value"] for f in factors if f.get("additive"))
    return _clamp(base + extra)


def _warn_rr(out):
    lv = out.get("levels") or {}
    rr = lv.get("rr1")
    if rr is not None and rr < 1:
        out["reasons"].append(f"Rasio TP1 terhadap SL hanya {rr:.2f}: potensi untung kecil dibanding risiko. "
                              "Pakai ukuran sangat kecil atau lewati.")


def pre_signal(summary, ctx_dir, live, pre_hi=None, pre_lo=None, h1_score=None, sur=None):
    """Sinyal SEBELUM rilis. Skor dari tren H1, kecenderungan riwayat, dan (bila ada) Forecast vs Previous.
    Selalu memberi arah bila ada minimal satu faktor; kekuatan bukti ditampilkan apa adanya."""
    out = {"kind": "PRA", "direction": "WAIT", "strength": None, "confidence": 0,
           "reasons": [], "levels": None, "straddle": None, "factors": [], "score": None}
    n = summary.get("n", 0)
    fx = []

    if h1_score is not None:
        v = _clamp(h1_score / 5.0)
        fx.append(_fac("trend", "Tren H1", v, W_TREND, f"skor indikator H1 {h1_score:+d} dari ±5"))
    elif ctx_dir in ("BUY", "SELL"):
        fx.append(_fac("trend", "Tren H1", 0.6 if ctx_dir == "BUY" else -0.6, W_TREND, f"tren H1 {ctx_dir}"))

    sig_hist = False
    if n >= 3:
        u = summary["up60"]
        shrink = n / (n + 4.0)                      # sampel kecil ditahan (n=6 -> 60%)
        v = (u["rate"] - 0.5) * 2 * shrink
        sig_hist = u["lo"] > 0.5 or u["hi"] < 0.5
        fx.append(_fac("hist", "Riwayat reaksi", v, W_HIST,
                       f"{u['k']} dari {n} kejadian naik di menit ke-60"
                       f"{' (signifikan secara statistik)' if sig_hist else f' (sampel kecil, pengaruh ditahan {round((1 - shrink) * 100)}%)'}"))

    if sur and sur.get("stage") == "forecast" and abs(sur["v"]) > 0:
        fx.append(_fac("fcst", "Forecast vs Previous", sur["v"], W_FCST, sur["text"], additive=True))

    out["factors"] = fx
    if not fx:
        out["reasons"].append("Belum ada data untuk menentukan arah: harga H1 dan riwayat reaksi belum termuat.")
        return out

    s = _combine(fx)
    out["score"] = round(s, 3)
    if abs(s) < FLOOR_PRE:
        out["reasons"].append("Faktor-faktor saling meniadakan (skor hampir nol). Tidak ada arah yang lebih unggul; tunggu reaksi setelah rilis.")
    else:
        d = "BUY" if s > 0 else "SELL"
        out["direction"] = d
        out["strength"] = _strength(s)
        out["confidence"] = min(100, round(abs(s) * 100))
        parts = ", ".join(f"{f['name']} {'BUY' if f['value'] > 0 else 'SELL' if f['value'] < 0 else 'netral'} ({f['value']:+.2f})" for f in fx)
        out["reasons"].append(f"Arah {d} dari skor gabungan {s:+.2f}: {parts}.")
        trend_f = next((f for f in fx if f["key"] == "trend"), None)
        hist_f = next((f for f in fx if f["key"] == "hist"), None)
        if trend_f and hist_f and trend_f["value"] * hist_f["value"] < 0:
            out["reasons"].append("Tren H1 dan riwayat reaksi berlawanan arah. Keyakinan diturunkan secara otomatis.")
        if n < MIN_N:
            out["reasons"].append(f"Riwayat baru {n} kejadian (idealnya minimal {MIN_N}), jadi bukti statistik masih lemah.")
        elif not sig_hist:
            out["reasons"].append("Riwayat reaksi belum cukup konsisten secara statistik; pengaruhnya ditahan.")
        out["reasons"].append("Ini kecenderungan dari data, bukan prediksi. Arah sebelum rilis sering berbalik oleh angka berita. "
                              "Paling aman: ukuran kecil, atau tunggu reaksi setelah rilis.")
        if live is not None and n >= 3:
            sg = 1 if d == "BUY" else -1
            sl_d = summary["adv_long"]["p75"] if d == "BUY" else summary["fav_long"]["p75"]
            tp1 = summary["fav_long"]["p50"] if d == "BUY" else summary["adv_long"]["p50"]
            tp2 = summary["fav_long"]["p75"] if d == "BUY" else summary["adv_long"]["p75"]
            if sl_d and tp1 is not None and tp2 is not None:
                out["levels"] = {"entry": _r2(live), "stop_loss": _r2(live - sg * sl_d),
                                 "tp1": _r2(live + sg * tp1), "tp2": _r2(live + sg * tp2),
                                 "risk_points": _r2(sl_d), "rr1": _r2(tp1 / sl_d)}
                _warn_rr(out)
                out["reasons"].append("SL, TP1, TP2 diambil dari sebaran pergerakan 60 menit pada kejadian lalu (SL = persentil 75 gerak melawan arah).")
        elif live is not None:
            out["reasons"].append("Level SL/TP belum dihitung karena riwayat reaksi masih kurang dari 3 kejadian.")
    if n >= 3 and pre_hi is not None and pre_lo is not None:
        mr = summary.get("med_range60") or 0
        buf = 0.15 * mr
        out["straddle"] = {"buy_above": _r2(pre_hi + buf), "sell_below": _r2(pre_lo - buf),
                           "typical_move_60m": _r2(mr),
                           "note": "Alternatif lebih aman: tunggu rilis, masuk hanya setelah candle M5 menutup di luar zona ini."}
    return out


def no_direction(sig):
    """Sinyal pra-news TANPA prediksi arah. Arah sebelum angka keluar tidak terbukti andal, jadi dimatikan;
    zona breakout (straddle) tetap ditampilkan sebagai rencana bersyarat."""
    out = dict(sig)
    out.update(direction="WAIT", strength=None, confidence=0, levels=None, score=None, factors=[])
    out["reasons"] = [
        "Tidak ada prediksi arah sebelum rilis. Arah tebakan sebelum angka keluar tidak terbukti andal "
        "(angka berita sering membalik arah), jadi fitur ini dimatikan.",
        "Arah baru diberikan SETELAH angka keluar dan harga bereaksi, dan hanya bila angka (Actual vs Forecast) serta harga searah.",
        "Rencana aman: tunggu angka dan 1 candle M5 setelah rilis. Spread melebar dan harga acak tepat saat rilis."]
    return out


def post_signal(summary, p0, last_close, minutes_since, sur=None):
    """Sinyal SESUDAH rilis: reaksi harga (bobot terbesar) + kejutan angka (Actual vs Forecast) + pola lanjutan riwayat."""
    out = {"kind": "PASCA", "direction": "WAIT", "strength": None, "confidence": 0,
           "reasons": [], "levels": None, "factors": [], "score": None}
    n = summary.get("n", 0)
    r_now = last_close - p0
    out["reaction"] = {"p0": _r2(p0), "move": _r2(r_now), "minutes": round(minutes_since)}
    sv = sur["v"] if sur and sur.get("stage") == "actual" else None
    if sur and sur.get("stage") == "actual":
        out["reasons"].append(sur["text"])
    if minutes_since < SETTLE_MIN:
        out["kind"] = "RILIS"
        out["lean"] = sur["bias"] if sv else None
        out["reasons"].append("Rilis baru keluar. Spread lebar dan harga acak. Tunggu candle M5 pertama menutup (minimal 5 menit) sebelum entry.")
        if out["lean"]:
            out["reasons"].append(f"Arah awal dari angka: {out['lean']}. Masuk hanya bila harga setelah 5 menit ikut bergerak ke arah itu.")
        return out

    if sv is None and minutes_since < SETTLE_NOACT_MIN:
        out["kind"] = "RILIS"
        out["reasons"].append(f"Angka Actual belum terbaca. Arah dari harga saja tidak dipercaya sebelum menit ke-{SETTLE_NOACT_MIN}: "
                              "tunggu angka (atau isi manual di kartu angka berita).")
        return out

    scale = summary.get("med_abs_r15") if n >= 3 else None
    if scale and scale > 0:
        vp = _clamp(r_now / (2.0 * scale))
        pnote = f"gerak {r_now:+.2f} poin sejak rilis; gerak 15 menit yang biasa {scale:.2f} poin"
    else:
        vp = 0.0 if r_now == 0 else math.copysign(0.3, r_now)
        pnote = f"gerak {r_now:+.2f} poin sejak rilis (skala riwayat belum tersedia)"
    fx = [_fac("price", "Reaksi harga", vp, W_PRICE, pnote)]
    if sv is not None:
        fx.append(_fac("surp", "Kejutan angka", sv, W_SURP, sur["text"]))
    cont = summary.get("cont") or {}
    if n >= 3 and cont.get("n", 0) >= 3 and cont.get("rate") is not None and abs(vp) >= 0.5:
        fx.append(_fac("cont", "Pola lanjutan riwayat", math.copysign((cont["rate"] - 0.5) * 2, r_now), W_CONT,
                       f"pada reaksi besar, harga lanjut searah {cont['k']} dari {cont['n']} kali", additive=True))
    out["factors"] = fx
    s = _combine(fx)
    out["score"] = round(s, 3)
    if sv is not None and vp * sv < 0 and abs(vp) > 0.15 and abs(sv) > 0.15:
        out["reasons"].append("Angka dan harga bertentangan: pasar tidak sependapat dengan kejutan angka. TUNGGU, tidak ada sinyal.")
        out["conflict"] = True
        return out
    if abs(s) < FLOOR_POST:
        out["reasons"].append("Reaksi harga belum jelas (gerak kecil atau saling meniadakan dengan angka). Tunggu candle berikutnya.")
        return out
    d = "BUY" if s > 0 else "SELL"
    sg = 1 if d == "BUY" else -1
    out["direction"] = d
    out["strength"] = _strength(s)
    out["confidence"] = min(CONF_CAP if sv is not None else CONF_CAP_NOACT, round(abs(s) * 100))
    if sv is None:
        out["reasons"].append("Peringatan: arah ini dari harga saja karena angka Actual belum terbaca. Bukti lemah (dibatasi maksimal 50%).")
    out["reasons"].append(f"Arah {d} dari skor gabungan {s:+.2f}. Ini kecenderungan dari data, bukan prediksi.")
    if n < MIN_N:
        out["reasons"].append(f"Riwayat baru {n} kejadian (idealnya minimal {MIN_N}): bukti statistik masih lemah.")
    if n >= 3:
        aligned = sg * r_now > 0
        if aligned:
            sl = p0 - sg * 0.1 * summary["med_range60"]
            ext = summary.get("ext") or {}
            tp1, tp2 = max(ext.get("p50") or 0, 0), max(ext.get("p75") or 0, 0)
            if tp1 <= 0 or tp2 <= 0:
                tp1, tp2 = 0.5 * summary["med_abs_r60"], summary["med_abs_r60"]
            out["reasons"].append(f"SL di sisi harga sebelum rilis ({p0:.2f}): kembali ke sana berarti reaksi gagal.")
            risk = abs(last_close - sl)
        else:
            risk = summary["adv_long"]["p75"] if d == "BUY" else summary["fav_long"]["p75"]
            tp1 = summary["fav_long"]["p50"] if d == "BUY" else summary["adv_long"]["p50"]
            tp2 = summary["fav_long"]["p75"] if d == "BUY" else summary["adv_long"]["p75"]
            sl = last_close - sg * risk
            out["reasons"].append("Arah sinyal berlawanan dengan gerak harga sejak rilis, jadi SL/TP memakai sebaran gerak 60 menit riwayat.")
        if risk and tp1 is not None and tp2 is not None:
            tp2 = max(tp2, tp1)
            out["levels"] = {"entry": _r2(last_close), "stop_loss": _r2(sl),
                             "tp1": _r2(last_close + sg * tp1), "tp2": _r2(last_close + sg * tp2),
                             "risk_points": _r2(abs(last_close - sl)), "rr1": _r2(tp1 / abs(last_close - sl))}
            _warn_rr(out)
    else:
        out["reasons"].append("Level SL/TP belum dihitung karena riwayat reaksi masih kurang dari 3 kejadian.")
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
