import unittest

from radar import discover, pda


class PdaTest(unittest.TestCase):
    def test_bonding_curve_matches_pumpfun_api(self):
        # par real (mint, curva) devuelto por la API de pump.fun el 14-oct-2026
        self.assertEqual(pda.bonding_curve("Fak3rJEBfR4Vb8DoFpecf6yoxbkkr1gGUH5tdj2rpump"), "BriJJUhbZPktbk4iwripFoqgrZTFrrXPGuBaKGCiLc8h")

    def test_b58_roundtrip(self):
        s = "BriJJUhbZPktbk4iwripFoqgrZTFrrXPGuBaKGCiLc8h"
        self.assertEqual(pda.b58encode(pda.b58decode(s)), s)


class CotradeTest(unittest.TestCase):
    def test_cotraders_exclude_seed_and_need_repeats(self):
        r = {"cost": 1.0, "proceeds": 2.0, "hold": 900}
        per = {"m1": {"A": r, "S": r}, "m2": {"A": r, "B": r}, "m3": {"A": r}}
        out = discover.cotraders(per, {"S"}, min_tokens=3)
        self.assertEqual([w for w, _ in out], ["A"])


if __name__ == "__main__":
    unittest.main()
