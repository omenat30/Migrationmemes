"""Regla de «tiburón» (radar/sharks.py): compró antes del pump fuerte y vendió con beneficio; prefiltro de actividad y bots."""
import unittest

from radar import sharks

NOW = 1_795_000_000


def tr(w, buy, sell, avg_cost, start=None, transfer=False):
    return {"wallet": w, "buy_usd": buy, "sell_usd": sell, "avg_cost": avg_cost, "start": start, "transfer_in": transfer, "tags": []}


class SharksTest(unittest.TestCase):
    def test_regla(self):
        rows = [tr("PRONTO", 500, 4000, 0.00001, start=NOW + 40),      # entrada a 10k de mcap con máximo de 1M: 1 % del máximo, vendió x8
                tr("SINVENDER", 500, 200, 0.00001),                     # pronto pero no ha vendido: no cuenta (beneficio en papel)
                tr("TARDE", 500, 4000, 0.0005),                         # entró a 500k: 50 % del máximo
                tr("REGALO", 500, 4000, 0.00001, transfer=True),        # recibió por transferencia (creador / reparto)
                tr("PEQUE", 50, 900, 0.00001)]                          # menos de 200 USD
        got = sharks.early_sharks(rows, 1e9, 1_000_000, created_ts=NOW)
        self.assertEqual([g["wallet"] for g in got], ["PRONTO"])
        self.assertEqual(got[0]["secs_after_launch"], 40)
        self.assertAlmostEqual(got[0]["peak_frac"], 0.01)

    def test_prefiltro(self):
        ev = {"sharks": [{"wallet": w, "buy": 500, "sold": 4000, "realized": 8, "entry_mcap": 10000, "peak_frac": 0.01, "secs_after_launch": 40}
                         for w in ("BUENA", "INACTIVA", "BOT", "PIERDE")]}
        pool = sharks.aggregate({"M1": dict(ev, sym="A"), "M2": {"sym": "B", "sharks": ev["sharks"][:1]}})
        base = {"pnl": 0.8, "realized_profit": 9000, "winrate": 0.5, "buys": 300, "last_ts": NOW - 3600}
        stats = {"BUENA": base, "INACTIVA": dict(base, last_ts=NOW - 9 * 86400), "BOT": dict(base, buys=40000), "PIERDE": dict(base, pnl=-0.2)}
        got = sharks.rank_candidates(pool, stats, NOW)
        self.assertEqual([w for w, _ in got], ["BUENA"])
        self.assertEqual(got[0][1]["tokens"], 2)


if __name__ == "__main__":
    unittest.main()
