import json
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from radar import backtest, costs, demo
from radar.config import load_config
from radar.recorder import Recorder
from radar.store import Store

CFG = load_config("/nonexistent.json")
T0 = 1_800_000_000
SOL = 100.0


def curve_point(prog):
    vs, vt = costs.reserves_from_progress(prog, CFG)
    price = vs / vt * SOL
    return {"progress": prog, "price": price, "mcap": price * 1e9, "vsol": vs, "vtok": vt}


def add_token(st, mint, entry_t, kind, rng, feat=None, feat_ts=None):
    """kind: win (completa y mantiene) | dump (se hunde un 80 %) | flat (completa y cae un 10 %) | stall (se queda parado)."""
    st.rec_add(mint, "C" + mint, "cr", "n", "S", entry_t - 3600, entry_t - 600, 80)
    t = entry_t - 600
    for i in range(41):  # 80 % -> 100 % en 10 min
        prog = 80 + min(i, 40) * 0.5
        if prog < 100:
            cp = curve_point(prog)
            st.rec_point(mint, t + i * 15, prog, cp["price"], cp["mcap"], cp["vsol"], cp["vtok"], None, "curve", SOL)
    last_curve_ts = t + 40 * 15
    p_end = curve_point(99.9)["price"]
    if kind in ("win", "flat"):
        st.rec_complete(mint, last_curve_ts + 15)
        mult = 1.0 if kind == "win" else 0.9
        for j in range(1, 200):
            st.rec_point(mint, last_curve_ts + 15 + j * 30, 100, p_end * mult, p_end * mult * 1e9, None, None, 200_000, "amm", SOL)
    elif kind == "dump":
        for j in range(1, 100):
            price = p_end * max(0.1, 1 - 0.02 * j)
            st.rec_point(mint, last_curve_ts + j * 15, 95, price, price * 1e9, curve_point(95)["vsol"], curve_point(95)["vtok"], None, "curve", SOL)
    if feat:
        st.rec_set_feat(mint, feat, feat_ts or entry_t - 1000)


class Recorder_(unittest.TestCase):
    def test_records_path_completion_and_features(self):
        st = Store(":memory:")
        rng = random.Random(1)
        coin = demo.synth_inputs(rng, "good", CFG, T0, 0.92)[0] | {"sol_quote": True, "complete": False, "pool": None, "created_ts": T0 - 5000}
        state = {"coin": coin}

        class Pump:
            def list_live(s, sol=None, offset=0):
                return [state["coin"]] if offset == 0 else []

            def creator_coins(s, c, sol=None):
                return [{"mint": "x", "mcap_usd": 100, "ath_mcap": 50000}]

        class Hel:
            available = True

            def holders(s, mint, ex):
                return [{"owner": f"h{i}", "amount": 5e6} for i in range(12)], 2.0e8

            def take_usage(s):
                return {}

            def curve_signatures(s, a, until=None, limit=1000):
                return []

            def parse_transactions(s, sigs):
                return []

            def curve_state(s, c):
                return None

        class Dex:
            def sol_usd(s):
                return SOL

            def best_pair(s, m):
                return {"price": 1e-4, "liq": 80_000, "mcap": 100_000}

        rec = Recorder(CFG, st, Pump(), Hel(), Dex(), log=lambda *a: None)
        r = rec.step(T0)
        self.assertEqual(r["new"], 1)
        tok = st.rec_get(coin["mint"])
        self.assertIsNotNone(tok["feat_ts"], "al cruzar el 90 % se graban características")
        f = json.loads(tok["feat"])
        self.assertEqual(f["creator_rugs"], 1)
        self.assertGreater(f["top10_pct"], 0)
        # migra
        state["coin"] = coin | {"complete": True, "pool": "POOL"}
        r2 = rec.step(T0 + 15)
        self.assertEqual(r2["completed"], 1)
        self.assertEqual(st.rec_get(coin["mint"])["completed_ts"], T0 + 15)
        rec.step(T0 + 60)
        phases = [p["phase"] for p in st.rec_path_of(coin["mint"])]
        self.assertEqual(phases[0], "curve")
        self.assertIn("amm", phases)

    def test_other_quote_tokens_are_never_recorded(self):
        st = Store(":memory:")
        coin = demo.synth_inputs(random.Random(2), "good", CFG, T0, 0.95)[0] | {"sol_quote": False, "pool": None}

        class Pump:
            def list_live(s, sol=None, offset=0):
                return [coin] if offset == 0 else []

        class Dex:
            def sol_usd(s):
                return SOL

        class Hel:
            available = False

        Recorder(CFG, st, Pump(), Hel(), Dex(), log=lambda *a: None).step(T0)
        self.assertEqual(st.rec_all(), [])


class Backtest(unittest.TestCase):
    def build(self, kinds, feat=None, feat_off=-1000, start=T0):
        st = Store(":memory:")
        rng = random.Random(3)
        for i, k in enumerate(kinds):
            add_token(st, f"M{i}", start + i * 3000, k, rng, feat, (start + i * 3000) + feat_off)
        return st

    def test_completion_jump_is_a_real_gain_after_costs(self):
        st = self.build(["win"] * 80)
        rep = backtest.run(st, CFG, T0 + 10 ** 6)
        self.assertIn(rep["verdict"], ("RENTABLE (provisional)", "INCONCLUSO"))
        self.assertGreater(rep["test"]["mean"], 0.1)  # +40 % de la curva menos costes
        self.assertEqual(rep["test"]["reasons"].get("migración"), rep["test"]["n"])

    def test_losing_mix_is_discarded_and_stop_works(self):
        kinds = (["dump"] * 3 + ["win"]) * 25  # 75 % se hunde, 25 % gana
        rep = backtest.run(self.build(kinds), CFG, T0 + 10 ** 6)
        self.assertEqual(rep["verdict"], "DESCARTAR")
        self.assertGreater(rep["test"]["stop_pct"], 50)

    def test_stop_exit_is_worse_than_nominal_minus_60(self):
        st = self.build(["dump"])
        tok = st.rec_all()[0]
        r = backtest.simulate(tok, st.rec_path_of("M0"), {"entry": 93, "exit": "migrate"}, CFG, T0 + 10 ** 6)
        self.assertTrue(r["stopped"])
        self.assertLess(r["ret"], -0.6)

    def test_flat_after_migration_loses_costs(self):
        st = self.build(["flat"] * 3)
        tok = st.rec_all()[0]
        r = backtest.simulate(tok, st.rec_path_of("M0"), {"entry": 93, "exit": "migrate"}, CFG, T0 + 10 ** 6)
        self.assertFalse(r["stopped"])

    def test_filter_cannot_use_features_recorded_after_entry(self):
        feat = {"top10_pct": 10, "creator_rugs": 0, "buyers5": 50, "wash_share": 0.0}
        late = self.build(["win"], feat=feat, feat_off=+5000)   # características grabadas DESPUÉS de entrar
        early = self.build(["win"], feat=feat, feat_off=-5000)
        v = {"entry": 93, "exit": "migrate", "top10_max": 35}
        t_late, t_early = late.rec_all()[0], early.rec_all()[0]
        self.assertIsNone(backtest.simulate(t_late, late.rec_path_of("M0"), v, CFG, T0 + 10 ** 6))
        self.assertIsNotNone(backtest.simulate(t_early, early.rec_path_of("M0"), v, CFG, T0 + 10 ** 6))

    def test_missing_feature_never_passes_a_filter(self):
        st = self.build(["win"], feat={"top10_pct": None, "creator_rugs": 0, "buyers5": 50, "wash_share": 0.0})
        v = {"entry": 93, "exit": "migrate", "top10_max": 35}
        self.assertIsNone(backtest.simulate(st.rec_all()[0], st.rec_path_of("M0"), v, CFG, T0 + 10 ** 6))

    def test_unfinished_trades_are_censored_not_guessed(self):
        st = Store(":memory:")
        add_token(st, "M0", T0, "stall", random.Random(1))  # curva sin completar, grabado hace poco
        tok = st.rec_all()[0]
        r = backtest.simulate(tok, st.rec_path_of("M0"), {"entry": 93, "exit": "migrate"}, CFG, tok["last_ts"] + 60)
        self.assertTrue(r.get("censored"))

    def test_late_fill_after_migration_is_counted_as_late(self):
        st = self.build(["win"])
        tok = st.rec_all()[0]
        r = backtest.simulate(tok, st.rec_path_of("M0"), {"entry": 93, "exit": "migrate"}, CFG, T0 + 10 ** 6, latency_s=600)
        self.assertTrue(r["late"])

    def test_not_enough_data_says_so(self):
        rep = backtest.run(self.build(["win"] * 5), CFG, T0 + 10 ** 6)
        self.assertEqual(rep["verdict"], "SIN DATOS SUFICIENTES")

    def test_twelve_closed_variants(self):
        vs = backtest.load_variants()
        self.assertLessEqual(len(vs), 12)
        self.assertEqual(len({v["id"] for v in vs}), len(vs))


if __name__ == "__main__":
    unittest.main()
