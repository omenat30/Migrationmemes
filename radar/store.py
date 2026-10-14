"""Base de datos SQLite: observaciones, series de precio, alertas y caché."""
import json
import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS observations(
  id INTEGER PRIMARY KEY, mint TEXT, ts INTEGER, price REAL, mcap REAL, progress REAL,
  score REAL, discarded INTEGER, features TEXT);
CREATE INDEX IF NOT EXISTS ix_obs_mint ON observations(mint, ts);
CREATE TABLE IF NOT EXISTS latest(mint TEXT PRIMARY KEY, ts INTEGER, name TEXT, symbol TEXT, result TEXT);
CREATE TABLE IF NOT EXISTS tracked(
  mint TEXT PRIMARY KEY, kind TEXT, start_ts INTEGER, until_ts INTEGER, next_ts INTEGER,
  mcap0 REAL, name TEXT, symbol TEXT, curve TEXT);
CREATE TABLE IF NOT EXISTS series(
  mint TEXT, ts INTEGER, price REAL, mcap REAL, vsol REAL, vtok REAL, liq REAL, complete INTEGER, sol_usd REAL,
  PRIMARY KEY(mint, ts));
CREATE TABLE IF NOT EXISTS alerts(
  id INTEGER PRIMARY KEY, mint TEXT UNIQUE, ts INTEGER, price REAL, mcap REAL, progress REAL, score REAL,
  name TEXT, symbol TEXT, reason TEXT, result TEXT, emailed INTEGER DEFAULT 0, email_note TEXT);
CREATE TABLE IF NOT EXISTS trades(
  sig TEXT PRIMARY KEY, mint TEXT, ts INTEGER, wallet TEXT, is_buy INTEGER, sol REAL, tokens REAL, slot INTEGER);
CREATE INDEX IF NOT EXISTS ix_trades_mint ON trades(mint, ts);
CREATE TABLE IF NOT EXISTS rec_tokens(
  mint TEXT PRIMARY KEY, curve TEXT, creator TEXT, name TEXT, symbol TEXT, created_ts INTEGER, first_ts INTEGER,
  first_progress REAL, last_ts INTEGER, completed_ts INTEGER, feat TEXT, feat_ts INTEGER);
CREATE TABLE IF NOT EXISTS rec_path(
  mint TEXT, ts INTEGER, progress REAL, price REAL, mcap REAL, vsol REAL, vtok REAL, liq REAL, phase TEXT, sol_usd REAL,
  PRIMARY KEY(mint, ts));
CREATE TABLE IF NOT EXISTS wallet_cache(addr TEXT PRIMARY KEY, ts INTEGER, data TEXT);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
"""


class Store:
    def __init__(self, path):
        self.path = path
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=15)
        self.db.row_factory = sqlite3.Row
        if path != ":memory:":
            self.db.execute("PRAGMA journal_mode=WAL")  # el hilo de muestreo y el de análisis escriben a la vez
            self.db.execute("PRAGMA busy_timeout=15000")
        self.db.executescript(SCHEMA)
        try:  # bases creadas antes de añadir la columna
            self.db.execute("ALTER TABLE tracked ADD COLUMN curve TEXT")
        except sqlite3.OperationalError:
            pass
        self.db.commit()

    def clone(self):
        """Otra conexión a la misma base (un hilo, una conexión). No válido para :memory:."""
        if self.path == ":memory:":
            raise ValueError("una base en memoria no se puede compartir entre hilos")
        return Store(self.path)

    def close(self):
        self.db.close()

    # --- meta
    def get_meta(self, k, default=None):
        r = self.db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return json.loads(r["v"]) if r else default

    def set_meta(self, k, v):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (k, json.dumps(v)))
        self.db.commit()

    # --- observaciones
    def add_observation(self, res):
        f = res["features"]
        self.db.execute(
            "INSERT INTO observations(mint,ts,price,mcap,progress,score,discarded,features) VALUES(?,?,?,?,?,?,?,?)",
            (res["mint"], res["ts"], res["price"], res["mcap"], res["progress"], res["score"],
             int(res["discarded"]), json.dumps(f)))
        self.db.commit()

    def set_latest(self, res, name, symbol):
        self.db.execute("INSERT OR REPLACE INTO latest VALUES(?,?,?,?,?)",
                        (res["mint"], res["ts"], name, symbol, json.dumps(res)))
        self.db.commit()

    def latest_since(self, ts):
        rows = self.db.execute("SELECT * FROM latest WHERE ts>=? ORDER BY ts DESC", (ts,)).fetchall()
        return [{"name": r["name"], "symbol": r["symbol"], **json.loads(r["result"])} for r in rows]

    def last_eval_ts(self, mint):
        r = self.db.execute("SELECT ts FROM latest WHERE mint=?", (mint,)).fetchone()
        return r["ts"] if r else 0

    def observations(self, mint=None):
        q = "SELECT mint,ts,price,mcap,progress,score,discarded,features FROM observations"
        rows = self.db.execute(q + (" WHERE mint=? ORDER BY ts" if mint else " ORDER BY ts"),
                               (mint,) if mint else ()).fetchall()
        return [{"mint": r["mint"], "ts": r["ts"], "price": r["price"], "mcap": r["mcap"],
                 "features": json.loads(r["features"])} for r in rows]

    # --- seguimiento
    def get_tracked(self, mint):
        return self.db.execute("SELECT * FROM tracked WHERE mint=?", (mint,)).fetchone()

    def track(self, mint, kind, now, until, mcap0, name, symbol, curve=None):
        self.db.execute("INSERT OR IGNORE INTO tracked(mint,kind,start_ts,until_ts,next_ts,mcap0,name,symbol,curve) "
                        "VALUES(?,?,?,?,?,?,?,?,?)", (mint, kind, now, until, now, mcap0, name, symbol, curve))
        self.db.commit()

    def extend_tracking(self, mint, until):
        self.db.execute("UPDATE tracked SET until_ts=MAX(until_ts,?) WHERE mint=?", (until, mint))
        self.db.commit()

    def due_tracked(self, now):
        return self.db.execute("SELECT * FROM tracked WHERE next_ts<=? AND ?<=until_ts", (now, now)).fetchall()

    def set_next(self, mint, ts):
        self.db.execute("UPDATE tracked SET next_ts=? WHERE mint=?", (ts, mint))
        self.db.commit()

    def count_tracked(self, kind):
        return self.db.execute("SELECT COUNT(*) c FROM tracked WHERE kind=?", (kind,)).fetchone()["c"]

    def all_tracked(self, kind=None):
        q = "SELECT * FROM tracked" + (" WHERE kind=?" if kind else "")
        return self.db.execute(q, (kind,) if kind else ()).fetchall()

    def add_sample(self, mint, s):
        self.db.execute("INSERT OR REPLACE INTO series VALUES(?,?,?,?,?,?,?,?,?)",
                        (mint, int(s["ts"]), s["price"], s.get("mcap"), s.get("vsol"), s.get("vtok"),
                         s.get("liq"), int(bool(s.get("complete"))), s.get("sol_usd")))
        self.db.commit()

    def series(self, mint):
        rows = self.db.execute("SELECT * FROM series WHERE mint=? ORDER BY ts", (mint,)).fetchall()
        return [dict(r, complete=bool(r["complete"])) for r in rows]

    # --- alertas
    def add_alert(self, res, name, symbol, reason):
        cur = self.db.execute(
            "INSERT OR IGNORE INTO alerts(mint,ts,price,mcap,progress,score,name,symbol,reason,result) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (res["mint"], res["ts"], res["price"], res["mcap"], res["progress"], res["score"],
             name, symbol, reason, json.dumps(res)))
        self.db.commit()
        return cur.rowcount > 0

    def has_alert(self, mint):
        return self.db.execute("SELECT 1 FROM alerts WHERE mint=?", (mint,)).fetchone() is not None

    def mark_emailed(self, mint, ok, note):
        self.db.execute("UPDATE alerts SET emailed=?, email_note=? WHERE mint=?", (int(ok), note, mint))
        self.db.commit()

    def alerts(self):
        rows = self.db.execute("SELECT * FROM alerts ORDER BY ts DESC").fetchall()
        return [dict(r) for r in rows]

    # --- trades de la curva (incremental)
    def add_trades(self, mint, trades):
        self.db.executemany("INSERT OR IGNORE INTO trades VALUES(?,?,?,?,?,?,?,?)",
                            [(t["sig"], mint, int(t["ts"]), t["wallet"], int(t["is_buy"]), t["sol"], t["tokens"], t.get("slot"))
                             for t in trades])
        self.db.commit()

    def trades_since(self, mint, ts):
        rows = self.db.execute("SELECT * FROM trades WHERE mint=? AND ts>=? ORDER BY ts", (mint, ts)).fetchall()
        return [{"sig": r["sig"], "ts": r["ts"], "wallet": r["wallet"], "is_buy": bool(r["is_buy"]), "sol": r["sol"],
                 "tokens": r["tokens"], "slot": r["slot"]} for r in rows]

    def last_trade_sig(self, mint):
        return self.get_meta("lastsig:" + mint)

    def set_last_trade_sig(self, mint, sig):
        self.set_meta("lastsig:" + mint, sig)

    # --- grabador de histórico
    def rec_get(self, mint):
        return self.db.execute("SELECT * FROM rec_tokens WHERE mint=?", (mint,)).fetchone()

    def rec_add(self, mint, curve, creator, name, symbol, created_ts, now, progress):
        self.db.execute("INSERT OR IGNORE INTO rec_tokens(mint,curve,creator,name,symbol,created_ts,first_ts,first_progress,last_ts) "
                        "VALUES(?,?,?,?,?,?,?,?,?)", (mint, curve, creator, name, symbol, created_ts, now, progress, now))
        self.db.commit()

    def rec_point(self, mint, ts, progress, price, mcap, vsol, vtok, liq, phase, sol_usd):
        self.db.execute("INSERT OR REPLACE INTO rec_path VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (mint, int(ts), progress, price, mcap, vsol, vtok, liq, phase, sol_usd))
        self.db.execute("UPDATE rec_tokens SET last_ts=? WHERE mint=?", (int(ts), mint))
        self.db.commit()

    def rec_complete(self, mint, ts):
        self.db.execute("UPDATE rec_tokens SET completed_ts=COALESCE(completed_ts,?) WHERE mint=?", (int(ts), mint))
        self.db.commit()

    def rec_set_feat(self, mint, feat, ts):
        self.db.execute("UPDATE rec_tokens SET feat=?, feat_ts=? WHERE mint=?", (json.dumps(feat), int(ts), mint))
        self.db.commit()

    def rec_active(self, now, post_s, stale_s):
        """Tokens a seguir: en curva y vistos hace poco, o migrados dentro de la ventana posterior."""
        rows = self.db.execute("SELECT * FROM rec_tokens").fetchall()
        out = []
        for r in rows:
            if r["completed_ts"]:
                if now - r["completed_ts"] <= post_s:
                    out.append(r)
            elif now - r["last_ts"] <= stale_s:
                out.append(r)
        return out

    def rec_path_of(self, mint):
        return [dict(r) for r in self.db.execute("SELECT * FROM rec_path WHERE mint=? ORDER BY ts", (mint,)).fetchall()]

    def rec_all(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM rec_tokens ORDER BY first_ts").fetchall()]

    # --- caché de wallets
    def get_wallet(self, addr, max_age, now):
        r = self.db.execute("SELECT ts,data FROM wallet_cache WHERE addr=?", (addr,)).fetchone()
        if r and now - r["ts"] <= max_age:
            return json.loads(r["data"])
        return None

    def put_wallet(self, addr, data, now):
        self.db.execute("INSERT OR REPLACE INTO wallet_cache VALUES(?,?,?)", (addr, now, json.dumps(data)))
        self.db.commit()
