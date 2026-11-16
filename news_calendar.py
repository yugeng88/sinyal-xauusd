"""Kalender berita HIGH-IMPACT semua mata uang (v19.11), dibaca dari kalender Forex Factory.

Berdampingan dengan radar bawaan (FOMC, NFP, CPI AS, PPI, PCE) yang punya jadwal resmi dan riwayat reaksi harga.
Lapisan ini melengkapinya dengan SEMUA berita berdampak tinggi lain: CPI Kanada, Retail Sales, ISM, GDP, klaim
pengangguran, keputusan suku bunga ECB/BoE/BoJ, dan seterusnya.

Prinsip (sama dengan news.py):
- Tidak ada tanggal karangan: jadwal berasal dari feed kalender (pekan ini + pekan depan). Bila feed gagal, yang
  tampil hanya radar bawaan, `MANUAL_EVENTS` (catatan dari kalender pengguna), dan `CAL_EXTRA`.
- Tidak ada riwayat reaksi harga untuk berita-berita ini, jadi TIDAK ADA sinyal entry (Entry/SL/TP) dari lapisan ini.
  Yang diberikan: hitung mundur, Forecast/Previous/Actual, pembacaan kejutan angka, notifikasi, dan peringatan
  "hindari entry baru" di sekitar jam rilis.
- Arah untuk emas hanya diberikan untuk berita USD. Untuk mata uang lain dampak ke XAUUSD/NASDAQ tidak langsung,
  jadi yang ditulis hanya arah mata uang itu sendiri.
- Ukuran "kejutan" (unit) adalah aturan praktis, bukan hasil riset.
"""
import hashlib
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

import requests

import news

PRE_MIN_DEFAULT = 60                       # menit sebelum rilis untuk peringatan pertama
LIST_BACK_MIN = 180                        # berita yang sudah rilis tetap tampil selama 3 jam (untuk membaca angka)
LIST_AHEAD_DAYS = 8

# Catatan dari kalender pengguna (screenshot 16 Nov 2026, jam WIB 20:30 = 13:30 UTC = 08:30 ET).
# Dipakai HANYA bila feed tidak punya satu pun berita untuk mata uang dan jam yang sama. Angka = Kons./Sebl. di layar.
# Judul "Indeks Harga Konsumen Umum (CPI) Ta..." terpotong di layar, ditulis apa adanya.
MANUAL_EVENTS = [
    {"currency": "CAD", "title": "Rata-Rata Pemangkasan CPI (Tahunan)", "utc": "2026-11-16T13:30:00Z", "impact": "high", "forecast": "1.9%", "previous": "1.8%", "kind": "inflation"},
    {"currency": "CAD", "title": "Tingkat Inflasi MoM", "utc": "2026-11-16T13:30:00Z", "impact": "medium", "forecast": "0.4%", "previous": "0.1%", "kind": "inflation"},
    {"currency": "CAD", "title": "Tingkat Inflasi YoY", "utc": "2026-11-16T13:30:00Z", "impact": "high", "forecast": "3.2%", "previous": "3.1%", "kind": "inflation"},
    {"currency": "CAD", "title": "Median IHK (Tahunan)", "utc": "2026-11-16T13:30:00Z", "impact": "high", "forecast": "2.0%", "previous": "1.9%", "kind": "inflation"},
    {"currency": "CAD", "title": "Tingkat Inflasi Inti YoY", "utc": "2026-11-16T13:30:00Z", "impact": "medium", "forecast": "2.2%", "previous": "2.2%", "kind": "inflation"},
    {"currency": "CAD", "title": "Indeks Harga Konsumen Umum (CPI) Tahunan", "utc": "2026-11-16T13:30:00Z", "impact": "high", "forecast": "2.5%", "previous": "2.4%", "kind": "inflation"},
    {"currency": "USD", "title": "NY Empire State Manufacturing Index", "utc": "2026-11-16T13:30:00Z", "impact": "high", "forecast": "18.0", "previous": "25.5", "kind": "activity"},
]

# --------------------------------------------------------------- klasifikasi
# (regex judul huruf kecil) -> (kategori, tanda, unit)
# tanda = +1: angka LEBIH TINGGI dari perkiraan menguatkan mata uangnya; -1: sebaliknya (mis. pengangguran, klaim).
# unit  = ukuran satu kejutan yang dianggap bermakna (aturan praktis).
# Aturan paling atas yang cocok dipakai. Judul tanpa angka (pernyataan, pidato, notulen) tidak punya tanda.
_NONNUMERIC = re.compile(r"speak|speech|testif|press conference|statement|minutes|meeting|summit|"
                         r"auction|monetary policy (report|summary)|policy report|economic projections|"
                         r"outlook|conference|forum|g7|g20|opec|ecb president|governor|chair", re.I)
_RULES = [
    (r"unemployment claims|jobless claims|initial claims|continuing claims", ("Tenaga kerja", -1, 10_000.0)),
    (r"unemployment rate", ("Tenaga kerja", -1, 0.1)),
    (r"average hourly earnings|average earnings|wage|employment cost|labor cost", ("Tenaga kerja", +1, 0.1)),
    (r"non-?farm|payrolls|adp|employment change|jolts|job openings|employment$", ("Tenaga kerja", +1, 50_000.0)),
    (r"core pce|pce price|pce deflator|core cpi|\bcpi\b|\bhicp\b|\bppi\b|inflation|price index|trimmed mean|"
     r"cpi-?(trim|median|common)", ("Inflasi", +1, 0.1)),
    (r"federal funds rate|cash rate|official bank rate|bank rate|main refinancing|deposit facility|policy rate|"
     r"overnight rate|interest rate|rate decision|rate statement", ("Suku bunga", +1, 0.25)),
    (r"retail sales", ("Konsumsi", +1, 0.3)),
    (r"\bgdp\b", ("Pertumbuhan", +1, 0.2)),
    (r"empire state|philly fed|\bzew\b", ("Aktivitas bisnis", +1, 5.0)),
    (r"\bpmi\b|\bism\b|tankan|\bifo\b|business activity|manufacturing index|services index",
     ("Aktivitas bisnis", +1, 1.0)),
    (r"sentiment|confidence|expectations", ("Survei", +1, 2.0)),
    (r"durable goods|factory orders|industrial production|manufacturing production", ("Industri", +1, 0.5)),
    (r"housing starts|building permits|home sales|pending home|new home", ("Perumahan", +1, 50_000.0)),
    (r"trade balance|current account", ("Perdagangan", +1, None)),
]
_COMPILED = [(re.compile(p, re.I), v) for p, v in _RULES]

CURRENCY_NAME = {"USD": "dolar AS", "EUR": "euro", "GBP": "poundsterling", "JPY": "yen", "CAD": "dolar Kanada",
                 "CHF": "franc Swiss", "AUD": "dolar Australia", "NZD": "dolar Selandia Baru", "CNY": "yuan"}
_KIND_LABEL = {"inflation": "Inflasi", "activity": "Aktivitas bisnis"}


def classify(currency, title, kind=None):
    """-> {category, sign, unit}. sign/unit None bila judul tidak punya angka yang bisa dibaca arahnya."""
    t = str(title or "")
    if _NONNUMERIC.search(t) and not re.search(r"rate|cpi|gdp|payroll|sales", t, re.I):
        return {"category": "Pidato / pernyataan", "sign": None, "unit": None}
    for rx, (cat, sign, unit) in _COMPILED:
        if rx.search(t):
            return {"category": cat, "sign": sign, "unit": unit}
    if kind in _KIND_LABEL:                                   # catatan manual berbahasa Indonesia
        return {"category": _KIND_LABEL[kind], "sign": +1, "unit": 0.1 if kind == "inflation" else 1.0}
    return {"category": "Lainnya", "sign": None, "unit": None}


# ------------------------------------------------------------------- pembacaan
def _size(ratio):
    return "kecil" if ratio < 1 else "sedang" if ratio < 2 else "besar"


def reading(ev, actual_override=None):
    """Baca angka berita. Hanya bila Actual ada (dari feed atau diketik manual) dan Forecast bisa dibaca.
    Arah emas HANYA untuk berita USD; mata uang lain hanya diberi arah mata uangnya sendiri."""
    actual = (actual_override or ev.get("actual") or "") or None
    out = {"stage": None, "actual": actual, "gold": None, "currency_lean": None, "size": None, "text": None}
    sign, unit = ev.get("sign"), ev.get("unit")
    f, a = news.parse_num(ev.get("forecast")), news.parse_num(actual)
    if actual is None or a is None:
        return out
    if f is None or sign is None:
        out["stage"] = "actual"
        out["text"] = f"Actual {actual}. " + ("Perkiraan tidak tersedia, jadi tidak ada kejutan yang bisa dihitung."
                                              if f is None else "Jenis berita ini tidak punya aturan arah.")
        return out
    d = round(a - f, 9)
    out["stage"] = "actual"
    cur = ev["currency"]
    if abs(d) < 1e-9:
        out["text"] = f"Actual {actual} sama dengan perkiraan {ev.get('forecast')}. Tidak ada kejutan; ikuti reaksi harga."
        return out
    strong = d * sign > 0                                      # lebih kuat untuk mata uangnya
    ratio = round(abs(d) / unit, 6) if unit else None
    size = _size(ratio) if ratio is not None else None
    out.update(size=size, currency_lean="kuat" if strong else "lemah")
    name = CURRENCY_NAME.get(cur, cur)
    txt = (f"Actual {actual} {'di atas' if d > 0 else 'di bawah'} perkiraan {ev.get('forecast')}"
           f"{f' (kejutan {size})' if size else ''}: lebih {'kuat' if strong else 'lemah'} untuk {name}.")
    if cur == "USD":
        out["gold"] = "SELL" if strong else "BUY"
        txt += f" Dolar cenderung {'menguat' if strong else 'melemah'}, emas cenderung {'turun (SELL)' if strong else 'naik (BUY)'}."
        txt += " Indeks saham (NASDAQ) bisa berbeda: data kuat bisa berarti ekonomi baik atau suku bunga naik."
    else:
        txt += f" Dampak ke XAUUSD/NASDAQ tidak langsung (lewat pergerakan dolar AS); tidak ada arah untuk emas."
    out["text"] = txt
    return out


# --------------------------------------------------------------------- feed
def _parse_ts(row):
    for k in ("datetimeISO", "dateRaw", "date"):
        s = row.get(k)
        if not s:
            continue
        try:
            dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        except ValueError:
            continue
        return (dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc))
    return None


def _norm_impact(x):
    s = str(x or "").strip().lower()
    return {"high": "high", "medium": "medium", "low": "low", "holiday": "holiday"}.get(s, s)


def _eid(cur, title, iso):
    return "CAL" + hashlib.sha1(f"{cur}|{title}|{iso}".encode()).hexdigest()[:10]


def _event(cur, title, t0, impact, forecast, previous, actual, source, kind=None):
    iso = t0.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    c = classify(cur, title, kind)
    return {"id": _eid(cur, title, iso), "currency": cur, "title": str(title).strip(), "t0": iso,
            "impact": impact, "forecast": forecast or None, "previous": previous or None,
            "actual": (actual or None) if actual not in ("", None) else None,
            "category": c["category"], "sign": c["sign"], "unit": c["unit"], "source": source,
            "relevance": "langsung" if cur == "USD" else "tidak langsung"}


def currencies():
    """Mata uang yang ditampilkan (env NEWS_CAL_CURRENCIES). Bawaan USD saja: emas dihargai dalam dolar AS, jadi
    hanya berita USD yang berdampak langsung ke XAUUSD. `ALL` atau daftar (mis. USD,EUR,CNY) untuk menambah."""
    raw = os.getenv("NEWS_CAL_CURRENCIES", "").strip().upper() or "USD"
    return None if raw == "ALL" else {x.strip() for x in raw.split(",") if x.strip()}


def impacts():
    raw = os.getenv("NEWS_CAL_IMPACT", "").strip().lower() or "high"
    return {x.strip() for x in raw.split(",") if x.strip()} or {"high"}


def from_rows(rows, allowed=None):
    """Baris feed -> daftar berita. Baris rusak dilewati."""
    allowed = allowed or impacts()
    out, seen = [], set()
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        imp = _norm_impact(r.get("impact"))
        if imp not in allowed:
            continue
        t0 = _parse_ts(r)
        cur = str(r.get("country") or r.get("currency") or "").strip().upper()
        title = str(r.get("title") or "").strip()
        if t0 is None or not cur or not title:
            continue
        ev = _event(cur, title, t0, imp, r.get("forecast"), r.get("previous"), r.get("actual"), "feed")
        if ev["id"] in seen:
            continue
        seen.add(ev["id"])
        out.append(ev)
    return out


def parse_extra(raw):
    """CAL_EXTRA (JSON): tambah berita sendiri tanpa mengubah kode. Contoh:
    [{"currency":"EUR","title":"ECB Rate Decision","utc":"2026-12-17T13:15:00Z","impact":"high"}]"""
    out = []
    try:
        for e in json.loads(raw or "[]"):
            t0 = datetime.fromisoformat(str(e["utc"]).replace("Z", "+00:00"))
            if t0.tzinfo is None:
                t0 = t0.replace(tzinfo=timezone.utc)
            out.append(_event(str(e["currency"]).upper(), e["title"], t0, _norm_impact(e.get("impact") or "high"),
                              e.get("forecast"), e.get("previous"), e.get("actual"), "manual", e.get("kind")))
    except (ValueError, TypeError, KeyError, AttributeError):
        pass
    return out


def manual_events():
    out = []
    for e in MANUAL_EVENTS:
        t0 = datetime.fromisoformat(e["utc"].replace("Z", "+00:00"))
        out.append(_event(e["currency"], e["title"], t0, e["impact"], e["forecast"], e["previous"], None,
                          "kalender pengguna", e.get("kind")))
    return out


# feed pekan depan (cadangan; tidak semua kali tersedia). Cache sederhana, tidak pernah melempar error.
_next = {"at": 0.0, "rows": None, "ok": False}
NEXT_TTL, NEXT_FAIL_TTL = 60 * 60, 15 * 60


def _next_url():
    base = os.getenv("NEWS_FEED_URL", news.FEED_URL)
    return base.replace("thisweek", "nextweek") if "thisweek" in base else None


def next_week_rows(now_ts=None, fetch=None):
    t = time.time() if now_ts is None else now_ts
    if os.getenv("NEWS_FEED", "").strip().lower() in ("off", "0", "no") or os.getenv("NEWS_CAL_NEXTWEEK", "").strip().lower() in ("off", "0", "no"):
        return None
    ttl = NEXT_TTL if _next["ok"] else NEXT_FAIL_TTL
    if _next["at"] and t - _next["at"] < ttl:
        return _next["rows"]
    _next["at"] = t
    try:
        if fetch is not None:
            rows = fetch()
        else:
            url = _next_url()
            if not url:
                return _next["rows"]
            r = requests.get(url, timeout=5, headers={"User-Agent": "Mozilla/5.0 (sinyal-xauusd)"})
            r.raise_for_status()
            rows = r.json()
        if isinstance(rows, list):
            _next.update(rows=rows, ok=True)
    except Exception:  # noqa: BLE001
        _next["ok"] = False
    return _next["rows"]


def _feed_all(now_ts=None):
    """Baris pekan ini (pakai cache news._feed_rows: tidak menambah permintaan) + pekan depan bila ada."""
    rows = news._feed_rows(now_ts=now_ts)
    hot = False
    for ev in from_rows(rows):
        if news.is_hot(ev, now_ts):
            hot = True
            break
    if hot:
        rows = news._feed_rows(now_ts=now_ts, hot=True)          # sekitar rilis: baca lebih sering agar Actual cepat terbaca
    nxt = next_week_rows(now_ts)
    return (rows or []) + (nxt or []) if (rows or nxt) else None


# ------------------------------------------------------------------ penyusunan
def _t(ev):
    return datetime.fromisoformat(ev["t0"])


def build(now, rows=None, curated_t0=(), extra=None, manual=None, actual_overrides=None):
    """Daftar berita kalender (dengan status dan pembacaan) yang relevan sekarang.
    - USD di jam yang sama dengan berita bawaan (NFP, CPI AS, FOMC, dst.) dilewati: sudah ditangani radar bawaan.
    - Catatan manual hanya dipakai bila feed tidak punya berita untuk mata uang + jam yang sama."""
    now = now.to_pydatetime() if hasattr(now, "to_pydatetime") else now
    skip = {x[:16] for x in curated_t0}
    cur_ok = currencies()
    evs = [e for e in from_rows(rows) if not (e["currency"] == "USD" and e["t0"][:16] in skip)
           and (cur_ok is None or e["currency"] in cur_ok)]
    have = {(e["currency"], e["t0"][:16]) for e in evs}
    for e in list(manual_events() if manual is None else manual) + list(extra or []):
        if (e["currency"], e["t0"][:16]) in have and e["source"] != "manual":
            continue
        if e["currency"] == "USD" and e["t0"][:16] in skip:
            continue
        if cur_ok is not None and e["currency"] not in cur_ok and e["source"] != "manual":
            continue
        if e["impact"] not in impacts() and e["source"] != "manual":      # hanya high (CAL_EXTRA tetap tampil)
            continue
        if e["id"] not in {x["id"] for x in evs}:
            evs.append(e)
    lo, hi = now - timedelta(minutes=LIST_BACK_MIN), now + timedelta(days=LIST_AHEAD_DAYS)
    out = []
    for e in evs:
        t0 = _t(e)
        if not (lo <= t0 <= hi):
            continue
        e = dict(e)
        e["status"], e["minutes"] = news.status_of(t0, now)
        e["reading"] = reading(e, (actual_overrides or {}).get(e["id"]))
        e["slot"] = e["t0"]
        out.append(e)
    out.sort(key=lambda x: (x["t0"], 0 if x["currency"] == "USD" else 1, x["title"]))
    return out


def slots(events):
    """Kelompokkan berita pada jam yang sama (mis. 7 data CPI Kanada pukul 13:30 UTC) jadi satu."""
    out = {}
    for e in events:
        s = out.setdefault(e["slot"], {"slot": e["slot"], "t0": e["t0"], "events": [], "status": e["status"],
                                       "minutes": e["minutes"]})
        s["events"].append(e)
    return [out[k] for k in sorted(out)]


# ----------------------------------------------------------------- pelindung
def guard_currencies():
    raw = os.getenv("NEWS_GUARD_CURRENCIES", "").strip().upper() or "USD"
    return None if raw == "ALL" else {x.strip() for x in raw.split(",") if x.strip()}


def _wib(iso):
    t = datetime.fromisoformat(iso) + timedelta(hours=7)
    return f"{t:%H:%M} WIB"


def guard(now, calendar_events, curated_events=(), before=None, after=None):
    """Peringatan "hindari entry baru" bila berita berdampak tinggi akan/baru saja rilis.
    Jendela: `before` menit sebelum (env NEWS_GUARD_BEFORE, bawaan 30) sampai `after` menit sesudah (bawaan 15)."""
    def _int(env, d):
        try:
            return max(0, int(os.getenv(env, "") or d))
        except ValueError:
            return d
    before = _int("NEWS_GUARD_BEFORE", 30) if before is None else before
    after = _int("NEWS_GUARD_AFTER", 15) if after is None else after
    if os.getenv("NEWS_GUARD", "").strip().lower() in ("off", "0", "no"):
        return []
    now = now.to_pydatetime() if hasattr(now, "to_pydatetime") else now
    cur_ok = guard_currencies()
    hits = {}
    for e in list(calendar_events) + list(curated_events):
        cur = e.get("currency", "USD")
        if cur_ok is not None and cur not in cur_ok:
            continue
        if e.get("impact", "high") != "high":
            continue
        m = (now - datetime.fromisoformat(e["t0"])).total_seconds() / 60
        if -before <= m <= after:
            h = hits.setdefault(e["t0"], {"t0": e["t0"], "minutes": round(m, 1), "names": [], "currencies": set()})
            h["names"].append(e.get("short") or e["title"])
            h["currencies"].add(cur)
    out = []
    for h in sorted(hits.values(), key=lambda x: x["t0"]):
        names = ", ".join(dict.fromkeys(h["names"]))
        names = names if len(names) <= 90 else names[:87] + "..."
        cur = "/".join(sorted(h["currencies"]))
        if h["minutes"] < 0:
            when = f"{-h['minutes']:.0f} menit lagi"
        else:
            when = f"baru rilis {h['minutes']:.0f} menit lalu"
        out.append({"t0": h["t0"], "minutes": h["minutes"], "currencies": sorted(h["currencies"]),
                    "text": f"Berita high-impact {cur}: {names} pukul {_wib(h['t0'])} ({when}). "
                            "Spread melebar dan harga acak: hindari entry baru sampai reaksi pertama selesai."})
    return out


# ---------------------------------------------------------------- notifikasi
def notify_currencies():
    raw = os.getenv("NEWS_CAL_NOTIFY", "").strip().upper() or "ALL"
    if raw in ("OFF", "0", "NO"):
        return set()
    return None if raw == "ALL" else {x.strip() for x in raw.split(",") if x.strip()}


def _line(e):
    f, p = e.get("forecast") or "–", e.get("previous") or "–"
    return f"{e['currency']} {e['title']}: perkiraan {f}, sebelumnya {p}"


def pre_message(slot, minutes_left):
    evs = slot["events"]
    usd = any(e["currency"] == "USD" for e in evs)
    cur = "/".join(sorted({e["currency"] for e in evs}))
    head = f"Berita high-impact {cur} {minutes_left:.0f} menit lagi · {_wib(slot['t0'])}"
    lines = [_line(e) for e in evs[:8]]
    if len(evs) > 8:
        lines.append(f"... dan {len(evs) - 8} berita lain di jam yang sama.")
    lines.append("Dampak ke emas/NASDAQ langsung (USD). Tidak ada sinyal arah dari lapisan ini: tunggu angka dan reaksi harga."
                 if usd else
                 "Dampak ke XAUUSD/NASDAQ tidak langsung (lewat dolar AS). Tidak ada sinyal arah dari lapisan ini.")
    lines.append("Spread melebar saat rilis. Bukan saran investasi.")
    return head, "\n".join(lines)


def post_message(slot):
    ev = [e for e in slot["events"] if e["reading"]["stage"] == "actual"]
    cur = "/".join(sorted({e["currency"] for e in ev}))
    head = f"Angka keluar {cur} · {_wib(slot['t0'])}"
    lines = []
    for e in ev[:6]:
        lines.append(f"{e['currency']} {e['title']}: actual {e['reading']['actual']} (perkiraan {e.get('forecast') or '–'}). "
                     f"{(e['reading']['text'] or '').split(': ', 1)[-1] if e['reading']['size'] else ''}".strip())
    lines.append("Tunggu 5 menit sebelum entry. Harga adalah hakim terakhir. Bukan saran investasi.")
    return head, "\n".join(lines)


def due_alerts(now, slot_list, pre_min=None):
    """Peringatan yang perlu dikirim sekarang: [(kunci, jenis, slot, menit)]. USD: 60 dan 5 menit; lainnya: 60 saja.
    Pasca-rilis hanya bila ada Actual dari feed."""
    pre_min = PRE_MIN_DEFAULT if pre_min is None else pre_min
    ok = notify_currencies()
    out = []
    for s in slot_list:
        evs = [e for e in s["events"] if ok is None or e["currency"] in ok]
        if not evs:
            continue
        s = {**s, "events": evs}
        left = -s["minutes"]
        usd = any(e["currency"] == "USD" for e in evs)
        if s["status"] == "PRA" and left <= pre_min:
            if usd and left <= 5:
                out.append((f"calw5:{s['slot']}", "pra_5", s, left))
            elif left > 5 or not usd:
                out.append((f"calw60:{s['slot']}", "pra_60", s, left))
        elif s["status"] == "PASCA" and any(e["reading"]["stage"] == "actual" for e in evs):
            out.append((f"calq:{s['slot']}", "pasca", s, -left))
    return out
