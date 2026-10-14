"""Bucle de detección: lista tokens, puntúa, avisa y mide. No opera nunca."""
import datetime
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import alerts as alerts_mod
from . import evaluate, wallet_history
from .sources.curve_trades import CurveTrades
from .sources.dexscreener import DexScreener
from .sources.gmgn import Gmgn, GmgnError, GmgnRateLimited
from .sources.helius import Helius
from .sources.pumpfun import PumpFun
from .util import RateLimiter, redact
from .variants import load_variants, passes


class Engine:
    def __init__(self, cfg, store, pump=None, helius=None, dex=None, log=print, rng=None, gmgn=None):
        self.cfg, self.store, self.log = cfg, store, log
        self.pump = pump or PumpFun(cfg, RateLimiter(8))
        self.helius = helius or Helius(cfg, RateLimiter(cfg["helius_rps"]))
        self.dex = dex or DexScreener(cfg, RateLimiter(4))
        self.gmgn = gmgn or Gmgn(cfg)
        self.curve_trades = CurveTrades(self.helius, store, cfg)
        self.rng = rng or random.Random()
        variants = {v["id"]: v for v in load_variants()}
        self.alert_variant = variants[cfg["alert_variant"]]
        self.errors = []

    # ---------- utilidades
    def err(self, msg):
        msg = redact(msg)
        self.errors = (self.errors + [{"ts": int(time.time()), "msg": msg}])[-20:]
        self.store.set_meta("errors", self.errors)
        self.log("! " + msg)

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

    def price_sample(self, mint, now, curve=None):
        """Precio de un token. Antes de migrar se lee la cuenta de la curva EN LA CADENA (verificado contra
        la API de pump.fun); pump.fun no ofrece consulta por dirección. Tras migrar, DexScreener."""
        sol = self.sol_usd(now)
        if curve and self.helius.available and sol:
            try:
                st = self.helius.curve_state(curve)
            except Exception:
                st = None
            if st and st["standard"] and not st["complete"] and st["vtok"] > 0:
                price = st["vsol"] / st["vtok"] * sol
                return {"ts": now, "price": price, "mcap": price * st["supply"], "vsol": st["vsol"],
                        "vtok": st["vtok"], "liq": None, "complete": False, "sol_usd": sol}
        try:
            d = self.dex.best_pair(mint)
        except Exception:
            d = None
        if d and d["price"]:
            return {"ts": now, "price": d["price"], "mcap": d["mcap"], "vsol": None, "vtok": None,
                    "liq": d["liq"], "complete": True, "sol_usd": sol}
        return None

    # ---------- consultas en paralelo (el cuello de botella eran las wallets, una a una)
    def _fetch_parallel(self, items, fn):
        """Ejecuta fn(item) en paralelo. Devuelve ({item: resultado}, primera_excepción_de_límite_o_None)."""
        out, limit_exc = {}, None
        if not items:
            return out, None
        with ThreadPoolExecutor(max_workers=max(1, self.cfg["wallets"]["parallel"])) as ex:
            futs = {ex.submit(fn, it): it for it in items}
            for f in as_completed(futs):
                it = futs[f]
                try:
                    out[it] = f.result()
                except GmgnRateLimited as e:
                    limit_exc = limit_exc or e
                except Exception as e:
                    self.err(f"wallet {str(it)[:6]}…: {e}")
        return out, limit_exc

    # ---------- análisis profundo de un token
    def deep(self, coin, now):
        """Descarga todo lo necesario y puntúa. GMGN si hay clave (una llamada de holders trae el fondeador de cada
        wallet); si no, Helius. Los trades vienen de Helius (el endpoint de pump.fun está roto)."""
        trades = self.trades_for(coin, now)
        if self.gmgn.available:
            return self.deep_gmgn(coin, trades, now)
        if self.helius.available:
            return self.deep_helius(coin, trades, now)
        return None

    def trades_for(self, coin, now):
        """Trades de la curva. Helius (verificado) si hay clave; pump.fun solo como último recurso,
        porque su endpoint de trades devuelve 400 desde el 14 oct 2026 (ver README)."""
        if self.helius.available and coin.get("bonding_curve"):
            trades, meta = self.curve_trades.refresh(coin["mint"], coin["bonding_curve"], now)
            if meta["capped"]:
                self.log(f"  {coin.get('symbol')}: tope de {self.curve_trades.budget} transacciones; cobertura parcial")
            return trades
        return self.pump.trades(coin["mint"])

    def deep_gmgn(self, coin, trades, now):
        cfg, mint = self.cfg, coin["mint"]
        sec = self.gmgn.security(mint)
        info = self.gmgn.info(mint)
        hl = self.gmgn.holders(mint)
        supply = info.get("total_supply") or cfg["total_supply"]
        holders = sorted(({"owner": h["owner"], "amount": h["pct"] * supply} for h in hl
                          if not h["excluded"] and h["pct"] > 0), key=lambda h: -h["amount"])
        excluded = sum(h["pct"] for h in hl if h["excluded"]) * supply
        if sec["renounced_mint"] is None or sec["renounced_freeze"] is None:
            minfo = None  # sin dato no se asume renunciado: la seguridad lo trata como no verificable
        else:
            minfo = {"mint_authority": None if sec["renounced_mint"] else "no renunciada (GMGN)",
                     "freeze_authority": None if sec["renounced_freeze"] else "no renunciada (GMGN)",
                     "supply": supply}
        if self.helius.available:  # contraste on-chain: si Helius ve una autoridad, manda Helius
            try:
                hm = self.helius.mint_info(mint)
                if hm and (hm["mint_authority"] or hm["freeze_authority"]):
                    minfo = hm
            except Exception as e:
                self.err(f"Helius mint {coin.get('symbol')}: {e}")
        creator = coin.get("creator") or info.get("creator")
        try:
            ccoins = self.gmgn.created_tokens(creator) if creator else None
        except GmgnRateLimited:
            raise
        except GmgnError as e:
            self.err(f"GMGN monedas del creador {coin.get('symbol')}: {e}")
            ccoins = None
        wallets = evaluate.select_wallets(trades, holders, cfg)
        hmap = {h["owner"]: h for h in hl}
        sol = coin.get("sol_usd") or 150.0
        wd, todo = {}, []
        for w in wallets:
            cached = self.store.get_wallet("g:" + w, cfg["wallets"]["wallet_cache_s"], now)
            if cached is not None:
                wd[w] = cached
            else:
                todo.append(w)

        def funder_of(w):
            h = hmap.get(w)
            # un fondeador con nombre es un exchange o protocolo: no cuenta como misma entidad
            return (h["funder"] if h and not h["funder_label"] else None), (h["funder_ts"] if h else None)

        def fetch(w):
            f, ts = funder_of(w)
            parsed = wallet_history.parse_gmgn_activity(w, self.gmgn.activity(w), f, ts, sol)
            return {"parsed": parsed, "summary": wallet_history.summarize(parsed, cfg)}

        budget = cfg["gmgn"]["history_wallets"]
        got, limit_exc = self._fetch_parallel(todo[:budget], fetch)
        for w, c in got.items():
            self.store.put_wallet("g:" + w, c, now)
            wd[w] = c
        if limit_exc:
            raise limit_exc
        for w in todo:
            if w not in wd:  # sin historial este ciclo: solo el fondeador, sin guardar en caché
                f, ts = funder_of(w)
                parsed = wallet_history.parse_gmgn_activity(w, [], f, ts, sol)
                wd[w] = {"parsed": parsed, "summary": wallet_history.summarize(parsed, cfg)}
        tags = lambda t: sum(1 for h in hl if t in h["tags"] or t in h["maker_tags"])
        extras = {"data_source": "gmgn", "smart_wallets": info["smart_wallets"], "renowned_wallets": info["renowned_wallets"],
                  "sniper_wallets": info["sniper_wallets"], "bundler_wallets": info["bundler_wallets"],
                  "rat_trader_wallets": info["rat_trader_wallets"], "bot_degen_rate": info["bot_degen_rate"],
                  "fresh_wallet_rate": info["fresh_wallet_rate"], "rug_ratio": sec["rug_ratio"],
                  "bundler_rate": sec["bundler_rate"], "rat_rate": sec["rat_rate"],
                  "insider_hold_rate": sec["insider_hold_rate"], "top10_rate_gmgn": sec["top10_rate"],
                  "smart_in_holders": tags("smart_degen"), "bundler_in_holders": tags("bundler"),
                  "creator_status": sec["creator_status"], "burn_status": sec["burn_status"]}
        return evaluate.evaluate_token(coin, trades, holders, minfo, ccoins, wd, cfg, now, excluded, extras)

    def deep_helius(self, coin, trades, now):
        mint, cfg = coin["mint"], self.cfg
        exclude = {x for x in (coin.get("bonding_curve"), coin.get("pool")) if x}
        holders, excluded = self.helius.holders(mint, exclude)
        minfo = self.helius.mint_info(mint)
        try:
            ccoins = self.pump.creator_coins(coin["creator"], coin.get("sol_usd")) if coin.get("creator") else None
        except Exception as e:
            self.err(f"monedas del creador {coin.get('symbol')}: {e}")
            ccoins = None
        wallets = evaluate.select_wallets(trades, holders, cfg)
        wd, todo = {}, []
        for w in wallets:
            cached = self.store.get_wallet(w, cfg["wallets"]["wallet_cache_s"], now)
            if cached is not None:
                wd[w] = cached
            else:
                todo.append(w)

        def fetch(w):
            txs = self.helius.wallet_txs(w)
            parsed = wallet_history.parse_wallet_txs(w, txs, 100, cfg["wallets"]["min_fund_sol"])
            return {"parsed": parsed, "summary": wallet_history.summarize(parsed, cfg)}

        got, _ = self._fetch_parallel(todo, fetch)
        for w, c in got.items():
            self.store.put_wallet(w, c, now)
            wd[w] = c
        return evaluate.evaluate_token(coin, trades, holders, minfo, ccoins, wd, cfg, now, excluded,
                                       {"data_source": "helius"})

    # ---------- un ciclo
    def cycle(self, now=None):
        t0 = time.time()
        now = int(now or t0)
        cfg, st = self.cfg, self.store
        if not (self.gmgn.available or self.helius.available):
            self.err("sin fuente de holders: falta GMGN_API_KEY o HELIUS_API_KEY (o GMGN está en pausa por límite de uso)")
            return
        sol = self.sol_usd(now)
        try:
            coins = self.pump.list_live(sol)
        except Exception as e:
            self.err(f"lista pump.fun: {e}")
            return
        g = cfg["gates"]
        eligible, other_quote = [], 0
        for c in coins:
            p = evaluate.curve_progress(c, cfg)
            if c["mcap_usd"] >= g["min_mcap_usd"] and g["min_curve_pct"] <= p < g["max_curve_pct"]:
                if not c.get("sol_quote"):
                    other_quote += 1  # fuera de alcance: no cotiza en SOL, no se puede fijar precio ni deslizamiento
                    continue
                eligible.append(c)
        due = [c for c in eligible if now - st.last_eval_ts(c["mint"]) >= cfg["deep_cache_seconds"]]
        # primero los más avanzados en la curva: son los que están a punto de migrar y los que importan
        due.sort(key=lambda c: -evaluate.curve_progress(c, cfg))
        done = attempted = 0
        for c in due[: cfg["max_deep_per_cycle"]]:
            if attempted and time.time() - t0 > cfg["cycle_budget_s"]:
                break  # no empezar otro token si ya pasamos del presupuesto de tiempo
            attempted += 1
            try:
                res = self.deep(c, now)
            except GmgnRateLimited as e:
                self.err(f"GMGN límite de uso, pausa hasta {e.reset_at and time.strftime('%H:%M:%S', time.localtime(e.reset_at))}: {e}")
                self.store.set_meta("gmgn_blocked_until", e.reset_at)
                break
            except Exception as e:
                self.err(f"análisis {c.get('symbol')}: {e}")
                continue
            if res is None:
                continue
            done += 1
            st.add_observation(res)
            st.set_latest(res, c["name"], c["symbol"])
            self.after_eval(c, res, now)
        self.maybe_control(eligible, now)
        st.set_meta("last_cycle", {"ts": now, "listed": len(coins), "eligible": len(eligible), "evaluated": done,
                                   "pending": max(0, len(due) - attempted), "other_quote": other_quote,
                                   "secs": round(time.time() - t0, 1)})
        self.record_usage(now)

    def record_usage(self, now):
        """Suma el consumo de llamadas a Helius por día (para vigilar el gasto del plan)."""
        u = self.helius.take_usage() if hasattr(self.helius, "take_usage") else {}
        if not u:
            return
        day = datetime.datetime.fromtimestamp(now, datetime.timezone.utc).strftime("%Y-%m-%d")
        log = self.store.get_meta("usage", {})
        d = log.setdefault(day, {})
        for k, v in u.items():
            d[k] = d.get(k, 0) + v
        for old in sorted(log)[:-7]:
            del log[old]
        self.store.set_meta("usage", log)

    def after_eval(self, coin, res, now):
        cfg, st = self.cfg, self.store
        mint = coin["mint"]
        tail = cfg["series"]["tail_s"]
        if res["score"] >= cfg["track_score"] and not res["discarded"]:
            if st.get_tracked(mint) is None:
                st.track(mint, "candidate", now, now + tail, res["mcap"], coin["name"], coin["symbol"], coin.get("bonding_curve"))
            else:
                st.extend_tracking(mint, now + tail)
            s = self.price_sample(mint, now, coin.get("bonding_curve"))
            if s:
                st.add_sample(mint, s)
        if passes(self.alert_variant, res["features"]) and not st.has_alert(mint):
            reason = alerts_mod.explain(res, coin["name"], coin["symbol"])
            if st.add_alert(res, coin["name"], coin["symbol"], reason):
                ok, note = alerts_mod.send_email(res, coin["name"], coin["symbol"], cfg)
                st.mark_emailed(mint, ok, note)
                self.log(f"ALERTA {coin['symbol']} score {res['score']} · correo: {note}")

    def maybe_control(self, eligible, now):
        """Un control cada 3600/control_per_hour s: token elegible al azar que no es candidato
        (pasa las mismas puertas de capitalización y curva, sin importar su puntuación)."""
        cfg, st = self.cfg, self.store
        last = st.get_meta("last_control", 0)
        if now - last < 3600 / max(cfg["control_per_hour"], 1):
            return
        pool = [c for c in eligible if st.get_tracked(c["mint"]) is None]
        if not pool:
            return
        c = self.rng.choice(pool)
        s = self.price_sample(c["mint"], now, c.get("bonding_curve"))
        if not s:
            return
        st.track(c["mint"], "control", now, now + cfg["series"]["tail_s"], c["mcap_usd"], c["name"], c["symbol"],
                 c.get("bonding_curve"))
        st.add_sample(c["mint"], s)
        st.set_meta("last_control", now)

    def sample_due(self, now):
        sc = self.cfg["series"]
        fails = 0
        for t in self.store.due_tracked(now):
            s = self.price_sample(t["mint"], now, t["curve"])
            if s:
                self.store.add_sample(t["mint"], s)
                every = sc["fast_every_s"] if now - t["start_ts"] < sc["fast_until_s"] else sc["slow_every_s"]
            else:
                fails += 1
                every = sc["fast_every_s"] * 2
            self.store.set_next(t["mint"], now + every)
        if fails:
            self.store.set_meta("sample_fails", {"ts": now, "n": fails})

    # ---------- bucles
    def _sampler_loop(self, stop):
        """Muestrea precios en un hilo propio: un ciclo de análisis lento no debe retrasar las mediciones."""
        store = self.store.clone()
        s = Engine(self.cfg, store, pump=self.pump, helius=self.helius, dex=self.dex, log=self.log,
                   rng=self.rng, gmgn=self.gmgn)
        while not stop.is_set():
            try:
                s.sample_due(int(time.time()))
            except Exception as e:
                s.err(f"muestreo: {type(e).__name__}: {e}")
            stop.wait(5)

    def run_forever(self):
        self.log("Radar en marcha. Solo avisa; no opera. Ctrl+C para parar.")
        stop = threading.Event()
        threading.Thread(target=self._sampler_loop, args=(stop,), daemon=True).start()
        last_report = 0
        try:
            while True:
                t0 = time.time()
                try:
                    self.cycle()
                    if t0 - last_report > 1800:
                        from .analysis import build_report
                        self.store.set_meta("report", build_report(self.store, self.cfg, int(t0)))
                        last_report = t0
                except Exception as e:  # nunca morir por un fallo de red
                    self.err(f"ciclo: {type(e).__name__}: {e}")
                time.sleep(max(1, self.cfg["poll_seconds"] - (time.time() - t0)))
        finally:
            stop.set()
