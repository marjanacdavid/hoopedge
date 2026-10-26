"""Zakljucavanje podataka NA SERVERU.

Zamagljivanje u CSS-u samo se zaobilazi (devtools, direktan poziv API-ja), pa server za zakljucane
igrace uopste ne salje prave podatke: ostaju samo ekipa, protivnik i vrijeme utakmice, a sve ostalo su
izmisljene (decoy) vrijednosti, uz `locked: true`. Front-end ih samo zamagli.

"Prvih N igraca" = onako kako ih korisnik vidi na dashboardu: utakmice po vremenu, a unutar
utakmice po model score (isti redoslijed kao groups() u index.html). Izbor se zakljucava (pin) za dan,
da osvjezavanje modela ne bi svaki put otkrivalo druge igrace.
"""
import random
import threading

from fastapi import HTTPException

from .auth import required_plan_for_market

_pin = {"slate": None, "ids": []}
_pin_lock = threading.Lock()


def _g(x, key, default=""):
    return x.get(key, default) if isinstance(x, dict) else getattr(x, key, default)


def display_order(items):
    """Isti redoslijed kao na dashboardu: grupe po (datum+vrijeme), unutar grupe model score opadajuce."""
    groups = {}
    for p in items:
        teams = "-".join(sorted([str(_g(p, "team")), str(_g(p, "opponent"))]))
        key = f"{_g(p, 'game_date')}|{_g(p, 'game_time')}|{teams}"
        groups.setdefault(key, []).append(p)
    ordered = sorted(groups.items(), key=lambda kv: str(_g(kv[1][0], "game_date")) + str(_g(kv[1][0], "game_time")))
    out = []
    for _, players in ordered:
        out.extend(sorted(players, key=lambda p: -float(_g(p, "model_score", 0) or 0)))
    return out


def free_ids(pts_items, limit):
    """Skup player_id-eva koje smije vidjeti plan s ogranicenjem (limit)."""
    if not limit:
        return set()
    ordered = display_order(pts_items)
    ids = [_g(p, "player_id") for p in ordered]
    slate = _g(ordered[0], "game_date") if ordered else None
    with _pin_lock:
        have = set(ids)
        keep = [i for i in _pin["ids"] if i in have] if _pin["slate"] == slate else []
        for i in ids:
            if len(keep) >= limit:
                break
            if i not in keep:
                keep.append(i)
        _pin["slate"], _pin["ids"] = slate, keep
        return set(keep[:limit])


def upgrade_error(market=None, ai=False, login=False):
    if login:
        return HTTPException(401, detail={"message": "Sign in to continue.", "login_required": True})
    if ai:
        return HTTPException(403, detail={"message": "HOOPEDGE AI is available on the Pro+ plan.",
                                          "upgrade_required": True, "required_plan": "pro_plus"})
    return HTTPException(403, detail={"message": f"The {market} market is not included in your plan.",
                                      "upgrade_required": True, "required_plan": required_plan_for_market(market or "PTS")})


def check_market(ent, market):
    if market not in ent["markets"]:
        raise upgrade_error(market=market)


# ---- zakljucani "stubovi" (izmisljene vrijednosti, nikad stvarni podaci)
def stub_projection(x, idx, market):
    rnd = random.Random(7919 + idx)
    season = round(rnd.uniform(9, 27), 1)
    return {
        "locked": True, "player_id": -(idx + 1), "name": "Locked Player", "headshot": None,
        "team": _g(x, "team"), "opponent": _g(x, "opponent"), "market": market,
        "game_date": _g(x, "game_date"), "game_time": _g(x, "game_time"),
        "line": None, "projection": round(season + rnd.uniform(-2, 2), 1),
        "stat_season": season, "stat_last5": round(season + rnd.uniform(-3, 3), 1),
        "stat_last10": round(season + rnd.uniform(-2, 2), 1), "stat_last20": round(season + rnd.uniform(-2, 2), 1),
        "model_score": 53, "confidence_score": round(rnd.uniform(48, 72), 1), "confidence": "", "lean": "",
        "expected_minutes": round(rnd.uniform(22, 35), 1), "usage": round(rnd.uniform(15, 30), 1), "pace": 100,
        "opponent_defense": 1.0, "trend": 0, "monte_carlo": 10000, "reasons": [], "thresholds": {}, "factors": {},
        "recent_games": [], "h2h_log": [], "edge": 0,
    }


def stub_smart(r, idx):
    rnd = random.Random(104729 + idx)
    return {
        "locked": True, "player_id": -(idx + 1), "name": "Locked Player", "headshot": None,
        "team": _g(r, "team"), "opponent": _g(r, "opponent"),
        "smart_market": _g(r, "smart_market"), "smart_source": "model", "smart_rank": _g(r, "smart_rank", idx + 1),
        "smart_score": 0, "pick_side": "OVER", "line": round(rnd.uniform(8, 26) // 1 + 0.5, 1),
        "win_chance": round(rnd.uniform(55, 70), 1), "projection": round(rnd.uniform(9, 27), 1), "dtm": 0, "books": 0,
    }


def gate_projections(items, ent, market, pts_items):
    """Primijeni plan na listu projekcija jednog trzista. Vraca listu (prave ili zakljucane stavke)."""
    check_market(ent, market)
    limit = ent["limit"]
    if limit is None:
        return items
    allowed = free_ids(pts_items, limit)
    out, n = [], 0
    for x in items:
        if _g(x, "player_id") in allowed:
            out.append(x)
        else:
            out.append(stub_projection(x, n, market))
            n += 1
    return out


def gate_smart(rows, ent, pts_items):
    rows = [r for r in rows if r.get("smart_market") in ent["markets"]]
    limit = ent["limit"]
    if limit is None:
        return rows
    allowed = free_ids(pts_items, limit)
    out, n = [], 0
    for r in rows:
        if r.get("player_id") in allowed:
            out.append(r)
        else:
            out.append(stub_smart(r, n))
            n += 1
    return out


def player_allowed(ent, player_id, pts_items):
    limit = ent["limit"]
    return limit is None or player_id in free_ids(pts_items, limit)
