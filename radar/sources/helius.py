"""Helius: RPC de Solana + transacciones enriquecidas. Requiere HELIUS_API_KEY.

La clave viaja en la URL (así lo exige Helius); `util.redact` la oculta de cualquier
mensaje de error o registro. Los formatos de respuesta usados aquí son los del RPC
estándar de Solana (fiables) y los de la API enriquecida (SIN VERIFICAR hasta `check`).
"""
import base64
import struct
import threading

from ..util import http_json


class Helius:
    def __init__(self, cfg, limiter):
        self.key = cfg["keys"]["helius"]
        self.rpc_url = cfg["endpoints"]["helius_rpc"].rstrip("/") + "/?api-key=" + self.key
        self.api = cfg["endpoints"]["helius_api"].rstrip("/")
        self.limiter = limiter
        self.usage, self._ulock = {}, threading.Lock()

    @property
    def available(self):
        return bool(self.key)

    def _count(self, kind, n=1):
        with self._ulock:
            self.usage[kind] = self.usage.get(kind, 0) + n

    def take_usage(self):
        """Devuelve y reinicia el contador de llamadas (para medir el consumo real de Helius)."""
        with self._ulock:
            u, self.usage = self.usage, {}
        return u

    def curve_state(self, curve):
        """Estado de la curva de bonding LEÍDO DE LA CADENA (verificado contra la API de pump.fun en 4 tokens).
        Cuenta: 8 bytes de discriminador + 5 u64 (reservas virtuales de tokens y SOL, reales de tokens y SOL,
        suministro) + 1 byte `complete`. `standard`: curva en SOL con reservas virtuales = reales + 30."""
        r = self._rpc("getAccountInfo", [curve, {"encoding": "base64"}])
        v = (r or {}).get("value")
        if not v:
            return None
        raw = base64.b64decode(v["data"][0])
        if len(raw) < 49:
            return None
        vt, vs, rt, rs, sup = struct.unpack("<5Q", raw[8:48])
        return {"vtok": vt / 1e6, "vsol": vs / 1e9, "rtok": rt / 1e6, "rsol": rs / 1e9, "supply": sup / 1e6,
                "complete": bool(raw[48]), "standard": abs(vs / 1e9 - rs / 1e9 - 30.0) < 0.01}

    def _rpc(self, method, params):
        self._count("rpc")
        r = http_json(self.rpc_url, body={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                      limiter=self.limiter)
        if "error" in r:
            raise RuntimeError(f"RPC {method}: {r['error'].get('message') if isinstance(r['error'], dict) else r['error']}")
        return r["result"]

    def mint_info(self, mint):
        """{mint_authority, freeze_authority, supply, decimals} o None."""
        res = self._rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}])
        val = (res or {}).get("value")
        info = (((val or {}).get("data") or {}).get("parsed") or {}).get("info")
        if not info:
            return None
        return {"mint_authority": info.get("mintAuthority"), "freeze_authority": info.get("freezeAuthority"),
                "supply": float(info.get("supply", 0)) / (10 ** int(info.get("decimals", 0))),
                "decimals": int(info.get("decimals", 0))}

    def holders(self, mint, exclude_owners):
        """Mayores holders (hasta 20 cuentas), sin curva ni pool, ordenados.
        Devuelve (holders, cantidad_excluida): lo que tienen la curva y el pool, para
        calcular el circulante real = suministro - excluida."""
        res = self._rpc("getTokenLargestAccounts", [mint])
        accts = (res or {}).get("value", [])
        if not accts:
            return [], 0.0
        addrs = [a["address"] for a in accts]
        infos = self._rpc("getMultipleAccounts", [addrs, {"encoding": "jsonParsed"}])["value"]
        out, excluded = [], 0.0
        for a, inf in zip(accts, infos):
            owner = ((((inf or {}).get("data") or {}).get("parsed") or {}).get("info") or {}).get("owner")
            if not owner:
                continue
            if owner in exclude_owners:
                excluded += float(a.get("uiAmount") or 0)
                continue
            out.append({"owner": owner, "amount": float(a.get("uiAmount") or 0)})
        out.sort(key=lambda h: -h["amount"])
        return out, excluded

    def curve_signatures(self, address, until=None, limit=1000):
        """Firmas más recientes de una cuenta (la curva), de más nueva a más vieja.
        `until`: se detiene al llegar a esta firma (ya vista). Incluye las fallidas (campo `err`)."""
        opts = {"limit": limit, "commitment": "confirmed"}
        if until:
            opts["until"] = until
        return self._rpc("getSignaturesForAddress", [address, opts]) or []

    def parse_transactions(self, signatures):
        """Transacciones enriquecidas (máx. 100 por llamada)."""
        if not signatures:
            return []
        self._count("parse_calls")
        self._count("parsed_txs", len(signatures[:100]))
        return http_json(f"{self.api}/v0/transactions?api-key={self.key}", body={"transactions": signatures[:100]},
                         limiter=self.limiter)

    def wallet_txs(self, wallet, limit=100):
        self._count("wallet_calls")
        return http_json(f"{self.api}/v0/addresses/{wallet}/transactions?api-key={self.key}&limit={limit}",
                         limiter=self.limiter)
