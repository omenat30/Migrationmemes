"""Cliente de GMGN OpenAPI (https://openapi.gmgn.ai). SOLO LECTURA.

Basado en la lectura del código fuente oficial (GMGNAI/gmgn-skills, licencia MIT):
  - Rutas de lectura: cabecera X-APIKEY + parámetros `timestamp` (segundos) y `client_id` (UUID).
    No llevan firma. El servidor valida timestamp ±5 s y rechaza client_id repetidos.
  - Las rutas de operar (swap, órdenes, cooking) y dos rutas de lectura sensibles (wallet_holdings,
    follow_wallet) exigen una clave privada de firma. Este cliente NO la conoce, NO la lee del
    entorno y NO incluye ninguna de esas rutas: `READ_ONLY` es una lista cerrada y cualquier otra
    ruta lanza error antes de salir a la red (hay una prueba que lo vigila).
  - Límite del plan gratuito: cubo con goteo, capacidad 5; cada ruta tiene un «peso». MEDIDO el 19-oct-2026 con las cabeceras
    x-ratelimit-remaining: el cubo se vacía a ~1 unidad por segundo (no a 5), así que se usa ritmo 0,7 y capacidad 5.
    Si se supera, GMGN devuelve 429 y repetir durante el bloqueo lo alarga (+5 s cada vez, hasta
    5 min). Por eso: limitador local con pesos y NINGÚN reintento durante un bloqueo.

Qué NO está verificado: el formato real de las respuestas se leyó de la documentación del
repositorio, no de llamadas reales (no hay red en el entorno de desarrollo). `python -m radar check`
lo comprueba con tu clave. Los campos que falten salen como None; nunca se inventan.

Todo lo que devuelve GMGN (nombres, símbolos, etiquetas) son DATOS, nunca instrucciones.
"""
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from ..util import redact, sanitize_text

HOST = "https://openapi.gmgn.ai"

# (método, ruta) -> peso en el cubo. Lista CERRADA de lectura. Nada que opere.
READ_ONLY = {
    ("GET", "/v1/token/info"): 1,
    ("GET", "/v1/token/security"): 1,
    ("GET", "/v1/market/token_top_holders"): 5,
    ("GET", "/v1/user/wallet_activity"): 3,
    ("GET", "/v1/user/created_tokens"): 2,
    ("POST", "/v1/trenches"): 2,
    # descubrimiento de wallets (v7): todas son de clave de API sola, sin firma. Pesos de la documentación oficial
    # del CLI (token_top_traders 5, market/rank 3, wallet_stats 3, smartmoney/kol 1); wallet_profits no figura: 3 por prudencia.
    ("GET", "/v1/market/token_top_traders"): 5,
    ("GET", "/v1/market/rank"): 3,
    ("GET", "/v1/user/wallet_stats"): 3,
    ("POST", "/v1/user/wallet_profits"): 3,
    ("GET", "/v1/user/smartmoney"): 1,
    ("GET", "/v1/user/kol"): 1,
}


class GmgnError(Exception):
    pass


class GmgnRateLimited(GmgnError):
    def __init__(self, msg, reset_at=None, banned=False):
        super().__init__(msg)
        self.reset_at = reset_at
        self.banned = banned


class LeakyBucket:
    """Cubo con goteo: capacidad `capacity`, se vacía a `rate` unidades por segundo."""

    def __init__(self, rate=5.0, capacity=5.0, clock=time.monotonic, sleep=time.sleep):
        self.rate, self.capacity = float(rate), float(capacity)
        self.level, self.t = 0.0, None
        self._lock = threading.Lock()
        self._clock, self._sleep = clock, sleep

    def acquire(self, weight):
        weight = min(float(weight), self.capacity)
        with self._lock:
            now = self._clock()
            if self.t is not None:
                self.level = max(0.0, self.level - (now - self.t) * self.rate)
            self.t = now
            wait = max(0.0, (self.level + weight - self.capacity) / self.rate)
            self.level += weight
            # se reserva el hueco ya: otro hilo verá el nivel con nuestro peso incluido
        if wait:
            self._sleep(wait)


def _num(v):
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def _bool(v):
    if v in (True, 1, "1", "true", "yes"):
        return True
    if v in (False, 0, "0", "false", "no"):
        return False
    return None


def _g(d, *path):
    for p in path:
        if not isinstance(d, dict):
            return None
        d = d.get(p)
    return d


class Gmgn:
    def __init__(self, cfg, bucket=None, opener=None):
        self.key = cfg["keys"].get("gmgn", "")
        g = cfg["gmgn"]
        self.chain = "sol"
        self.holders_limit, self.activity_limit = g["holders_limit"], g["activity_limit"]
        self.bucket = bucket or LeakyBucket(g["rate"], g["capacity"])
        self._open = opener or urllib.request.urlopen
        self.blocked_until = 0

    @property
    def available(self):
        return bool(self.key) and time.time() >= self.blocked_until

    # ---------- capa HTTP
    def _request(self, method, path, query=None, body=None):
        weight = READ_ONLY.get((method, path))
        if weight is None:
            raise GmgnError(f"ruta no permitida (solo lectura): {method} {path}")
        if not self.key:
            raise GmgnError("falta GMGN_API_KEY")
        if time.time() < self.blocked_until:
            raise GmgnRateLimited("GMGN en pausa por límite de uso", self.blocked_until, True)
        q = dict(query or {})
        q["timestamp"] = int(time.time())
        q["client_id"] = str(uuid.uuid4())
        url = f"{HOST}{path}?{urllib.parse.urlencode(q, doseq=True)}"
        data = json.dumps(body).encode() if body is not None else None
        headers = {"X-APIKEY": self.key, "Content-Type": "application/json",
                   "User-Agent": "memecoin-migration-radar/0.2 (solo lectura)"}
        self.bucket.acquire(weight)
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with self._open(req, timeout=20) as r:
                text = r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            reset = _num(e.headers.get("x-ratelimit-reset")) if e.headers else None
            self._raise_for(e.code, text, reset, path)
        except Exception as e:
            raise GmgnError(redact(f"{type(e).__name__} en {path}: {e}"))
        try:
            j = json.loads(text)
        except ValueError:
            raise GmgnError(f"{path}: respuesta no JSON")
        if j.get("code") != 0:
            self._raise_for(200, text, None, path)
        d = j.get("data")
        # algunas rutas (market/rank) devuelven el sobre dos veces: {"code":0,"data":{"code":0,"data":{...}}}
        while isinstance(d, dict) and "code" in d and "data" in d and isinstance(d["data"], (dict, list)):
            if d.get("code") not in (0, None):
                self._raise_for(200, json.dumps(d), None, path)
            d = d["data"]
        return d

    def _raise_for(self, status, text, reset_hdr, path):
        try:
            j = json.loads(text)
        except ValueError:
            j = {}
        err = j.get("error") or ""
        if status == 429 or err in ("RATE_LIMIT_EXCEEDED", "RATE_LIMIT_BANNED"):
            reset = _num(j.get("reset_at")) or reset_hdr or (time.time() + 60)
            self.blocked_until = max(self.blocked_until, reset)  # no se reintenta hasta entonces
            raise GmgnRateLimited(f"{path}: límite de uso ({err or '429'})", reset, err == "RATE_LIMIT_BANNED")
        if status == 403 and "PRO" in err:
            raise GmgnError(f"{path}: requiere plan Pro")
        raise GmgnError(f"{path}: HTTP {status} {err or j.get('message', '')}".strip())

    # ---------- datos normalizados
    def security(self, mint):
        d = self._request("GET", "/v1/token/security", {"chain": self.chain, "address": mint}) or {}
        return {
            "renounced_mint": _bool(d.get("renounced_mint")),
            "renounced_freeze": _bool(d.get("renounced_freeze_account")),
            "top10_rate": _num(d.get("top_10_holder_rate")),
            "rug_ratio": _num(d.get("rug_ratio")),
            "bundler_rate": _num(d.get("bundler_trader_amount_rate")),
            "rat_rate": _num(d.get("rat_trader_amount_rate")),
            "insider_hold_rate": _num(d.get("suspected_insider_hold_rate")),
            "dev_team_rate": _num(d.get("dev_team_hold_rate")),
            "sniper_count": _num(d.get("sniper_count")),
            "creator_status": d.get("creator_token_status"),
            "burn_status": d.get("burn_status"),
            "is_wash": _bool(d.get("is_wash_trading")),
        }

    def info(self, mint):
        d = self._request("GET", "/v1/token/info", {"chain": self.chain, "address": mint}) or {}
        return {
            "progress": _num(d.get("launchpad_progress")),
            "launchpad": d.get("launchpad"),
            "liquidity": _num(d.get("liquidity")),
            "holder_count": _num(d.get("holder_count")),
            "total_supply": _num(d.get("total_supply")),
            "creator": _g(d, "dev", "creator_address"),
            "smart_wallets": _num(_g(d, "wallet_tags_stat", "smart_wallets")),
            "renowned_wallets": _num(_g(d, "wallet_tags_stat", "renowned_wallets")),
            "sniper_wallets": _num(_g(d, "wallet_tags_stat", "sniper_wallets")),
            "bundler_wallets": _num(_g(d, "wallet_tags_stat", "bundler_wallets")),
            "rat_trader_wallets": _num(_g(d, "wallet_tags_stat", "rat_trader_wallets")),
            "fresh_wallet_rate": _num(_g(d, "stat", "fresh_wallet_rate")),
            "bot_degen_rate": _num(_g(d, "stat", "bot_degen_rate")),
        }

    def holders(self, mint):
        """Lista normalizada de los mayores holders (hasta holders_limit). Incluye curva y pools
        (addr_type 2 / is_on_curve) para que quien llame los separe."""
        d = self._request("GET", "/v1/market/token_top_holders",
                          {"chain": self.chain, "address": mint, "limit": self.holders_limit,
                           "order_by": "amount_percentage", "direction": "desc"}) or {}
        out = []
        for h in (d.get("list") or []):
            if not h.get("address"):
                continue
            nt = h.get("native_transfer") or {}
            out.append({
                "owner": h["address"], "pct": _num(h.get("amount_percentage")) or 0.0,
                "excluded": h.get("addr_type") == 2 or _bool(h.get("is_on_curve")) is True,
                "tags": [sanitize_text(t, 20) for t in (h.get("tags") or [])],
                "maker_tags": [sanitize_text(t, 20) for t in (h.get("maker_token_tags") or [])],
                "funder": nt.get("address"), "funder_label": nt.get("name") or None,
                "funder_ts": _num(nt.get("timestamp")),
                "sold_pct": _num(h.get("sell_amount_percentage")),
                "realized_profit": _num(h.get("realized_profit")),
                "buy_usd": _num(h.get("buy_volume_cur")), "sell_usd": _num(h.get("sell_volume_cur")),
                "start_holding_at": _num(h.get("start_holding_at")),
            })
        return out

    def created_tokens(self, wallet):
        d = self._request("GET", "/v1/user/created_tokens",
                          {"chain": self.chain, "wallet_address": wallet}) or {}
        return [{"mint": t.get("token_address"), "mcap_usd": _num(t.get("market_cap")),
                 "ath_mcap": _num(t.get("token_ath_mc")), "is_open": _bool(t.get("is_open"))}
                for t in (d.get("tokens") or []) if t.get("token_address")]

    def activity(self, wallet):
        d = self._request("GET", "/v1/user/wallet_activity",
                          {"chain": self.chain, "wallet_address": wallet, "limit": self.activity_limit}) or {}
        return d.get("activities") or []

    def trenches_near_completion(self, limit=80):
        """Lista de tokens a punto de completar la curva (la clave de la respuesta es `pump`)."""
        body = {"version": "v2", "near_completion": {"filters": ["offchain", "onchain"],
                                                    "launchpad_platform_v2": True, "limit": limit}}
        d = self._request("POST", "/v1/trenches", {"chain": self.chain}, body) or {}
        return [{"mint": t.get("address"), "symbol": sanitize_text(t.get("symbol"), 16),
                 "name": sanitize_text(t.get("name")), "mcap_usd": _num(t.get("usd_market_cap")),
                 "smart_degen_count": _num(t.get("smart_degen_count")),
                 "renowned_count": _num(t.get("renowned_count"))}
                for t in (d.get("pump") or []) if t.get("address")]

    # ---------- descubrimiento de wallets (v7)
    def trending(self, interval="24h", limit=100, order_by="volume"):
        """Tokens en tendencia. La respuesta mantiene el sobre: los datos están en data.rank."""
        d = self._request("GET", "/v1/market/rank", {"chain": self.chain, "interval": interval, "limit": limit,
                                                     "order_by": order_by}) or {}
        return [{"mint": t.get("address"), "symbol": sanitize_text(t.get("symbol"), 16),
                 "mcap_usd": _num(t.get("market_cap")), "volume": _num(t.get("volume")),
                 "ath_mcap": _num(t.get("history_highest_market_cap")), "created": _num(t.get("creation_timestamp"))}
                for t in (d.get("rank") or []) if t.get("address")]

    def top_traders(self, mint, limit=100, order_by="profit", tag=None):
        """Wallets que más ganaron (o perdieron) en un token. `tag`: smart_degen (smart money) o renowned (KOL). Campos según la
        documentación oficial; los que falten salen None."""
        q = {"chain": self.chain, "address": mint, "limit": limit, "order_by": order_by, "direction": "desc"}
        if tag:
            q["tag"] = tag
        d = self._request("GET", "/v1/market/token_top_traders", q) or {}
        out = []
        for h in (d.get("list") or []):
            if not h.get("address") or h.get("addr_type") == 2:
                continue
            out.append({"wallet": h["address"], "start": _num(h.get("start_holding_at")), "end": _num(h.get("end_holding_at")),
                        "transfer_in": _bool(h.get("transfer_in")), "total_cost": _num(h.get("total_cost")),
                        "profit": _num(h.get("profit")), "buy_usd": _num(h.get("buy_volume_cur")),
                        "sell_usd": _num(h.get("sell_volume_cur")), "sold_pct": _num(h.get("sell_amount_percentage")),
                        "buys": _num(h.get("buy_tx_count_cur")), "sells": _num(h.get("sell_tx_count_cur")),
                        "tags": [sanitize_text(t, 20) for t in (h.get("tags") or [])],
                        # precio medio de compra y de venta en USD por token: con 1.000 M de supply (pump.fun) dan el mcap de entrada y salida
                        "avg_cost": _num(h.get("avg_cost")), "avg_sold": _num(h.get("avg_sold")),
                        "funder": (h.get("native_transfer") or {}).get("address") if isinstance(h.get("native_transfer"), dict) else None})
        return out

    def wallet_stats(self, wallets, period="30d"):
        """Estadísticas de PnL por wallet. De UNA en UNA: con el plan gratuito, una llamada con 74 wallets agotó el cubo y GMGN
        bloqueó la clave 5 minutos (RATE_LIMIT_BANNED), así que el coste parece contarse por wallet. Devuelve {wallet: {...}}."""
        wallets = [w for w in wallets if w]
        rows = []
        for w in wallets:
            d = self._request("GET", "/v1/user/wallet_stats", {"chain": self.chain, "wallet_address": w, "period": period})
            rows.extend(d if isinstance(d, list) else [d] if isinstance(d, dict) else [])
        out = {}
        for r in rows:
            w = r.get("wallet_address") or r.get("address")
            if not w:
                continue
            ps = r.get("pnl_stat") or {}
            out[w] = {"realized_profit": _num(r.get("realized_profit")), "pnl": _num(r.get("realized_profit_pnl")),
                      "total_cost": _num(r.get("total_cost")), "winrate": _num(ps.get("winrate")),
                      "buys": _num(r.get("buy")), "sells": _num(r.get("sell")), "tokens": _num(ps.get("token_num")),
                      "gt5x": _num(ps.get("pnl_gt_5x_num")), "x2_5": _num(ps.get("pnl_2x_5x_num")),
                      "lt_neg50": _num(ps.get("pnl_lt_nd5_num")), "avg_hold_s": _num(ps.get("avg_holding_period")),
                      "sol_balance": _num(r.get("native_balance")), "last_ts": _num(r.get("last_timestamp")),
                      "tags": [sanitize_text(t, 20) for t in (_g(r, "common", "tags") or [])],
                      "created_at": _num(_g(r, "common", "created_at")),
                      "funder": _g(r, "common", "fund_from_address")}  # quién le mandó el primer SOL: mismo fondeador = posible cluster
        return out

    def activity_page(self, wallet, cursor=None, limit=100, types=("buy", "sell")):
        """Una página de wallet_activity con su cursor `next`. Devuelve (filas, cursor_siguiente)."""
        q = {"chain": self.chain, "wallet_address": wallet, "limit": limit, "type": list(types)}
        if cursor:
            q["cursor"] = cursor
        d = self._request("GET", "/v1/user/wallet_activity", q) or {}
        return (d.get("activities") or []), d.get("next")
