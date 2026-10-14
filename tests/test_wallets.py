import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from radar import wallets
from radar.config import load_config
from radar.store import Store

CFG = load_config("/nonexistent.json")


def summ(**k):
    base = {"bot": False, "sold": 8, "closed": 8, "pnl_sol": 3.0, "median_hold_s": 900, "quick_exit_ratio": 0.1}
    base.update(k)
    return base


class Classify(unittest.TestCase):
    def test_rules(self):
        self.assertEqual(wallets.classify(summ(), CFG), "CANDIDATA")
        self.assertEqual(wallets.classify(summ(bot=True), CFG), "BOT")
        self.assertEqual(wallets.classify(summ(quick_exit_ratio=0.7), CFG), "EXTRACTORA")
        self.assertEqual(wallets.classify(summ(closed=2, sold=2), CFG), "SIN HISTORIAL")
        self.assertEqual(wallets.classify(summ(pnl_sol=-1), CFG), "PIERDE")
        self.assertEqual(wallets.classify(summ(median_hold_s=60, quick_exit_ratio=0.2), CFG), "PIERDE")

    def test_profitable_but_flips_fast_is_extractor_not_candidate(self):
        self.assertEqual(wallets.classify(summ(pnl_sol=50, quick_exit_ratio=0.6), CFG), "EXTRACTORA")


def add(st, mint, ts, wallet, buy, price, sol=1.0):
    st.add_trades(mint, [{"sig": f"{mint}{ts}{wallet}{buy}", "ts": ts, "wallet": wallet, "is_buy": buy, "sol": sol,
                          "tokens": sol / price, "slot": ts}])


class Follower(unittest.TestCase):
    def test_follower_loses_when_wallet_sells_into_a_spike(self):
        """La wallet compra a 1.0, el precio sube a 2.0 en 20 s y ella vende a 2.0; el seguidor entra tarde a 2.0 y sale tras la caída."""
        st = Store(":memory:")
        add(st, "M", 100, "W", True, 1.0)
        for i, p in enumerate([1.2, 1.6, 2.0]):
            add(st, "M", 110 + i * 5, "x", True, p)
        add(st, "M", 130, "W", False, 2.0)          # ella vende al máximo
        for i, p in enumerate([1.5, 1.0, 0.7, 0.5]):  # y después cae
            add(st, "M", 140 + i * 10, "y", False, p)
        res, _ = wallets.follower_returns(st, {"EXTRACTORA": ["W"]})
        r30 = res["EXTRACTORA"][30]
        self.assertEqual(len(r30), 1)
        self.assertLess(r30[0], -0.3)            # el seguidor pierde aunque la wallet ganó +100 %

    def test_unresolved_positions_are_not_counted_as_results(self):
        st = Store(":memory:")
        add(st, "M", 100, "W", True, 1.0)
        add(st, "M", 200, "y", True, 3.0)
        res, unres = wallets.follower_returns(st, {"CANDIDATA": ["W"]})
        self.assertEqual(res["CANDIDATA"][30], [])
        self.assertGreaterEqual(unres["CANDIDATA"], 1)

    def test_ledger_filters_small_wallets(self):
        st = Store(":memory:")
        add(st, "M", 1, "big", True, 1.0, sol=2.0)
        add(st, "M", 2, "dust", True, 1.0, sol=0.05)
        self.assertEqual(list(wallets.ledger(st, 1.0)), ["big"])


if __name__ == "__main__":
    unittest.main()


class PnlWithoutTopTwo(unittest.TestCase):
    def test_luck_driven_profit_is_visible(self):
        from radar import wallet_history
        pos = {}
        wins = [10.0, 8.0]          # dos golpes grandes
        for i, g in enumerate(wins + [-1.0] * 6):
            pos[f"M{i}"] = {"buy_sol": 1.0, "buy_tok": 100.0, "sell_sol": 1.0 + g, "sell_tok": 100.0,
                            "first_buy": 1000 * i, "first_sell": 1000 * i + 900, "last_sell": 1000 * i + 900}
        p = {"wallet": "W", "positions": pos, "n_trades": 16, "n_txs": 16, "span_s": 10 ** 6}
        s = wallet_history.summarize(p, CFG)
        self.assertGreater(s["pnl_sol"], 0)
        self.assertLess(s["pnl_ex_top2"], 0)   # sin sus 2 mejores operaciones pierde: no es habilidad repetible
