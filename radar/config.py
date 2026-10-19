"""Configuración: valores por defecto + config.json + variables de entorno / .env."""
import copy
import json
import os

DEFAULTS = {
    # Umbral de migración de pump.fun en SOL reales dentro de la curva.
    # SIN VERIFICAR: `python -m radar calibrate` lo mide con tokens ya migrados.
    "curve_target_sol": 85.0,
    "curve_tokens_initial": 793_100_000,
    "total_supply": 1_000_000_000,
    "poll_seconds": 20,
    "deep_cache_seconds": 120,
    "max_deep_per_cycle": 4,
    "cycle_budget_s": 90,  # no empezar otro token si el ciclo ya pasó de este tiempo
    "track_score": 55,
    "alert_variant": "V00",
    "gates": {"min_mcap_usd": 30000, "min_curve_pct": 60, "max_curve_pct": 99.5},
    "weights": {"curve": 15, "volume": 25, "wallets": 25, "history": 20, "manipulation": 15},
    "volume": {"window_s": 300, "min_unique_buyers": 15, "min_buy_sell_ratio": 1.5, "max_spike_share": 0.6},
    "wallets": {
        "first_buyers": 12, "top_holders": 12, "target_independent": 8,
        "max_cluster_pct": 25, "funding_window_s": 3600, "same_slot_min_repeats": 2,
        "min_fund_sol": 0.02, "ignore_funders": [], "wallet_cache_s": 21600, "parallel": 5,
    },
    "history": {"min_closed": 3, "min_hold_s": 300, "quick_exit_s": 120,
                "max_quick_exit_ratio": 0.3, "bot_trades_per_day": 300},
    "manipulation": {"wash_window_s": 60, "wash_ratio_lo": 0.7, "wash_ratio_hi": 1.4,
                     "max_wash_share": 0.25, "max_creator_pct": 10, "max_cluster_pct": 35},
    "security": {"max_top10_pct": 35, "max_prev_rugs": 1, "rug_ath_min_usd": 15000,
                 "rug_drop_pct": 90, "unknown_is_fail": True, "min_sells_for_sellable": 3},
    # Tu operación: 100 USD por trade y cierre manual si cae un 60 % desde tu entrada.
    "costs": {"position_usd": 100.0, "stop_loss_pct": 60.0, "stop_reaction_s": 30, "latency_s": 30, "fee_pct": 1.0, "amm_fee_pct": 0.30,  # comisión en el pool tras migrar: SIN VERIFICAR
              
              "priority_fee_sol": 0.002, "exit_slippage_pct": 3.0, "rug_drop_pct": 90, "rug_liquidity_usd": 2000},
    "recorder": {"poll_s": 15, "pages": 6, "min_progress": 75, "feat_progress": 90, "post_s": 7200, "stale_s": 1800,
                 "chain_checks_per_step": 20, "dex_every_s": 30},
    # Backtest (reglas fijadas antes de ver datos; ver HIPOTESIS_v4.md)
    "backtest": {"min_mcap_usd": 30000, "max_hold_s": 7200, "exit_delay_s": 60, "target_pct": 30, "time30_s": 1800,
                 "min_n_select": 15, "min_n_test": 30, "ci_seed": 7, "boot": 2000, "latency_grid_s": [30, 60, 120, 300]},
    # Panel de copia (HIPOTESIS_v7.md): filtros del usuario para elegir wallets a copiar.
    "copy": {"min_hits10": 0, "min_roi": 0.30, "max_idle_days": 0, "require_robust": True, "recent_days": 14, "min_recent_closed": 0, "min_closed": 20, "min_hold_s": 600, "short_hold_s": 120, "max_short_share": 0.35,
             "stop_loss_pct": 60.0, "top_n": 10, "days": 60, "min_span_days": 15, "hit_mult": 11.0},
    "series": {"fast_every_s": 60, "fast_until_s": 7200, "slow_every_s": 900, "tail_s": 90000},
    "control_per_hour": 12,
    "analysis": {"primary_horizon_s": 3600, "horizons_s": [300, 3600, 86400],
                 "min_n_select": 10, "min_n_test": 15, "alpha": 0.10, "perm": 5000, "seed": 7},
    "endpoints": {
        "pumpfun_api": "https://frontend-api-v3.pump.fun",
        "pumpfun_list_path": "/coins?offset=0&limit=50&sort=last_trade_timestamp&order=DESC&includeNsfw=false",
        "dexscreener_api": "https://api.dexscreener.com",
        "helius_rpc": "https://mainnet.helius-rpc.com",
        "helius_api": "https://api.helius.xyz",
    },
    "helius_rps": 5,
    # Trades de la curva vía Helius: tope de transacciones parseadas por token y ciclo (cuida los créditos).
    "helius_trades": {"parse_budget": 400, "sig_limit": 1000},
    # GMGN (solo lectura). Rate/capacity = plan gratuito 5/5 con pesos por ruta (ver sources/gmgn.py).
    "gmgn": {"enabled": True, "rate": 0.7, "capacity": 5, "holders_limit": 100, "activity_limit": 50,
             "history_wallets": 14},
    "email": {"enabled": False, "to": "albertomenat@gmail.com",
              "smtp_host": "smtp.gmail.com", "smtp_port": 465},
    "server": {"host": "127.0.0.1", "port": 8787},
    "db_path": "data/radar.sqlite",
}


def _merge(base, over):
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def load_dotenv(path=".env"):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_config(path="config.json"):
    load_dotenv()
    cfg = copy.deepcopy(DEFAULTS)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            _merge(cfg, json.load(f))
    # El umbral de aviso NO se configura aquí: lo fija la variante `alert_variant` de
    # variants.json (lista cerrada, definida antes de medir). Se copia para mostrarlo.
    from .variants import load_variants
    av = {v["id"]: v for v in load_variants()}[cfg["alert_variant"]]
    cfg["alert_score"] = av["min_score"]
    cfg["keys"] = {
        "helius": os.environ.get("HELIUS_API_KEY", ""),
        "gmgn": os.environ.get("GMGN_API_KEY", "") if cfg["gmgn"]["enabled"] else "",
        "smtp_user": os.environ.get("SMTP_USER", ""),
        "smtp_password": os.environ.get("SMTP_PASSWORD", ""),
    }
    return cfg
