import numpy as np
from .models import PlayerInput, Projection

MC_SIMS = 10000
SHRINK = 0.75     # model nije kalibrisan: vjerovatnoce se vuku 25% prema 50/50
MIN_EDGE = 3.0    # minimalna prednost (procentnih poena) nad kladionicom za OVER/UNDER preporuku

PACE_SCALE = {"PTS": 2.8, "PA": 3.4, "AST": 1.35, "REB": 1.35, "3PM": 0.35}
# Odbrana po poziciji djeluje relativno (u % forme igraca), ne u fiksnim poenima.
# Vrijednosti su namjerno oprezne jer je uzorak po poziciji sumovit; kalibrisi uz tracking.
POS_DEF_MULT = {"PTS": 0.60, "PA": 0.55, "AST": 0.60, "REB": 0.50, "3PM": 0.50}
POS_DEF_CAP = 0.12        # najvise +-12% forme
POS_DEF_MIN_GAMES = 4     # ispod toga se koristi stari timski faktor
DEF_SCALE = {"PTS": 3.0, "PA": 3.4, "AST": 1.25, "REB": 1.25, "3PM": 0.25}
THRESHOLDS = {"PTS": (20, 25, 30, 35, 40), "PA": (25, 30, 35, 40, 45), "AST": (5, 7, 9, 11, 13), "REB": (5, 7, 9, 11, 13), "3PM": (1, 2, 3, 4, 5)}


def _game_values(rows, market):
    """Vrijednosti tržišta po utakmici (najnovija prva) za grafikon na profilu igraca."""
    out = []
    for g in rows or []:
        if market == "PTS": v = g.get("pts")
        elif market == "AST": v = g.get("ast")
        elif market == "REB": v = g.get("reb")
        elif market == "3PM": v = g.get("tpm")
        else: v = (g.get("pts") + g.get("ast")) if g.get("pts") is not None and g.get("ast") is not None else None
        if v is None:
            continue
        out.append({"date": g.get("date", ""), "opp": g.get("opp", ""), "home": bool(g.get("home")),
                    "min": g.get("min"), "po": bool(g.get("po")), "v": float(v)})
    return out


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
        h2h_val, inj_bump, h2h_cap = p.h2h_ast, p.injury_bump_ast, 1.0
        std_src = p.ast_std if p.ast_std > 0 else 0.4 * p.recent_std
    elif market == "REB":
        last5,last10,last20,season = p.reb_last5,p.reb_last10,p.reb_last20,p.reb_season
        label, suffix = "REB", "REB"
        usage_weight = 0.018
        base_home, base_road = 0.15, -0.08
        sd_floor, sd_scale = 2.2, 0.72
        h2h_val, inj_bump, h2h_cap = p.h2h_reb, p.injury_bump_reb, 1.0
        std_src = p.reb_std if p.reb_std > 0 else 0.4 * p.recent_std
    elif market == "3PM":
        last5,last10,last20,season = p.tpm_last5,p.tpm_last10,p.tpm_last20,p.tpm_season
        label, suffix = "3PM", "3PM"
        usage_weight = 0.012
        base_home, base_road = 0.05, -0.03
        sd_floor, sd_scale = 0.9, 0.7
        h2h_val, inj_bump, h2h_cap = None, 0.0, 0.5
        std_src = p.tpm_std if p.tpm_std > 0 else 1.2
    elif market == "PA":
        last5,last10,last20,season = p.pa_last5,p.pa_last10,p.pa_last20,p.pa_season
        label, suffix = "P+A", "P+A"
        usage_weight = 0.075
        base_home, base_road = 0.65, -0.30
        sd_floor, sd_scale = 4.5, 0.72
        h2h_val, inj_bump, h2h_cap = None, p.injury_bump_pts + p.injury_bump_ast, 2.0
        std_src = p.pa_std if p.pa_std > 0 else 1.15 * p.recent_std
    else:
        last5,last10,last20,season = p.last5,p.last10,p.last20,p.season
        label, suffix = "PTS", "PTS"
        usage_weight = 0.045
        base_home, base_road = 0.45, -0.20
        sd_floor, sd_scale = 3.8, 0.72
        h2h_val, inj_bump, h2h_cap = p.h2h, p.injury_bump_pts, 2.0
        std_src = p.recent_std

    form = (.40*last5 + .25*last10 + .20*last20 + .15*season)
    trend = last5 - last20
    expected_minutes = max(8.0, min(42.0, p.minutes + np.clip(trend * 0.18, -1.5, 1.5)))
    minute_factor = expected_minutes / max(1.0, p.minutes)
    home_adj = base_home if p.home else base_road
    pace_adj = np.clip((p.pace_factor - 1.0) * PACE_SCALE.get(market, 1.35), -1.8, 1.8)
    if p.game_total:      # ako imamo ocekivani total, on zamjenjuje pola grubog 'pace' proxyja
        pace_adj *= 0.5
    pos_f = (p.defense_pos or {}).get(market)
    use_pos = pos_f is not None and p.defense_pos_games >= POS_DEF_MIN_GAMES
    if use_pos:
        # faktor po poziciji ZAMJENJUJE timski (inace bi se odbrana racunala dvaput)
        rel = float(np.clip((1.0 - pos_f) * POS_DEF_MULT.get(market, 0.5), -POS_DEF_CAP, POS_DEF_CAP))
        defense_adj = form * rel
    else:
        defense_adj = np.clip((1.0 - p.defense_factor) * DEF_SCALE.get(market, 1.25), -2.5, 2.5)
    usage_adj = np.clip((p.usage - 20.0) * usage_weight, -1.2, 1.8)

    projection = form * (0.72 + 0.28 * minute_factor)
    projection += home_adj + pace_adj + defense_adj + usage_adj
    # H2H: small sample (2-6 games), so it gets a small, capped weight.
    h2h_adj = 0.0
    if h2h_val is not None and p.h2h_games > 0:
        w = min(0.10, 0.02 * p.h2h_games)
        h2h_adj = float(np.clip(w * (h2h_val - form), -h2h_cap, h2h_cap))
    inj_bump = float(inj_bump or 0.0)  # extra production when teammates are out (capped in provider)
    projection += h2h_adj + inj_bump
    # ---- kontekst utakmice: odmor, ocekivani total, rizik od blowouta ----
    # Konzervativne pocetne procjene; kalibrisi ih kad imas tracking.
    rest_pct = (-2.0 if p.b2b else 0.0) + (-1.0 if p.three_in_four else 0.0) + (1.0 if p.opp_b2b else 0.0)
    total_pct = float(np.clip(0.6 * (p.game_total / 225.0 - 1.0) * 100.0, -5.0, 5.0)) if p.game_total else 0.0
    blow_pct = 0.0
    if p.spread is not None and p.minutes >= 26:
        sev = float(np.clip((abs(p.spread) - 7.0) / 10.0, 0.0, 1.0))
        blow_pct = -(4.0 if p.spread < 0 else 2.0) * sev   # favorit vise sjedi u 4. cetvrtini
    context_pct = rest_pct + total_pct + blow_pct
    projection *= 1.0 + context_pct / 100.0
    projection = max(0.1, projection)

    k_sd = 0.095 if market in ("PTS", "PA") else 0.065
    sd = max(sd_floor, std_src * sd_scale + projection * k_sd)
    rng = np.random.default_rng(seed + int(p.id) + {"PTS": 0, "AST": 100000, "REB": 200000, "3PM": 300000, "PA": 400000}.get(market, 0))
    if market == "3PM":   # mali cijeli brojevi: gamma-Poisson (prekomjerna disperzija)
        lam = rng.gamma(6.0, max(projection, 0.05) / 6.0, int(sims))
        samples = rng.poisson(lam).astype(float)
    else:
        samples = np.clip(rng.normal(projection, sd, int(sims)), 0, None)
    thresholds = {f"{t}+": round(float((samples >= t).mean()) * 100, 1) for t in THRESHOLDS.get(market, (5, 7, 9, 11, 13))}

    # ---- linija kladionice -> over/under ----
    ln = (p.lines or {}).get(market)
    line_val = over_pct = under_pct = delta = None
    edge_pts = 0.0
    lean = "PROJECTION"
    pick_side = win_chance = market_prob_pct = odds_price = None
    books_n = 0
    market_note = None
    if ln and ln.get("line") is not None:
        line_val = float(ln["line"])
        if line_val % 1 == 0.5:
            o_raw, u_raw = float((samples > line_val).mean()), float((samples < line_val).mean())
        else:  # cijela linija: moguc push
            o_raw, u_raw = float((samples > line_val + 0.5).mean()), float((samples < line_val - 0.5).mean())
        shift = (1.0 - SHRINK) * (o_raw - u_raw) / 2.0
        o_s, u_s = o_raw - shift, u_raw + shift
        tot = max(1e-9, o_s + u_s)
        co, cu = o_s / tot, u_s / tot                     # uslovne vjerovatnoce bez pusha
        if ln.get("over") and ln.get("under"):
            io, iu = 1.0 / ln["over"], 1.0 / ln["under"]
            mo, mu = io / (io + iu), iu / (io + iu)       # tržišna vjerovatnoca bez vig-a
        else:
            mo = mu = 0.5
        side_over = co > mo
        side_prob, mkt_prob = (co, mo) if side_over else (cu, mu)
        edge_pts = abs(co - mo) * 100.0
        over_pct, under_pct = round(co * 100, 1), round(cu * 100, 1)
        delta = round(float(projection) - line_val, 2)
        lean = ("OVER" if side_over else "UNDER") if edge_pts >= MIN_EDGE else "NO EDGE"
        pick_side = "OVER" if side_over else "UNDER"
        win_chance, market_prob_pct = round(side_prob * 100, 1), round(mkt_prob * 100, 1)
        odds_price = ln.get("over") if side_over else ln.get("under")
        books_n = int(ln.get("books", 0) or 0)
        market_note = (f"Line {line_val:g} ({ln.get('books', 1)} books): model {'OVER' if side_over else 'UNDER'} "
                       f"{side_prob*100:.0f}% vs market {mkt_prob*100:.0f}% (edge {edge_pts:.1f} pts)")

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
    if use_pos:
        gname = {"G": "guards", "F": "forwards", "C": "centers"}.get(p.pos_group, p.pos_group)
        reasons.append(f"Opponent defense vs {gname}: {pos_f:.2f} over {p.defense_pos_games} games ({defense_adj:+.1f} {label}; above 1.00 = tougher)")
        if p.defense_pos_missing:
            def _miss(x):
                return f"{x['name']} ({x['grp']}, {x['status']})" if isinstance(x, dict) else str(x)
            reasons.append("Opponent missing defenders: " + ", ".join(_miss(x) for x in p.defense_pos_missing[:3]))
    else:
        reasons.append(f"Opponent defense {p.defense_factor:.2f} (above 1.00 = tougher than average)")
    reasons.append(f"Expected pace {p.pace_factor*100:.0f}% of neutral")
    reasons.append(f"Usage {p.usage:.1f}% ({p.usage_source.lower()})")
    reasons.append("Home court" if p.home else "Road game")

    if h2h_val is not None and p.h2h_games > 0:
        reasons.append(f"H2H vs {p.opponent}: {h2h_val:.1f} {label} in {p.h2h_games} games ({h2h_adj:+.1f} adj)")
    if inj_bump > 0.05:
        who = ", ".join(p.injured_teammates) or "teammates"
        reasons.append(f"{who} out: +{inj_bump:.1f} {label}")
    if p.injury_status:
        reasons.append(f"Status: {p.injury_status}")
    if market_note:
        reasons.append(market_note)
    if rest_pct:
        tags = [t for t, on in (("back-to-back", p.b2b), ("3 games in 4 nights", p.three_in_four), ("opponent on back-to-back", p.opp_b2b)) if on]
        reasons.append(f"Rest: {', '.join(tags)} ({rest_pct:+.1f}%)")
    if p.game_total:
        reasons.append(f"Game total {p.game_total:g}: {total_pct:+.1f}%")
    if blow_pct:
        reasons.append(f"Blowout risk (spread {p.spread:+g}): {blow_pct:+.1f}% minutes")

    return Projection(
        player_id=p.id,name=p.name,team=p.team,opponent=p.opponent,line=line_val,
        projection=round(float(projection),2),market=market,stat_last5=round(last5,2),stat_last10=round(last10,2),stat_last20=round(last20,2),stat_season=round(season,2),
        delta=delta,over_probability=over_pct,under_probability=under_pct,edge=round(edge_pts,1),confidence=_confidence(float(confidence_score)),confidence_score=round(float(confidence_score),1),
        model_score=round(float(model_score),1),lean=lean,last5=p.last5,last10=p.last10,last20=p.last20,
        season=p.season,minutes=p.minutes,expected_minutes=round(float(expected_minutes),1),usage=p.usage,
        usage_source=p.usage_source,pace=round(float(p.pace_factor*100),1),opponent_defense=round(float(p.defense_factor),3),
        home_away_adjustment=round(float(home_adj),2),trend=round(float(trend),2),monte_carlo=int(sims),recent_std=round(float(p.recent_std),2),
        reasons=reasons,thresholds=thresholds,h2h=(round(float(h2h_val),2) if h2h_val is not None and p.h2h_games>0 else None),h2h_games=p.h2h_games,injury_status=p.injury_status,injury_bump=round(inj_bump,2),rest_days=p.rest_days,b2b=p.b2b,game_total=p.game_total,spread=p.spread,context_pct=round(context_pct,2),recent_games=_game_values(p.games, market),h2h_log=_game_values(p.h2h_log, market),pick_side=pick_side,win_chance=win_chance,market_prob=market_prob_pct,dtm=round(edge_pts,1),odds_price=odds_price,books=books_n,
        factors={"form":round(form,2),"minutes":round(expected_minutes,1),"pace_factor":round(p.pace_factor,3),"defense_factor":round(p.defense_factor,3),"usage":round(p.usage,1),"trend":round(trend,2),"h2h_adj":round(h2h_adj,2),"injury_bump":round(inj_bump,2),"context_pct":round(context_pct,2),"defense_adj":round(float(defense_adj),2)},
        game_date=p.game_date,game_time=p.game_time,headshot=p.headshot,source=p.source,leader_score=round(float(leader_score),1),is_leader=bool(model_score>=62),
        position_group=p.pos_group,opponent_defense_pos=(round(float(pos_f),3) if use_pos else None),defense_pos_games=(p.defense_pos_games if use_pos else 0),
        opponent_missing_defenders=(list(p.defense_pos_missing) if use_pos else [])
    )
