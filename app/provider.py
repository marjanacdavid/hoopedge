import time, logging
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests
from .models import PlayerInput

BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
WEB = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba"
log = logging.getLogger("hoopedge.provider")

class ESPNFreeProvider:
    """ESPN public/free endpoints. No API key. Undocumented endpoints are cached."""
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "HOOPEDGE/2.1", "Accept": "application/json"})
        self.cache = {}
        self.ttl = 300
        self.projection_cache = (0.0, [])
        self.team_metrics_cache = (0.0, {})
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
                    timeout=(4, 10),
                )
                if r.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                    time.sleep(0.35)
                    continue
                r.raise_for_status()
                data = r.json()
                self.cache[key] = (time.time(), data)
                return data
            except Exception as e:
                last_exc = e
                if attempt == 0:
                    time.sleep(0.2)
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

    def _gamelog(self, athlete_id):
        year = datetime.now(ZoneInfo("America/New_York")).year
        for season in (year, year - 1):
            try:
                data = self._get(f"{WEB}/athletes/{athlete_id}/gamelog", {"season": season})
                labels = [str(x).upper() for x in (data.get("labels") or [])]
                names = [str(x).lower() for x in (data.get("names") or [])]
                events = data.get("events") or []
                if isinstance(events, dict): events = list(events.values())
                stat_labels = labels[3:] if len(labels) >= 4 else labels
                stat_names = names[3:] if len(names) >= 4 else names
                rows = []
                for item in events:
                    if not isinstance(item, dict): continue
                    stats = item.get("stats") or item.get("statistics") or []
                    if isinstance(stats, dict): stats = stats.get("statistics") or stats.get("stats") or []
                    if not isinstance(stats, list): continue
                    if len(stats) == len(labels): slabels, snames = labels, names
                    elif len(stats) == len(stat_labels): slabels, snames = stat_labels, stat_names
                    else:
                        slabels = stat_labels[-len(stats):] if stats else []
                        snames = stat_names[-len(stats):] if stats else []
                    mapping={}
                    for i,v in enumerate(stats):
                        if i < len(slabels): mapping[slabels[i]]=v
                        if i < len(snames): mapping[snames[i]]=v
                    def pick(*keys):
                        for k in keys:
                            if k in mapping: return mapping[k]
                        return None
                    pts=self._num(pick("PTS","POINTS","points"),-1)
                    ast=self._num(pick("AST","ASSISTS","assists"),-1)
                    reb=self._num(pick("REB","REBOUNDS","rebounds"),-1)
                    mins=self._num(pick("MIN","MINUTES","minutes"),0)
                    if not (0 <= pts <= 100): continue
                    row={"pts":pts,"ast":ast if 0 <= ast <= 40 else 0.0,"reb":reb if 0 <= reb <= 40 else 0.0,"min":mins if 0 <= mins <= 60 else 0}
                    for out,keyset in (("fga",("FGA","fieldgoalsattempted")),("fta",("FTA","freethrowsattempted")),("tov",("TO","TOV","turnovers")),("usg",("USG%","USG"))):
                        val=pick(*keyset)
                        if val is not None:
                            n=self._num(val,-1)
                            if n >= 0: row[out]=n
                    # ESPN event metadata gives location/date when present.
                    row["date"]=str(item.get("date") or item.get("gameDate") or "")
                    row["home"]=str(item.get("homeAway") or item.get("home_away") or "").lower()=="home"
                    rows.append(row)
                if rows:
                    self.last_stats["gamelogs"] += 1
                    return rows
            except Exception:
                continue
        return []

    def _historical_team_metrics(self, days=10):
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
        for _,events in results:
            self.last_stats["historical_scoreboards"] = self.last_stats.get("historical_scoreboards", 0) + 1
            for event in events:
                comp=(event.get("competitions") or [{}])[0]
                comps=comp.get("competitors") or []
                if len(comps)!=2: continue
                vals=[]
                for c in comps:
                    try: vals.append(float((c.get("score") or {}).get("value", c.get("score",0))))
                    except Exception: vals.append(0)
                if len(vals)!=2 or max(vals)<=0: continue
                combined=sum(vals); league_combined.append(combined)
                for idx,c in enumerate(comps):
                    tid=(c.get("team") or {}).get("id")
                    if not tid: continue
                    d=team.setdefault(str(tid),{"for":[],"against":[]})
                    d["for"].append(vals[idx]); d["against"].append(vals[1-idx])
        league_avg=float(np.mean(league_combined)) if league_combined else 224.0
        metrics={}
        for tid,d in team.items():
            if not d["against"]: continue
            pf=float(np.mean(d["for"])); pa=float(np.mean(d["against"]))
            # defense_factor >1 = tougher than average; <1 = softer.
            defense_factor=max(0.90,min(1.12,pa/112.0))
            pace_factor=max(0.90,min(1.12,(pf+pa)/max(1.0,league_avg)))
            metrics[tid]={"defense_factor":defense_factor,"pace_factor":pace_factor,"pf":pf,"pa":pa,"games":len(d["for"])}
        self.last_stats["team_metrics"]=len(metrics)
        self.team_metrics_cache=(time.time(), metrics)
        return metrics
    def _athlete_stats(self, athlete_id):
        """Optional season summary fallback. Never pollute the UI diagnostics with 404s."""
        try:
            year = datetime.now(ZoneInfo("America/New_York")).year
            url=f"{WEB}/athletes/{athlete_id}/stats"
            r=self.session.get(url, params={"season":year, "seasontype":2}, timeout=6)
            if r.status_code != 200:
                return {}
            data=r.json()
            vals={}
            for cat in data.get("categories", []):
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
        return players

    def players(self):
        now=time.time()
        if now-self.projection_cache[0] < 60 and self.projection_cache[1]:
            return self.projection_cache[1]
        self.last_errors=[]
        self.last_stats={"scoreboard":0,"rosters":0,"gamelogs":0,"players":0,"games":0,"teams":0,"eligible_players":0,"historical_scoreboards":0,"team_metrics":0}
        out=[]
        team_metrics=self._historical_team_metrics(days=10)
        for day in self.dates():
            try:
                events=self.scoreboard(day)
                self.last_stats["games"] += sum(1 for e in events if (e.get("competitions") or [{}])[0].get("competitors"))
            except Exception as e:
                self.last_errors.append(f"scoreboard {day}: {e}")
                continue
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
            with ThreadPoolExecutor(max_workers=8) as ex:
                futures={ex.submit(self._roster,tid):(day,event,side,opp) for day,event,side,opp,tid in team_jobs}
                roster_results=[]
                for f,meta in [(f,m) for f,m in futures.items()]:
                    try: roster_results.append((meta,f.result()))
                    except Exception as e: self.last_errors.append(f"roster {meta[0]}: {e}")
            athlete_jobs=[]
            for (day,event,side,opp),roster in roster_results:
                active=[a for a in roster if a.get("active",True) and a.get("id")]
                # Analyze the complete active roster. We no longer truncate to 12 players;
                # the UI can show the strongest 12 while the dashboard reports the true
                # number of analyzed players.
                for a in active:
                    athlete_jobs.append((day,event,side,opp,a))
            def build(job):
                day,event,side,opp,a=job
                aid=a.get("id")
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
                return PlayerInput(id=int(aid),name=name,team=team.get("abbreviation", ""),opponent=oppteam.get("abbreviation", ""),home=side.get("homeAway")=="home",line=None,last5=round(l5,2),last10=round(l10,2),last20=round(l20,2),season=round(season,2),ast_last5=round(a5,2),ast_last10=round(a10,2),ast_last20=round(a20,2),ast_season=round(aseason,2),reb_last5=round(r5,2),reb_last10=round(r10,2),reb_last20=round(r20,2),reb_season=round(rseason,2),minutes=round(minutes,1),usage=round(usage,1),pace_factor=round(pace_factor,3),defense_factor=round(defense_factor,3),injury_usage_bump=0,trend=round(trend,2),recent_std=round(recent_std,2),home_split=home_split,away_split=away_split,opponent_defense=om.get("pa",0),expected_pace=pace_factor*224,game_date=day.isoformat(),game_time=event.get("date", ""),headshot=headshot,source="ESPN Free API")
            with ThreadPoolExecutor(max_workers=8) as ex:
                fs=[ex.submit(build,j) for j in athlete_jobs]
                for f in as_completed(fs):
                    try:
                        x=f.result()
                        if x: out.append(x)
                    except Exception as e: self.last_errors.append(f"player build: {e}")
        seen=set(); unique=[]
        for p in out:
            k=(p.id,p.game_date,p.team,p.opponent)
            if k not in seen: seen.add(k); unique.append(p)
        self.last_stats["players"]=len(unique)
        self.last_stats["eligible_players"]=len(unique)
        self.last_stats["teams"]=len({p.team for p in unique})
        if not unique and not self.last_errors:
            self.last_errors.append("No eligible player statistics were returned for today's/tomorrow's scheduled games.")
        self.projection_cache=(time.time(),unique)
        return unique
