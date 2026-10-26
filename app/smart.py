"""Smart Prediction: rang lista pickova po vjerovatnoci (Win Chance) kroz sve kategorije.

- Ako postoji linija kladionice, pick je najbolja strana te linije (izvor "book").
- Ako ne postoji, linija je sezonski prosjek igraca (floor + 0.5), izvor "model":
  'hoce li igrac preci svoj sezonski prosjek'. To nije vrijednost prema tržištu.
smart_score = win_chance - kazne (malo minuta, nema prave linije).
"""
import math

from .engine import project

MARKETS = ("PTS", "AST", "REB", "3PM", "PA")
MIN_SEASON = {"PTS": 8.0, "AST": 1.5, "REB": 2.5, "3PM": 0.9, "PA": 10.0}


def build_smart(players, data):
    idx = {m: {r.player_id: r for r in data.get(m, [])} for m in MARKETS}
    out = []
    for p in players:
        for m in MARKETS:
            base = idx[m].get(p.id)
            if base is None or base.expected_minutes < 12 or base.stat_season < MIN_SEASON[m]:
                continue
            ln = (p.lines or {}).get(m)
            if ln and ln.get("line") is not None:
                r, source = base, "book"
            else:
                pseudo = math.floor(base.stat_season) + 0.5
                pp = p.model_copy(update={"lines": {**(p.lines or {}), m: {"line": pseudo, "over": None, "under": None, "books": 0}}})
                r, source = project(pp, m), "model"
            if r.win_chance is None:
                continue
            score = r.win_chance - (3.0 if r.expected_minutes < 20 else 0.0) - (2.0 if source == "model" else 0.0)
            d = r.model_dump()
            d.pop("recent_games", None); d.pop("h2h_log", None)
            d.update(smart_market=m, smart_source=source, smart_score=round(score, 1))
            out.append(d)
    out.sort(key=lambda d: d["smart_score"], reverse=True)
    for i, d in enumerate(out, 1):
        d["smart_rank"] = i
    return out
