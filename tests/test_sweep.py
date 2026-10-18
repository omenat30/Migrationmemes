import unittest

from radar import deepwallet, sweep
from radar.config import DEFAULTS


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
