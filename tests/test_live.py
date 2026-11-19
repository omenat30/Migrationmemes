"""Seguimiento en vivo (radar/live.py): acumulación sin contar dos veces, tokens previos, valoración y paridad con el panel."""
import json
import os
import random
import shutil
import subprocess
import unittest

from radar import audit, live

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
START = 1_795_000_000
DAY = 86400


def row(ev, mint, ts, usd, amt, tx, sym="TOK"):
    return {"event_type": ev, "timestamp": ts, "cost_usd": str(usd), "token_amount": str(amt), "tx_hash": tx,
            "token": {"address": mint, "symbol": sym}}


class MergeTest(unittest.TestCase):
    def setUp(self):
        self.doc = live.new_doc("W", START)

    def test_no_cuenta_dos_veces(self):
        rows = [row("buy", "A", START + 10, 100, 1000, "t1"), row("sell", "A", START + 50, 150, 500, "t2"),
                row("sell", "A", START + 50, 60, 500, "t3")]
        live.merge(self.doc, rows, 100.0, START + 100)
        live.merge(self.doc, rows, 100.0, START + 200)          # la misma lectura otra vez: no cambia nada
        p = self.doc["pos"][0]
        self.assertEqual((p[live.COST], p[live.PROCEEDS], p[live.NB], p[live.NS]), (100.0, 210.0, 1, 2))
        # fila nueva en el mismo segundo que la marca de agua: sí entra
        live.merge(self.doc, rows + [row("buy", "B", START + 50, 20, 10, "t4")], 100.0, START + 300)
        self.assertEqual([p[live.MINT] for p in self.doc["pos"]], ["A", "B"])
        self.assertEqual(self.doc["pos"][0][live.PROCEEDS], 210.0)

    def test_tokens_previos_y_ventas_huerfanas(self):
        rows = [row("buy", "OLD", START - DAY, 50, 100, "p1"),          # comprado antes del inicio
                row("buy", "OLD", START + 10, 50, 100, "p2"),           # recompra después: no es entrada nueva
                row("sell", "GONE", START + 20, 80, 100, "p3"),         # venta de algo comprado mucho antes
                row("buy", "NEW", START + 30, 10, 100, "p4")]
        live.merge(self.doc, rows, 100.0, START + 100)
        self.assertEqual([p[live.MINT] for p in self.doc["pos"]], ["NEW"])
        self.assertIn("OLD", self.doc["pre"])

    def test_vende_mas_de_lo_que_compro(self):
        rows = [row("buy", "A", START + 10, 100, 100, "a"), row("sell", "A", START + 20, 400, 200, "b")]
        live.merge(self.doc, rows, 100.0, START + 30)
        st, mult = live.value(self.doc["pos"][0], START + 30)
        self.assertEqual(st, "closed")
        self.assertAlmostEqual(mult, 2.0)        # 400 USD por 200 tokens; solo cuentan los 100 comprados -> 200 / 100

    def test_estados(self):
        rows = [row("buy", "C", START + 1, 10, 100, "c1"), row("sell", "C", START + 2, 30, 95, "c2"),
                row("buy", "S", START + 3, 10, 100, "s1"), row("sell", "S", START + 4, 4, 50, "s2"),
                row("buy", "O", START + 5, 10, 100, "o1")]
        now = START + 8 * DAY
        live.merge(self.doc, rows, 100.0, now)
        live.merge(self.doc, [row("sell", "O", now - DAY, 5, 10, "o2")], 100.0, now)
        got = {p[live.MINT]: live.value(p, now) for p in self.doc["pos"]}
        self.assertEqual(got["C"][0], "closed")
        self.assertEqual(got["S"], ("stale", 0.4))          # quieta 8 días: lo vendido; lo que queda, a 0
        self.assertEqual(got["O"][0], "open")               # se movió ayer: todavía no cuenta

    def test_neto_igual_que_auditoria(self):
        self.assertAlmostEqual(live.net(2.0, 100.0, 15, 75.0), audit.net_return(2.0, 100.0, 15, 75.0))
        self.assertAlmostEqual(live.net(1.0, None, 15, 75.0, extra=0.05), audit.net_return(1.0, None, 15, 75.0) - 0.05)
        self.assertEqual(live.net(0.0, None, 15, 75.0, extra=0.05), -1.0)

    def test_promesa_solo_antes_del_inicio(self):
        wdoc = {"pos": [[START - 70 * DAY, 10, 3.0, 1, 50], [START - DAY, 10, 2.0, 1, 50], [START + DAY, 10, 9.0, 1, 50]],
                "m": {"span_days": 58}}
        pr = live.promise_from_wallet_doc(wdoc, START)
        self.assertEqual([r[1] for r in pr["hist"]], [2.0])
        self.assertEqual(pr["hist_span"], 58)


def _live_js():
    src = open(os.path.join(ROOT, "dashboard", "copy.html"), encoding="utf-8").read()
    a = src.index("/* ===== BEGIN LIVE")
    b = src.index("/* ===== END LIVE")
    return src[a:b]


@unittest.skipUnless(shutil.which("node"), "node no instalado")
class ParityLiveTest(unittest.TestCase):
    def test_paridad_resumen(self):
        rng = random.Random(5)
        now = START + 10 * DAY
        docs, wallets = {}, {}
        for w in ("W1", "W2"):
            d = live.new_doc(w, START)
            rows, k = [], 0
            for i in range(60):
                m, t = f"{w}M{i}", START + rng.randint(0, 9 * DAY)
                rows.append(row("buy", m, t, rng.uniform(20, 900), rng.uniform(1e5, 5e7), f"{w}b{i}"))
                if rng.random() < 0.8:
                    rows.append(row("sell", m, t + rng.randint(30, 3 * DAY), rng.uniform(0, 3000), rng.uniform(1e4, 6e7), f"{w}s{i}"))
            live.merge(d, rows, 80.0, now)
            docs[w] = d
            wallets[w] = {"start_ts": START, "per_day14": 3.2,
                          "hist": [[START - rng.randint(1, 50 * DAY), rng.choice([0.0, 0.4, 0.9, 1.3, 2.5, 12.0]), rng.choice([None, 30.0, 300.0])]
                                   for _ in range(40)]}
        meta = {"sol_usd": 80.0, "stale_days": 7, "wallets": wallets, "cost": live.cost_model()}
        for sizes, extra in (({"W1": 15, "W2": 15}, 0.0), ({"W1": 5, "W2": 3}, 0.05), ({"W1": 250, "W2": 40}, 0.02)):
            py = live.summarize(meta, docs, now, sizes, extra)
            js = _live_js() + "\nconst M=%s,D=%s;console.log(JSON.stringify(liveSummary(M,D,%d,%s,%s)))" % (
                json.dumps(meta), json.dumps(docs), now, json.dumps(sizes), json.dumps(extra))
            got = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
            for w in py:
                for k in ("opened", "open", "real_usd", "promise_usd", "days"):
                    self.assertAlmostEqual(got[w][k], py[w][k], places=6, msg=f"{w} {k} {sizes}")
                for part in ("closed", "with_bags", "promise"):
                    for k in ("n", "mean", "win"):
                        self.assertAlmostEqual(got[w][part][k], py[w][part][k], places=6, msg=f"{w} {part}.{k}")


if __name__ == "__main__":
    unittest.main()
