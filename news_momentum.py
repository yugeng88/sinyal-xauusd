"""NEWS MOMENTUM (v19.31): sinyal BUY/SELL LIMIT saat pasar bergerak mendadak karena berita tak terjadwal.

Contoh: emas dan Nasdaq naik 2-3% dalam beberapa jam setelah aksi jual besar (relief rally).

Prinsip (sama dengan modul news lain: jujur soal batas bukti):
  - Pemicu = GERAKAN HARGA (impuls M5 besar dan cepat), bukan judul berita. Berita terbit setelah harga bergerak,
    jadi judul hanya KONFIRMASI. Entry LIMIT di pullback 38.2-61.8% dari impuls, jangan mengejar.
  - Sinyal hanya keluar bila ada konfirmasi berita: (a) instrumen lain bergerak searah, atau (b) skor judul
    searah. Judul yang jelas berlawanan memblokir sinyal.
  - Searah tren H1 BUKAN syarat (rebound setelah aksi jual selalu melawan tren H1), tetapi dicatat sebagai
    peringatan dan mengurangi "kekuatan bukti".
  - Kekuatan bukti = jumlah konfirmasi (lintas aset, judul, tren H1) dari 3. Bukan probabilitas profit.
  - Tidak ada backtest berita (RSS hanya menyimpan judul beberapa hari). Catat hasilnya di akun demo dulu.
"""
from __future__ import annotations

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

import news_context
import signals

OFF_VALUES = ("0", "off", "false", "no")


def enabled():
    return os.getenv("NEWS_MOMENTUM", "1").strip().lower() not in OFF_VALUES


def notify_enabled():
    return os.getenv("MOM_NOTIFY", "1").strip().lower() not in OFF_VALUES


def _f(name, default):
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return float(default)


def cfg():
    return {
        "atr": _f("MOM_ATR", 2.5),                  # impuls minimal = sekian x ATR M5 (diukur sebelum impuls)
        "lookback": int(_f("MOM_LOOKBACK", 36)),    # candle M5 yang dicari impulsnya (36 = 3 jam)
        "max_bars": int(_f("MOM_MAX_BARS", 12)),    # impuls harus selesai dalam sekian candle (12 = 60 menit)
        "expire": int(_f("MOM_EXPIRE_BARS", 18)),   # rencana kedaluwarsa sekian candle setelah puncak (18 = 90 menit)
        "zone": (_f("MOM_ZONE_NEAR", 0.382), _f("MOM_ZONE_FAR", 0.618)),
        "entry": _f("MOM_ENTRY", 0.5),
        "cancel": _f("MOM_CANCEL", 0.786),          # pullback lebih dalam dari ini = impuls gagal
        "cross": _f("MOM_CROSS_RATIO", 0.6),        # instrumen lain cukup bergerak 0.6x ambang yang sama
        "stale_min": _f("MOM_STALE_MIN", 20),
    }


# ------------------------------------------------------------------ deteksi impuls dan status
def find_impulse(closed, c):
    """Cari kaki impuls terbesar (naik atau turun) dalam `lookback` candle tertutup. None bila tidak ada."""
    n = len(closed)
    if n < 60:
        return None
    atr = signals.atr(closed)
    hi, lo, tm = closed["high"].to_numpy(), closed["low"].to_numpy(), closed["time"]
    start = max(1, n - c["lookback"])
    best = None
    for direction in ("BUY", "SELL"):
        for j in range(start, n):                                    # j = candle puncak/dasar impuls
            lo_i = max(start - 1, j - c["max_bars"])
            if direction == "BUY":
                i = lo_i + int(lo[lo_i:j + 1].argmin())
                leg = float(hi[j] - lo[i])
            else:
                i = lo_i + int(hi[lo_i:j + 1].argmax())
                leg = float(hi[i] - lo[j])
            if i >= j or leg <= 0:
                continue
            ref = float(atr.iloc[max(0, i - 1)])                     # ATR sebelum impuls (tidak digelembungkan impuls)
            if ref <= 0:
                continue
            ratio = leg / ref
            if best is None or ratio > best["ratio"]:
                best = {"direction": direction, "i": i, "j": j, "leg": leg, "atr": ref, "ratio": round(ratio, 2),
                        "origin": float(lo[i] if direction == "BUY" else hi[i]),
                        "peak": float(hi[j] if direction == "BUY" else lo[j]),
                        "origin_time": tm.iloc[i], "peak_time": tm.iloc[j]}
    return best


def _status(imp, closed, price, c):
    """Status rencana dari posisi harga terhadap impuls. Dihitung ulang tiap kali dari candle (tanpa state tersimpan)."""
    d, leg = imp["direction"], imp["leg"]
    sign = 1 if d == "BUY" else -1
    after = closed.iloc[imp["j"] + 1:]
    bars_since = len(after)
    retr = lambda p: (imp["peak"] - p) / leg * sign                  # 0 = di puncak, 1 = kembali ke awal impuls
    deepest = 0.0
    if bars_since:
        ext = after["low"].min() if d == "BUY" else after["high"].max()
        deepest = retr(float(ext))
    now_retr = retr(price)
    if bars_since > c["expire"]:
        return "EXPIRED", now_retr, deepest
    if deepest >= c["cancel"] or now_retr >= 1.0:
        return "CANCELLED", now_retr, deepest
    near, far = c["zone"]
    if near <= now_retr <= far:
        return "IN_ZONE", now_retr, deepest
    if now_retr > far:
        return "DEEP", now_retr, deepest
    return "WAIT_PULLBACK", now_retr, deepest


def plan_levels(imp, symbol, c):
    d, leg = imp["direction"], imp["leg"]
    sign = 1 if d == "BUY" else -1
    near, far = c["zone"]
    entry = imp["peak"] - sign * leg * c["entry"]
    zone = sorted([imp["peak"] - sign * leg * near, imp["peak"] - sign * leg * far])
    lv = signals.make_levels(d, entry, imp["atr"], symbol, struct=abs(entry - imp["origin"]))
    return lv, [round(zone[0], 2), round(zone[1], 2)]


# ------------------------------------------------------------------ konfirmasi berita
def judge(direction, cross, sent, h1_dir):
    """Gabungkan konfirmasi. Mengembalikan (ok, evidence, reasons, warnings)."""
    sign = 1 if direction == "BUY" else -1
    reasons, warns = [], []
    cross_ok = bool(cross and cross.get("direction") == direction)
    s = (sent or {}).get("score", 0.0)
    usable = bool(sent and sent.get("usable"))
    sent_ok = usable and s * sign >= 0.15
    sent_bad = usable and s * sign <= -0.15
    h1_ok = h1_dir == direction
    if cross_ok:
        reasons.append(f"{cross['symbol']} ikut bergerak searah ({cross['ratio']}x ATR)")
    else:
        warns.append("instrumen lain belum bergerak searah")
    if sent_ok:
        reasons.append(f"judul berita searah (skor {s:+.2f} dari {sent['n_hits']} judul)")
    elif sent_bad:
        warns.append(f"judul berita berlawanan (skor {s:+.2f}); sinyal ditahan")
    elif not usable:
        warns.append("judul berita belum cukup untuk dibaca")
    if h1_ok:
        reasons.append(f"tren H1 {h1_dir} searah")
    elif h1_dir in ("BUY", "SELL"):
        warns.append(f"melawan tren H1 ({h1_dir}); risiko lebih tinggi, rebound bisa gagal")
    ok = (cross_ok or sent_ok) and not sent_bad
    n = int(cross_ok) + int(sent_ok) + int(h1_ok)
    return ok, {"cross": cross_ok, "sentiment": sent_ok, "h1": h1_ok, "n": n, "of": 3,
                "label": {0: "TANPA BUKTI", 1: "LEMAH", 2: "SEDANG", 3: "KUAT"}[n]}, reasons, warns


def detect(df, symbol, now=None, cross=None, sent=None, h1_dir=None):
    """Hasil NEWS MOMENTUM untuk satu instrumen dari candle M5. Tidak pernah melempar error."""
    c = cfg()
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    out = {"symbol": symbol, "state": "NONE", "direction": "WAIT", "label": "tidak ada gerakan mendadak",
           "threshold_atr": c["atr"], "reasons": [], "warnings": [], "levels": None, "zone": None,
           "experimental": True}
    try:
        if df is None or len(df) < 61:
            out["label"] = "data M5 belum cukup"
            return out
        closed, run = signals.split_closed(df, now, 5)
        last_t = pd.Timestamp(df["time"].iloc[-1])
        if (now - last_t) > pd.Timedelta(minutes=c["stale_min"]):
            out.update(state="STALE", label="data M5 lama atau pasar tutup")
            return out
        price = float(df["close"].iloc[-1])
        imp = find_impulse(closed.reset_index(drop=True), c)
        if imp is None:
            return out
        out["best_ratio"] = imp["ratio"]
        if imp["ratio"] < c["atr"]:
            out["label"] = f"gerakan terbesar {imp['ratio']}x ATR (ambang {c['atr']}x)"
            return out
        st, now_retr, deepest = _status(imp, closed.reset_index(drop=True), price, c)
        lv, zone = plan_levels(imp, symbol, c)
        ok, ev, reasons, warns = judge(imp["direction"], cross, sent, h1_dir)
        d = imp["direction"]
        out.update(impulse={"direction": d, "origin": round(imp["origin"], 2), "peak": round(imp["peak"], 2),
                            "leg": round(imp["leg"], 2), "ratio": imp["ratio"], "atr": round(imp["atr"], 2),
                            "origin_time": imp["origin_time"].isoformat(), "peak_time": imp["peak_time"].isoformat(),
                            "bars": int(imp["j"] - imp["i"]), "pct": round(imp["leg"] / imp["origin"] * 100, 2)},
                   price=round(price, 2), retrace=round(now_retr, 2), evidence=ev, reasons=reasons,
                   warnings=warns, levels=lv, zone=zone,
                   key=f"{symbol}:{d}:{imp['origin_time'].strftime('%Y%m%d%H%M')}")
        if st in ("EXPIRED", "CANCELLED"):
            out.update(state=st, direction="WAIT",
                       label="rencana kedaluwarsa" if st == "EXPIRED" else "BATAL: pullback terlalu dalam, impuls gagal")
            return out
        if not ok:
            out.update(state="NO_CONFIRM", direction="WAIT",
                       label="gerakan besar terdeteksi, tetapi belum ada konfirmasi berita")
            return out
        label = {"WAIT_PULLBACK": "MENUNGGU PULLBACK ke zona entry", "IN_ZONE": "DI ZONA ENTRY",
                 "DEEP": "pullback dalam: jangan tambah entry"}[st]
        out.update(state=st, direction=d if st in ("WAIT_PULLBACK", "IN_ZONE") else "WAIT",
                   plan_direction=d, label=label)
        return out
    except Exception as e:  # noqa: BLE001
        out.update(state="ERROR", label=f"galat: {type(e).__name__}: {str(e)[:80]}")
        return out


def cross_of(res):
    """Ringkasan impuls instrumen lain untuk konfirmasi lintas aset (ambang lebih rendah)."""
    imp = (res or {}).get("impulse")
    if not imp or res.get("state") in ("EXPIRED", "CANCELLED", "STALE", "ERROR"):
        return None
    if imp["ratio"] < cfg()["atr"] * cfg()["cross"]:
        return None
    return {"symbol": res["symbol"], "direction": imp["direction"], "ratio": imp["ratio"]}


# ------------------------------------------------------------------ judul berita pasar umum
MARKET_Q = {
    "XAUUSD": ["gold price today", "gold dollar Fed yields"],
    "NASDAQ": ["Nasdaq stock futures today", "Wall Street stocks Fed"],
}
MAX_AGE_H = 6
HL_TTL, HL_RETRY = 300, 60
_hl = {}

UP = {  # sentimen naik untuk saham teknologi (risk-on)
    "relief rally": 1.0, "rebound": 0.6, "rebounds": 0.6, "futures jump": 0.9, "futures surge": 0.9, "futures rise": 0.7,
    "stocks rally": 0.9, "stocks surge": 0.9, "stocks gain": 0.6, "stocks rise": 0.7, "nasdaq rises": 0.8,
    "nasdaq jumps": 0.9, "nasdaq climbs": 0.8, "nasdaq surges": 0.9, "tech rally": 0.8, "wall street rallies": 0.9,
    "wall street rises": 0.7, "hike bets fade": 0.8, "hike bets retreat": 0.8, "rate cut": 0.6, "dovish": 0.7,
    "yields fall": 0.6, "yields drop": 0.6, "softer inflation": 0.6, "cooler than expected": 0.8,
}
DOWN = {
    "selloff": 0.8, "sell-off": 0.8, "rout": 0.9, "plunge": 0.9, "plunges": 0.9, "tumble": 0.8, "tumbles": 0.8,
    "stocks fall": 0.8, "stocks slide": 0.8, "nasdaq falls": 0.9, "nasdaq slumps": 0.9, "nasdaq drops": 0.9,
    "tech selloff": 1.0, "hawkish": 0.7, "rate hike": 0.6, "yields surge": 0.7, "yields jump": 0.7, "crash": 0.9,
    "wall street falls": 0.9, "futures fall": 0.8, "futures slide": 0.8, "futures drop": 0.8,
    "hotter than expected": 0.8, "margin call": 0.6,
}
_PAST = re.compile(r"\b(after|following|from|despite|since|ahead of)\b", re.I)


def main_clause(title):
    """Judul sering menyebut kejadian lampau ('naik setelah aksi jual Jumat'). Hanya klausa utama yang dinilai."""
    return _PAST.split(title, maxsplit=1)[0]


def market_sentiment(symbol, items):
    """Skor -1..+1 untuk instrumen dari judul (kamus frasa sederhana, tanpa penanganan negasi)."""
    if symbol == "XAUUSD":
        bull, bear = news_context.BULL_GOLD, news_context.BEAR_GOLD
    else:
        bull, bear = UP, DOWN
    scores = []
    for r in items:
        low = main_clause(r["title"]).lower()
        b = sum(w for p, w in bull.items() if p in low)
        s = sum(w for p, w in bear.items() if p in low)
        if b or s:
            scores.append(max(-1.0, min(1.0, b - s)))
    score = round(sum(scores) / len(scores), 2) if scores else 0.0
    return {"score": score, "n_titles": len(items), "n_hits": len(scores), "usable": len(scores) >= 3}


def collect(symbol, now_ts=None, fetch=None):
    """Judul 6 jam terakhir untuk instrumen. Cache 5 menit, tidak pernah melempar error."""
    t = time.time() if now_ts is None else now_ts

    def one(q):
        c = _hl.get(q)
        if c and t - c[0] < HL_TTL:
            return c[1], c[2]
        try:
            rows = news_context.parse_rss((fetch or news_context._http_text)(news_context._rss_url(q)))
            _hl[q] = (t, rows, None)
            return rows, None
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {str(e)[:90]}"
            old = c[1] if c else []
            _hl[q] = (t - HL_TTL + HL_RETRY, old, err)
            return old, err

    with ThreadPoolExecutor(max_workers=2) as ex:
        res = list(ex.map(one, MARKET_Q[symbol]))
    seen, items, errs = set(), [], []
    for rows, err in res:
        if err:
            errs.append(err)
        for r in rows:
            k = re.sub(r"\W+", " ", r["title"].lower()).strip()
            if k in seen or (r["ts"] is not None and t - r["ts"] > MAX_AGE_H * 3600):
                continue
            seen.add(k)
            items.append(r)
    items.sort(key=lambda r: r["ts"] or 0, reverse=True)
    return {"items": items[:10], "errors": errs}


def reset():
    _hl.clear()
