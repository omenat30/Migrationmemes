"""Estado JSON que consume el panel."""
import time

from . import analysis, study

KEEP = ("mint", "name", "symbol", "ts", "progress", "mcap", "price", "score", "raw_score", "discarded",
        "reasons", "criteria", "security", "features", "extras")


def history_rows(store, cfg, now, limit=60):
    """Migraciones REALES (grabadas en vivo o reconstruidas de la cadena), una fila por token, con enlaces para verificar."""
    rows = []
    for t in store.rec_all():
        if not t.get("completed_ts"):
            continue
        path = store.rec_path_of(t["mint"])
        curve = [p for p in path if p["phase"] == "curve"]
        amm = [p for p in path if p["phase"] == "amm"]
        c93 = next((p for p in curve if p["progress"] >= 93), None)
        c90 = next((p for p in curve if p["progress"] >= 90), None)
        last_curve = curve[-1] if curve else None
        mig = t["completed_ts"]
        sim = study.simulate_post(t, path, 60, "R1", cfg, now) if amm else None
        first_pool = next((p for p in amm if p["ts"] >= mig + 60), None)
        peak = None
        if first_pool:
            win = [p["price"] for p in amm if first_pool["ts"] <= p["ts"] <= first_pool["ts"] + 7200]
            peak = max(win) / first_pool["price"] if win else None
        info = {}
        if t.get("info"):
            import json
            info = json.loads(t["info"])
        rows.append({
            "mint": t["mint"], "symbol": t["symbol"], "name": t["name"], "src": t.get("src") or "live", "migrated_at": mig,
            "secs_90_to_mig": (mig - c90["ts"]) if c90 else None, "secs_93_to_mig": (mig - c93["ts"]) if c93 else None,
            "mcap_93": c93["mcap"] if c93 else None, "mcap_last_curve": last_curve["mcap"] if last_curve else None,
            "first_pool_mcap": first_pool["mcap"] if first_pool else None,
            "pool_vs_curve": (first_pool["price"] / last_curve["price"]) if (first_pool and last_curve) else None,
            "peak_mult": peak, "n_pool_points": len(amm), "n_curve_points": len(curve),
            "post60": ({"reason": sim.get("reason"), "ret": sim.get("ret"), "censored": bool(sim.get("censored"))} if sim else None),
            "links": {"pumpfun": f"https://pump.fun/coin/{t['mint']}", "dexscreener": f"https://dexscreener.com/solana/{t['mint']}",
                      "solscan": f"https://solscan.io/token/{t['mint']}"},
        })
    rows.sort(key=lambda r: -r["migrated_at"])
    return rows[:limit]


def build_state(store, cfg, now=None, mode="live"):
    now = int(now or time.time())
    cands = []
    for r in store.latest_since(now - 900):
        c = {k: r.get(k) for k in KEEP}
        c["volume"] = r["criteria"]["volume"].get("metrics", {})
        c["history"] = r["criteria"]["history"].get("metrics", {})
        c["links"] = r.get("links", [])
        cands.append(c)
    cands.sort(key=lambda c: (c["discarded"], -(c["score"] or 0), -(c["raw_score"] or 0)))
    outcomes = analysis.alert_outcomes(store, cfg, now)
    al = []
    for a in store.alerts():
        al.append({"mint": a["mint"], "name": a["name"], "symbol": a["symbol"], "ts": a["ts"], "price": a["price"],
                   "mcap": a["mcap"], "progress": a["progress"], "score": a["score"], "reason": a["reason"],
                   "emailed": bool(a["emailed"]), "email_note": a["email_note"], "outcomes": outcomes.get(a["mint"], {})})
    last = store.get_meta("last_cycle")
    return {
        "mode": mode, "generated_at": now,
        "config": {"alert_score": cfg["alert_score"], "track_score": cfg["track_score"],
                   "gates": cfg["gates"], "curve_target_sol": cfg["curve_target_sol"],
                   "position_usd": cfg["costs"]["position_usd"], "stop_loss_pct": cfg["costs"]["stop_loss_pct"], "weights": cfg["weights"]},
        "health": {"last_cycle": last, "errors": store.get_meta("errors", [])[-5:],
                   "sample_fails": store.get_meta("sample_fails"), "helius": bool(cfg["keys"]["helius"]), "gmgn": bool(cfg["keys"].get("gmgn")),
                   "gmgn_blocked_until": store.get_meta("gmgn_blocked_until"),
                   "email": bool(cfg["email"]["enabled"]), "sol_usd": (store.get_meta("sol_usd") or {}).get("v"),
                   "usage": store.get_meta("usage", {}),
                   "n_candidates_tracked": store.count_tracked("candidate"),
                   "n_controls_tracked": store.count_tracked("control")},
        "candidates": cands, "alerts": al, "report": store.get_meta("report"),
        "backtest": store.get_meta("bt_report"), "study_post": store.get_meta("study_post"),
        "history": history_rows(store, cfg, now), "wallets": store.get_meta("wallet_report"),
        "recorder": {"last": store.get_meta("rec_last"),
                     "tokens": store.db.execute("SELECT COUNT(*) c FROM rec_tokens").fetchone()["c"],
                     "completed": store.db.execute("SELECT COUNT(*) c FROM rec_tokens WHERE completed_ts IS NOT NULL").fetchone()["c"],
                     "with_feat": store.db.execute("SELECT COUNT(*) c FROM rec_tokens WHERE feat_ts IS NOT NULL").fetchone()["c"],
                     "points": store.db.execute("SELECT COUNT(*) c FROM rec_path").fetchone()["c"]},
    }
