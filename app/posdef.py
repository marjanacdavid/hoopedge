"""Protivnicka odbrana po pozicijama (G / F / C) iz ESPN box scoreova.

Ideja: za svaki tim izmjerimo koliko poena / asistencija / skokova / trojki PO 100 POSJEDA
primaju guardovi, forwardi i centri, ispravljeno za jacinu napadaca koje je taj tim vec
sreo. Rezultat je faktor po timu, poziciji i trzistu:

    faktor > 1.0  -> tezi protivnik za tu poziciju (prima manje od prosjeka lige)
    faktor < 1.0  -> mekši protivnik

Isti smjer kao postojeci `defense_factor` u provider.py. Cista logika bez mreze,
da se moze testirati odvojeno od ESPN-a.
"""
from collections import defaultdict

GROUPS = ("G", "F", "C")
GROUP_NAMES = {"G": "guards", "F": "forwards", "C": "centers"}
STATS = ("PTS", "AST", "REB", "3PM", "PA")

_POS_MAP = {"PG": "G", "SG": "G", "G": "G", "SF": "F", "PF": "F", "F": "F", "C": "C"}


def pos_group(pos):
    """ESPN oznaka pozicije (PG, SG, SF, PF, C, G, F, G-F, F-C ...) -> 'G' | 'F' | 'C' | ''."""
    p = str(pos or "").strip().upper()
    if not p:
        return ""
    if p in _POS_MAP:
        return _POS_MAP[p]
    for tok in p.replace("/", "-").replace(" ", "-").split("-"):
        if tok in _POS_MAP:
            return _POS_MAP[tok]   # hibrid: prva oznaka odlucuje (G-F -> G, F-C -> F)
    return _POS_MAP.get(p[:1], "")


def _num(v, default=0.0):
    try:
        return float(str(v).replace(",", "").strip())
    except Exception:
        return default


def _made_att(v):
    """'5-12' -> (5.0, 12.0); '7' -> (7.0, 0.0)."""
    s = str(v or "").strip()
    if "-" in s:
        a, _, b = s.partition("-")
        return _num(a), _num(b)
    return _num(s), 0.0


def parse_box(data, pos_lookup=None):
    """ESPN `summary?event=ID` JSON -> {team_id: {"poss": float, "grp": {G|F|C: {stat: vrijednost}}}}.

    Vraca None ako box score nije upotrebljiv (nema dva tima ili nema podataka o posjedima).
    """
    pos_lookup = pos_lookup or {}
    blocks = ((data or {}).get("boxscore") or {}).get("players") or []
    out = {}
    for t in blocks:
        tid = str((t.get("team") or {}).get("id") or "")
        if not tid:
            continue
        grp = {g: dict.fromkeys(STATS, 0.0) for g in GROUPS}
        fga = fta = oreb = tov = 0.0
        played = 0
        roster = []
        for block in t.get("statistics") or []:
            labels = [str(x).upper() for x in (block.get("labels") or block.get("names") or [])]
            idx = {l: i for i, l in enumerate(labels)}

            def col(stats, *names):
                for n in names:
                    i = idx.get(n)
                    if i is not None and i < len(stats):
                        return stats[i]
                return None

            for ath in block.get("athletes") or []:
                if ath.get("didNotPlay"):
                    continue
                stats = ath.get("stats") or []
                if _num(col(stats, "MIN", "MINUTES")) <= 0:
                    continue
                played += 1
                _, a_fg = _made_att(col(stats, "FG"))
                _, a_ft = _made_att(col(stats, "FT"))
                fga += a_fg
                fta += a_ft
                oreb += _num(col(stats, "OREB"))
                tov += _num(col(stats, "TO", "TOV"))
                info = ath.get("athlete") or {}
                pos = (info.get("position") or {}).get("abbreviation") or pos_lookup.get(str(info.get("id") or ""))
                g = pos_group(pos)
                if not g:
                    continue
                reb_i = _num(col(stats, "REB"))
                dreb_i = _num(col(stats, "DREB")) if col(stats, "DREB") is not None else max(0.0, reb_i - _num(col(stats, "OREB")))
                roster.append({"id": str(info.get("id") or ""), "name": str(info.get("displayName") or info.get("shortName") or ""),
                               "grp": g, "min": _num(col(stats, "MIN", "MINUTES")),
                               "stl": _num(col(stats, "STL")), "blk": _num(col(stats, "BLK")), "dreb": dreb_i})
                pts = _num(col(stats, "PTS"))
                ast = _num(col(stats, "AST"))
                reb = _num(col(stats, "REB"))
                tpm, _ = _made_att(col(stats, "3PT", "3PM"))
                s = grp[g]
                s["PTS"] += pts
                s["AST"] += ast
                s["REB"] += reb
                s["3PM"] += tpm
                s["PA"] += pts + ast
        poss = fga - oreb + tov + 0.44 * fta
        if played >= 5 and poss >= 40:
            out[tid] = {"poss": poss, "grp": grp, "players": roster}
    return out if len(out) == 2 else None


def box_to_rows(date, box):
    """Jedan box score -> dva reda (napadac, branic). Rezultat za compute_factors."""
    if not box or len(box) != 2:
        return []
    (a, ra), (b, rb) = list(box.items())
    return [
        {"att": a, "def": b, "date": date, "poss": ra["poss"], "grp": ra["grp"], "players": ra.get("players", [])},
        {"att": b, "def": a, "date": date, "poss": rb["poss"], "grp": rb["grp"], "players": rb.get("players", [])},
    ]


def compute_factors(rows, k_off=6.0, k_def=8.0, decay=0.94, clip=(0.85, 1.15)):
    """rows -> {team_id: {"games": n, "G": {stat: faktor}, "F": {...}, "C": {...}}}.

    1. Stopa po 100 posjeda za svaku poziciju i trziste.
    2. Napadac se ispravlja: tim koji je sreo jake napadace ne izgleda 'mekan' zbog njih.
    3. Novije utakmice vrijede vise (decay po utakmici).
    4. Malo utakmica -> faktor se vuce prema 1.0 (shrinkage k_def).
    """
    rows = [r for r in rows if r.get("poss", 0) > 0]
    if not rows:
        return {}

    def rate(r, g, s):
        return r["grp"][g][s] / r["poss"] * 100.0

    tot_poss = sum(r["poss"] for r in rows)
    league = {(g, s): sum(r["grp"][g][s] for r in rows) / tot_poss * 100.0 for g in GROUPS for s in STATS}

    # jacina napada svakog tima (shrunk), po poziciji i trzistu
    by_att = defaultdict(list)
    for r in rows:
        by_att[r["att"]].append(r)
    off = {}
    for tid, rs in by_att.items():
        n = len(rs)
        p = sum(r["poss"] for r in rs)
        for g in GROUPS:
            for s in STATS:
                lg = league[(g, s)]
                raw = (sum(r["grp"][g][s] for r in rs) / p * 100.0) / lg if lg > 0 else 1.0
                off[(tid, g, s)] = 1.0 + (raw - 1.0) * n / (n + k_off)

    adj = []
    for r in rows:
        a = {(g, s): rate(r, g, s) / max(0.5, off.get((r["att"], g, s), 1.0)) for g in GROUPS for s in STATS}
        adj.append((r, a))
    adj_league = {k: sum(a[k] for _, a in adj) / len(adj) for k in league}

    by_def = defaultdict(list)
    for r, a in adj:
        by_def[r["def"]].append((r, a))

    lo, hi = clip
    out = {}
    for tid, items in by_def.items():
        items.sort(key=lambda x: x[0]["date"], reverse=True)   # najnovija prva
        n = len(items)
        w = [decay ** i for i in range(n)]
        sw = sum(w)
        entry = {"games": n}
        for g in GROUPS:
            entry[g] = {}
            for s in STATS:
                lg = adj_league[(g, s)]
                if lg <= 0:
                    entry[g][s] = 1.0
                    continue
                ratio = (sum(wi * a[(g, s)] for wi, (_, a) in zip(w, items)) / sw) / lg   # primljeno / liga
                ratio = 1.0 + (ratio - 1.0) * n / (n + k_def)
                entry[g][s] = round(min(hi, max(lo, 1.0 / max(ratio, 0.05))), 3)
        out[tid] = entry
    return out


# ---------------------------------------------------------------------------
# Povrijedjeni branioci protivnika
# ---------------------------------------------------------------------------
# Izostanak stvarno utice samo koliko je igrac bio "ugraden" u nedavnu odbranu tima.
# Zato se doprinos racuna kao tezinski prosjek minuta kroz nedavne utakmice, a utakmice koje je
# propustio racunaju se kao 0 minuta: ko je odsutan vec 10 utakmica ima mali doprinos jer je to
# vec sadrzano u stopama koje tim prima, a ko je ispao jucer ima pun doprinos.

STATUS_WEIGHT = (("out", 1.0), ("doubtful", 0.75), ("questionable", 0.3), ("day-to-day", 0.3), ("day to day", 0.3))


def status_weight(status):
    """ESPN status povrede -> koliko racunamo da igrac nece igrati (0..1)."""
    s = str(status or "").strip().lower()
    for key, w in STATUS_WEIGHT:
        if s.startswith(key):
            return w
    return 0.0


def status_label(weight):
    """Tezina statusa -> citljiv naziv za prikaz."""
    return "Out" if weight >= 1.0 else "Doubtful" if weight >= 0.75 else "Questionable"


def _def_events(p):
    return p["stl"] + p["blk"] + 0.3 * p["dreb"]


def build_profiles(rows, decay=0.94, k_min=100.0, rel_clip=(0.6, 1.8)):
    """rows -> {team_id: {"players": {pid: {...}}, "group_total": {G,F,C}, "total": x}}.

    Doprinos odbrani = ponderisane minute x relativna stopa defanzivnih dogadjaja (STL + BLK + 0.3 DREB
    po minuti, u odnosu na ligu za istu poziciju, shrunk prema 1.0 za igrace s malo minuta).
    """
    ev = {g: 0.0 for g in GROUPS}
    mn = {g: 0.0 for g in GROUPS}
    for r in rows:
        for p in r.get("players", []):
            ev[p["grp"]] += _def_events(p)
            mn[p["grp"]] += p["min"]
    league = {g: (ev[g] / mn[g] if mn[g] > 0 else 0.0) for g in GROUPS}

    by_team = defaultdict(list)
    for r in rows:
        by_team[r["att"]].append(r)          # red napadaca = vlastiti igraci tog tima

    out = {}
    for tid, games in by_team.items():
        games.sort(key=lambda r: r["date"], reverse=True)
        w = [decay ** i for i in range(len(games))]
        sw = sum(w)
        tot = {}
        for wi, r in zip(w, games):
            for p in r.get("players", []):
                if not p["id"]:
                    continue
                d = tot.setdefault(p["id"], {"name": p["name"], "grp": p["grp"], "wmin": 0.0, "min": 0.0, "ev": 0.0})
                d["wmin"] += wi * p["min"]
                d["min"] += p["min"]
                d["ev"] += _def_events(p)
                if p["name"]:
                    d["name"] = p["name"]
        players, group_total = {}, {g: 0.0 for g in GROUPS}
        for pid, d in tot.items():
            lg = league[d["grp"]]
            rate = (d["ev"] + k_min * lg) / (d["min"] + k_min) if lg > 0 else 0.0   # shrunk
            rel = min(rel_clip[1], max(rel_clip[0], rate / lg)) if lg > 0 else 1.0
            wdef = (d["wmin"] / sw) * rel
            players[pid] = {"name": d["name"], "grp": d["grp"], "wdef": wdef, "avg_min": d["wmin"] / sw}
            group_total[d["grp"]] += wdef
        out[tid] = {"players": players, "group_total": group_total, "total": sum(group_total.values())}
    return out


def apply_injuries(factors, profiles, injured, k=0.15, spill=0.25, min_avg_min=8.0, clip=(0.80, 1.15)):
    """Omekša faktore protivnika kad ključni branioci ne igraju.

    injured: {athlete_id: tezina 0..1} (vidi status_weight). Vraca NOVI dict; ulazni se ne mijenja.
    Za svaku poziciju: udio izgubljene odbrane = vlastita grupa + spill * ostale grupe (npr. izostanak
    centra slabi i odbranu na obodu, ali manje). Faktor: f / (1 + k * udio). Dodaje "missing" listu.
    """
    out = {}
    for tid, entry in factors.items():
        new = {key: (dict(val) if isinstance(val, dict) else val) for key, val in entry.items()}
        prof = profiles.get(tid)
        missing = []
        if prof and prof["total"] > 0:
            lost = {g: 0.0 for g in GROUPS}
            for pid, p in prof["players"].items():
                wt = injured.get(pid, 0.0)
                if wt > 0 and p["avg_min"] >= min_avg_min:
                    lost[p["grp"]] += wt * p["wdef"]
                    missing.append({"name": p["name"], "grp": p["grp"], "status": status_label(wt), "status_weight": wt,
                                    "share": round(wt * p["wdef"] / prof["total"], 3)})
            lost_all = sum(lost.values())
            if lost_all > 0:
                for g in GROUPS:
                    own = lost[g] / prof["group_total"][g] if prof["group_total"][g] > 0 else 0.0
                    other = (lost_all - lost[g]) / prof["total"]
                    share = min(1.0, own) + spill * min(1.0, other)
                    for stat, f in entry[g].items():
                        new[g][stat] = round(min(clip[1], max(clip[0], f / (1.0 + k * share))), 3)
        new["missing"] = sorted(missing, key=lambda m: -m["share"])[:4]
        out[tid] = new
    return out
