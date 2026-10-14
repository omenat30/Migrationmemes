import base64
import os
import random
import struct
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from radar import demo
from radar.config import load_config
from radar.engine import Engine
from radar.sources.helius import Helius
from radar.sources.pumpfun import normalize_coin
from radar.store import Store
from radar.util import RateLimiter

NOW = 1_800_000_000


def account(vt, vs, rt, rs, supply, complete):
    """Cuenta de la curva con el formato REAL verificado: 8 bytes + 5 u64 + bool (+ resto hasta 166)."""
    raw = b"\x17\xb7\xf8\x37\x60\xd8\xac\x60" + struct.pack("<5Q", vt, vs, rt, rs, supply) + bytes([complete])
    return raw + b"\x00" * (166 - len(raw))


class FakeRpc(Helius):
    def __init__(self, cfg, raw):
        cfg["keys"]["helius"] = "K"
        super().__init__(cfg, RateLimiter(100))
        self.raw = raw

    def _rpc(self, method, params):
        self._count("rpc")
        return {"value": {"owner": "6EF8rrec", "data": [base64.b64encode(self.raw).decode(), "base64"]}} if self.raw else {"value": None}


class CurveState(unittest.TestCase):
    def test_decode_matches_real_values(self):
        # Valores reales de un token estándar (MOBA, 14 oct 2026): vt, vs, rt, rs, supply
        h = FakeRpc(load_config("/x"), account(1_070_532_928_000_000, 30_069_100_000, 790_632_928_000_000, 69_100_000, 1_000_000_000_000_000, 0))
        s = h.curve_state("C")
        self.assertAlmostEqual(s["vtok"], 1_070_532_928)
        self.assertAlmostEqual(s["vsol"], 30.0691)
        self.assertAlmostEqual(s["rsol"], 0.0691)
        self.assertFalse(s["complete"])
        self.assertTrue(s["standard"])

    def test_non_sol_curve_is_not_standard(self):
        # callinu: reservas virtuales de 757 «SOL» con 74 reales: no es una curva en SOL
        h = FakeRpc(load_config("/x"), account(967_232_177_000_000, 757_174_000_000, 687_332_177_000_000, 74_636_200_000, 10 ** 15, 0))
        self.assertFalse(h.curve_state("C")["standard"])

    def test_missing_or_short_account(self):
        self.assertIsNone(FakeRpc(load_config("/x"), None).curve_state("C"))
        self.assertIsNone(FakeRpc(load_config("/x"), b"\x00" * 20).curve_state("C"))

    def test_usage_counter_resets(self):
        h = FakeRpc(load_config("/x"), account(1, 1, 1, 1, 1, 0))
        h.curve_state("C")
        h.curve_state("C")
        self.assertEqual(h.take_usage(), {"rpc": 2})
        self.assertEqual(h.take_usage(), {})


class QuoteMint(unittest.TestCase):
    def raw(self, qd, vs, rs):
        return {"mint": "m", "quote_decimals": qd, "virtual_sol_reserves": int(vs * 1e9), "real_sol_reserves": int(rs * 1e9),
                "real_token_reserves": 5e14, "virtual_token_reserves": 7e14, "usd_market_cap": 1}

    def test_real_cases(self):
        self.assertTrue(normalize_coin(self.raw(9, 30.119, 0.119))["sol_quote"])      # FUD, estándar
        self.assertFalse(normalize_coin(self.raw(8, 8148.06, 796.48))["sol_quote"])   # FOUR: 8 decimales
        self.assertFalse(normalize_coin(self.raw(6, 44541.19, 5029.3))["sol_quote"])  # napcat: 6 decimales
        self.assertFalse(normalize_coin(self.raw(9, 757.17, 74.6))["sol_quote"])      # reservas fuera de lo estándar


class FakeHel:
    available = True

    def __init__(self, state):
        self.state = state
        self.usage = {}

    def curve_state(self, c):
        return self.state

    def take_usage(self):
        u, self.usage = self.usage, {}
        return u


class FakeDex:
    def __init__(self, pair=None):
        self.pair = pair

    def sol_usd(self):
        return 100.0

    def best_pair(self, m):
        return self.pair


class Pricing(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config("/x")
        self.store = Store(":memory:")

    def eng(self, state, pair=None):
        return Engine(self.cfg, self.store, pump=object(), helius=FakeHel(state), dex=FakeDex(pair), gmgn=type("G", (), {"available": False})(),
                      log=lambda *a: None)

    def test_price_comes_from_chain_before_migration(self):
        st = {"vsol": 115.0, "vtok": 279_900_000.0, "supply": 1e9, "complete": False, "standard": True}
        s = self.eng(st).price_sample("M", NOW, "CURVE")
        self.assertFalse(s["complete"])
        self.assertAlmostEqual(s["price"], 115.0 / 279_900_000 * 100.0)
        self.assertAlmostEqual(s["mcap"], s["price"] * 1e9)
        self.assertEqual(s["vsol"], 115.0)

    def test_after_migration_uses_dexscreener(self):
        st = {"vsol": 0, "vtok": 0, "supply": 1e9, "complete": True, "standard": True}
        s = self.eng(st, {"price": 4e-5, "liq": 50_000, "mcap": 40_000}).price_sample("M", NOW, "CURVE")
        self.assertTrue(s["complete"])
        self.assertEqual(s["liq"], 50_000)

    def test_non_standard_curve_is_never_priced_from_reserves(self):
        st = {"vsol": 757.0, "vtok": 967e6, "supply": 1e9, "complete": False, "standard": False}
        self.assertIsNone(self.eng(st, None).price_sample("M", NOW, "CURVE"))


class CycleBehaviour(unittest.TestCase):
    def test_non_sol_tokens_are_excluded_and_counted_and_most_advanced_goes_first(self):
        cfg = load_config("/x")
        cfg["keys"]["helius"] = "K"
        cfg["max_deep_per_cycle"] = 1
        store = Store(":memory:")
        rng = random.Random(1)
        mk = lambda prog, sol: demo.synth_inputs(rng, "good", cfg, NOW, prog)[0] | {"sol_quote": sol}
        a, b, c = mk(0.80, True), mk(0.95, True), mk(0.97, False)
        evaluated = []

        class Pump:
            def list_live(s, sol=None):
                return [a, b, c]

        class Hel:
            available = True

            def take_usage(s):
                return {"rpc": 3}

        eng = Engine(cfg, store, pump=Pump(), helius=Hel(), dex=FakeDex(), gmgn=type("G", (), {"available": False})(), log=lambda *x: None)
        eng.deep = lambda coin, now: evaluated.append(coin["mint"]) or None
        eng.cycle(NOW)
        self.assertEqual(evaluated, [b["mint"]], "solo se evalúa el más avanzado en SOL; el de otra moneda se excluye")
        lc = store.get_meta("last_cycle")
        self.assertEqual((lc["eligible"], lc["other_quote"], lc["pending"]), (2, 1, 1))
        self.assertEqual(list(store.get_meta("usage").values())[0], {"rpc": 3})


class StoreThreads(unittest.TestCase):
    def test_clone_shares_data_across_threads(self):
        with tempfile.TemporaryDirectory() as d:
            st = Store(os.path.join(d, "t.sqlite"))
            st.set_meta("k", 1)
            out = []

            def worker():
                c = st.clone()
                out.append(c.get_meta("k"))
                c.set_meta("j", 2)
                c.close()

            th = threading.Thread(target=worker)
            th.start()
            th.join()
            self.assertEqual(out, [1])
            self.assertEqual(st.get_meta("j"), 2)
            st.close()
        with self.assertRaises(ValueError):
            Store(":memory:").clone()

    def test_tracked_keeps_curve_for_the_sampler(self):
        st = Store(":memory:")
        st.track("M", "candidate", NOW, NOW + 10, 1.0, "n", "S", "CURVE123")
        self.assertEqual(st.get_tracked("M")["curve"], "CURVE123")


if __name__ == "__main__":
    unittest.main()
