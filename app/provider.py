import os, re, time, logging
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests
from .models import PlayerInput
from . import posdef

BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
WEB = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba"
log = logging.getLogger("hoopedge.provider")

class ESPNFreeProvider:
    """ESPN public/free endpoints. No API key. Undocumented endpoints are cached."""
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "HOOPEDGE/2.1", "Accept": "application/json"})
        self.cache = {}
        self.ttl = 900
        # Render-friendly limits: keep the first request comfortably below the platform proxy timeout.
        self.max_build_seconds = 22.0
        self.max_players_per_team = 13      # kandidati; rotacija se filtrira po minutama
        self.min_rotation_minutes = float(os.getenv("HOOPEDGE_MIN_MINUTES", "10"))  # igraci ispod ovoga se ne prikazuju
        self.injuries_cache = (0.0, {})
        self.team_played = {}   # team_id -> skup datuma odigranih utakmica (iz historijskih scoreboarda)
        self.projection_cache = (0.0, [])
        self.team_metrics_cache = (0.0, {})
        # Odbrana po pozicijama: box scoreovi zavrsenih utakmica se ne mijenjaju, pa se kesiraju trajno.
        self.posdef_cache = (0.0, {})
        self.posdef_meta = (0, 0)
        self.posdef_profiles = {}  # team_id -> doprinos igraca odbrani (za korekciju zbog povreda)
        self.posdef_days = {}      # datum -> [(event_id, datum_iso)] iz zavrsenih scoreboarda
        self.box_cache = {}        # event_id -> parsirani box score ({} = neupotrebljiv)
        self.pos_lookup = {}       # athlete_id -> pozicija (rezerva ako box score nema poziciju)
        self.posdef_days_window = int(os.getenv("HOOPEDGE_POSDEF_DAYS", "45"))
        self.posdef_max_new_boxes = int(os.getenv("HOOPEDGE_POSDEF_MAX_BOXES", "80"))
        self.last_errors = []
        self.last_stats = {"scoreboard":0,"rosters":0,"gamelogs":0,"players":0,"games":0,"teams":0,"eligible_players":0,"historical_scoreboards":0,"team_metrics":0}

    def _get(self, url, params=None):
        key = url + "?" + "&".join(f"{k}={v}" for k,v in sorted((params or {}).items()))
        now = time.time()
        if key in self.cache and now - self.cache[key][0] < self.ttl:
            return self.cache[key][1]

        last_exc = None
        # ESPN occasionally returns transient 5xx/429 responses from its public
        # endpoints. One short retry is enough to make Render much more reliable
        # without materially increasing normal request time.
        for attempt in range(2):
            try:
                r = self.session.get(
                    url,
                    params=params,
                    timeout=(2.5, 5),
                )
                if r.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                    time.sleep(0.15)
                    continue
                r.raise_for_status()
                data = r.json()
                self.cache[key] = (time.time(), data)
                return data
            except Exception as e:
                last_exc = e
                if attempt == 0:
                    time.sleep(0.1)
                    continue

        msg = f"{url} params={params}: {type(last_exc).__name__}: {last_exc}"
        log.error("ESPN request failed: %s", msg)
        self.last_errors.append(msg)
        self.last_errors = self.last_errors[-10:]
        raise last_exc

    def dates(self):
        # Use user's local calendar date. Querying local today/tomorrow is more intuitive for the UI.
        now = datetime.now(ZoneInfo("Europe/Sarajevo"))
        return [now.date(), now.date() + timedelta(days=1)]

    def scoreboard(self, day):
        data = self._get(f"{BASE}/scoreboard", {"dates": day.strftime('%Y%m%d')})
        events = data.get("events", [])
        self.last_stats["scoreboard"] += 1
        return events

    @staticmethod
    def _num(v, default=0.0):
        try: return float(str(v).replace(",", ""))
        except Exception: return default

    @staticmethod
    def _season_year():
        """ESPN broji sezonu po godini u kojoj zavrsava (2026-27 -> 2027)."""
        now = datetime.now(ZoneInfo("America/New_York"))
        return now.year + 1 if now.month >= 10 else now.year

    def _parse_item(self, item, labels, names, meta):
        """Jedan red game loga -> dict ili None. Radi za oba ESPN rasporeda."""
        if not isinstance(item, dict):
            return None
        eid = str(item.get("eventId") or item.get("id") or "")
        m = meta.get(eid) if isinstance(meta.get(eid), dict) else {}
        src = {**m, **item}
        stat_labels = labels[3:] if len(labels) >= 4 else labels
        stat_names = names[3:] if len(names) >= 4 else names
        stats = item.get("stats") or item.get("statistics") or []
        if isinstance(stats, dict): stats = stats.get("statistics") or stats.get("stats") or []
        if not isinstance(stats, list): return None
        if len(stats) == len(labels): slabels, snames = labels, names
        elif len(stats) == len(stat_labels): slabels, snames = stat_labels, stat_names
        else:
            slabels = stat_labels[-len(stats):] if stats else []
            snames = stat_names[-len(stats):] if stats else []
        mapping = {}
        for i, v in enumerate(stats):
            if i < len(slabels): mapping[slabels[i]] = v
            if i < len(snames): mapping[snames[i]] = v
        def pick(*keys):
            for k in keys:
                if k in mapping: return mapping[k]
            return None
        pts = self._num(pick("PTS", "POINTS", "points"), -1)
        ast = self._num(pick("AST", "ASSISTS", "assists"), -1)
        reb = self._num(pick("REB", "REBOUNDS", "rebounds"), -1)
        mins = self._num(pick("MIN", "MINUTES", "minutes"), 0)
        if not (0 <= pts <= 100): return None
        row = {"pts": pts, "ast": ast if 0 <= ast <= 40 else 0.0, "reb": reb if 0 <= reb <= 40 else 0.0, "min": mins if 0 <= mins <= 60 else 0}
        tpm = None
        for k, v in mapping.items():
            lk = str(k).lower()
            if lk in ("3pt", "3ptm", "3pm") or lk.startswith("threepointfieldgoalsmade"):
                mt = re.match(r"\s*(\d+)(?:\s*-\s*\d+)?\s*$", str(v))
                if mt:
                    tpm = float(mt.group(1)); break
        if tpm is not None and 0 <= tpm <= 20:
            row["tpm"] = tpm
        for out, keyset in (("fga", ("FGA", "fieldgoalsattempted")), ("fta", ("FTA", "freethrowsattempted")), ("tov", ("TO", "TOV", "turnovers")), ("usg", ("USG%", "USG"))):
            val = pick(*keyset)
            if val is not None:
                n = self._num(val, -1)
                if n >= 0: row[out] = n
        row["eid"] = eid
        row["stype"] = str(src.get("_stype") or "")
        row["date"] = str(src.get("date") or src.get("gameDate") or "")
        at_vs = str(src.get("atVs") or "").lower()
        row["home"] = str(src.get("homeAway") or src.get("home_away") or "").lower() == "home" or at_vs == "vs"
        opp = src.get("opponent")
        if isinstance(opp, dict):
            row["opp_id"] = str(opp.get("id") or src.get("opponentId") or "")
            row["opp"] = str(opp.get("abbreviation") or "").upper()
        else:
            row["opp_id"] = str(src.get("opponentId") or "")
            row["opp"] = str(opp or "").upper() if isinstance(opp, str) else ""
        return row

    def _gamelog_season(self, athlete_id, season):
        """Redovi game loga za jednu sezonu (redoslijed kako ga ESPN vraca)."""
        data = self._get(f"{WEB}/athletes/{athlete_id}/gamelog", {"season": season})
        labels = [str(x).upper() for x in (data.get("labels") or [])]
        names = [str(x).lower() for x in (data.get("names") or [])]
        events = data.get("events") or []
        meta = events if isinstance(events, dict) else {}
        items = [{**v, "eventId": k} for k, v in events.items() if isinstance(v, dict)] if isinstance(events, dict) else list(events)
        rows = [r for r in (self._parse_item(it, labels, names, meta) for it in items) if r]
        if not rows:
            # drugi raspored: seasonTypes[].categories[].events[] + metapodaci iz data["events"]
            items = []
            for st in data.get("seasonTypes") or []:
                for cat in (st or {}).get("categories") or []:
                    for ev in (cat or {}).get("events") or []:
                        if isinstance(ev, dict): items.append({**ev, "_stype": str((st or {}).get("displayName") or "")})
            rows = [r for r in (self._parse_item(it, labels, names, meta) for it in items) if r]
        stmap = self._season_type_map(data)
        for r in rows:
            r["season"] = season
            r["stype"] = stmap.get(r.get("eid", ""), r.get("stype", ""))
        # preseason (i izlozbene) utakmice ne ulaze u formu, minute ni H2H
        return [r for r in rows if "preseason" not in r["stype"].lower()]

    @staticmethod
    def _season_type_map(data):
        """eventId -> naziv tipa sezone ('Regular Season', 'Preseason', 'Postseason')."""
        out = {}
        for st in data.get("seasonTypes") or []:
            name = str((st or {}).get("displayName") or "")
            for cat in (st or {}).get("categories") or []:
                for ev in (cat or {}).get("events") or []:
                    if isinstance(ev, dict):
                        eid = str(ev.get("eventId") or ev.get("id") or "")
                        if eid: out[eid] = name
        return out

    def _gamelog(self, athlete_id):
        """Najnovije utakmice prvo. Rano u sezoni dopunjeno prosloscu sezonom (do ~20 utakmica)."""
        sy = self._season_year()
        rows = []
        for season in (sy, sy - 1):
            try:
                rows += self._gamelog_season(athlete_id, season)
            except Exception:
                continue
            if len(rows) >= 20:
                break
        if rows:
            self.last_stats["gamelogs"] += 1
        return rows

    def _h2h(self, athlete_id, oppteam, rows, deadline):
        """Prosjek igraca protiv ovog protivnika (zadnjih max 6 utakmica, 2 sezone)."""
        opp_id = str((oppteam or {}).get("id") or "")
        opp_abbr = str((oppteam or {}).get("abbreviation") or "").upper()
        if not opp_id and not opp_abbr:
            return {}
        def match(r):
            if opp_id and r.get("opp_id"): return r["opp_id"] == opp_id
            return bool(opp_abbr) and r.get("opp") == opp_abbr
        def pool(rs): return [r for r in rs if match(r) and r.get("min", 0) >= 8 and (not r.get("stype") or "regular" in r["stype"].lower())]
        games = pool(rows)
        seasons = [r.get("season") for r in rows if r.get("season")]
        if seasons:  # do 2 starije sezone, dok ne skupimo 6 susreta
            older = min(seasons) - 1
            for _ in range(2):
                if len(games) >= 6 or time.time() >= deadline - 5:
                    break
                try:
                    games += pool(self._gamelog_season(athlete_id, older))
                except Exception:
                    pass
                older -= 1
        games = games[:6]
        if not games:
            return {"games": 0}
        n = len(games)
        avg = lambda k: round(sum(g[k] for g in games) / n, 2)
        return {"games": n, "pts": avg("pts"), "ast": avg("ast"), "reb": avg("reb"), "log": games}

    def _rest_info(self, tid, day, upcoming):
        """(dani odmora, back-to-back, 3 utakmice u 4 dana) za tim na dati datum."""
        dates = set(self.team_played.get(str(tid), set())) | set(upcoming.get(str(tid), set()))
        prev = [d for d in dates if d < day]
        if not prev:
            return None, False, False
        gap = (day - max(prev)).days
        three = sum(1 for d in prev if (day - d).days <= 3) >= 2
        return gap - 1, gap == 1, three

    @staticmethod
    def _espn_odds(comp, team_abbr):
        """(total, spread iz perspektive tima) iz ESPN scoreboard 'odds', ako postoji."""
        for o in (comp or {}).get("odds") or []:
            try: total = float(o["overUnder"]) if o.get("overUnder") is not None else None
            except Exception: total = None
            details, spread = str(o.get("details") or ""), None
            mt = re.search(r"([A-Z]{2,4})\s*([+-]\d+(?:\.\d+)?)", details)
            if mt:
                val = float(mt.group(2))
                spread = val if mt.group(1) == team_abbr else -val
            elif details.strip().upper() in ("EVEN", "PK", "PICK", "PICKEM"):
                spread = 0.0
            if total is not None or spread is not None:
                return total, spread
        return None, None

    @staticmethod
    def _game_dict(x):
        """Jedna odigrana utakmica za prikaz grafikona (bez internih polja)."""
        return {"date": x.get("date", ""), "opp": x.get("opp", ""), "home": bool(x.get("home")), "min": x.get("min"),
                "pts": x.get("pts"), "ast": x.get("ast"), "reb": x.get("reb"), "tpm": x.get("tpm"),
                "po": "post" in str(x.get("stype", "")).lower()}

    @staticmethod
    def _is_out(status):
        return str(status or "").lower().startswith(("out", "doubtful"))

    def _injuries(self):
        """{athlete_id: status} iz ESPN injuries feeda. Greska nije fatalna."""
        cached_at, cached = self.injuries_cache
        if cached and time.time() - cached_at < 600:
            return cached
        result = {}
        try:
            data = self._get(f"{BASE}/injuries")
            for team in data.get("injuries") or []:
                for inj in (team or {}).get("injuries") or []:
                    ath = inj.get("athlete") or {}
                    aid = str(ath.get("id") or "")
                    if not aid:
                        for link in ath.get("links") or []:
                            mt = re.search(r"/id/(\d+)", str((link or {}).get("href", "")))
                            if mt: aid = mt.group(1); break
                    status = inj.get("status") or (inj.get("type") or {}).get("description") or ""
                    if aid and status:
                        result[aid] = str(status)
        except Exception as e:
            log.warning("injuries feed failed: %s", e)
        self.injuries_cache = (time.time(), result)
        return result

    def _apply_injury_bumps(self, active, sidelined):
        """Saigraci koji igraju dobijaju dio produkcije igraca koji izostaju (umjereno, s capom)."""
        groups = {}
        for o in sidelined:
            if o.minutes >= 15:
                groups.setdefault((o.team, o.game_date), []).append(o)
        for p in active:
            outs = groups.get((p.team, p.game_date))
            if not outs:
                continue
            mates = [q for q in active if q.team == p.team and q.game_date == p.game_date]
            for key, attr, cap in (("pts", "last10", 3.0), ("ast", "ast_last10", 1.5), ("reb", "reb_last10", 1.5)):
                out_total = sum(getattr(o, attr) for o in outs)
                pool = sum(getattr(q, attr) for q in mates) or 1.0
                bump = min(cap, 0.35 * out_total * getattr(p, attr) / pool)
                setattr(p, f"injury_bump_{key}", round(bump, 2))
            p.injury_usage_bump = p.injury_bump_pts
            p.injured_teammates = [o.name for o in outs][:3]

    def debug_player(self, athlete_id, opp=""):
        sy = self._season_year()
        out = {"season_year": sy, "seasons": {}, "injury_status": self._injuries().get(str(athlete_id), "")}
        if opp:  # sve utakmice protiv tog protivnika (skraćenica ili ESPN id), 4 sezone unazad
            key, games = str(opp).upper(), []
            for season in range(sy, sy - 4, -1):
                try:
                    for r in self._gamelog_season(athlete_id, season):
                        if key in (r.get("opp", ""), r.get("opp_id", "")):
                            games.append({"season": season, "date": r.get("date"), "opp": r.get("opp"), "pts": r["pts"],
                                          "ast": r["ast"], "reb": r["reb"], "min": r["min"], "type": r.get("stype", "")})
                except Exception as e:
                    games.append({"season": season, "error": str(e)[:120]})
            ok = [g for g in games if "pts" in g]
            out["h2h_games"] = games
            out["h2h_avg_pts_all_listed"] = round(sum(g["pts"] for g in ok) / len(ok), 2) if ok else None
        for season in (sy, sy - 1):
            try:
                raw = self._get(f"{WEB}/athletes/{athlete_id}/gamelog", {"season": season})
                rows = self._gamelog_season(athlete_id, season)
                out["seasons"][str(season)] = {
                    "top_level_keys": sorted(raw.keys()),
                    "rows": len(rows),
                    "rows_with_opponent": sum(1 for r in rows if r.get("opp") or r.get("opp_id")),
                    "rows_by_type": {t: sum(1 for r in rows if r.get("stype") == t) for t in {r.get("stype", "") for r in rows}},
                    "sample_row": rows[:1],
                }
            except Exception as e:
                out["seasons"][str(season)] = {"error": str(e)[:200]}
        return out

    def _historical_team_metrics(self, days=14):
        """Build real team defensive/pace proxies from completed ESPN scoreboards.
        Pace is a scoring-environment proxy because public ESPN scoreboard data does
        not expose possessions. It is explicitly not labeled as official pace.
        """
        # Team metrics are only supporting inputs to the model. Cache them so
        # Render does not have to download ten historical scoreboards on every
        # new browser request or after the short projection cache expires.
        cached_at, cached_metrics = self.team_metrics_cache
        if cached_metrics and time.time() - cached_at < 1800:
            self.last_stats["team_metrics"] = len(cached_metrics)
            return cached_metrics

        now = datetime.now(ZoneInfo("Europe/Sarajevo"))
        days_list=[now.date()-timedelta(days=i) for i in range(1, days+1)]
        team={}; league_combined=[]
        def fetch(day):
            try: return day, self.scoreboard(day)
            except Exception: return day, []
        with ThreadPoolExecutor(max_workers=6) as ex:
            results=list(ex.map(fetch, days_list))
        played={}
        for day,events in results:
            self.last_stats["historical_scoreboards"] = self.last_stats.get("historical_scoreboards", 0) + 1
            for event in events:
                comp=(event.get("competitions") or [{}])[0]
                comps=comp.get("competitors") or []
                if len(comps)!=2: continue
                vals=[]
                if ((event.get("status") or {}).get("type") or {}).get("completed") is False:
                    continue  # nezavrsene utakmice ne ulaze u metrike
                for c in comps:
                    # ESPN scoreboard vraca score kao string ("112"), neki feedovi kao {"value": 112}
                    sc = c.get("score")
                    if isinstance(sc, dict): sc = sc.get("value", sc.get("displayValue", 0))
                    try: vals.append(float(sc))
                    except Exception: vals.append(0)
                if len(vals)!=2 or max(vals)<=0: continue
                combined=sum(vals); league_combined.append(combined)
                for idx,c in enumerate(comps):
                    tid=(c.get("team") or {}).get("id")
                    if not tid: continue
                    played.setdefault(str(tid),set()).add(day)
                    d=team.setdefault(str(tid),{"for":[],"against":[]})
                    d["for"].append(vals[idx]); d["against"].append(vals[1-idx])
        league_avg=float(np.mean(league_combined)) if league_combined else 224.0
        metrics={}
        league_team_avg=league_avg/2.0
        for tid,d in team.items():
            if not d["against"]: continue
            pf=float(np.mean(d["for"])); pa=float(np.mean(d["against"]))
            games=len(d["for"]); w=min(1.0, games/8.0)  # malo utakmica -> priblizi neutralnom
            # defense_factor >1 = tezi protivnik (prima manje poena od prosjeka lige); <1 = meksi.
            raw_def=league_team_avg/max(1.0,pa)
            raw_pace=(pf+pa)/max(1.0,league_avg)
            defense_factor=max(0.90,min(1.12,1.0+(raw_def-1.0)*w))
            pace_factor=max(0.90,min(1.12,1.0+(raw_pace-1.0)*w))
            metrics[tid]={"defense_factor":defense_factor,"pace_factor":pace_factor,"pf":pf,"pa":pa,"games":games}
        self.last_stats["team_metrics"]=len(metrics)
        self.team_played=played
        self.team_metrics_cache=(time.time(), metrics)
        return metrics
    def _fetch_box(self, eid):
        """Box score jedne utakmice -> parsirani dict, {} ako je neupotrebljiv, None ako zahtjev nije uspio."""
        for attempt in range(2):
            try:
                r = self.session.get(f"{BASE}/summary", params={"event": eid}, timeout=(2.5, 6))
                if r.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                    time.sleep(0.2)
                    continue
                r.raise_for_status()
                return posdef.parse_box(r.json(), self.pos_lookup) or {}
            except Exception:
                if attempt == 0:
                    time.sleep(0.1)
                    continue
        return None

    def _position_defense(self):
        """{team_id: {"games": n, "G": {PTS: f, ...}, "F": {...}, "C": {...}}} (vidi posdef.py).

        Koristi se box scoreove zadnjih HOOPEDGE_POSDEF_DAYS dana (zadano 45). Zavrseni box scoreovi
        se kesiraju trajno, pa svaki sljedeci krug povlaci samo nove utakmice. Rezultat se kesira 30 min.
        """
        cached_at, cached = self.posdef_cache
        if cached and time.time() - cached_at < 1800:
            self.last_stats["posdef_games"], self.last_stats["posdef_teams"] = self.posdef_meta
            return cached
        today = datetime.now(ZoneInfo("Europe/Sarajevo")).date()
        window = [today - timedelta(days=i) for i in range(1, self.posdef_days_window + 1)]

        def day_events(day):
            # stariji dani su zavrseni i ne mijenjaju se; zadnja 2 dana se uvijek osvjeze
            if day in self.posdef_days and day < today - timedelta(days=2):
                return day, self.posdef_days[day]
            try:
                events = self.scoreboard(day)
            except Exception:
                return day, self.posdef_days.get(day, [])
            keep = []
            for ev in events:
                if ((ev.get("status") or {}).get("type") or {}).get("completed") is not True:
                    continue
                season = ev.get("season") or {}
                if season.get("type") == 1 or str(season.get("slug") or "").lower() == "preseason":
                    continue   # preseason rotacije ne govore nista o regularnoj odbrani
                if ev.get("id"):
                    keep.append((str(ev["id"]), str(ev.get("date") or day.isoformat())))
            self.posdef_days[day] = keep
            return day, keep

        with ThreadPoolExecutor(max_workers=6) as ex:
            events = [e for _, evs in ex.map(day_events, window) for e in evs]

        wanted = {eid for eid, _ in events}
        self.box_cache = {k: v for k, v in self.box_cache.items() if k in wanted}   # drzi samo prozor
        missing = [eid for eid in wanted if eid not in self.box_cache][: self.posdef_max_new_boxes]
        if missing:
            with ThreadPoolExecutor(max_workers=6) as ex:
                for eid, box in zip(missing, ex.map(self._fetch_box, missing)):
                    if box is not None:
                        self.box_cache[eid] = box

        rows = []
        for eid, date in events:
            rows += posdef.box_to_rows(date, self.box_cache.get(eid))
        factors = posdef.compute_factors(rows)
        self.posdef_profiles = posdef.build_profiles(rows)
        self.last_stats["posdef_games"] = len(rows) // 2
        self.last_stats["posdef_teams"] = len(factors)
        if factors:
            self.posdef_cache = (time.time(), factors)
            self.posdef_meta = (len(rows) // 2, len(factors))
        return factors

    def _athlete_stats(self, athlete_id):
        """Optional season summary fallback. Never pollute the UI diagnostics with 404s."""
        try:
            year = self._season_year()
            url=f"{WEB}/athletes/{athlete_id}/stats"
            r=self.session.get(url, params={"season":year, "seasontype":2}, timeout=6)
            if r.status_code != 200:
                return {}
            data=r.json()
            vals={}
            cats=[c for c in (data.get("categories") or []) if isinstance(c, dict)]
            # 'totals' kategorija sadrzi SEZONSKE ZBIROVE (npr. 39 skokova ukupno) - to nisu prosjeci po utakmici
            avg_cats=[c for c in cats if "avg" in str(c.get("name") or c.get("displayName") or "").lower() or "average" in str(c.get("name") or c.get("displayName") or "").lower()]
            if not avg_cats:
                avg_cats=[c for c in cats if "total" not in str(c.get("name") or c.get("displayName") or "").lower()] or cats
            for cat in avg_cats:
                labels=cat.get("labels") or []
                totals=cat.get("totals") or []
                for i,label in enumerate(labels):
                    if i>=len(totals): continue
                    u=str(label).upper(); value=self._num(totals[i],-1)
                    if u=="PTS" and 0<=value<=100: vals["pts"]=value
                    elif u=="MIN" and 0<=value<=60: vals["min"]=value
                    elif u=="AST" and 0<=value<=40: vals["ast"]=value
                    elif u=="REB" and 0<=value<=40: vals["reb"]=value
                    elif "USG" in u and 0<=value<=60: vals["usage"]=value
            return vals
        except Exception:
            return {}

    def _roster(self, team_id):
        data = self._get(f"{BASE}/teams/{team_id}/roster")
        raw = data.get("athletes", [])
        # ESPN roster is usually position groups containing an `items` list.
        players=[]
        for item in raw:
            if isinstance(item, dict) and isinstance(item.get("items"), list):
                players.extend(x for x in item["items"] if isinstance(x, dict))
            elif isinstance(item, dict) and item.get("id"):
                players.append(item)
        self.last_stats["rosters"] += 1
        for pl in players:
            ab = (pl.get("position") or {}).get("abbreviation") if isinstance(pl.get("position"), dict) else None
            if ab and pl.get("id"):
                self.pos_lookup[str(pl["id"])] = ab
        return players

    def players(self):
        now=time.time()
        if now-self.projection_cache[0] < 60 and self.projection_cache[1]:
            return self.projection_cache[1]
        self.last_errors=[]
        self.last_stats={"scoreboard":0,"rosters":0,"gamelogs":0,"players":0,"games":0,"teams":0,"eligible_players":0,"historical_scoreboards":0,"team_metrics":0}
        out=[]
        # Historical team metrics are useful but are not required to build a
        # projection. They used to add 10 extra ESPN requests to the cold-start
        # request and could push Render over its gateway timeout. Use cached metrics
        # when available; otherwise the engine receives neutral factors.
        # Projekcije se racunaju u pozadinskoj niti (ne u HTTP zahtjevu), pa je
        # sigurno povuci historijske metrike ovdje; rezultat se kesira 30 min.
        try:
            team_metrics = self._historical_team_metrics()
        except Exception as e:
            self.last_errors.append(f"team metrics: {e}")
            team_metrics = {}
        try:
            pos_defense = self._position_defense()
        except Exception as e:
            self.last_errors.append(f"position defense: {e}")
            pos_defense = {}
        injuries = self._injuries()
        # povrijedjeni branioci protivnika omeksavaju faktor (koristi svjezu listu povreda, ne kesirani faktor)
        try:
            inj_weights = {aid: posdef.status_weight(st) for aid, st in injuries.items()}
            pos_defense = posdef.apply_injuries(pos_defense, self.posdef_profiles,
                                                {a: w for a, w in inj_weights.items() if w > 0}) if pos_defense else {}
        except Exception as e:
            self.last_errors.append(f"defender injuries: {e}")
        upcoming = {}   # team_id -> datumi utakmica iz scoreboarda danas/sutra
        build_deadline = time.time() + self.max_build_seconds
        for day in self.dates():
            if time.time() >= build_deadline:
                self.last_errors.append("Render time budget reached before all scheduled games were processed.")
                break
            try:
                events=self.scoreboard(day)
                self.last_stats["games"] += sum(1 for e in events if (e.get("competitions") or [{}])[0].get("competitors"))
            except Exception as e:
                self.last_errors.append(f"scoreboard {day}: {e}")
                continue
            for event in events:
                for c in ((event.get("competitions") or [{}])[0].get("competitors") or []):
                    t_id=(c.get("team") or {}).get("id")
                    if t_id: upcoming.setdefault(str(t_id),set()).add(day)
            team_jobs=[]
            teams_seen=set()
            for event in events:
                comp=(event.get("competitions") or [{}])[0]
                competitors=comp.get("competitors") or []
                if len(competitors)!=2: continue
                home=next((c for c in competitors if c.get("homeAway")=="home"), competitors[0])
                away=next((c for c in competitors if c.get("homeAway")=="away"), competitors[1])
                for side,opp in ((home,away),(away,home)):
                    tid=(side.get("team") or {}).get("id")
                    if tid and tid not in teams_seen:
                        teams_seen.add(tid)
                        team_jobs.append((day,event,side,opp,tid))
            with ThreadPoolExecutor(max_workers=10) as ex:
                futures={ex.submit(self._roster,tid):(day,event,side,opp) for day,event,side,opp,tid in team_jobs}
                roster_results=[]
                for f,meta in [(f,m) for f,m in futures.items()]:
                    try: roster_results.append((meta,f.result()))
                    except Exception as e: self.last_errors.append(f"roster {meta[0]}: {e}")
            athlete_jobs=[]
            for (day,event,side,opp),roster in roster_results:
                active=[a for a in roster if a.get("active",True) and a.get("id")]
                # Render cold starts need a bounded number of player log requests.
                # ESPN roster ordering puts the principal rotation players first in
                # the public roster feed; keep the first N active players per team.
                active=active[:self.max_players_per_team]
                for a in active:
                    athlete_jobs.append((day,event,side,opp,a))
            def build(job):
                day,event,side,opp,a=job
                aid=a.get("id")
                status=injuries.get(str(aid),"")
                try: logrows=self._gamelog(aid)
                except Exception as e: logrows=[]
                # Prefer game logs. Only call the season-summary endpoint when
                # the game log did not contain usable scoring data. This removes
                # one extra ESPN request for nearly every player and is important
                # on slower Render instances.
                pts=[x["pts"] for x in logrows if x.get("pts",-1)>=0]
                stats={}
                if not pts:
                    try: stats=self._athlete_stats(aid)
                    except Exception: stats={}
                ast=[x["ast"] for x in logrows if x.get("ast",-1)>=0]
                reb=[x["reb"] for x in logrows if x.get("reb",-1)>=0]
                mins=[x["min"] for x in logrows if x["min"]>0]
                if not pts and stats.get("pts",0)>0: pts=[float(stats["pts"])]
                if not ast and stats.get("ast",0)>0: ast=[float(stats["ast"])]
                if not reb and stats.get("reb",0)>0: reb=[float(stats["reb"])]
                if not pts: return None
                l5=sum(pts[:5])/min(5,len(pts)); l10=sum(pts[:10])/min(10,len(pts)); l20=sum(pts[:20])/min(20,len(pts))
                a5=sum(ast[:5])/min(5,len(ast)) if ast else 0.0; a10=sum(ast[:10])/min(10,len(ast)) if ast else 0.0; a20=sum(ast[:20])/min(20,len(ast)) if ast else 0.0
                r5=sum(reb[:5])/min(5,len(reb)) if reb else 0.0; r10=sum(reb[:10])/min(10,len(reb)) if reb else 0.0; r20=sum(reb[:20])/min(20,len(reb)) if reb else 0.0
                season=stats.get("pts") or (sum(pts)/len(pts))
                aseason=stats.get("ast") or (sum(ast)/len(ast) if ast else 0.0)
                rseason=stats.get("reb") or (sum(reb)/len(reb) if reb else 0.0)
                minutes=sum(mins[:10])/min(10,len(mins)) if mins else (stats.get("min") or 30)
                tpm=[x["tpm"] for x in logrows if x.get("tpm") is not None]
                pa=[x["pts"]+x["ast"] for x in logrows if x.get("ast",-1)>=0 and x["pts"]>=0]
                _avg=lambda v,n: (sum(v[:n])/min(n,len(v))) if v else 0.0
                _sy=max([x.get("season",0) for x in logrows] or [0])
                _cur=[x["tpm"] for x in logrows if x.get("tpm") is not None and x.get("season")==_sy] or tpm
                _std=lambda v,d: float(np.std(v[:10])) if len(v[:10])>1 else d
                mk_extra=dict(
                    games=[self._game_dict(x) for x in logrows if x.get("min",0)>0][:30],
                    ast_std=_std(ast,2.0), reb_std=_std(reb,2.5),
                    tpm_last5=round(_avg(tpm,5),2), tpm_last10=round(_avg(tpm,10),2), tpm_last20=round(_avg(tpm,20),2),
                    tpm_season=round(sum(_cur)/len(_cur),2) if _cur else 0.0, tpm_std=_std(tpm,1.2),
                    pa_last5=round(_avg(pa,5),2), pa_last10=round(_avg(pa,10),2), pa_last20=round(_avg(pa,20),2),
                    pa_season=round(season+aseason,2), pa_std=_std(pa,5.5))
                trend=l5-l20
                recent_std=float(np.std(pts[:10])) if len(pts[:10])>1 else 5.0
                home_pts=[r["pts"] for r in logrows if r.get("home") and r["pts"]>=0]
                away_pts=[r["pts"] for r in logrows if not r.get("home") and r["pts"]>=0]
                home_split=float(np.mean(home_pts)) if home_pts else None
                away_split=float(np.mean(away_pts)) if away_pts else None
                usage=stats.get("usage")
                usage_source="ESPN advanced" if usage is not None else "Estimated"
                if usage is None:
                    # Transparent scoring-volume proxy, not official USG%.
                    usage=max(12.0,min(35.0,20.0 + ((l10/max(1.0,minutes))-0.45)*16.0))
                name=a.get("fullName") or a.get("displayName") or f'{a.get("firstName","")} {a.get("lastName","")}'.strip()
                hs=a.get("headshot"); headshot=hs.get("href") if isinstance(hs,dict) else hs
                team=side.get("team",{}); oppteam=opp.get("team",{})
                tm=team_metrics.get(str(team.get("id")),{"pace_factor":1.0})
                om=team_metrics.get(str(oppteam.get("id")),{"defense_factor":1.0,"pace_factor":1.0})
                pace_factor=max(.90,min(1.12,(tm.get("pace_factor",1.0)+om.get("pace_factor",1.0))/2))
                defense_factor=om.get("defense_factor",1.0)
                h2h=self._h2h(aid,oppteam,logrows,build_deadline)
                _rd,_b2b,_three=self._rest_info((side.get("team") or {}).get("id"),day,upcoming)
                _,_opp_b2b,_=self._rest_info((opp.get("team") or {}).get("id"),day,upcoming)
                _total,_spread=self._espn_odds((event.get("competitions") or [{}])[0],team.get("abbreviation",""))
                ctx=dict(team_nick=str(team.get("name") or ""),opp_nick=str(oppteam.get("name") or ""),
                         rest_days=_rd,b2b=_b2b,three_in_four=_three,opp_b2b=_opp_b2b,game_total=_total,spread=_spread)
                ctx.update(mk_extra)
                _pos = (a.get("position") or {}).get("abbreviation") if isinstance(a.get("position"), dict) else None
                _grp = posdef.pos_group(_pos or self.pos_lookup.get(str(aid)))
                _dp = pos_defense.get(str(oppteam.get("id")), {})
                ctx.update(position=str(_pos or ""), pos_group=_grp,
                           defense_pos=dict(_dp.get(_grp, {})) if _grp else {},
                           defense_pos_games=int(_dp.get("games", 0)) if _grp else 0,
                           defense_pos_missing=[dict(m) for m in _dp.get("missing", [])] if _grp else [])
                ctx["h2h_log"]=[self._game_dict(x) for x in h2h.get("log",[])]
                return PlayerInput(id=int(aid),name=name,team=team.get("abbreviation", ""),opponent=oppteam.get("abbreviation", ""),home=side.get("homeAway")=="home",line=None,last5=round(l5,2),last10=round(l10,2),last20=round(l20,2),season=round(season,2),ast_last5=round(a5,2),ast_last10=round(a10,2),ast_last20=round(a20,2),ast_season=round(aseason,2),reb_last5=round(r5,2),reb_last10=round(r10,2),reb_last20=round(r20,2),reb_season=round(rseason,2),minutes=round(minutes,1),usage=round(usage,1),pace_factor=round(pace_factor,3),defense_factor=round(defense_factor,3),injury_usage_bump=0,h2h=h2h.get("pts"),h2h_ast=h2h.get("ast"),h2h_reb=h2h.get("reb"),h2h_games=int(h2h.get("games",0)),injury_status=status,**ctx,trend=round(trend,2),recent_std=round(recent_std,2),home_split=home_split,away_split=away_split,opponent_defense=om.get("pa",0),expected_pace=pace_factor*224,game_date=day.isoformat(),game_time=event.get("date", ""),headshot=headshot,source="ESPN Free API")
            with ThreadPoolExecutor(max_workers=12) as ex:
                fs=[ex.submit(build,j) for j in athlete_jobs]
                pending=set(fs)
                while pending and time.time() < build_deadline:
                    done_now={f for f in pending if f.done()}
                    if not done_now:
                        time.sleep(0.03)
                        continue
                    for f in done_now:
                        pending.remove(f)
                        try:
                            x=f.result()
                            if x: out.append(x)
                        except Exception as e:
                            self.last_errors.append(f"player build: {e}")
                for f in pending:
                    f.cancel()
                if pending:
                    self.last_errors.append(
                        f"Render time budget reached; skipped {len(pending)} player lookups."
                    )
        sidelined=[p for p in out if self._is_out(p.injury_status)]
        active=[p for p in out if not self._is_out(p.injury_status) and p.minutes>=self.min_rotation_minutes]
        self._apply_injury_bumps(active, sidelined)
        self.last_stats["injured_out"]=len(sidelined)
        self.last_stats["h2h_players"]=sum(1 for p in active if p.h2h_games>0)
        seen=set(); unique=[]
        for p in active:
            k=(p.id,p.game_date,p.team,p.opponent)
            if k not in seen: seen.add(k); unique.append(p)
        self.last_stats["players"]=len(unique)
        self.last_stats["eligible_players"]=len(unique)
        self.last_stats["teams"]=len({p.team for p in unique})
        if not unique and not self.last_errors:
            self.last_errors.append("No eligible player statistics were returned for today's/tomorrow's scheduled games.")
        self.projection_cache=(time.time(),unique)
        return unique
