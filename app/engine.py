import numpy as np
from .models import PlayerInput, Projection

MC_SIMS = 10000

def _confidence(score):
    if score >= 82: return "ELITE"
    if score >= 72: return "STRONG"
    if score >= 62: return "GOOD"
    if score >= 52: return "LEAN"
    return "PASS"

def project(p: PlayerInput, market="PTS", sims=MC_SIMS, seed=42):
    market = (market or "PTS").upper()
    if market == "AST":
        last5,last10,last20,season = p.ast_last5,p.ast_last10,p.ast_last20,p.ast_season
        label, suffix = "AST", "AST"
        usage_weight = 0.035
        base_home, base_road = 0.20, -0.10
        sd_floor, sd_scale = 1.9, 0.72
    elif market == "REB":
        last5,last10,last20,season = p.reb_last5,p.reb_last10,p.reb_last20,p.reb_season
        label, suffix = "REB", "REB"
        usage_weight = 0.018
        base_home, base_road = 0.15, -0.08
        sd_floor, sd_scale = 2.2, 0.72
    else:
        last5,last10,last20,season = p.last5,p.last10,p.last20,p.season
        label, suffix = "PTS", "PTS"
        usage_weight = 0.045
        base_home, base_road = 0.45, -0.20
        sd_floor, sd_scale = 3.8, 0.72

    form = (.40*last5 + .25*last10 + .20*last20 + .15*season)
    trend = last5 - last20
    expected_minutes = max(8.0, min(42.0, p.minutes + np.clip(trend * 0.18, -1.5, 1.5)))
    minute_factor = expected_minutes / max(1.0, p.minutes)
    home_adj = base_home if p.home else base_road
    pace_adj = np.clip((p.pace_factor - 1.0) * (2.8 if market == "PTS" else 1.35), -1.8, 1.8)
    defense_adj = np.clip((1.0 - p.defense_factor) * (3.0 if market == "PTS" else 1.25), -2.5, 2.5)
    usage_adj = np.clip((p.usage - 20.0) * usage_weight, -1.2, 1.8)

    projection = form * (0.72 + 0.28 * minute_factor)
    projection += home_adj + pace_adj + defense_adj + usage_adj
    projection = max(0.1, projection)

    sd = max(sd_floor, p.recent_std * sd_scale + projection * (0.095 if market == "PTS" else 0.065))
    rng = np.random.default_rng(seed + int(p.id) + ({"PTS":0,"AST":100000,"REB":200000}.get(market,0)))
    samples = np.clip(rng.normal(projection, sd, int(sims)), 0, None)
    thresholds = {f"{t}+": round(float((samples >= t).mean()) * 100, 1) for t in ((20,25,30,35,40) if market == "PTS" else ((5,7,9,11,13) if market == "AST" else (5,7,9,11,13)))}

    signal = abs(projection - form)
    consistency = max(0.0, 1.0 - min(p.recent_std, 12.0) / 15.0)
    data_quality = 0.92 if p.source.startswith("ESPN") else 0.80
    model_score = np.clip(50 + signal*8 + consistency*22 + (8 if expected_minutes >= 30 else 0) + (5 if abs(trend)>=1 else 0), 0, 99)
    confidence_score = np.clip(48 + consistency*28 + (8 if expected_minutes >= 28 else 0) + data_quality*12 + (3 if abs(p.pace_factor-1)<.08 else 0), 0, 99)
    leader_score = model_score + min(10, signal*2.0)

    reasons=[]
    if trend > 0.7: reasons.append(f"Form trend +{trend:.1f} {label} vs L20")
    elif trend < -0.7: reasons.append(f"Form trend {trend:.1f} {label} vs L20")
    else: reasons.append(f"Stable recent {label.lower()} form")
    reasons.append(f"Expected minutes {expected_minutes:.1f}")
    reasons.append(f"Opponent defense factor {p.defense_factor:.2f}")
    reasons.append(f"Expected pace {p.pace_factor*100:.0f}% of neutral")
    reasons.append(f"Usage {p.usage:.1f}% ({p.usage_source.lower()})")
    reasons.append("Home court" if p.home else "Road game")

    return Projection(
        player_id=p.id,name=p.name,team=p.team,opponent=p.opponent,line=p.line,
        projection=round(float(projection),2),market=market,stat_last5=round(last5,2),stat_last10=round(last10,2),stat_last20=round(last20,2),stat_season=round(season,2),
        delta=None,over_probability=None,under_probability=None,edge=0,confidence=_confidence(float(confidence_score)),confidence_score=round(float(confidence_score),1),
        model_score=round(float(model_score),1),lean="PROJECTION",last5=p.last5,last10=p.last10,last20=p.last20,
        season=p.season,minutes=p.minutes,expected_minutes=round(float(expected_minutes),1),usage=p.usage,
        usage_source=p.usage_source,pace=round(float(p.pace_factor*100),1),opponent_defense=round(float(p.defense_factor),3),
        home_away_adjustment=round(float(home_adj),2),trend=round(float(trend),2),monte_carlo=int(sims),recent_std=round(float(p.recent_std),2),
        reasons=reasons,thresholds=thresholds,
        factors={"form":round(form,2),"minutes":round(expected_minutes,1),"pace_factor":round(p.pace_factor,3),"defense_factor":round(p.defense_factor,3),"usage":round(p.usage,1),"trend":round(trend,2)},
        game_date=p.game_date,game_time=p.game_time,headshot=p.headshot,source=p.source,leader_score=round(float(leader_score),1),is_leader=bool(model_score>=62)
    )
