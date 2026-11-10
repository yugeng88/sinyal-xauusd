"""Uji ujung-ke-ujung halaman NEWS memakai harga SINTETIS (acak terkendali), tanpa internet.
Hanya memeriksa bahwa alur data -> sinyal -> JSON bekerja. Bukan data pasar nyata."""
import os
import random
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("NEWS_FEED", "off")
import app as A  # noqa: E402
import data  # noqa: E402
import news  # noqa: E402


def fake_range(a, b, seed, drift=0.0):
    rnd = random.Random(seed)
    times = pd.date_range(pd.Timestamp(a).floor("5min"), pd.Timestamp(b), freq="5min", tz="UTC")
    p, rows = 4000.0, []
    for t in times:
        o = p
        p = o + rnd.uniform(-1.5, 1.5) + drift
        rows.append({"time": t, "open": o, "high": max(o, p) + 0.6, "low": min(o, p) - 0.6, "close": p, "volume": 1})
    return pd.DataFrame(rows)


class Base(unittest.TestCase):
    def setUp(self):
        news._win.clear()
        news._calls.clear()
        self._orig = (A.ensure_fresh, data.get_range, news.feed_values)
        A.ensure_fresh = lambda *a, **k: None
        counter = {"i": 0}

        def gr(key, tf, a, b):
            counter["i"] += 1
            return fake_range(a, b, seed=counter["i"], drift=0.05)
        data.get_range = gr
        A.states[("XAUUSD", "H1")]["signal"] = {"direction": "BUY", "score": 3, "market_closed": False}
        A.states[("XAUUSD", "M5")]["signal"] = {"source": "uji-sintetis"}
        A.states[("XAUUSD", "M5")]["error"] = None

    def tearDown(self):
        A.ensure_fresh, data.get_range, news.feed_values = self._orig

    def load_all(self, now, ev_id=None, manual=None):
        v = None
        for _ in range(4):
            v = A.news_view(ev_id, now=now, manual=manual)
            pr = v["focus"]["progress"]
            if pr["done"] >= pr["total"]:
                break
        return v["focus"]


class TestPra(Base):
    def test_cpi_pra_beri_arah(self):
        now = pd.Timestamp("2026-11-08T12:00:00Z")
        A.raw[("XAUUSD", "M5")] = fake_range(now - pd.Timedelta(hours=6), now, seed=99)
        f = self.load_all(now)
        self.assertEqual(f["id"], "CPI@2026-11-10")
        self.assertEqual(f["status"], "PRA")
        self.assertEqual(f["progress"]["done"], f["progress"]["total"])
        s = f["signal"]
        self.assertIn(s["direction"], ("BUY", "SELL"))      # inti perbaikan: tidak lagi TUNGGU
        self.assertTrue(s["factors"])
        self.assertIsNotNone(s["levels"])

    def test_forecast_dari_feed_masuk_input(self):
        now = pd.Timestamp("2026-11-08T12:00:00Z")
        A.raw[("XAUUSD", "M5")] = fake_range(now - pd.Timedelta(hours=6), now, seed=99)
        news.feed_values = lambda ev, rows=None: {"title": "Core CPI m/m", "forecast": "0.2%", "previous": "0.3%", "actual": None}
        f = self.load_all(now)
        self.assertEqual(f["inputs"]["forecast"], "0.2%")
        self.assertEqual(f["inputs"]["metric"], "Core CPI m/m")
        self.assertEqual(f["surprise"]["stage"], "forecast")
        self.assertTrue(any(x["key"] == "fcst" for x in f["signal"]["factors"]))

    def test_manual_menimpa_feed(self):
        now = pd.Timestamp("2026-11-08T12:00:00Z")
        A.raw[("XAUUSD", "M5")] = fake_range(now - pd.Timedelta(hours=6), now, seed=99)
        news.feed_values = lambda ev, rows=None: {"title": "Core CPI m/m", "forecast": "0.2%", "previous": "0.3%", "actual": None}
        f = self.load_all(now, manual={"forecast": "0.4%", "previous": "", "actual": ""})
        self.assertEqual(f["inputs"]["forecast"], "0.4%")
        self.assertEqual(f["inputs"]["previous"], "0.3%")


class TestPasca(Base):
    def test_cpi_panas_harga_turun_sell(self):
        ev0 = news.event_utc("CPI", pd.Timestamp("2026-11-10").date())
        now = pd.Timestamp(ev0) + pd.Timedelta(minutes=20)
        # candle M5 terbaru: harga turun tajam setelah rilis
        idx = pd.date_range(now - pd.Timedelta(hours=3), now, freq="5min", tz="UTC")
        rows, p = [], 4000.0
        for t in idx:
            o = p
            p = o - 2.0 if t >= pd.Timestamp(ev0) else o + 0.02
            rows.append({"time": t, "open": o, "high": max(o, p) + 0.5, "low": min(o, p) - 0.5, "close": p, "volume": 1})
        A.raw[("XAUUSD", "M5")] = pd.DataFrame(rows)
        f = self.load_all(now, ev_id="CPI@2026-11-10", manual={"forecast": "0.2%", "previous": "0.3%", "actual": "0.3%"})
        self.assertIn(f["status"], ("PASCA",))
        s = f["signal"]
        self.assertEqual(s["direction"], "SELL")
        self.assertEqual(f["surprise"]["bias"], "SELL")
        self.assertGreater(s["levels"]["stop_loss"], s["levels"]["entry"])


class TestRoute(Base):
    def test_api_news_parameter(self):
        now = pd.Timestamp.now(tz="UTC")
        A.raw[("XAUUSD", "M5")] = fake_range(now - pd.Timedelta(hours=6), now, seed=7)
        c = A.app.test_client()
        r = c.get("/api/news?f=0.2%25&p=0.3%25&a=")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        j = r.get_json()
        self.assertEqual(j["focus"]["inputs"]["forecast"], "0.2%")
        self.assertIn("signal", j["focus"])

    def test_halaman_utama(self):
        c = A.app.test_client()
        r = c.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("numcard", r.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
