"""Analisis dampak makro lintas instrumen untuk TAB NEWS saja.

Ini mesin aturan transparan, BUKAN model AI/LLM dan bukan probabilitas profit.
NASDAQ diperlakukan WAIT untuk NFP/FOMC karena dampaknya dapat bercampur.
"""
from __future__ import annotations


def market_impact(event_type, surprise, trends=None):
    """Gabungkan kejutan aktual dengan tren H1. Tanpa Actual/konfirmasi -> WAIT."""
    trends = trends or {}
    stage = (surprise or {}).get("stage")
    bias_gold = (surprise or {}).get("bias")
    size = (surprise or {}).get("size")
    actual_ready = stage == "actual" and bias_gold in ("BUY", "SELL")

    # Untuk kejutan inflasi dan suku bunga, kejutan panas cenderung menekan
    # aset berdurasi panjang (NASDAQ) dan emas melalui USD/yield. NFP ambigu.
    if actual_ready and event_type in {"CPI", "PPI", "PCE", "FOMC"}:
        bias_nasdaq = bias_gold
        nasdaq_note = "Kejutan inflasi/suku bunga; bias makro searah tekanan yield dan USD."
    elif actual_ready and event_type == "NFP":
        bias_nasdaq = "MIXED"
        nasdaq_note = "NFP dapat menguatkan prospek pertumbuhan sekaligus menaikkan yield; perlu konfirmasi harga."
    else:
        bias_nasdaq = None
        nasdaq_note = "Belum ada kejutan Actual yang dapat dinilai."

    def item(symbol, macro, note):
        trend = trends.get(symbol)
        direction = "WAIT"
        reason = note
        if macro in ("BUY", "SELL") and trend in ("BUY", "SELL"):
            if macro == trend:
                direction = macro
                reason += f" Tren H1 {trend} mengonfirmasi bias makro."
            else:
                reason += f" Tren H1 {trend} berlawanan dengan bias makro {macro}; tunggu."
        elif macro == "MIXED":
            reason += " Tidak ada arah tunggal yang layak diterbitkan."
        elif macro in ("BUY", "SELL"):
            reason += " Menunggu konfirmasi tren H1."
        else:
            reason += " Isi Actual setelah rilis untuk menghitung kejutan."
        return {"symbol": symbol, "macro_bias": macro or "WAIT", "trend_h1": trend or "UNKNOWN",
                "direction": direction, "strength": size or "belum tersedia", "reason": reason}

    gold_note = ((surprise or {}).get("text") or "Belum ada kejutan Actual yang dapat dinilai.")
    return {
        "mode": "rule_based",
        "label": "Analisis dampak makro lintas instrumen",
        "nasdaq": item("NASDAQ", bias_nasdaq, nasdaq_note),
        "xauusd": item("XAUUSD", bias_gold if actual_ready else None, gold_note),
        "disclaimer": "Bias makro bukan sinyal entry. BUY/SELL hanya muncul jika Actual tersedia dan tren H1 searah; selain itu WAIT.",
    }
