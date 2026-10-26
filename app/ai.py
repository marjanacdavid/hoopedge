"""HOOPEDGE AI asistent (Gemini): objasnjava projekcije tvog modela.

Brojeve racuna engine.py. Gemini ih samo cita preko alata i tumaci.
Env varijable:
  GEMINI_API_KEY        (besplatno: https://aistudio.google.com/apikey)
  HOOPEDGE_AI_MODEL     (opciono, default gemini-3.5-flash)
  HOOPEDGE_AI_RATE      (opciono, poruka po satu po IP-u, default 20)
"""
import json
import logging
import os
import time
from collections import defaultdict, deque

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

log = logging.getLogger("hoopedge.ai")
MODEL = os.getenv("HOOPEDGE_AI_MODEL", "gemini-3.5-flash")
FALLBACK_MODELS = ["gemini-2.5-flash", "gemini-flash-latest", "gemini-2.5-flash-lite"]  # ako glavni model ne postoji za tvoj kljuc
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_FALLBACKS = ["llama-3.3-70b-versatile"]
RATE_LIMIT = int(os.getenv("HOOPEDGE_AI_RATE", "20"))
_hits = defaultdict(deque)

SYSTEM = (
    "Ti si HOOPEDGE asistent za NBA projekcije (PTS, AST, REB). "
    "Sve brojke uzimas ISKLJUCIVO iz alata; nikad ih ne izmisljas i ne "
    "citas iz memorije. Ako igraca nema u alatu, reci to. Linije kladionica "
    "ponekad nisu dostupne (book_line je prazan): tada ne tvrdi over/under "
    "nego reci prag npr. '25+' prema thresholds_pct. Kad book_line postoji, "
    "citiraj lean, over_pct/under_pct i edge_pts iz alata i naglasi da su to "
    "procjene modela, ne garancija. Objasni kratko (3-6 recenica): projekcija, glavni faktori "
    "(forma, minute, tempo, odbrana protivnika, usage) i nesigurnost "
    "(recent_std). Ovo je statisticka procjena, ne garancija i ne finansijski "
    "savjet. Odgovaraj na jeziku kojim korisnik pise."
)


def gemini_key() -> str:
    """Kljuc iz env varijable; uklanja razmake, navodnike i slucajni prefiks 'GEMINI_API_KEY='."""
    k = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip().strip("\"'").strip()
    if k.upper().startswith("GEMINI_API_KEY="):
        k = k.split("=", 1)[1].strip().strip("\"'")
    return k


def groq_key() -> str:
    k = (os.getenv("GROQ_API_KEY") or "").strip().strip("\"'").strip()
    if k.upper().startswith("GROQ_API_KEY="):
        k = k.split("=", 1)[1].strip().strip("\"'")
    return k


def groq_report() -> dict:
    """Groq kljucevi pocinju s 'gsk_'."""
    k = groq_key()
    return {"loaded": bool(k), "length": len(k), "looks_valid": k.startswith("gsk_")}


class AIError(Exception):
    def __init__(self, kind, message):
        super().__init__(message)
        self.kind, self.message = kind, message


def key_report() -> dict:
    """Dijagnostika bez otkrivanja kljuca: Google kljucevi pocinju s 'AIza' i imaju 39 znakova."""
    k = gemini_key()
    return {"loaded": bool(k), "length": len(k), "looks_valid": k.startswith("AIza") and len(k) == 39}


def _summary(x) -> dict:
    return {
        "name": x.name, "team": x.team, "opponent": x.opponent, "market": x.market,
        "game_date": x.game_date, "game_time": x.game_time,
        "projection": x.projection, "line": x.line,
        "last5": x.stat_last5, "last10": x.stat_last10, "last20": x.stat_last20,
        "season": x.stat_season, "expected_minutes": x.expected_minutes,
        "usage": x.usage, "pace_pct": x.pace, "opponent_defense_factor": x.opponent_defense,
        "opponent_defense_vs_position": x.opponent_defense_pos, "position_group": x.position_group, "opponent_missing_defenders": x.opponent_missing_defenders,
        "recent_std": x.recent_std, "trend": x.trend,
        "confidence": x.confidence, "model_score": x.model_score,
        "thresholds_pct": x.thresholds, "reasons": x.reasons,
        "book_line": x.line, "lean": x.lean, "over_pct": x.over_probability,
        "under_pct": x.under_probability, "edge_pts": x.edge,
        "back_to_back": x.b2b, "rest_days": x.rest_days, "game_total": x.game_total,
        "spread_for_team": x.spread, "context_adjustment_pct": x.context_pct,
    }


class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    history: list[dict] = Field(default_factory=list, max_length=8)


def build_router(get_state, guard=None):
    """get_state() vraca STATE dict iz main.py (kljuc 'data', 'ready')."""
    router = APIRouter()

    # ---- alati (Gemini ih poziva sam; potpisi i docstringovi su njegova uputa) ----
    def get_player_projection(player_name: str, market: str = "PTS") -> dict:
        """Vraca projekciju jednog igraca. player_name je ime ili dio imena,
        market je PTS, AST, REB, 3PM (trojke) ili PA (poeni+asistencije)."""
        st = get_state()
        if not st["ready"]:
            return {"error": "Model se jos zagrijava, pokusaj za minut."}
        rows = st["data"].get(str(market).upper(), [])
        q = player_name.lower().strip()
        hits = [r for r in rows if q and q in r.name.lower()]
        if not hits:
            return {"error": f"Nema igraca '{player_name}' medju danasnjim/sutrasnjim utakmicama."}
        return {"results": [_summary(r) for r in hits[:3]]}

    def get_top_players(market: str = "PTS", limit: int = 5) -> dict:
        """Vraca igrace s najvisim model_score za trziste (PTS, AST ili REB),
        iz danasnjih i sutrasnjih utakmica. limit je od 1 do 10."""
        st = get_state()
        if not st["ready"]:
            return {"error": "Model se jos zagrijava, pokusaj za minut."}
        rows = st["data"].get(str(market).upper(), [])
        n = max(1, min(int(limit), 10))
        top = sorted(rows, key=lambda r: r.model_score, reverse=True)[:n]
        return {"results": [_summary(r) for r in top]}

    GROQ_TOOLS = [
        {"type": "function", "function": {
            "name": "get_player_projection",
            "description": "Projekcija jednog igraca za trziste. player_name je ime ili dio imena.",
            "parameters": {"type": "object", "properties": {
                "player_name": {"type": "string"},
                "market": {"type": "string", "enum": ["PTS", "AST", "REB", "3PM", "PA"]}},
                "required": ["player_name"]}}},
        {"type": "function", "function": {
            "name": "get_top_players",
            "description": "Igraci s najvisim model_score za trziste (danasnje/sutrasnje utakmice).",
            "parameters": {"type": "object", "properties": {
                "market": {"type": "string", "enum": ["PTS", "AST", "REB", "3PM", "PA"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10}}}}},
    ]
    TOOL_IMPL = {"get_player_projection": get_player_projection, "get_top_players": get_top_players}

    def _history(body):
        return [{"role": m["role"], "content": str(m["content"])[:1000]}
                for m in body.history if m.get("role") in ("user", "assistant") and m.get("content")]

    def ask_gemini(key, body):
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            raise AIError("other", "Nedostaje paket google-genai (pip install google-genai).")
        contents = []
        for m in _history(body):
            role = "user" if m["role"] == "user" else "model"
            contents.append(types.Content(role=role, parts=[types.Part.from_text(text=m["content"])]))
        contents.append(types.Content(role="user", parts=[types.Part.from_text(text=body.question)]))
        client = genai.Client(api_key=key)
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM,
            tools=[get_player_projection, get_top_players],  # automatski poziva alate
            automatic_function_calling=types.AutomaticFunctionCallingConfig(maximum_remote_calls=4),
            max_output_tokens=1500,
        )
        last_err, overloaded = "", False
        for attempt in range(2):          # drugi krug nakon kratke pauze ako je Google preopterecen
            overloaded = False
            for model in dict.fromkeys([MODEL, *FALLBACK_MODELS]):
                try:
                    resp = client.models.generate_content(model=model, contents=contents, config=config)
                    return resp.text or "Nisam uspio formirati odgovor, pokusaj preciznije pitanje."
                except Exception as exc:
                    last_err = str(exc).replace(key, "***")
                    log.error("Gemini call failed (model=%s): %s", model, last_err[:500])
                    low = last_err.lower()
                    if "429" in last_err or "RESOURCE_EXHAUSTED" in last_err:
                        raise AIError("rate", "Besplatni Gemini limit je potrosen.")
                    if "503" in last_err or "unavailable" in low or "high demand" in low or "overloaded" in low or "500" in last_err:
                        overloaded = True
                        continue
                    if "404" in last_err or "not_found" in low or "not found" in low:
                        continue
                    raise AIError("other", last_err[:180])
            if not overloaded:
                break
            time.sleep(2)
        if overloaded:
            raise AIError("overloaded", "Google Gemini je trenutno preopterecen.")
        raise AIError("other", last_err[:180])

    def ask_groq(key, body):
        import requests
        base = [{"role": "system", "content": SYSTEM}, *_history(body), {"role": "user", "content": body.question}]
        last_err = ""
        for model in dict.fromkeys([GROQ_MODEL, *GROQ_FALLBACKS]):
            msgs = list(base)
            try:
                for _ in range(4):
                    r = requests.post(GROQ_URL, headers={"Authorization": f"Bearer {key}"}, timeout=(5, 40),
                                      json={"model": model, "messages": msgs, "tools": GROQ_TOOLS,
                                            "tool_choice": "auto", "max_tokens": 1200, "temperature": 0.3})
                    if r.status_code >= 400:
                        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
                    msg = r.json()["choices"][0]["message"]
                    calls = msg.get("tool_calls")
                    if not calls:
                        return (msg.get("content") or "").strip() or "Nisam uspio formirati odgovor."
                    msgs.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
                    for c in calls:
                        impl = TOOL_IMPL.get(c["function"]["name"])
                        try:
                            out = impl(**json.loads(c["function"].get("arguments") or "{}")) if impl else {"error": "nepoznat alat"}
                        except Exception as e:
                            out = {"error": f"los poziv alata: {e}"}
                        msgs.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(out, default=str)})
                last_err = "Groq nije zavrsio analizu."
            except Exception as exc:
                last_err = str(exc).replace(key, "***")
                log.error("Groq call failed (model=%s): %s", model, last_err[:500])
        low = last_err.lower()
        if "429" in last_err or "rate" in low:
            raise AIError("rate", "Groq limit je potrosen.")
        if "401" in last_err or "invalid api key" in low:
            raise AIError("other", "Groq kljuc nije validan.")
        raise AIError("other", last_err[:180])

    @router.post("/api/chat")
    def chat(body: ChatIn, request: Request):
        if guard:
            guard(request)   # samo prijavljeni korisnici s Pro+ planom (ili admin)
        gkey, qkey = gemini_key(), groq_key()
        if not gkey and not qkey:
            raise HTTPException(503, detail={"message": "AI nije podesen (postavi GEMINI_API_KEY ili GROQ_API_KEY)."})

        ip = request.client.host if request.client else "?"
        now = time.time()
        q = _hits[ip]
        while q and now - q[0] > 3600:
            q.popleft()
        if len(q) >= RATE_LIMIT:
            raise HTTPException(429, detail={"message": "Dosegnut limit pitanja, pokusaj kasnije."})
        q.append(now)

        providers = [("Gemini", gkey, ask_gemini), ("Groq", qkey, ask_groq)]
        if os.getenv("HOOPEDGE_AI_PROVIDER", "auto").lower() == "groq":
            providers.reverse()
        errors = []
        for name, key, fn in providers:
            if not key:
                continue
            try:
                return {"answer": fn(key, body), "provider": name}
            except AIError as e:
                errors.append((name, e))
        kinds = {e.kind for _, e in errors}
        if kinds == {"rate"}:
            raise HTTPException(429, detail={"message": "Besplatni limit AI-ja je potrosen, pokusaj kasnije."})
        if "overloaded" in kinds and kinds <= {"overloaded", "rate"}:
            raise HTTPException(503, detail={"message": "AI je trenutno preopterecen (privremeno). Pokusaj ponovo za minut-dva."})
        raise HTTPException(502, detail={"message": "AI trenutno nije dostupan: " + "; ".join(f"{n}: {e.message}" for n, e in errors)[:300]})

    return router
