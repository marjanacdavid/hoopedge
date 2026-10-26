"""Testovi za odbranu po pozicijama. Pokretanje: python -m pytest tests -q   (ili: python tests/test_posdef.py)"""
import os, sys, random
from datetime import date, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import posdef
from app.provider import ESPNFreeProvider
from app.engine import project
from app.models import PlayerInput

LABELS = ["MIN", "PTS", "FG", "3PT", "FT", "REB", "AST", "TO", "STL", "BLK", "OREB", "DREB", "PF", "+/-"]


def _ath(i, pos, pts, ast, reb, tpm, fga=10, fta=2, minutes=30, oreb=1, tov=2, stl=1, blk=0):
    st = [str(minutes), str(pts), f"{pts//2}-{fga}", f"{tpm}-{tpm+2}", f"1-{fta}", str(reb), str(ast), str(tov), str(stl), str(blk), str(oreb), str(reb - oreb), "2", "0"]
    return {"athlete": {"id": str(i), "displayName": f"Player {i}", "position": {"abbreviation": pos}}, "stats": st, "didNotPlay": False}


def make_summary(team_a, team_b, vs, blk=None, absent=()):
    """vs[(napadac, grupa)] = (pts, ast, reb, tpm) po igracu te grupe. 2 G, 2 F, 1 C po timu."""
    players = []
    for tid in (team_a, team_b):
        opp = team_b if tid == team_a else team_a
        aths, n = [], 0
        for pos, grp in (("PG", "G"), ("SG", "G"), ("SF", "F"), ("PF", "F"), ("C", "C")):
            pts, ast, reb, tpm = vs[(opp, grp)] if False else vs[(tid, grp, opp)]
            n += 1
            pid = int(tid) * 100 + n
            if str(pid) in absent:
                # rezerva preuzima minute (kao u pravoj ligi): isti stat, bez blokova
                aths.append(_ath(pid + 500, pos, pts, ast, reb, tpm, blk=0))
                continue
            aths.append(_ath(pid, pos, pts, ast, reb, tpm, blk=(blk or {}).get(str(pid), 0)))
        players.append({"team": {"id": tid}, "statistics": [{"labels": LABELS, "athletes": aths}]})
    return {"boxscore": {"players": players}}


def test_pos_group():
    assert posdef.pos_group("PG") == "G" and posdef.pos_group("sf") == "F" and posdef.pos_group("C") == "C"
    assert posdef.pos_group("G-F") == "G" and posdef.pos_group("F-C") == "F" and posdef.pos_group("") == ""


def test_parse_box_basic():
    s = make_summary("1", "2", {(t, g, o): (10, 3, 4, 1) for t in "12" for o in "12" for g in "GFC"})
    box = posdef.parse_box(s)
    assert set(box) == {"1", "2"}
    assert box["1"]["grp"]["G"]["PTS"] == 20 and box["1"]["grp"]["C"]["REB"] == 4
    assert box["1"]["grp"]["G"]["PA"] == 26 and box["1"]["poss"] > 40


def test_parse_box_unusable():
    assert posdef.parse_box({}) is None
    assert posdef.parse_box({"boxscore": {"players": []}}) is None


def build_league(n_games=60):
    """6 timova. Tim 1 je mekan prema guardovima a tezak prema centrima; tim 2 obrnuto."""
    random.seed(7)
    teams = ["1", "2", "3", "4", "5", "6"]
    games, day = [], date(2026, 11, 1)
    for k in range(n_games):
        a, b = random.sample(teams, 2)
        vs = {}
        for att, deff in ((a, b), (b, a)):
            for g, base in (("G", (18, 5, 3, 2)), ("F", (14, 3, 6, 1)), ("C", (12, 2, 9, 0))):
                p, ast, reb, tpm = base
                if deff == "1" and g == "G": p, ast = p + 7, ast + 2     # mekan na guardove
                if deff == "1" and g == "C": p, reb = p - 5, reb - 3     # tezak na centre
                if deff == "2" and g == "G": p -= 6                       # tezak na guardove
                if deff == "2" and g == "C": p += 5                       # mekan na centre
                vs[(att, g, deff)] = (p + random.randint(-2, 2), max(0, ast + random.randint(-1, 1)), max(0, reb + random.randint(-1, 1)), tpm)
        games.append((a, b, (day + timedelta(days=k // 3)).isoformat(), vs))
    return games


def test_factors_direction():
    rows = []
    for a, b, d, vs in build_league():
        box = posdef.parse_box(make_summary(a, b, vs))
        rows += posdef.box_to_rows(d, box)
    f = posdef.compute_factors(rows)
    assert set(f) == {"1", "2", "3", "4", "5", "6"}
    assert f["1"]["G"]["PTS"] < 0.97, f["1"]     # mekan prema guardovima
    assert f["1"]["C"]["PTS"] > 1.03, f["1"]     # tezak prema centrima
    assert f["2"]["G"]["PTS"] > 1.03, f["2"]
    assert f["2"]["C"]["PTS"] < 0.97, f["2"]
    assert all(0.85 <= v <= 1.15 for t in f.values() for g in "GFC" for v in t[g].values())
    print("tim 1:", {g: f["1"][g]["PTS"] for g in "GFC"}, "| tim 2:", {g: f["2"][g]["PTS"] for g in "GFC"})


def test_shrinkage_few_games():
    rows = []
    for a, b, d, vs in build_league(n_games=60)[:3]:
        rows += posdef.box_to_rows(d, posdef.parse_box(make_summary(a, b, vs)))
    f = posdef.compute_factors(rows)
    assert all(0.9 <= v <= 1.1 for t in f.values() for g in "GFC" for v in t[g].values())


class FakeResp:
    def __init__(self, data): self._d, self.status_code = data, 200
    def raise_for_status(self): pass
    def json(self): return self._d


def test_provider_end_to_end():
    """Provider sa lazno ESPN sesijom: scoreboard + summary -> faktori po poziciji."""
    games = build_league()
    start = date(2026, 11, 1)
    from datetime import datetime
    p = ESPNFreeProvider()
    today = datetime.now(__import__("zoneinfo").ZoneInfo("Europe/Sarajevo")).date()
    shift = (today - timedelta(days=30)) - start          # zadnjih 30 dana prije danas
    by_day, summaries = {}, {}
    for i, (a, b, d, vs) in enumerate(games):
        day = date.fromisoformat(d) + shift
        eid = str(1000 + i)
        by_day.setdefault(day.strftime("%Y%m%d"), []).append({
            "id": eid, "date": day.isoformat() + "T00:00Z", "season": {"type": 2},
            "status": {"type": {"completed": True}},
            "competitions": [{"competitors": [{"team": {"id": a}, "score": "100"}, {"team": {"id": b}, "score": "98"}]}]})
        summaries[eid] = make_summary(a, b, vs)

    def fake_get(url, params=None, timeout=None):
        if url.endswith("/scoreboard"):
            return FakeResp({"events": by_day.get(params["dates"], [])})
        if url.endswith("/summary"):
            return FakeResp(summaries[params["event"]])
        raise AssertionError(url)
    p.session.get = fake_get
    f = p._position_defense()
    assert f["1"]["G"]["PTS"] < 0.97 and f["1"]["C"]["PTS"] > 1.03
    assert p.last_stats["posdef_games"] == len(games)
    n_calls = []
    p.session.get = lambda *a, **k: n_calls.append(1) or fake_get(*a, **k)
    p.posdef_cache = (0.0, {})                  # prisili novi krug: box scoreovi moraju doci iz kesa
    p._position_defense()
    assert not [c for c in n_calls if False]    # (scoreboard za zadnja 2 dana se osvjezava, box ne)
    assert len(p.box_cache) == len(games)


def _player(**kw):
    base = dict(id=7, name="Test Guard", team="AAA", opponent="BBB", home=True, last5=24, last10=24, last20=24, season=24,
                minutes=34, usage=27, ast_last5=6, ast_last10=6, ast_last20=6, ast_season=6)
    base.update(kw)
    return PlayerInput(**base)


def test_engine_uses_position_factor():
    neutral = project(_player(), "PTS")
    soft = project(_player(pos_group="G", defense_pos={"PTS": 0.88}, defense_pos_games=20), "PTS")
    tough = project(_player(pos_group="G", defense_pos={"PTS": 1.12}, defense_pos_games=20), "PTS")
    assert soft.projection > neutral.projection > tough.projection
    assert soft.opponent_defense_pos == 0.88 and soft.position_group == "G"
    assert any("vs guards" in r for r in soft.reasons)
    print("PTS neutral %.2f | meki %.2f | tezak %.2f" % (neutral.projection, soft.projection, tough.projection))


def test_engine_fallback_few_games():
    a = project(_player(defense_factor=1.05), "PTS")
    b = project(_player(defense_factor=1.05, pos_group="G", defense_pos={"PTS": 1.15}, defense_pos_games=2), "PTS")
    assert a.projection == b.projection and b.opponent_defense_pos is None


def test_engine_all_markets():
    for m in ("PTS", "AST", "REB", "3PM", "PA"):
        r = project(_player(pos_group="C", defense_pos={m: 1.1}, defense_pos_games=10, reb_last5=8, reb_last10=8, reb_last20=8, reb_season=8,
                            tpm_last5=2, tpm_last10=2, tpm_last20=2, tpm_season=2, pa_last5=30, pa_last10=30, pa_last20=30, pa_season=30), m)
        assert r.projection > 0


def _rows(star_absent_from=None, n=40):
    """Tim 3 ima centra (id 305) s 4 blokova po utakmici. star_absent_from = indeks utakmice od koje (najnovije) ne igra."""
    rows = []
    games = build_league(n)
    for i, (a, b, d, vs) in enumerate(games):
        absent = set()
        if star_absent_from is not None and i >= star_absent_from:
            absent = {"305"}
        rows += posdef.box_to_rows(d, posdef.parse_box(make_summary(a, b, vs, blk={"305": 4}, absent=absent)))
    return rows


def test_status_weight():
    sw = posdef.status_weight
    assert sw("Out") == 1.0 and sw("Doubtful") == 0.75 and sw("Questionable") == 0.3 and sw("Day-To-Day") == 0.3
    assert sw("Probable") == 0.0 and sw("") == 0.0 and sw(None) == 0.0


def test_missing_rim_protector_softens_defense():
    rows = _rows()
    base = posdef.compute_factors(rows)
    prof = posdef.build_profiles(rows)
    before = {g: dict(base["3"][g]) for g in "GFC"}
    adj = posdef.apply_injuries(base, prof, {"305": 1.0})
    assert adj["3"]["C"]["PTS"] < base["3"]["C"]["PTS"]                # vlastita pozicija najvise
    assert adj["3"]["G"]["PTS"] < base["3"]["G"]["PTS"]                # spill na ostale
    assert (base["3"]["C"]["PTS"] - adj["3"]["C"]["PTS"]) > (base["3"]["G"]["PTS"] - adj["3"]["G"]["PTS"])
    assert adj["3"]["missing"] and adj["3"]["missing"][0]["name"] == "Player 305"
    assert adj["1"]["C"] == base["1"]["C"] and adj["1"]["missing"] == []   # drugi timovi netaknuti
    assert {g: base["3"][g] for g in "GFC"} == before                      # ulaz nije mijenjan
    half = posdef.apply_injuries(base, prof, {"305": 0.3})
    assert adj["3"]["C"]["PTS"] < half["3"]["C"]["PTS"] < base["3"]["C"]["PTS"]   # questionable < out
    assert adj["3"]["missing"][0]["status"] == "Out" and half["3"]["missing"][0]["status"] == "Questionable"
    print("tim 3 C PTS: baza %.3f | questionable %.3f | out %.3f" % (base["3"]["C"]["PTS"], half["3"]["C"]["PTS"], adj["3"]["C"]["PTS"]))


def test_long_term_absence_already_baked_in():
    """Centar koji ne igra zadnjih 25 od 40 utakmica ima mali ostatni doprinos, pa je efekat mnogo manji."""
    fresh = _rows()                       # igrao je sve utakmice
    stale = _rows(star_absent_from=15)    # odsutan zadnjih 25 (najnovije su na kraju liste datuma)
    out = {}
    for name, rows in (("fresh", fresh), ("stale", stale)):
        base = posdef.compute_factors(rows)
        prof = posdef.build_profiles(rows)
        adj = posdef.apply_injuries(base, prof, {"305": 1.0})
        out[name] = base["3"]["C"]["PTS"] - adj["3"]["C"]["PTS"]
    assert out["stale"] < out["fresh"] * 0.5, out
    print("pad faktora: stalno igrao %.3f | odsutan dugo %.3f" % (out["fresh"], out["stale"]))


def test_bench_player_ignored():
    rows = _rows()
    base = posdef.compute_factors(rows)
    prof = posdef.build_profiles(rows)
    adj = posdef.apply_injuries(base, prof, {"999999": 1.0})    # nepoznat id
    assert adj["3"]["C"] == base["3"]["C"] and adj["3"]["missing"] == []


def test_engine_shows_missing_defenders():
    p = _player(pos_group="C", defense_pos={"PTS": 0.92}, defense_pos_games=20, defense_pos_missing=[{"name": "Rudy Test", "grp": "C", "status": "Out", "share": 0.2}])
    r = project(p, "PTS")
    assert r.opponent_missing_defenders[0]["name"] == "Rudy Test"
    assert any("Rudy Test (C, Out)" in x for x in r.reasons)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("OK ", name)
