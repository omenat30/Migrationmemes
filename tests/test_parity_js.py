"""Prueba de paridad: la lógica de simulación del panel (dashboard/copy.html) da lo mismo que radar/copysim.py."""
import json
import os
import random
import shutil
import subprocess
import unittest

from radar import copysim

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _sim_js():
    src = open(os.path.join(ROOT, "dashboard", "copy.html"), encoding="utf-8").read()
    a = src.index("/* ===== BEGIN SIM")
    b = src.index("/* ===== END SIM")
    return src[a:b]


@unittest.skipUnless(shutil.which("node"), "node no instalado")
class ParityTest(unittest.TestCase):
    def test_paridad(self):
        rng = random.Random(3)
        pos = [[1_790_000_000 + i * 600, rng.uniform(10, 4000), rng.choice([0.0, 0.3, 0.8, 1.2, 2.0, 5.0, 12.0, 30.0]) * rng.uniform(0.9, 1.1), 1.0]
               for i in range(80)]
        cases = [dict(size=100, delay=30, fee=1.0, imp=2.0, apply=True), dict(size=2500, delay=120, fee=1.0, imp=2.0, apply=True),
                 dict(size=500, delay=60, fee=0.5, imp=1.0, apply=False), dict(size=100, delay=30, fee=1.0, imp=2.0, apply=True, pen=0.05)]
        js = _sim_js() + "\nconst P=%s,C=%s;console.log(JSON.stringify(C.map(c=>{const r=simulate(P,Object.assign({stopPct:60},c));return [r.n,r.expectedR,r.totalUsd,r.maxDd,r.win]})))" % (json.dumps(pos), json.dumps(cases))
        out = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
        for c, got in zip(cases, out):
            py = copysim.simulate(pos, c["size"], delay_s=c["delay"], entry_penalty=c.get("pen"), fee_pct=c["fee"], impact_per_1k_pct=c["imp"], stop_pct=60.0, apply_stop=c["apply"])
            exp = [py["n"], py["expected_r"], py["total_usd"], py["max_drawdown_usd"], py["win"]]
            for g, e in zip(got, exp):
                self.assertAlmostEqual(g, e, places=6, msg=str(c))


if __name__ == "__main__":
    unittest.main()
