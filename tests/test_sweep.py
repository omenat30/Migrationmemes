import unittest

from radar import deepwallet, sweep
import copy as _copy

from radar.config import DEFAULTS as _DEF

DEFAULTS = _copy.deepcopy(_DEF)
DEFAULTS["copy"]["max_idle_days"] = 0  # los datos de prueba son de fechas fijas


def mk(mult, hold=3600, cost=1.0, ts=1_790_000_000):
    return {"mint": "m", "closed": True, "cost": cost, "proceeds": cost * mult, "entry_ts": ts, "hold": hold, "mult": mult}


def metrics_for(positions, **kw):
    m = deepwallet.metrics("W" * 40, positions, len(positions) * 2, 0, 30.0, DEFAULTS)
    m["coverage"] = {"reached_start": True}
    m.update(kw)
    return m


class DeepTest(unittest.TestCase):
    def test_positions_good_wallet_passes(self):
        pos = [mk(0.9, ts=1_790_000_000 + i * 900) for i in range(30)] + [mk(2.0, ts=1_790_400_000 + i * 900) for i in range(6)] + [mk(14.0, ts=1_790_100_000), mk(13.0, ts=1_790_200_000), mk(3.0, ts=1_790_300_000)]
        ok, why = deepwallet.passes(metrics_for(pos), DEFAULTS)
        self.assertTrue(ok, why)

    def test_luck_is_rejected(self):
        pos = [mk(0.8, ts=1_790_000_000 + i * 900) for i in range(30)] + [mk(20.0, ts=1_790_100_000)]
        ok, why = deepwallet.passes(metrics_for(pos), DEFAULTS)
        self.assertFalse(ok)
        self.assertTrue(any("2 mejores" in w for w in why))

    def test_dumper_rejected(self):
        pos = [mk(1.2, hold=40, ts=1_790_000_000 + i * 900) for i in range(30)] + [mk(15.0, hold=40, ts=1_790_100_000)]
        ok, why = deepwallet.passes(metrics_for(pos), DEFAULTS)
        self.assertFalse(ok)


class SweepTest(unittest.TestCase):
    def good(self):
        pos = [mk(0.9, ts=1_790_000_000 + i * 900) for i in range(30)] + [mk(2.0, ts=1_790_400_000 + i * 900) for i in range(6)] + [mk(14.0, ts=1_790_100_000), mk(13.0, ts=1_790_200_000), mk(3.0, ts=1_790_300_000)]
        return {"metrics": metrics_for(pos), "positions": pos}

    def test_add_then_keep_joined_ts(self):
        r = self.good()
        docs, meta = sweep.build_docs([r], {}, DEFAULTS, now=1000)
        w = r["metrics"]["wallet"]
        self.assertEqual(docs[w]["status"], "active")
        self.assertEqual(docs[w]["joined_ts"], 1000)
        self.assertEqual(meta["changes"][0]["type"], "add")
        docs2, meta2 = sweep.build_docs([r], {w: {"joined_ts": 1000, "status": "active"}}, DEFAULTS, now=2000)
        self.assertEqual(docs2[w]["joined_ts"], 1000)
        self.assertEqual(meta2["changes"], [])

    def test_drop_is_logged_with_reason_and_kept(self):
        r = self.good()
        w = r["metrics"]["wallet"]
        bad = [mk(0.5, hold=30, ts=1_790_000_000 + i * 900) for i in range(30)] + [mk(12.0, hold=30, ts=1_790_100_000)]
        r2 = {"metrics": metrics_for(bad), "positions": bad}
        docs, meta = sweep.build_docs([r2], {w: {"joined_ts": 1000, "status": "active"}}, DEFAULTS, now=3000)
        self.assertEqual(docs[w]["status"], "dropped")
        self.assertEqual(docs[w]["joined_ts"], 1000)
        self.assertEqual(meta["changes"][0]["type"], "drop")
        self.assertTrue(meta["changes"][0]["why"])


if __name__ == "__main__":
    unittest.main()


class DustTest(unittest.TestCase):
    def test_dust_in_route_is_ignored_but_real_second_token_is_not(self):
        from radar import wallet_history as wh
        W = "Wxxxx"
        tx = {"tokenTransfers": [{"mint": "A", "tokenAmount": 1000, "toUserAccount": W, "fromUserAccount": "p"},
                                 {"mint": "B", "tokenAmount": 1e-7, "toUserAccount": "p", "fromUserAccount": W}],
              "accountData": [{"account": W, "nativeBalanceChange": -2_000_000_000}]}
        self.assertEqual(wh.derive_trade(W, tx), ("buy", "A", 2.0, 1000.0))
        tx["tokenTransfers"][1]["tokenAmount"] = 900
        self.assertIsNone(wh.derive_trade(W, tx))


class GmgnDiscoverTest(unittest.TestCase):
    def test_pipeline_filters_by_pnl_and_batches(self):
        from radar import discover

        class FakeG:
            def __init__(self):
                self.stat_calls = []

            def trending(self, iv, limit, ob):
                return [{"mint": "AAApump"}, {"mint": "BBB"}]  # el segundo no es de pump.fun

            def top_traders(self, mint, limit, order_by):
                return [{"wallet": "W1", "profit": 900.0}, {"wallet": "W2", "profit": 50.0}, {"wallet": "W3", "profit": 400.0}]

            def wallet_stats(self, ws, period):
                self.stat_calls.append(list(ws))
                allst = {"W1": {"pnl": 0.5, "winrate": 0.6, "buys": 30, "realized_profit": 900.0},
                         "W3": {"pnl": 0.1, "winrate": 0.6, "buys": 30, "realized_profit": 900.0}}
                return {w: allst[w] for w in ws if w in allst}

        g = FakeG()
        out = discover.gmgn_candidates(g, intervals=("24h",), order_by=("volume",), log=lambda m: None)
        self.assertEqual([w for w, _ in out], ["W1"])
        self.assertEqual(g.stat_calls, [["W1"], ["W3"]])  # de una en una; W2 no llega a la ganancia mínima por token


class GmgnWalletTest(unittest.TestCase):
    def test_positions_from_activity_and_metrics(self):
        from radar import gmgnwallet
        t0 = 1_790_000_000
        rows = []
        for i in range(25):  # 25 operaciones x2 y x0,5 alternas, tenencia de 20 min
            tok = {"address": "M%d" % i}
            rows.append({"event_type": "buy", "token": tok, "cost_usd": 100.0, "token_amount": 1000, "timestamp": t0 + i * 3600})
            rows.append({"event_type": "sell", "token": tok, "cost_usd": 200.0 if i % 2 == 0 else 50.0, "token_amount": 1000, "timestamp": t0 + i * 3600 + 1200})
        rows.append({"event_type": "transferIn", "token": {"address": "X"}, "cost_usd": 5, "token_amount": 5, "timestamp": t0})
        pos, n, ign = gmgnwallet.positions_from_activity(rows, sol_usd=100.0)
        self.assertEqual((len(pos), n, ign), (25, 50, 1))
        self.assertAlmostEqual(pos[0]["cost"], 1.0)
        m = deepwallet.metrics("W" * 40, pos, n, ign, 30.0, DEFAULTS)
        self.assertEqual(m["n_closed"], 25)
        self.assertAlmostEqual(m["median_hold_s"], 1200.0)
        self.assertAlmostEqual(m["roi"], (13 * 2.0 + 12 * 0.5) / 25 - 1)

    def test_open_position_is_not_counted(self):
        from radar import gmgnwallet
        rows = [{"event_type": "buy", "token": {"address": "A"}, "cost_usd": 100, "token_amount": 10, "timestamp": 1},
                {"event_type": "sell", "token": {"address": "A"}, "cost_usd": 500, "token_amount": 5, "timestamp": 2}]
        pos, _, _ = gmgnwallet.positions_from_activity(rows, 100.0)
        self.assertFalse(pos[0]["closed"])
        self.assertIsNone(pos[0]["mult"])


class IdleTest(unittest.TestCase):
    def test_wallet_idle_for_weeks_is_rejected_even_with_open_buys_counted(self):
        import time as _t
        old = _t.time() - 30 * 86400
        pos = [mk(0.9, ts=int(old) + i * 900) for i in range(30)] + [mk(2.0, ts=int(old) + 40000 + i * 900) for i in range(6)] + [mk(14.0, ts=int(old) + 90000), mk(13.0, ts=int(old) + 100000), mk(3.0, ts=int(old) + 110000)]
        cfg = _copy.deepcopy(_DEF)
        m = metrics_for(pos)
        ok, why = deepwallet.passes(m, cfg)
        self.assertFalse(ok)
        self.assertTrue(any("sin operar" in w for w in why))
        # una compra abierta reciente cuenta como actividad
        pos.append({"mint": "open", "closed": False, "cost": 1.0, "proceeds": 0.0, "entry_ts": int(_t.time()) - 3 * 86400, "exit_ts": None, "hold": None, "mult": None})
        m2 = metrics_for(pos)
        self.assertLess((_t.time() - m2["last_ts"]) / 86400, 4)
