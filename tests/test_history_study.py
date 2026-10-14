import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from radar import costs, history, study
from radar.config import load_config
from radar.store import Store

CFG = load_config("/nonexistent.json")
SOL = 100.0
T0 = 1_800_000_000


class FakeH:
    """Helius con una curva simulada exacta: genera operaciones hacia delante hasta completar y las sirve como Helius."""

    def __init__(self, n=120, seed=3):
        rng = random.Random(seed)
        vs, vt = 30.0, 1_073_000_000.0
        self.truth, self.txs = [], []
        for i in range(n):
            buy = rng.random() < 0.8
            sol = rng.uniform(0.05, 1.2)
            if buy:
                new_vs = vs + sol
                new_vt = 30.0 * 1_073_000_000.0 / new_vs
                tokens = vt - new_vt
            else:
                new_vs = vs - sol
                new_vt = 30.0 * 1_073_000_000.0 / new_vs
                tokens = new_vt - vt
            vs, vt = new_vs, new_vt
            self.truth.append({"ts": T0 + i * 5, "vsol": vs, "vtok": vt})
            a, b = ("CURVE", "U%d" % i) if buy else ("U%d" % i, "CURVE")
            self.txs.append({"signature": f"S{i}", "timestamp": T0 + i * 5, "slot": i, "type": "SWAP", "source": "PUMP_FUN",
                             "transactionError": None,
                             "tokenTransfers": [{"fromUserAccount": a, "toUserAccount": b, "tokenAmount": tokens, "mint": "MINT"}],
                             "accountData": [{"account": "CURVE", "nativeBalanceChange": int((1 if buy else -1) * sol * 1e9)}]})
        self.final = (vs, vt)

    def curve_state(self, curve):  # estado FINAL real de la simulación (curva aún sin completar)
        return {"vsol": self.final[0], "vtok": self.final[1], "rsol": self.final[0] - 30, "rtok": 0, "supply": 1e9,
                "complete": False, "standard": True}

    def curve_signatures(self, address, until=None, limit=1000, before=None):
        return [{"signature": t["signature"], "blockTime": t["timestamp"], "err": None} for t in reversed(self.txs)][:limit]

    def parse_transactions(self, sigs):
        by = {t["signature"]: t for t in self.txs}
        return [dict(by[s]) for s in sigs]


class Reconstruction(unittest.TestCase):
    def test_undoing_trades_recovers_the_exact_price_path(self):
        h = FakeH()
        pts, meta = history.reconstruct_curve(h, "MINT", "CURVE", SOL, CFG, max_txs=600)
        self.assertEqual(meta["trades"], 120)
        self.assertEqual(len(pts), 120)
        for p, truth in zip(pts, h.truth):
            self.assertAlmostEqual(p["vsol"], truth["vsol"], places=3)
            self.assertAlmostEqual(p["vtok"], truth["vtok"], delta=2.0)
            self.assertAlmostEqual(p["price"], truth["vsol"] / truth["vtok"] * SOL, delta=truth["vsol"] / truth["vtok"] * SOL * 1e-6)

    def test_completed_curve_starts_from_the_theoretical_final_state(self):
        h = FakeH()
        h.curve_state = lambda c: {"vsol": 0, "vtok": 0, "rsol": 0, "rtok": 0, "supply": 1e9, "complete": True, "standard": False}
        pts, _ = history.reconstruct_curve(h, "MINT", "CURVE", SOL, CFG)
        self.assertAlmostEqual(pts[-1]["vsol"], history.FINAL_VSOL)   # el último punto parte del estado final conocido
        self.assertAlmostEqual(pts[-1]["progress"], 100.0, delta=0.01)

    def test_non_standard_curve_is_refused(self):
        h = FakeH()
        h.curve_state = lambda c: {"vsol": 757.0, "vtok": 9e8, "rsol": 74.0, "rtok": 6e8, "supply": 1e9, "complete": False, "standard": False}
        self.assertIsNone(history.reconstruct_curve(h, "MINT", "CURVE", SOL, CFG)[0])


def make_token(st, mint, mult_path, mig=T0, liq=40_000.0):
    """Token migrado con precio en el pool = 1.0 * multiplicadores, una operación cada 10 s."""
    st.rec_add(mint, "C", "cr", "n", "S", mig - 3600, mig - 600, 90, src="backfill")
    st.rec_complete(mint, mig)
    for i, m in enumerate(mult_path):
        st.rec_point(mint, mig + 10 * i, 100, 1e-5 * m, 1e-5 * m * 1e9, None, None, liq, "amm", SOL)


class PostMigrationStudy(unittest.TestCase):
    def build(self, paths):
        st = Store(":memory:")
        for i, p in enumerate(paths):
            make_token(st, f"M{i}", p)
        return st

    def test_x3_is_reached_and_exits_at_target(self):
        up = [1.0] * 10 + [1.5, 2.0, 3.2, 3.5, 3.0] + [3.0] * 20
        st = self.build([up])
        r = study.simulate_post(st.rec_all()[0], st.rec_path_of("M0"), 60, "R1", CFG, T0 + 10 ** 6)
        self.assertEqual(r["reason"], "x3")
        self.assertGreater(r["ret"], 1.5)

    def test_stop_hits_on_a_dump(self):
        down = [1.0] * 8 + [0.7, 0.45, 0.3, 0.2] + [0.1] * 30
        st = self.build([down])
        r = study.simulate_post(st.rec_all()[0], st.rec_path_of("M0"), 30, "R1", CFG, T0 + 10 ** 6)
        self.assertEqual(r["reason"], "stop")
        self.assertLess(r["ret"], -0.6)

    def test_later_entry_buys_at_the_later_price(self):
        pump_then_flat = [1.0, 1.0, 1.0, 2.0, 2.0, 2.0, 2.0] + [2.0] * 400
        st = self.build([pump_then_flat])
        early = study.simulate_post(st.rec_all()[0], st.rec_path_of("M0"), 0, "R2", CFG, T0 + 10 ** 6)
        late = study.simulate_post(st.rec_all()[0], st.rec_path_of("M0"), 60, "R2", CFG, T0 + 10 ** 6)
        self.assertGreater(early["ret"], late["ret"] + 0.5)   # llegar tarde se paga caro

    def test_unresolved_trade_is_censored(self):
        st = self.build([[1.0] * 12])   # solo 2 minutos de datos y nada resuelve
        r = study.simulate_post(st.rec_all()[0], st.rec_path_of("M0"), 30, "R1", CFG, T0 + 10 ** 6)
        self.assertTrue(r.get("censored"))

    def test_report_shape_and_survivor_caveat(self):
        rng = random.Random(1)
        paths = []
        for _ in range(40):
            p, v = [], 1.0
            for _ in range(400):
                v *= 1 + rng.gauss(0, 0.02)
                p.append(v)
            paths.append(p)
        st = self.build(paths)
        rep = study.run(st, CFG, T0 + 10 ** 6, "backfill")
        self.assertEqual(len(rep["rows"]), 8)
        self.assertIn("cota superior", rep["caveat"])
        self.assertTrue(all("peak_ge3" in r for r in rep["rows"] if r["n"]))


if __name__ == "__main__":
    unittest.main()
