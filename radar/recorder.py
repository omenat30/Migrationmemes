"""Grabador de histórico: construye el dataset que no existe.

pump.fun solo deja ver los ~1.000 tokens más recientes y no ofrece velas, así que el histórico se GRABA:
  - cada `poll_s` segundos, el precio y el avance de cada token en la zona final de la curva (>= min_progress),
  - el momento exacto en que completa la curva (migra) y, después, su precio y liquidez en el pool,
  - al cruzar `feat_progress`, características baratas del token (concentración, creador, volumen de compra).
Las rutas de precio salen del propio listado de pump.fun (sin llamadas extra por token). Solo se llama a
Helius al cruzar el umbral de características, o para tokens que dejan de aparecer en el listado.

No puntúa, no avisa, no opera. Solo graba para que `backtest` juzgue sin mirar el futuro.
"""
import time

from . import evaluate, manipulation
from .sources.curve_trades import CurveTrades
from .sources.dexscreener import DexScreener
from .sources.helius import Helius
from .sources.pumpfun import PumpFun
from .util import RateLimiter, redact


class Recorder:
    def __init__(self, cfg, store, pump=None, helius=None, dex=None, log=print):
        self.cfg, self.store, self.log = cfg, store, log
        self.r = cfg["recorder"]
        self.pump = pump or PumpFun(cfg, RateLimiter(8))
        self.helius = helius or Helius(cfg, RateLimiter(cfg["helius_rps"]))
        self.dex = dex or DexScreener(cfg, RateLimiter(4))
        self.trades = CurveTrades(self.helius, store, cfg)
        self.last_dex = {}
        self.errors = 0

    def err(self, msg):
        self.errors += 1
        self.log("! " + redact(msg))

    def sol_usd(self, now):
        c = self.store.get_meta("sol_usd")
        if c and now - c["ts"] < 300:
            return c["v"]
        try:
            v = self.dex.sol_usd()
            if v:
                self.store.set_meta("sol_usd", {"ts": now, "v": v})
                return v
        except Exception as e:
            self.err(f"precio SOL: {e}")
        return c["v"] if c else None

    # ---------- un paso
    def step(self, now=None):
        now = int(now or time.time())
        sol = self.sol_usd(now)
        if not sol:
            return {"error": "sin precio del SOL"}
        seen, new, completed = set(), 0, 0
        for page in range(self.r["pages"]):
            try:
                coins = self.pump.list_live(sol, offset=50 * page)
            except Exception as e:
                self.err(f"listado página {page}: {e}")
                break
            if not coins:
                break
            for c in coins:
                if not c.get("sol_quote"):
                    continue  # otra moneda de cotización: fuera de alcance
                known = self.store.rec_get(c["mint"])
                prog = evaluate.curve_progress(c, self.cfg)
                if c.get("complete") or c.get("pool"):
                    if known and not known["completed_ts"]:
                        self.store.rec_complete(c["mint"], now)
                        completed += 1
                    seen.add(c["mint"])
                    continue
                if prog < self.r["min_progress"] and not known:
                    continue
                if not known:
                    self.store.rec_add(c["mint"], c.get("bonding_curve"), c.get("creator"), c["name"], c["symbol"],
                                       int(c.get("created_ts") or 0), now, prog)
                    new += 1
                seen.add(c["mint"])
                self.store.rec_point(c["mint"], now, prog, c["price_usd"], c["mcap_usd"], c.get("virtual_sol"),
                                     c.get("virtual_tokens"), None, "curve", sol)
                self.maybe_features(c, prog, now)
        completed += self.chain_checks(seen, now, sol)
        self.post_migration(now, sol)
        return {"new": new, "completed": completed, "seen": len(seen)}

    def chain_checks(self, seen, now, sol):
        """Tokens grabados que dejaron de aparecer en el listado: se lee su curva en la cadena."""
        n_done, budget = 0, self.r["chain_checks_per_step"]
        if not self.helius.available:
            return 0
        for t in self.store.rec_active(now, 0, self.r["stale_s"]):
            if t["mint"] in seen or not t["curve"] or budget <= 0 or now - t["last_ts"] < 30:
                continue
            budget -= 1
            try:
                st = self.helius.curve_state(t["curve"])
            except Exception as e:
                self.err(f"curva {t['symbol']}: {e}")
                continue
            if not st:
                continue
            if st["complete"]:
                self.store.rec_complete(t["mint"], now)
                n_done += 1
            elif st["standard"] and st["vtok"] > 0:
                price = st["vsol"] / st["vtok"] * sol
                prog = max(0.0, min(100.0, (1 - st["rtok"] / self.cfg["curve_tokens_initial"]) * 100))
                self.store.rec_point(t["mint"], now, prog, price, price * st["supply"], st["vsol"], st["vtok"], None, "curve", sol)
        return n_done

    def post_migration(self, now, sol):
        """Tras migrar: precio y liquidez en el pool (DexScreener), para saber qué pasó después."""
        for t in self.store.rec_active(now, self.r["post_s"], 0):
            if not t["completed_ts"] or now - self.last_dex.get(t["mint"], 0) < self.r["dex_every_s"]:
                continue
            self.last_dex[t["mint"]] = now
            try:
                d = self.dex.best_pair(t["mint"])
            except Exception as e:
                self.err(f"Dex {t['symbol']}: {e}")
                continue
            if d and d["price"]:
                self.store.rec_point(t["mint"], now, 100.0, d["price"], d["mcap"], None, None, d["liq"], "amm", sol)

    # ---------- características baratas al cruzar el umbral
    def maybe_features(self, coin, prog, now):
        t = self.store.rec_get(coin["mint"])
        if prog < self.r["feat_progress"] or (t and t["feat_ts"]):
            return
        feat = {"progress": round(prog, 2), "mcap": coin["mcap_usd"], "age_s": now - int(coin.get("created_ts") or now)}
        # concentración de holders (top 10 sobre el circulante)
        try:
            holders, excluded = self.helius.holders(coin["mint"], {x for x in (coin.get("bonding_curve"), coin.get("pool")) if x})
            supply = self.cfg["total_supply"]
            circ = max(supply - excluded, sum(h["amount"] for h in holders))
            feat["top10_pct"] = round(sum(h["amount"] for h in holders[:10]) / circ * 100, 2) if circ else None
        except Exception as e:
            feat["top10_pct"] = None
            self.err(f"holders {coin['symbol']}: {e}")
        # creador: tokens previos que llegaron alto y se hundieron
        try:
            from . import security
            cc = self.pump.creator_coins(coin["creator"], coin.get("sol_usd")) if coin.get("creator") else None
            feat["creator_rugs"] = security.count_prev_rugs(cc, self.cfg["security"], coin["mint"])[0] if cc is not None else None
            feat["creator_coins"] = len(cc) if cc is not None else None
        except Exception as e:
            feat["creator_rugs"] = None
            self.err(f"creador {coin['symbol']}: {e}")
        # volumen de compra y wash, con trades reconstruidos de Helius
        try:
            trades, meta = self.trades.refresh(coin["mint"], coin["bonding_curve"], now)
            v = evaluate.score_volume(trades, now, self.cfg)["metrics"]
            feat.update({"buyers5": v["unique_buyers"], "ratio": v["ratio"], "vol5_sol": v["vol_sol"], "covered": v["covered"]})
            feat["wash_share"] = round(max(manipulation.wash_stats(trades, {}, self.cfg)["wash_share"], 0), 3)
        except Exception as e:
            feat.update({"buyers5": None, "ratio": None, "wash_share": None})
            self.err(f"trades {coin['symbol']}: {e}")
        self.store.rec_set_feat(coin["mint"], feat, now)

    def run_forever(self, stop=None):
        self.log("Grabador en marcha (solo registra). Ctrl+C para parar.")
        while not (stop and stop.is_set()):
            t0 = time.time()
            try:
                r = self.step()
                self.store.set_meta("rec_last", {"ts": int(t0), **r, "secs": round(time.time() - t0, 1)})
            except Exception as e:
                self.err(f"paso: {type(e).__name__}: {e}")
            time.sleep(max(1, self.r["poll_s"] - (time.time() - t0)))
