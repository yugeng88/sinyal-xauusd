"""Analisis dampak makro lintas instrumen untuk TAB NEWS saja.

Ini mesin aturan transparan, BUKAN model AI/LLM dan bukan probabilitas profit.
NASDAQ diperlakukan WAIT untuk NFP/FOMC karena dampaknya dapat bercampur.
"""
from __future__ import annotations

import os


def h1_gate_types():
    """Jenis berita yang MASIH wajib searah tren H1 sebelum BUY/SELL terbit (env NEWS_H1_GATE, mis. "CPI,PCE").
    Bawaan (v19.39): kosong. Arah NEWS ditentukan oleh data (Actual vs Forecast); tren H1 hanya konteks."""
    return {x.strip().upper() for x in os.getenv("NEWS_H1_GATE", "").split(",") if x.strip()}


def market_impact(event_type, surprise, trends=None):
    """Gabungkan kejutan aktual dengan tren H1 (konteks). Tanpa Actual -> WAIT. Jenis di NEWS_H1_GATE wajib searah H1."""
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
    elif actual_ready and event_type in {"NFP", "RETAIL"}:
        bias_nasdaq = "MIXED"
        nasdaq_note = "Data pekerjaan/konsumsi kuat dapat menguatkan prospek pertumbuhan sekaligus menaikkan yield; perlu konfirmasi harga."
    else:
        bias_nasdaq = None
        nasdaq_note = "Belum ada kejutan Actual yang dapat dinilai."

    gate = h1_gate_types()
    gated = str(event_type).upper() in gate

    def item(symbol, macro, note):
        trend = trends.get(symbol)
        direction = "WAIT"
        reason = note
        h1_status = "belum ada" if trend not in ("BUY", "SELL") else ("searah" if trend == macro else "berlawanan")
        if macro in ("BUY", "SELL"):
            if trend in ("BUY", "SELL") and macro == trend:
                direction = macro
                reason += f" Tren H1 {trend} mengonfirmasi bias makro."
            elif gated:                                   # perilaku lama, hanya untuk jenis berita di NEWS_H1_GATE
                direction = "WAIT"
                reason += (f" Tren H1 {trend} berlawanan dengan bias makro {macro}; tunggu." if trend in ("BUY", "SELL")
                           else " Menunggu konfirmasi tren H1.")
            else:                                         # bawaan: arah dari data, tren H1 hanya konteks
                direction = macro
                if trend in ("BUY", "SELL"):
                    reason += (f" Tren H1 {trend} berlawanan dengan bias makro {macro}: ini entri kontra-tren, "
                               "risiko lebih tinggi (rebound bisa gagal); pertimbangkan ukuran lebih kecil.")
                else:
                    reason += " Tren H1 belum termuat; arah murni dari data rilis."
        elif macro == "MIXED":
            reason += " Tidak ada arah tunggal yang layak diterbitkan."
        else:
            reason += " Isi Actual setelah rilis untuk menghitung kejutan."
        return {"symbol": symbol, "macro_bias": macro or "WAIT", "trend_h1": trend or "UNKNOWN",
                "h1_status": h1_status, "counter_trend": direction in ("BUY", "SELL") and h1_status == "berlawanan",
                "direction": direction, "strength": size or "belum tersedia", "reason": reason}

    gold_note = ((surprise or {}).get("text") or "Belum ada kejutan Actual yang dapat dinilai.")
    return {
        "mode": "rule_based",
        "label": "Analisis dampak makro lintas instrumen",
        "nasdaq": item("NASDAQ", bias_nasdaq, nasdaq_note),
        "xauusd": item("XAUUSD", bias_gold if actual_ready else None, gold_note),
        "disclaimer": "Bias makro bukan sinyal entry. BUY/SELL muncul jika Actual tersedia (arah dari data rilis); tren H1 hanya konteks dan menandai entri kontra-tren sebagai risiko lebih tinggi. Selain itu WAIT.",
    }
