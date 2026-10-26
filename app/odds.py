"""Linije za player props (PTS/REB/AST) preko The Odds API.

Env varijable:
  ODDS_API_KEY           kljuc (NIKAD u kodu) - bez njega je modul iskljucen
  ODDS_MARKETS           default "player_points"  (dodaj player_rebounds,player_assists - svaki market kosta kredite)
  ODDS_REGIONS           default "us"
  ODDS_REFRESH_SECONDS   default 43200 (12h)  - koliko cesto se smije trositi kredit
  ODDS_MIN_REMAINING     default 30 - kad preostalih kredita padne ispod ovoga, prestaje dohvatanje
  ODDS_HORIZON_HOURS     default 30 - uzimaju se samo utakmice koje pocinju u tom roku
Trosak jednog osvjezavanja = broj utakmica x broj marketa x broj regiona (lista utakmica je besplatna).
"""
import logging
import os
import re
import time
import unicodedata
from datetime import datetime, timezone
from statistics import median

import requests

log = logging.getLogger("hoopedge.odds")
BASE = "https://api.the-odds-api.com/v4/sports/basketball_nba"
MARKET_KEYS = {"player_points": "PTS", "player_rebounds": "REB", "player_assists": "AST",
               "player_threes": "3PM", "player_points_assists": "PA"}
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z ]", " ", s)
    return " ".join(w for w in s.split() if w not in SUFFIXES)


def parse_dt(v):
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


class OddsProvider:
    def __init__(self):
        self.key = os.getenv("ODDS_API_KEY", "").strip()
        self.markets = [m.strip() for m in os.getenv("ODDS_MARKETS", "player_points").split(",") if m.strip() in MARKET_KEYS]
        self.regions = os.getenv("ODDS_REGIONS", "us").strip() or "us"
        self.ttl = int(os.getenv("ODDS_REFRESH_SECONDS", "43200"))
        self.min_remaining = int(os.getenv("ODDS_MIN_REMAINING", "30"))
        self.horizon_h = float(os.getenv("ODDS_HORIZON_HOURS", "30"))
        self.session = requests.Session()
        self.want_game_lines = os.getenv("ODDS_GAME_LINES", "1") != "0"
        self.game_lines = []     # [ {commence, home, away, total, home_spread} ]
        self.lines = {}          # (market, normalized name) -> [ {commence, line, over, under, books} ]
        self.fetched_at = 0.0
        self.status = {"enabled": bool(self.key), "markets": self.markets, "remaining": None,
                       "last_cost": None, "events": 0, "props": 0, "error": None, "fetched_at": None}

    # ---------- HTTP ----------
    def _clean(self, msg: str) -> str:
        return msg.replace(self.key, "***") if self.key else msg

    def _get(self, path, params=None):
        try:
            r = self.session.get(BASE + path, params={**(params or {}), "apiKey": self.key}, timeout=(3, 12))
        except requests.RequestException as e:
            raise RuntimeError(self._clean(f"Odds API network: {type(e).__name__}"))
        rem = r.headers.get("x-requests-remaining")
        if rem is not None:
            try: self.status["remaining"] = float(rem)
            except ValueError: pass
        last = r.headers.get("x-requests-last")
        if last is not None:
            try: self.status["last_cost"] = float(last)
            except ValueError: pass
        if r.status_code in (401, 403):
            raise RuntimeError("Odds API: nevazeci ili neaktivan kljuc")
        if r.status_code == 429:
            raise RuntimeError("Odds API: rate limit / kredit potrosen")
        if r.status_code >= 400:
            raise RuntimeError(f"Odds API HTTP {r.status_code}")
        return r.json()

    # ---------- refresh ----------
    def refresh_if_due(self):
        if not self.key or not self.markets:
            return False
        if time.time() - self.fetched_at < self.ttl:
            return False
        rem = self.status["remaining"]
        if rem is not None and rem < self.min_remaining:
            self.status["error"] = f"Preostalo kredita ({rem:.0f}) ispod ODDS_MIN_REMAINING; dohvatanje pauzirano."
            self.fetched_at = time.time()
            return False
        try:
            self._fetch()
            self.status["error"] = None
            self.fetched_at = time.time()
            self.status["fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        except Exception as e:
            self.status["error"] = self._clean(str(e))[:200]
            self.fetched_at = time.time() - self.ttl + 900   # pokusaj ponovo za 15 min
            return False
        return True

    def _fetch(self):
        events = self._get("/events", {"dateFormat": "iso"})          # besplatno
        now = datetime.now(timezone.utc)
        soon = []
        for e in events:
            t = parse_dt(e.get("commence_time"))
            if t and 0 <= (t - now).total_seconds() <= self.horizon_h * 3600:
                soon.append((t, e))
        soon.sort(key=lambda x: x[0])
        per_event = len(self.markets) * len(self.regions.split(","))
        rem = self.status["remaining"]
        if rem is not None:
            affordable = int(max(0, rem - self.min_remaining) // per_event)
            soon = soon[:affordable]
        new_lines = {}
        fetched = 0
        for t, e in soon:
            data = self._get(f"/events/{e['id']}/odds", {
                "regions": self.regions, "markets": ",".join(self.markets),
                "oddsFormat": "decimal", "dateFormat": "iso"})
            self._ingest(t, data, new_lines)
            fetched += 1
        self.status["events"] = fetched
        self.status["props"] = len(new_lines)
        if new_lines or not soon:
            self.lines = new_lines
        if self.want_game_lines:
            try:
                self._fetch_game_lines()
            except Exception as e:
                log.warning("game lines failed: %s", self._clean(str(e)))

    def _fetch_game_lines(self):
        """Total i spread za sve utakmice jednim pozivom (2 kredita po regionu)."""
        cost = 2 * len(self.regions.split(","))
        rem = self.status["remaining"]
        if rem is not None and rem - cost < self.min_remaining:
            return
        data = self._get("/odds", {"regions": self.regions, "markets": "totals,spreads",
                                    "oddsFormat": "decimal", "dateFormat": "iso"})
        out = []
        for ev in data:
            t = parse_dt(ev.get("commence_time"))
            if not t:
                continue
            home, away = ev.get("home_team", ""), ev.get("away_team", "")
            totals, spreads = [], []
            for bk in ev.get("bookmakers") or []:
                for mk in bk.get("markets") or []:
                    for oc in mk.get("outcomes") or []:
                        pt = oc.get("point")
                        if pt is None:
                            continue
                        if mk.get("key") == "totals" and oc.get("name") == "Over":
                            totals.append(float(pt))
                        elif mk.get("key") == "spreads" and oc.get("name") == home:
                            spreads.append(float(pt))
            if totals or spreads:
                out.append({"commence": t, "home": norm_name(home), "away": norm_name(away),
                            "total": median(totals) if totals else None,
                            "home_spread": median(spreads) if spreads else None})
        self.game_lines = out
        self.status["game_lines"] = len(out)

    def game_line(self, home_nick, away_nick, game_time):
        """Total/spread utakmice; timovi se prepoznaju po nadimku (Cavaliers, Trail Blazers...)."""
        hn, an, t = norm_name(home_nick), norm_name(away_nick), parse_dt(game_time)
        if not hn or not an:
            return None
        for g in self.game_lines:
            if g["home"].endswith(hn) and g["away"].endswith(an) and (t is None or abs((g["commence"] - t).total_seconds()) <= 6 * 3600):
                return g
        return None

    def _ingest(self, commence, data, out):
        acc = {}  # (market, player, point) -> {book: {"Over": price, "Under": price}}
        for bk in data.get("bookmakers") or []:
            for mk in bk.get("markets") or []:
                market = MARKET_KEYS.get(mk.get("key"))
                if not market:
                    continue
                for o in mk.get("outcomes") or []:
                    side, point, price = o.get("name"), o.get("point"), o.get("price")
                    player = norm_name(o.get("description") or "")
                    if side not in ("Over", "Under") or point is None or price is None or not player:
                        continue
                    acc.setdefault((market, player, float(point)), {}).setdefault(bk.get("key"), {})[side] = float(price)
        by_player = {}
        for (market, player, point), books in acc.items():
            by_player.setdefault((market, player), {})[point] = books
        for key, points in by_player.items():
            all_pts = sorted(points)
            mid = median(all_pts)
            # konsenzus linija: ona koju nudi najvise kladionica (izjednaceno -> bliza medijani)
            line = max(all_pts, key=lambda p: (len(points[p]), -abs(p - mid)))
            books = points[line]
            overs = [b["Over"] for b in books.values() if "Over" in b]
            unders = [b["Under"] for b in books.values() if "Under" in b]
            out.setdefault(key, []).append({
                "commence": commence, "line": line, "books": len(books),
                "over": median(overs) if overs else None,
                "under": median(unders) if unders else None,
            })

    # ---------- lookup ----------
    def lookup(self, market, player_name, game_time):
        cands = self.lines.get((market, norm_name(player_name)))
        if not cands:
            return None
        t = parse_dt(game_time)
        if t:
            best = min(cands, key=lambda c: abs((c["commence"] - t).total_seconds()))
            return best if abs((best["commence"] - t).total_seconds()) <= 3 * 3600 else None
        return cands[0] if len(cands) == 1 else None

    def public_status(self):
        s = dict(self.status)
        s["cached_props"] = len(self.lines)
        return s
