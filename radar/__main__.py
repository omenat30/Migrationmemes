"""Línea de comandos:  python -m radar <run|record|backtest|serve|demo|check|calibrate|analyze|export>"""
import argparse
import json
import os
import random
import statistics
import sys
import threading
import time

from . import analysis
from .config import load_config
from .store import Store


def _store(cfg, path=None):
    return Store(path or cfg["db_path"])


def cmd_run(cfg, a):
    from .engine import Engine
    from .server import serve
    st = _store(cfg)
    if not cfg["keys"]["helius"]:
        print("Falta HELIUS_API_KEY (ver README, paso 2). El panel arrancará, pero sin ella no hay análisis.")
    eng = Engine(cfg, st)
    threading.Thread(target=serve, args=(st, cfg, "live"), daemon=True).start()
    eng.run_forever()


def cmd_serve(cfg, a):
    from .server import serve
    serve(_store(cfg), cfg, "live")


def cmd_demo(cfg, a):
    from .demo import populate
    from .server import serve
    path = "data/demo.sqlite"
    if os.path.exists(path):
        os.remove(path)
    st = _store(cfg, path)
    now = int(time.time())
    populate(st, cfg, random.Random(12), now)
    rep = analysis.build_report(st, cfg, now)
    st.set_meta("report", rep)
    from . import backtest
    from .demo import populate_recorder
    populate_recorder(st, cfg, random.Random(5), now - 6 * 86400)
    st.set_meta("bt_report", backtest.run(st, cfg, now))
    print("DATOS SINTÉTICOS. Veredicto del análisis sobre datos al azar:", rep["verdict"])
    serve(st, cfg, "demo")


def cmd_record(cfg, a):
    """Graba histórico (precio de cada token cerca de migrar, qué pasa al migrar, características). No puntúa ni avisa."""
    from .recorder import Recorder
    Recorder(cfg, _store(cfg)).run_forever()


def cmd_backtest(cfg, a):
    """Simula tu operación (100 USD, stop -60 %) sobre el histórico grabado. Reglas en HIPOTESIS_v4.md."""
    from . import backtest
    st = _store(cfg)
    rep = backtest.run(st, cfg, int(time.time()))
    st.set_meta("bt_report", rep)
    print(json.dumps(rep, indent=2, ensure_ascii=False, default=str))


def cmd_backfill(cfg, a):
    """Reconstruye desde la cadena migraciones recientes de pump.fun y las guarda (src=backfill). Ver HIPOTESIS_v5.md."""
    from . import history
    from .sources.dexscreener import DexScreener
    from .sources.helius import Helius
    from .sources.pumpfun import PumpFun
    from .util import RateLimiter
    st = _store(cfg)
    pf, h, lim = PumpFun(cfg, RateLimiter(6)), Helius(cfg, RateLimiter(cfg["helius_rps"])), RateLimiter(3)
    sol = DexScreener(cfg, lim).sol_usd()
    pick, ncand = history.pick_recent_migrations(pf, lambda m: history.dex_pair(m, lim), sol, a.hours, a.n * 3, seed=a.seed)
    # solo pools pequeños: los enormes no se pueden reconstruir hasta su inicio
    pick = [(c, d) for c, d in pick if (d.get("liq") or 0) < a.max_liq and (d.get("mcap") or 0) < a.max_liq * 25][: a.n]
    print(f"candidatos migrados en el listado: {ncand} · elegidos: {len(pick)}", flush=True)
    ok = 0
    for i, (c, d) in enumerate(pick, 1):
        t0 = time.time()
        try:
            curve, cm = history.reconstruct_curve(h, c["mint"], c["bonding_curve"], sol, cfg)
            pool, pm = history.pool_swaps(h, d["pool"], c["mint"], d["created"], d["created"] + 7200, sol, max_pages=a.pages)
        except Exception as e:
            print(f"[{i}/{len(pick)}] {c['symbol']}: error {str(e)[:80]}", flush=True)
            continue
        good = bool(pool) and pm["reached_start"] and bool(curve) and cm.get("trades", 0) >= 10
        print(f"[{i}/{len(pick)}] {c['symbol']:10} curva {cm.get('trades', 0):4} trades · pool {pm['points']:4} ops · "
              f"{'OK' if good else 'EXCLUIDO (' + ('pool no alcanzó el inicio' if not pm['reached_start'] else 'datos insuficientes') + ')'} · {time.time()-t0:.0f}s", flush=True)
        if not good:
            continue
        st.rec_add(c["mint"], c["bonding_curve"], c.get("creator"), c["name"], c["symbol"], int(c.get("created_ts") or 0), int(curve[0]["ts"]),
                   curve[0]["progress"], src="backfill", info={"url": d.get("url"), "pool": d["pool"], "liq_now": d.get("liq")})
        for p in curve:
            st.rec_point(c["mint"], p["ts"], p["progress"], p["price"], p["mcap"], p["vsol"], p["vtok"], None, "curve", sol)
        for p in pool:
            st.rec_point(c["mint"], p["ts"], 100.0, p["price"], p["mcap"], None, None, d.get("liq"), "amm", sol)
        st.rec_complete(c["mint"], int(d["created"]))
        ok += 1
    print(f"hecho: {ok} migraciones reales reconstruidas", flush=True)


def cmd_study(cfg, a):
    """Estudio A: entrar después de migrar (100 USD, stop -60 %, objetivo x3). Ver HIPOTESIS_v5.md."""
    from . import study
    st = _store(cfg)
    rep = study.run(st, cfg, int(time.time()), a.src)
    st.set_meta("study_post", rep)
    print(json.dumps(rep, indent=2, ensure_ascii=False, default=str))


def cmd_wallets(cfg, a):
    """Cribado de wallets: ¿quién gana de verdad y quién gana vendiéndote a ti? Ver HIPOTESIS_v6.md."""
    from . import wallets
    from .sources.helius import Helius
    from .util import RateLimiter
    st = _store(cfg)
    rep = wallets.run(st, Helius(cfg, RateLimiter(cfg["helius_rps"])), cfg, int(time.time()), a.min_buy, log=lambda m: print(m, flush=True))
    st.set_meta("wallet_report", rep)
    print(json.dumps(rep, indent=2, ensure_ascii=False, default=str))


def cmd_judge(cfg, a):
    """Juzga wallets que TÚ eliges (de GMGN, Axiom...). Lee un archivo con una dirección por línea. Ver HIPOTESIS_v6.md."""
    import re
    from . import wallets
    from .sources.helius import Helius
    from .util import RateLimiter
    addrs = []
    with open(a.file, encoding="utf-8") as f:
        for line in f:
            w = line.split("#")[0].strip().split()[0] if line.split("#")[0].strip() else ""
            if re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", w) and w not in addrs:
                addrs.append(w)
    print(f"{len(addrs)} direcciones válidas", flush=True)
    st = _store(cfg)
    scr = wallets.screen(st, Helius(cfg, RateLimiter(cfg["helius_rps"])), cfg, addrs, int(time.time()), workers=2,
                         log=lambda m: print(m, flush=True))
    rows = []
    for w in addrs:
        v = scr.get(w)
        if not v:
            print(f"{w[:8]}…  sin datos (límite de Helius: repite el comando)")
            continue
        x = v["summary"]
        rows.append((v["class"], w, x))
        fmt = lambda t, d=1: "—" if t is None else f"{t:.{d}f}"
        print(f"{v['class']:13} {w}  cerradas {x['closed']:3} · ganancia {fmt(x['pnl_sol'])} SOL (sin sus 2 mejores: {fmt(x.get('pnl_ex_top2'))}) · "
              f"aciertos {fmt((x['win_rate'] or 0) * 100, 0)}% · tenencia mediana {fmt((x['median_hold_s'] or 0) / 60, 0)} min · salidas <2 min {fmt((x['quick_exit_ratio'] or 0) * 100, 0)}%")
    print("\nLeyenda: CANDIDATA = gana, aguanta y no sale corriendo; EXTRACTORA = cierra casi todo en <2 min; BOT = >300 operaciones/día.")
    print("Una CANDIDATA no es «de fiar»: son solo sus últimas 100 transacciones. Contrástala con su PnL a 30 días en tu plataforma.")


def cmd_analyze(cfg, a):
    st = _store(cfg)
    rep = analysis.build_report(st, cfg, int(time.time()))
    st.set_meta("report", rep)
    print(json.dumps(rep, indent=2, ensure_ascii=False, default=str))


def cmd_export(cfg, a):
    from .state import build_state
    st = _store(cfg, a.db)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(build_state(st, cfg, mode="demo" if a.db and "demo" in a.db else "live"), f, ensure_ascii=False)
    print("escrito", a.out)


def _row(name, ok, note):
    print(f"[{'OK ' if ok else 'FALLA'}] {name}: {note}")
    return ok


def cmd_check(cfg, a):
    """Prueba cada fuente y la FORMA de sus datos. No envía correos."""
    from .sources.dexscreener import DexScreener
    from .sources.helius import Helius
    from .sources.pumpfun import PumpFun
    from .util import RateLimiter, redact
    pump, dex = PumpFun(cfg, RateLimiter(5)), DexScreener(cfg, RateLimiter(3))
    hel = Helius(cfg, RateLimiter(3))
    coins = []
    t = time.time()
    try:
        sol = dex.sol_usd()
        _row("DexScreener (precio SOL)", bool(sol), f"{sol} USD")
    except Exception as e:
        sol = None
        _row("DexScreener", False, redact(e))
    try:
        coins = pump.list_live(sol)
        need = ("mint", "mcap_usd", "real_sol", "virtual_sol", "virtual_tokens", "creator", "bonding_curve")
        miss = [k for k in need if coins[0].get(k) is None] if coins else list(need)
        _row("pump.fun lista", bool(coins) and not miss, f"{len(coins)} tokens en {time.time()-t:.1f}s; campos que faltan: {miss or 'ninguno'}")
    except Exception as e:
        _row("pump.fun lista", False, redact(e))
    if coins:
        c = coins[0]
        try:
            tr = pump.trades(c["mint"], max_pages=1)
            miss = [k for k in ("wallet", "ts", "sol", "slot") if tr and not tr[0].get(k)]
            _row("pump.fun trades", bool(tr) and not miss, f"{len(tr)} trades; campos que faltan: {miss or 'ninguno'}")
        except Exception as e:
            _row("pump.fun trades", False, redact(e))
        try:
            cc = pump.creator_coins(c["creator"], sol)
            _row("pump.fun monedas del creador", True, f"{len(cc)} monedas; con ath_mcap: {sum(1 for x in cc if x['ath_mcap'])}")
        except Exception as e:
            _row("pump.fun monedas del creador", False, redact(e))
    from .sources.gmgn import Gmgn, GmgnError, GmgnRateLimited
    gm = Gmgn(cfg)
    if not gm.available:
        print("[ -- ] GMGN sin clave (GMGN_API_KEY en .env): se usará Helius")
    elif coins:
        c = coins[0]
        try:
            sec = gm.security(c["mint"])
            miss = [k for k in ("renounced_mint", "renounced_freeze", "top10_rate", "rug_ratio") if sec.get(k) is None]
            _row("GMGN seguridad", not miss, f"campos que faltan: {miss or 'ninguno'}")
            inf = gm.info(c["mint"])
            miss = [k for k in ("progress", "total_supply", "smart_wallets", "creator") if inf.get(k) is None]
            _row("GMGN info", not miss, f"progreso {inf.get('progress')}; campos que faltan: {miss or 'ninguno'}")
            hl = gm.holders(c["mint"])
            ex = [h for h in hl if h["excluded"]]
            with_f = [h for h in hl if h["funder"]]
            _row("GMGN holders", bool(hl), f"{len(hl)} holders ({len(ex)} curva/pool), {len(with_f)} con fondeador conocido")
            if hl:
                rows = gm.activity(next(h["owner"] for h in hl if not h["excluded"]))
                from . import wallet_history as wh
                p = wh.parse_gmgn_activity("x", rows)
                _row("GMGN actividad de wallet", p["n_trades"] > 0, f"{len(rows)} filas, {p['n_trades']} operaciones reconocidas (0 → formato distinto)")
            cr = c.get("creator")
            if cr:
                cc = gm.created_tokens(cr)
                _row("GMGN monedas del creador", True, f"{len(cc)} monedas; con ath: {sum(1 for x in cc if x['ath_mcap'])}")
        except GmgnRateLimited as e:
            _row("GMGN", False, f"límite de uso: {e}")
        except GmgnError as e:
            _row("GMGN", False, str(e))
    if not hel.available:
        print("[ -- ] Helius sin clave: opcional si GMGN funciona (se usa solo para contrastar mint/freeze)")
    elif coins:
        c = coins[0]
        try:
            mi = hel.mint_info(c["mint"])
            _row("Helius mint", mi is not None, str(mi))
            hs, _exc = hel.holders(c["mint"], {c.get("bonding_curve"), c.get("pool")} - {None})
            _row("Helius holders", bool(hs), f"{len(hs)} holders")
            if hs:
                from . import wallet_history as wh
                txs = hel.wallet_txs(hs[0]["owner"])
                p = wh.parse_wallet_txs(hs[0]["owner"], txs)
                _row("Helius historial de wallet", p["n_trades"] > 0,
                     f"{p['n_txs']} txs, {p['n_trades']} swaps reconocidos (0 → el formato no coincide; revisa wallet_history.py)")
        except Exception as e:
            _row("Helius", False, redact(e))
    if cfg["email"]["enabled"]:
        import smtplib
        import ssl
        try:
            with smtplib.SMTP_SSL(cfg["email"]["smtp_host"], cfg["email"]["smtp_port"], context=ssl.create_default_context(), timeout=15) as s:
                s.login(cfg["keys"]["smtp_user"], cfg["keys"]["smtp_password"])
            _row("Correo (solo inicio de sesión, no se envía nada)", True, "credenciales válidas")
        except Exception as e:
            _row("Correo", False, redact(e))
    else:
        print("[ -- ] Correo desactivado (email.enabled=false en config.json)")


def cmd_calibrate(cfg, a):
    """Mide cuántos SOL tenía la curva al completarse en tokens ya migrados."""
    from .sources.pumpfun import PumpFun
    from .util import RateLimiter
    cfg["endpoints"]["pumpfun_list_path"] = cfg["endpoints"]["pumpfun_list_path"].replace("complete=false", "complete=true")
    coins = PumpFun(cfg, RateLimiter(5)).list_live()
    vals = [c["real_sol"] for c in coins if c.get("real_sol")]
    if not vals:
        print("No se pudo medir (¿ruta de la API distinta? ver `check`).")
        return
    print(f"{len(vals)} tokens migrados. SOL reales en la curva al migrar: mín {min(vals):.1f} · mediana {statistics.median(vals):.1f} · máx {max(vals):.1f}")
    print(f'Pon en config.json:  "curve_target_sol": {round(statistics.median(vals), 1)}')


def main():
    ap = argparse.ArgumentParser(prog="radar")
    ap.add_argument("--config", default="config.json")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("run", "serve", "demo", "check", "calibrate", "analyze", "record", "backtest"):
        sub.add_parser(n)
    wl = sub.add_parser("wallets")
    wl.add_argument("--min-buy", type=float, default=1.0)
    jd = sub.add_parser("judge")
    jd.add_argument("file")
    sd = sub.add_parser("study")
    sd.add_argument("--src", default=None)
    bf = sub.add_parser("backfill")
    bf.add_argument("--n", type=int, default=25)
    bf.add_argument("--hours", type=float, default=3.0)
    bf.add_argument("--seed", type=int, default=7)
    bf.add_argument("--max-liq", type=float, default=150000)
    bf.add_argument("--pages", type=int, default=3)
    ex = sub.add_parser("export")
    ex.add_argument("out")
    ex.add_argument("--db", default=None)
    a = ap.parse_args()
    cfg = load_config(a.config)
    {"run": cmd_run, "serve": cmd_serve, "demo": cmd_demo, "check": cmd_check, "calibrate": cmd_calibrate,
     "analyze": cmd_analyze, "export": cmd_export, "record": cmd_record, "backtest": cmd_backtest, "backfill": cmd_backfill, "study": cmd_study, "wallets": cmd_wallets, "judge": cmd_judge}[a.cmd](cfg, a)


if __name__ == "__main__":
    sys.exit(main())
