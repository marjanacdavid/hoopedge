"""Tracking tacnosti: cuva projekcije, ocjenjuje ih prema stvarnim rezultatima i racuna statistiku.

SQLite fajl (env HOOPEDGE_DB, default data/hoopedge.db). NAPOMENA: na besplatnom Renderu je disk
privremen (briše se pri restartu/deployu) - za trajne podatke koristi Render Disk ili vanjsku bazu,
a /api/tracking/export.csv za rucni backup.
"""
import csv
import io
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone

log = logging.getLogger("hoopedge.tracking")
SCHEMA = """
CREATE TABLE IF NOT EXISTS picks(
  id INTEGER PRIMARY KEY AUTOINCREMENT, pkey TEXT UNIQUE,
  created_at REAL, player_id INTEGER, name TEXT, team TEXT, opponent TEXT, market TEXT,
  game_time TEXT, game_date TEXT, projection REAL, line REAL, side TEXT, lean TEXT,
  win_chance REAL, market_prob REAL, dtm REAL, price REAL, books INTEGER,
  b2b INTEGER, spread REAL, total REAL,
  status TEXT DEFAULT 'pending', actual REAL, result TEXT, proj_error REAL, graded_at REAL);
CREATE INDEX IF NOT EXISTS idx_status ON picks(status);
"""


def _dt(v):
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


class Tracker:
    def __init__(self, path=None):
        self.path = path or os.getenv("HOOPEDGE_DB", "data/hoopedge.db")
        d = os.path.dirname(self.path)
        if d:
            os.makedirs(d, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.db.executescript(SCHEMA)
        self.last_grade = 0.0

    # ---------- upis ----------
    def record(self, projections):
        """Prvi snimak po (igrac, trziste, utakmica) se cuva; kasnije promjene linije ga ne prepisuju."""
        n = 0
        with self.lock:
            for r in projections:
                if not r.game_time:
                    continue
                key = f"{r.player_id}|{r.market}|{r.game_time}"
                cur = self.db.execute(
                    """INSERT OR IGNORE INTO picks(pkey,created_at,player_id,name,team,opponent,market,game_time,game_date,
                       projection,line,side,lean,win_chance,market_prob,dtm,price,books,b2b,spread,total)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (key, time.time(), r.player_id, r.name, r.team, r.opponent, r.market, r.game_time, r.game_date,
                     r.projection, r.line, r.pick_side, r.lean, r.win_chance, r.market_prob, r.dtm, r.odds_price,
                     r.books, int(bool(r.b2b)), r.spread, r.game_total))
                n += cur.rowcount
            self.db.commit()
        return n

    # ---------- ocjenjivanje ----------
    def grade(self, provider, min_interval=1800, max_players=40):
        if time.time() - self.last_grade < min_interval:
            return 0
        self.last_grade = time.time()
        now = datetime.now(timezone.utc)
        with self.lock:
            pending = [dict(x) for x in self.db.execute("SELECT * FROM picks WHERE status='pending'")]
        due = [p for p in pending if (_dt(p["game_time"]) and (now - _dt(p["game_time"])).total_seconds() > 4 * 3600)]
        by_player = {}
        for p in due:
            by_player.setdefault(p["player_id"], []).append(p)
        graded = 0
        sy = provider._season_year()
        for pid, picks in list(by_player.items())[:max_players]:
            rows = []
            for season in (sy, sy - 1):
                try:
                    rows += provider._gamelog_season(pid, season)
                except Exception:
                    continue
            for p in picks:
                t = _dt(p["game_time"])
                match = [r for r in rows if _dt(r.get("date")) and abs((_dt(r["date"]) - t).total_seconds()) <= 8 * 3600]
                if not match:
                    if (now - t).total_seconds() > 30 * 3600:   # nema reda ni 30h kasnije -> igrac nije igrao
                        self._settle(p["id"], "void", None, None, None)
                        graded += 1
                    continue
                row = match[0]
                actual = {"PTS": row["pts"], "AST": row["ast"], "REB": row["reb"],
                          "PA": row["pts"] + row["ast"], "3PM": row.get("tpm")}.get(p["market"])
                if actual is None:
                    continue
                result = None
                if p["line"] is not None and p["side"]:
                    if actual == p["line"]: result = "PUSH"
                    elif (actual > p["line"]) == (p["side"] == "OVER"): result = "WIN"
                    else: result = "LOSS"
                self._settle(p["id"], "graded", actual, result, actual - p["projection"])
                graded += 1
        return graded

    def _settle(self, pid, status, actual, result, err):
        with self.lock:
            self.db.execute("UPDATE picks SET status=?,actual=?,result=?,proj_error=?,graded_at=? WHERE id=?",
                            (status, actual, result, err, time.time(), pid))
            self.db.commit()

    # ---------- statistika ----------
    def _rows(self, where="1=1", args=()):
        with self.lock:
            return [dict(x) for x in self.db.execute(f"SELECT * FROM picks WHERE {where}", args)]

    @staticmethod
    def _roi(rows):
        units = 0.0
        for r in rows:
            if r["result"] == "WIN": units += (r["price"] or 1.91) - 1.0
            elif r["result"] == "LOSS": units -= 1.0
        decided = [r for r in rows if r["result"] in ("WIN", "LOSS")]
        return round(units / len(decided) * 100, 1) if decided else None

    def summary(self):
        graded = self._rows("status='graded'")
        out = {"total_recorded": len(self._rows()), "graded": len(graded), "markets": {}, "bets": {}, "calibration": []}
        for m in ("PTS", "AST", "REB", "3PM", "PA"):
            g = [r for r in graded if r["market"] == m and r["proj_error"] is not None]
            if g:
                out["markets"][m] = {"n": len(g),
                                     "mae": round(sum(abs(r["proj_error"]) for r in g) / len(g), 2),
                                     "bias": round(sum(r["proj_error"] for r in g) / len(g), 2)}
        bets = [r for r in graded if r["lean"] in ("OVER", "UNDER") and r["result"] in ("WIN", "LOSS", "PUSH")]
        wl = [r for r in bets if r["result"] in ("WIN", "LOSS")]
        out["bets"] = {"n": len(bets), "wins": sum(r["result"] == "WIN" for r in bets),
                       "losses": sum(r["result"] == "LOSS" for r in bets), "pushes": sum(r["result"] == "PUSH" for r in bets),
                       "hit_rate": round(sum(r["result"] == "WIN" for r in wl) / len(wl) * 100, 1) if wl else None,
                       "roi_pct": self._roi(bets)}
        with_line = [r for r in graded if r["win_chance"] is not None and r["result"] in ("WIN", "LOSS")]
        for lo, hi in ((50, 55), (55, 60), (60, 65), (65, 101)):
            b = [r for r in with_line if lo <= r["win_chance"] < hi]
            if b:
                out["calibration"].append({"win_chance_range": f"{lo}-{min(hi,100)}%", "n": len(b),
                                           "predicted_pct": round(sum(r["win_chance"] for r in b) / len(b), 1),
                                           "actual_pct": round(sum(r["result"] == "WIN" for r in b) / len(b) * 100, 1)})
        return out

    def signals(self, min_n=20):
        """Smart-signal stil: gdje je model istorijski bio uspjesniji (trziste x strana x Win Chance x DTM)."""
        rows = [r for r in self._rows("status='graded'") if r["lean"] in ("OVER", "UNDER") and r["result"] in ("WIN", "LOSS")]
        def bucket(v, edges):
            for lo, hi in zip(edges, edges[1:]):
                if lo <= v < hi: return f"{lo}-{hi if hi < 999 else '+'}"
            return None
        groups = {}
        for r in rows:
            k = (r["market"], r["side"], bucket(r["win_chance"] or 0, [50, 55, 60, 65, 999]), bucket(r["dtm"] or 0, [3, 6, 9, 13, 999]))
            if None in k: continue
            groups.setdefault(k, []).append(r)
        out = []
        for (m, side, wc, dtm), g in groups.items():
            hit = sum(r["result"] == "WIN" for r in g) / len(g) * 100
            roi = self._roi(g)
            out.append({"market": m, "side": side, "win_chance": wc, "dtm": dtm, "n": len(g),
                        "hit_rate": round(hit, 1), "roi_pct": roi,
                        "signal": bool(len(g) >= min_n and hit >= 55 and (roi or 0) > 0)})
        out.sort(key=lambda x: (x["signal"], x["hit_rate"]), reverse=True)
        return {"min_n": min_n, "note": "Signal = n >= min_n, hit rate >= 55% i pozitivan ROI. Mali uzorci su sum, ne signal.", "groups": out}

    def picks(self, status=None, limit=100):
        where, args = ("status=?", (status,)) if status else ("1=1", ())
        with self.lock:
            return [dict(x) for x in self.db.execute(f"SELECT * FROM picks WHERE {where} ORDER BY id DESC LIMIT ?", (*args, limit))]

    def export_csv(self):
        rows = self._rows()
        buf = io.StringIO()
        if rows:
            w = csv.DictWriter(buf, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
        return buf.getvalue()
