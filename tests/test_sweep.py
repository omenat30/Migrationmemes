import unittest

from radar import deepwallet, sweep
import copy as _copy

from radar.config import DEFAULTS as _DEF

DEFAULTS = _copy.deepcopy(_DEF)
DEFAULTS["copy"]["max_idle_days"] = 0  # los datos de prueba son de fechas fijas
DEFAULTS["copy"]["min_recent_closed"] = 0


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
                allst = {"W1": {"pnl": 0.5, "winrate": 0.6, "buys": 30, "realized_profit": 1500.0},
                         "W3": {"pnl": 0.1, "winrate": 0.6, "buys": 30, "realized_profit": 1500.0}}
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
        cfg["copy"]["max_idle_days"] = 14  # el filtro ya no está activo por defecto
        m = metrics_for(pos)
        ok, why = deepwallet.passes(m, cfg)
        self.assertFalse(ok)
        self.assertTrue(any("sin operar" in w for w in why))
        # una compra abierta reciente cuenta como actividad
        pos.append({"mint": "open", "closed": False, "cost": 1.0, "proceeds": 0.0, "entry_ts": int(_t.time()) - 3 * 86400, "exit_ts": None, "hold": None, "mult": None})
        m2 = metrics_for(pos)
        self.assertLess((_t.time() - m2["last_ts"]) / 86400, 4)


class FlowsTest(unittest.TestCase):
    def test_summarize_detects_links_big_moves_and_flag(self):
        from radar import flows
        now = 1_792_000_000
        rows = [
            {"timestamp": now - 2 * 86400, "event_type": "transfer_out", "cost_usd": 13000, "from_address": "A", "to_address": "B", "token": {"symbol": "PUMP"}},
            {"timestamp": now - 3 * 86400, "event_type": "transfer_out", "cost_usd": 6000, "from_address": "A", "to_address": "X", "token": {"symbol": "PUMP"}},
            {"timestamp": now - 40 * 86400, "event_type": "transfer_in", "cost_usd": 300, "from_address": "Y", "to_address": "A", "token": {"symbol": "SOL"}},
            {"timestamp": now - 1 * 86400, "event_type": "transfer_in", "cost_usd": 1.6, "from_address": "Z", "to_address": "A", "token": {"symbol": "PUMP"}},  # polvo
        ]
        s = flows.summarize("A", rows, tracked={"A", "B", "C"}, now=now)
        self.assertEqual(s["out14"], 19000)
        self.assertEqual(s["in14"], 0)
        self.assertEqual(s["in60"], 300)
        self.assertEqual(s["links"], ["B"])
        self.assertTrue(s["flag"])
        self.assertEqual(s["big"][0][2], "B")

    def test_shared_destinations_and_balance_drop(self):
        from radar import flows
        pw = {"A": {"top": [["D", 5000, 0]]}, "B": {"top": [["D", 2000, 0], ["E", 10, 0]]}, "C": {"top": [["F", 9000, 0]]}}
        self.assertEqual(flows.shared_destinations(pw), {"D": ["A", "B"]})
        self.assertIsNotNone(flows.balance_drop([[1, 183.0], [2, 180.0]], 90.0))
        self.assertIsNone(flows.balance_drop([[1, 183.0]], 170.0))
        self.assertIsNone(flows.balance_drop([[1, 2.0]], 0.5))  # saldo pequeño: ruido


class DailyTest(unittest.TestCase):
    def test_daily_run_with_fake_gmgn(self):
        import json as _json
        import tempfile
        import time as _t
        from radar import daily
        now = int(_t.time())

        class FakeG:
            def trending(self, iv, limit, ob):
                return [{"mint": "TOK1pump"}]

            def top_traders(self, mint, limit, order_by):
                return [{"wallet": "NEW1", "profit": 5000.0}, {"wallet": "KNOWN", "profit": 9000.0}]

            def wallet_stats(self, ws, period):
                return {w: {"pnl": 0.8, "winrate": 0.6, "buys": 60, "realized_profit": 5000.0, "sol_balance": 100.0} for w in ws}

            def activity_page(self, wallet, cursor=None, limit=100, types=("buy", "sell")):
                if "transferIn" in types:
                    return [{"timestamp": now - 86400, "event_type": "transfer_out", "cost_usd": 9000, "from_address": wallet,
                             "to_address": "NEW1" if wallet != "NEW1" else "ELSEWHERE", "token": {"symbol": "PUMP"}}], None
                rows = []
                for i in range(30):  # 30 posiciones cerradas x2 con tenencia de 20 min, recientes
                    t = now - (i + 1) * 3 * 3600
                    tok = {"address": "M%d" % i}
                    rows.append({"event_type": "buy", "token": tok, "cost_usd": 100.0, "token_amount": 10, "timestamp": t})
                    rows.append({"event_type": "sell", "token": tok, "cost_usd": 200.0, "token_amount": 10, "timestamp": t + 1200})
                return rows, None

        cfg = _copy.deepcopy(_DEF)
        cfg["copy"]["min_span_days"] = 0
        prev = {"KNOWN": {"addr": "KNOWN", "status": "candidate", "joined_ts": None, "last_ts": 1, "m": {"roi": 0.5, "n_closed": 40}, "pos": []}}
        with tempfile.TemporaryDirectory() as td:
            out = td + "/o.json"
            docs, meta = daily.run(cfg, FakeG(), prev, out, 100.0, verify_n=2, refresh_n=1, log=lambda m: None)
            saved = _json.load(open(out))
        self.assertIn("NEW1", docs)
        self.assertIn("KNOWN", docs)  # refrescada
        self.assertEqual(docs["NEW1"]["status"], "active")
        self.assertIn("flows", docs["NEW1"])
        self.assertTrue(any(c["type"] == "flow" for c in meta["changes"]))  # salió 9000 USD en 14 días
        self.assertEqual(saved["meta"]["active"], meta["active"])
        self.assertTrue(docs["NEW1"]["balhist"])


class MigrantsTest(unittest.TestCase):
    def test_fast_winners_and_group(self):
        from radar import migrants
        rows = [
            {"wallet": "A", "buy_usd": 500, "sell_usd": 6000, "start": 1000, "end": 2000},        # x12 en 1000 s: acierto
            {"wallet": "B", "buy_usd": 500, "sell_usd": 6000, "start": 1000, "end": 9000},        # demasiado lento
            {"wallet": "C", "buy_usd": 0, "sell_usd": 9000, "start": 1000, "end": 1500},          # recibido por transferencia
            {"wallet": "D", "buy_usd": 500, "sell_usd": 1000, "start": 1000, "end": 1500},        # solo x2
            {"wallet": "E", "buy_usd": 500, "sell_usd": 6000, "start": 1000, "end": 1005},        # 5 s: bot
        ]
        w = migrants.fast_winners(rows)
        self.assertEqual([x["wallet"] for x in w], ["A"])
        per = {"m1": {"winners": w}, "m2": {"winners": w}, "m3": {"winners": w + [{"wallet": "Z", "mult": 9, "hold": 100, "buy": 200}]}}
        g = migrants.group(per, min_tokens=3)
        self.assertEqual([a for a, _ in g], ["A"])


class CrossingTest(unittest.TestCase):
    def test_classify_and_summarize(self):
        from radar import crossing
        mig = {"A": 1000, "B": 1000, "C": 1000, "D": None}
        P = lambda m, e, x, mult: {"mint": m, "entry_ts": e, "exit_ts": x, "mult": mult, "cost": 1.0, "hold": x - e}
        self.assertEqual(crossing.classify(P("A", 500, 1500, 3), 1000), "cruce")
        self.assertEqual(crossing.classify(P("B", 500, 900, 3), 1000), "previa")
        self.assertEqual(crossing.classify(P("C", 1100, 1500, 3), 1000), "tras")
        self.assertEqual(crossing.classify(P("D", 500, 1500, 3), None), "curva")
        s = crossing.summarize([P("A", 500, 1500, 3), P("A", 400, 1600, 1.0), P("D", 1, 2, 0.5)], mig)
        self.assertEqual(s["cruce"]["n"], 2)
        self.assertAlmostEqual(s["cruce"]["roi"], 1.0)
        self.assertEqual(s["curva"]["n"], 1)

    def test_mcap_bands(self):
        from radar import crossing
        G = crossing.GRAD_SOL
        P = lambda m_entry, m_exit, mult, hold=600: {"closed": True, "mult": mult, "cost": m_entry / 1e9 * 1e6, "bought": 1e6,
                                                     "proceeds": m_exit / 1e9 * 1e6, "sold": 1e6, "hold": hold}
        self.assertEqual(crossing.band(0.2 * G), "temprana")
        self.assertEqual(crossing.band(0.8 * G), "a_punto")
        self.assertEqual(crossing.band(1.5 * G), "recien")
        self.assertEqual(crossing.band(5 * G), "tarde")
        self.assertIsNone(crossing.band(5e7))  # supply distinta: fuera
        ps = [P(0.8 * G, 1.6 * G, 2.0), P(0.7 * G, 0.6 * G, 0.85), P(2 * G, 2.2 * G, 1.1), P(0.1 * G, 0.2 * G, 2.0)]
        s = crossing.summarize_mcap(ps, net_fn=lambda p: p["mult"] - 1)
        self.assertEqual(s["a_punto"]["n"], 2)
        self.assertEqual(s["near"]["n"], 3)
        self.assertEqual(s["cross"]["n"], 1)
        self.assertEqual(s["pre"]["n"], 3)
        self.assertEqual(s["post"]["n"], 1)
        self.assertAlmostEqual(s["a_punto"]["er"], ((2.0 - 1) + (0.85 - 1)) / 2 / 0.6, places=3)


class PumpsTest(unittest.TestCase):
    def test_is_pumping_and_early_buyers(self):
        from radar import pumps
        now = 10_000_000
        t = {"market_cap": 200000, "liquidity": 30000, "creation_timestamp": now - 7200, "price_change_percent1h": 400.0, "price_change_percent5m": 5.0}
        self.assertEqual(pumps.is_pumping(t, now)[0], "1h")
        self.assertIsNone(pumps.is_pumping(dict(t, creation_timestamp=now - 300), now))  # lanzamiento de hace minutos
        self.assertIsNone(pumps.is_pumping(dict(t, liquidity=1000), now))
        self.assertIsNone(pumps.is_pumping(dict(t, is_wash_trading=True), now))
        self.assertIsNone(pumps.is_pumping(dict(t, price_change_percent1h=50.0), now))
        # precio actual 5,0 tras subir +400 %: previo 1,0
        rows = [{"wallet": "a", "buy_usd": 500, "sell_usd": 1500, "avg_cost": 1.1, "profit": 1000, "transfer_in": False, "start": 1},
                {"wallet": "b", "buy_usd": 500, "sell_usd": 1500, "avg_cost": 3.0, "profit": 1000, "transfer_in": False, "start": 1},   # entró a mitad del pump
                {"wallet": "c", "buy_usd": 50, "sell_usd": 400, "avg_cost": 1.0, "profit": 350, "transfer_in": False, "start": 1},       # compra pequeña
                {"wallet": "d", "buy_usd": 500, "sell_usd": 1500, "avg_cost": 1.0, "profit": 1000, "transfer_in": True, "start": 1}]    # recibido por transferencia
        got = pumps.early_buyers(rows, 5.0, 400.0, 1e9)
        self.assertEqual([g["wallet"] for g in got], ["a"])
        self.assertEqual(got[0]["entry_mcap"], round(1.1 * 1e9))


class AuditTest(unittest.TestCase):
    def test_curve_impact_and_net(self):
        from radar import audit
        self.assertAlmostEqual(audit.curve_impact(27.96, 1.0), 1 / 30.0, places=2)   # inicio de la curva: v_sol = 30
        self.assertEqual(audit.curve_impact(900.0, 1.0), 0.0)                          # ya migrado
        self.assertEqual(audit.curve_impact(None, 1.0), 0.0)
        self.assertAlmostEqual(audit.net_return(1.0, None, entry_pen=0.0, exit_pen=0.0, fee=0.0), 0.0)
        self.assertEqual(audit.net_return(0.0), -1.0)                                  # sin stop: suelo -100 %
        self.assertLess(audit.net_return(2.0, 28.0), audit.net_return(2.0, 300.0))     # más caro entrar en la curva temprana

    def test_copiable_and_bags_and_trigger(self):
        from radar import audit
        now = 100 * 86400
        P = lambda ts, mult, hold, closed=True, last=None, proceeds=0.0: {"entry_ts": ts, "closed": closed, "mult": mult if closed else None, "cost": 1.0,
                                                                          "proceeds": proceeds, "hold": hold, "exit_ts": last, "bought": 1e6, "mint": "m%d" % ts}
        rows = audit.valued_positions([P(1, 2.0, 600), P(2, None, None, closed=False, last=2 * 86400, proceeds=0.4),
                                       P(3, None, None, closed=False, last=now - 3600, proceeds=0.0)], now)
        self.assertEqual(len(rows), 2)                     # la bolsa de hace una hora no se valora todavía
        self.assertTrue(rows[1]["stale"] and abs(rows[1]["mult"] - 0.4) < 1e-9)   # bolsa vieja: solo lo realizado
        kept, skipped = audit.copiable([{"hold": 10, "mult": 5}, {"hold": 45, "mult": 5}, {"hold": 120, "mult": 5}])
        self.assertEqual((len(kept), skipped), (2, 1))
        self.assertEqual(kept[0]["mult"], 1.0)             # 30-60 s: solo costes
        rr, how = audit.drop_trigger([{"mult": 1, "mint": "a"}, {"mult": 9, "mint": "b"}, {"mult": 2, "mint": "c"}])
        self.assertEqual([r["mint"] for r in rr], ["a", "c"])
        rr, how = audit.drop_trigger([{"mult": 1, "mint": "a"}, {"mult": 9, "mint": "b"}], ["a"])
        self.assertEqual([r["mint"] for r in rr], ["b"])

    def test_stats(self):
        from radar import audit
        self.assertAlmostEqual(audit.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertAlmostEqual(audit.spearman([1, 2, 3, 4], [40, 30, 20, 10]), -1.0)
        stats = {"a": (400, 1.0, 1.0), "b": (4, 3.0, 1.0), "c": (50, 0.0, 1.0), "d": (50, 0.2, 1.0)}
        shr, k, mu = audit.shrink(stats)
        self.assertLess(abs(shr["a"] - 1.0), abs(shr["b"] - 3.0))     # n alto: casi su propia media; n bajo: se encoge hacia la población
        self.assertLess(shr["b"], 3.0)
        rows = [{"ts": d * 86400 + 5} for d in range(30)]
        rs = [1.0] * 30
        self.assertEqual(audit.day_block_bootstrap(rows, rs), audit.day_block_bootstrap(rows, rs))   # determinista (semilla fija)
        self.assertAlmostEqual(audit.day_block_bootstrap(rows, rs), 1.0)
        self.assertAlmostEqual(audit.top_share([5, 3, 1, 1, -4], rows), 9 / 10)
        self.assertIsNone(audit.ex_top_fraction([1, 2]))

    def test_preserve(self):
        from radar import daily
        docs = {"A": {"addr": "A"}, "B": {"addr": "B", "cluster": {"id": "nuevo"}}}
        prev = {"A": {"cluster": {"id": "c1"}, "excluded": {"why": "x"}, "source_tag": "t"}, "B": {"cluster": {"id": "viejo"}}}
        daily.preserve(docs, prev)
        self.assertEqual(docs["A"]["cluster"]["id"], "c1")
        self.assertEqual(docs["A"]["excluded"]["why"], "x")
        self.assertEqual(docs["B"]["cluster"]["id"], "nuevo")   # lo que trae el documento nuevo manda


class EarlyStopTest(unittest.TestCase):
    def test_sniper_like(self):
        from radar import gmgnwallet
        rows = []
        for i in range(40):   # 40 tokens, compra y venta con 5 s de diferencia
            for ev, dt in (("buy", 0), ("sell", 5)):
                rows.append({"event_type": ev, "token": {"address": "M%d" % i}, "cost_usd": 100.0, "token_amount": 1000.0, "timestamp": 1000 + i * 100 + dt})
        self.assertTrue(gmgnwallet.sniper_like(rows))
        slow = [dict(r, timestamp=r["timestamp"] + (3600 if r["event_type"] == "sell" else 0)) for r in rows]
        self.assertFalse(gmgnwallet.sniper_like(slow))
        self.assertFalse(gmgnwallet.sniper_like(rows[:10]))   # pocas filas: no se corta


class PatientNetTest(unittest.TestCase):
    def test_retries_network_errors(self):
        from radar import discover
        import time as _t
        calls = {"n": 0}
        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise ConnectionRefusedError(111, "Connection refused")
            return "ok"
        orig = _t.sleep
        _t.sleep = lambda s_: None
        try:
            self.assertEqual(discover._patient(flaky, log=lambda m: None), "ok")
            self.assertEqual(calls["n"], 3)
            def dead():
                raise ConnectionRefusedError(111, "x")
            with self.assertRaises(ConnectionRefusedError):
                discover._patient(dead, log=lambda m: None, net_tries=2)
        finally:
            _t.sleep = orig
