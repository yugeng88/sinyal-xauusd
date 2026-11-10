"""Uji logika berita. Jalankan: python -m unittest discover -s tests -v

CATATAN: baris riwayat di bawah adalah DATA UJI BUATAN (sintetis) untuk memeriksa logika kode.
Bukan data pasar nyata dan bukan hasil backtest.
"""
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import news  # noqa: E402


def row(date, r5, r15, r60, up60, dn60):
    return {"t0": date + "T13:30:00+00:00", "date": date, "p0": 4000.0, "r5": r5, "r15": r15, "r30": r15,
            "r60": r60, "up60": up60, "dn60": dn60, "pre_hi": 4010.0, "pre_lo": 3990.0, "pre_drift": 1.0}


# 4 kejadian: 3 naik, 1 turun (mirip keadaan di layar: riwayat baru 4 dari 6)
ROWS4 = [row("2026-09-11", 3, 5, 9, 15, 6), row("2026-08-12", -2, -4, -7, 5, 14),
         row("2026-07-14", 4, 8, 12, 18, 5), row("2026-06-10", 1, 3, 6, 11, 4)]
# 6 kejadian campuran: 4 naik, 2 turun -> uji statistik lama TIDAK lolos (perlu 6 dari 6)
ROWS6 = ROWS4 + [row("2026-05-12", -3, -6, -10, 4, 16), row("2026-10-14", 2, 4, 7, 12, 5)]


class TestParse(unittest.TestCase):
    def test_angka(self):
        self.assertEqual(news.parse_num("0.3%"), 0.3)
        self.assertEqual(news.parse_num("145K"), 145000.0)
        self.assertEqual(news.parse_num("0,3"), 0.3)
        self.assertEqual(news.parse_num("1,234K"), 1234000.0)
        self.assertIsNone(news.parse_num("abc"))
        self.assertIsNone(news.parse_num(""))


class TestSurprise(unittest.TestCase):
    def test_di_atas_perkiraan_sell(self):
        s = news.surprise("CPI", "0.2%", "0.3%", "0.3%")      # kasus di video: core 0.3 vs forecast 0.2
        self.assertEqual(s["stage"], "actual")
        self.assertEqual(s["bias"], "SELL")
        self.assertLess(s["v"], 0)

    def test_di_bawah_perkiraan_buy(self):
        s = news.surprise("CPI", "0.3%", "0.3%", "0.1%")
        self.assertEqual(s["bias"], "BUY")
        self.assertGreater(s["v"], 0)

    def test_pembulatan_desimal(self):
        """0.3 - 0.2 = 0.0999999... harus dibaca tepat 1 unit (0,1 poin persen), bukan 'kecil'."""
        s = news.surprise("CPI", "0.2%", "0.3%", "0.3%")
        self.assertEqual(s["size"], "sedang")
        self.assertAlmostEqual(s["v"], -0.5, places=3)

    def test_sesuai(self):
        s = news.surprise("CPI", "0.3%", "0.3%", "0.3%")
        self.assertEqual(s["v"], 0)
        self.assertIsNone(s["bias"])

    def test_nfp_kilo(self):
        s = news.surprise("NFP", "145K", "164K", "250K")
        self.assertEqual(s["bias"], "SELL")
        self.assertEqual(s["size"], "besar")

    def test_forecast_vs_previous_bobot_kecil(self):
        a = news.surprise("CPI", "0.2%", "0.3%", None)
        self.assertEqual(a["stage"], "forecast")
        self.assertEqual(a["bias"], "BUY")
        b = news.surprise("CPI", "0.2%", "0.3%", "0.1%")
        self.assertLess(abs(a["v"]), abs(b["v"]))

    def test_fomc_pers_tanpa_angka(self):
        self.assertIsNone(news.surprise("FOMC_PC", "1", "2", "3"))


class TestPreSignal(unittest.TestCase):
    def test_keadaan_layar_tetap_beri_arah(self):
        """Layar: tren H1 BUY skor +3, riwayat baru 4 kejadian. Dulu TUNGGU, sekarang harus ada arah."""
        summ = news.summarize([dict(r) for r in ROWS4])
        sig = news.pre_signal(summ, "BUY", 4069.14, 4075.0, 4060.0, h1_score=3)
        self.assertEqual(sig["direction"], "BUY")
        self.assertIn(sig["strength"], ("LEMAH", "SEDANG"))
        self.assertTrue(any("lemah" in r.lower() for r in sig["reasons"]))   # jujur soal sampel kecil
        self.assertIsNotNone(sig["levels"])
        lv = sig["levels"]
        self.assertLess(lv["stop_loss"], lv["entry"])
        self.assertGreater(lv["tp1"], lv["entry"])

    def test_aturan_lama_memang_macet(self):
        """Bukti akar masalah: 4 naik dari 6 tidak lolos uji statistik lama (interval 95% mencakup 50%)."""
        summ = news.summarize([dict(r) for r in ROWS6])
        self.assertTrue(summ["enough"])
        self.assertFalse(summ["up60"]["lo"] > 0.5)

    def test_sell_levels_valid(self):
        summ = news.summarize([dict(r) for r in ROWS6])
        sig = news.pre_signal(summ, "SELL", 4000.0, None, None, h1_score=-4)
        self.assertEqual(sig["direction"], "SELL")
        lv = sig["levels"]
        self.assertGreater(lv["stop_loss"], lv["entry"])
        self.assertLess(lv["tp1"], lv["entry"])

    def test_tanpa_data_tetap_wait(self):
        sig = news.pre_signal({"n": 0, "enough": False}, None, None)
        self.assertEqual(sig["direction"], "WAIT")

    def test_hanya_tren(self):
        sig = news.pre_signal({"n": 0, "enough": False}, "BUY", 4000.0, h1_score=4)
        self.assertEqual(sig["direction"], "BUY")
        self.assertIsNone(sig["levels"])

    def test_forecast_dingin_mendukung_buy(self):
        summ = news.summarize([dict(r) for r in ROWS4])
        sur = news.surprise("CPI", "0.2%", "0.3%", None)
        a = news.pre_signal(summ, "BUY", 4000.0, h1_score=1, sur=sur)
        b = news.pre_signal(summ, "BUY", 4000.0, h1_score=1)
        self.assertGreaterEqual(a["score"], b["score"])


class TestPenyesuaian(unittest.TestCase):
    def test_forecast_searah_menaikkan_berlawanan_menurunkan(self):
        summ = news.summarize([dict(r) for r in ROWS4])
        base = news.pre_signal(summ, "BUY", 4000.0, h1_score=3)["confidence"]
        dingin = news.pre_signal(summ, "BUY", 4000.0, h1_score=3, sur=news.surprise("CPI", "0.2%", "0.3%", None))["confidence"]
        panas = news.pre_signal(summ, "BUY", 4000.0, h1_score=3, sur=news.surprise("CPI", "0.4%", "0.3%", None))["confidence"]
        self.assertGreater(dingin, base)
        self.assertLess(panas, base)


class TestPostSignal(unittest.TestCase):
    def setUp(self):
        self.summ = news.summarize([dict(r) for r in ROWS6])

    def test_menit_pertama_tunggu(self):
        sur = news.surprise("CPI", "0.2%", "0.3%", "0.3%")
        sig = news.post_signal(self.summ, 4000.0, 3990.0, 2, sur)
        self.assertEqual(sig["direction"], "WAIT")
        self.assertEqual(sig["kind"], "RILIS")
        self.assertEqual(sig["lean"], "SELL")

    def test_angka_panas_dan_harga_turun_sell(self):
        sur = news.surprise("CPI", "0.2%", "0.3%", "0.3%")
        sig = news.post_signal(self.summ, 4000.0, 3985.0, 15, sur)
        self.assertEqual(sig["direction"], "SELL")
        lv = sig["levels"]
        self.assertGreater(lv["stop_loss"], lv["entry"])
        self.assertLess(lv["tp1"], lv["entry"])

    def test_harga_naik_angka_dingin_buy(self):
        sur = news.surprise("CPI", "0.3%", "0.3%", "0.1%")
        sig = news.post_signal(self.summ, 4000.0, 4015.0, 20, sur)
        self.assertEqual(sig["direction"], "BUY")
        self.assertLess(sig["levels"]["stop_loss"], sig["levels"]["entry"])

    def test_konflik_ikut_harga(self):
        sur = news.surprise("CPI", "0.2%", "0.3%", "0.4%")     # panas -> condong SELL
        sig = news.post_signal(self.summ, 4000.0, 4030.0, 20, sur)  # tetapi harga naik kuat
        self.assertEqual(sig["direction"], "BUY")
        self.assertTrue(any("bertentangan" in r for r in sig["reasons"]))
        lv = sig["levels"]                                       # SL harus di sisi yang benar
        self.assertLess(lv["stop_loss"], lv["entry"])

    def test_harga_datar_wait(self):
        sig = news.post_signal(self.summ, 4000.0, 4000.3, 20, None)
        self.assertEqual(sig["direction"], "WAIT")

    def test_sl_sisi_benar_saat_berlawanan(self):
        sur = news.surprise("CPI", "0.2%", "0.3%", "0.5%")     # sangat panas -> SELL
        sig = news.post_signal(self.summ, 4000.0, 4004.0, 20, sur)   # harga naik sedikit
        if sig["direction"] == "SELL":
            self.assertGreater(sig["levels"]["stop_loss"], sig["levels"]["entry"])


class TestFeed(unittest.TestCase):
    ROWS = [
        {"title": "CPI m/m", "country": "USD", "date": "2026-11-10T08:30:00-05:00", "impact": "High", "forecast": "0.3%", "previous": "0.2%", "actual": None},
        {"title": "Core CPI m/m", "country": "USD", "date": "2026-11-10T08:30:00-05:00", "impact": "High", "forecast": "0.2%", "previous": "0.3%", "actual": ""},
        {"title": "Core CPI m/m", "country": "EUR", "date": "2026-11-10T08:30:00-05:00", "impact": "High", "forecast": "9.9%", "previous": "9.9%", "actual": None},
    ]

    def setUp(self):
        self._env = os.environ.pop("NEWS_FEED", None)      # modul lain mematikan feed lewat env; di sini diuji aktif
        evs = news.build_events(datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc))
        self.cpi = next(e for e in evs if e["id"] == "CPI@2026-11-10")

    def tearDown(self):
        if self._env is not None:
            os.environ["NEWS_FEED"] = self._env

    def test_pilih_core_usd(self):
        v = news.feed_values(self.cpi, self.ROWS)
        self.assertEqual(v["title"], "Core CPI m/m")
        self.assertEqual((v["forecast"], v["previous"], v["actual"]), ("0.2%", "0.3%", None))

    def test_tidak_cocok(self):
        self.assertIsNone(news.feed_values(self.cpi, [{"title": "Retail Sales m/m", "country": "USD", "date": "2026-11-10T08:30:00-05:00"}]))

    def test_feed_gagal_tidak_melempar(self):
        news._feed.update(at=0.0, rows=None, ok=False, err=None)
        def boom():
            raise RuntimeError("jaringan mati")
        self.assertIsNone(news._feed_rows(now_ts=1000.0, fetch=boom))
        self.assertFalse(news.feed_status()["ok"])

    def test_feed_cache(self):
        news._feed.update(at=0.0, rows=None, ok=False, err=None)
        calls = []
        def ok():
            calls.append(1)
            return self.ROWS
        news._feed_rows(now_ts=5000.0, fetch=ok)
        news._feed_rows(now_ts=5100.0, fetch=ok)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
