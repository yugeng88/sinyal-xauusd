"""Uji deterministik mesin konsensus strategi; bukan backtest profitabilitas."""
import os
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import signals


class TestStrategyEngine(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(41)
        n = 240
        times = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
        close = 4000 + np.cumsum(rng.normal(0.08, 0.7, n))
        open_ = np.r_[close[0], close[:-1]]
        high = np.maximum(open_, close) + rng.uniform(0.1, 0.8, n)
        low = np.minimum(open_, close) - rng.uniform(0.1, 0.8, n)
        self.df = pd.DataFrame({"time": times, "open": open_, "high": high,
                                "low": low, "close": close, "volume": 1})

    def test_returns_three_strategy_votes(self):
        out = signals.strategy_arrays(self.df)
        self.assertEqual(len(out["direction"]), len(self.df))
        self.assertEqual(set(out["strategies"]),
                         {"liquidity_sweep", "trend_pullback", "momentum_breakout"})
        self.assertTrue(set(out["direction"]).issubset({"BUY", "SELL", "WAIT"}))
        self.assertTrue(set(out["confidence"]).issubset({0, 70, 90}))

    def test_consensus_requires_two_votes(self):
        out = signals.strategy_arrays(self.df)
        for i, direction in enumerate(out["direction"]):
            votes = [v[i] for v in out["strategies"].values() if v[i] == direction]
            if direction == "WAIT":
                self.assertLess(max(sum(v[i] == side for v in out["strategies"].values())
                                    for side in ("BUY", "SELL")), 2)
            else:
                self.assertGreaterEqual(len(votes), 2)


    def test_nasdaq_keeps_legacy_engine(self):
        sig = signals.analyze(self.df, symbol="NASDAQ", tf="M5",
                              now=self.df.iloc[-1]["time"] + pd.Timedelta(minutes=5),
                              closed_only=False)
        self.assertIsNone(sig["strategy_engine"])
        self.assertEqual(sig["direction"], sig["legacy_direction"])

    def test_no_lookahead(self):
        full = signals.strategy_arrays(self.df)
        cut = signals.strategy_arrays(self.df.iloc[:180])
        for key in ("direction", "confidence", "votes"):
            self.assertEqual(full[key][179], cut[key][-1])
        for key in full["strategies"]:
            self.assertEqual(full["strategies"][key][179], cut["strategies"][key][-1])


if __name__ == "__main__":
    unittest.main()
