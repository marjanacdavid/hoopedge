from pathlib import Path
import logging
import os
import threading
import time

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .provider import ESPNFreeProvider
from .engine import project
from .ai import build_router, key_report, groq_report
from .odds import OddsProvider
from .tracking import Tracker
from .smart import build_smart, MARKETS
from . import accounts, gating, mailer

log = logging.getLogger("hoopedge.main")

# Resolve paths from this file instead of the process working directory.
# This works both locally (run_windows.bat) and on Render.
APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
WEB_DIR = PROJECT_DIR / "web"
INDEX_FILE = WEB_DIR / "index.html"
ACCOUNT_FILE = WEB_DIR / "account.html"

app = FastAPI(title="HOOPEDGE API", version="2.1.0")
provider = ESPNFreeProvider()
odds = OddsProvider()
tracker = Tracker()
accounts.seed_admin()   # admin nalog iz env-a (HOOPEDGE_ADMIN_USER / HOOPEDGE_ADMIN_PASSWORD_HASH)

# ---------- Pozadinski proračun ----------
STATE = {"data": {}, "ready": False, "updated": 0.0, "error": None}
_refresh_lock = threading.Lock()


def refresh():
    # Samo jedan proračun istovremeno
    if not _refresh_lock.acquire(blocking=False):
        return
    try:
        players = provider.players()
        try:
            odds.refresh_if_due()
            for p in players:
                found = {}
                for mk in MARKETS:
                    ln = odds.lookup(mk, p.name, p.game_time)
                    if ln:
                        found[mk] = ln
                p.lines = found
                if p.game_total is None or p.spread is None:
                    home_n, away_n = (p.team_nick, p.opp_nick) if p.home else (p.opp_nick, p.team_nick)
                    g = odds.game_line(home_n, away_n, p.game_time)
                    if g:
                        if p.game_total is None: p.game_total = g["total"]
                        if p.spread is None and g["home_spread"] is not None:
                            p.spread = g["home_spread"] if p.home else -g["home_spread"]
        except Exception:
            log.exception("Odds attach failed")
        STATE["data"] = {
            m: [project(p, market=m) for p in players]
            for m in MARKETS
        }
        try:
            STATE["smart"] = build_smart(players, STATE["data"])
        except Exception:
            log.exception("Smart build failed")
        try:
            tracker.record([r for m in MARKETS for r in STATE["data"][m]])
            tracker.grade(provider)
        except Exception:
            log.exception("Tracking failed")
        STATE["ready"] = bool(players)
        STATE["updated"] = time.time()
        STATE["error"] = None if players else (provider.last_errors[-5:] or "No players")
    except Exception as exc:
        log.exception("Refresh failed")
        STATE["error"] = str(exc)
    finally:
        _refresh_lock.release()


def _loop():
    while True:
        refresh()
        time.sleep(240 if STATE["ready"] else 30)


@app.on_event("startup")
def start_background():
    if not os.getenv("HOOPEDGE_BASE_URL"):
        log.warning("HOOPEDGE_BASE_URL nije postavljen: linkovi u emailu za potvrdu mogu biti ispravni samo uz SMTP bez ovoga.")
    if not mailer.configured():
        log.warning("SMTP nije podesen: emailovi se NE salju, linkovi se upisuju u log (journalctl -u hoopedge).")
    if accounts.dev_links_on():
        log.warning("DEV REZIM: linkovi za potvrdu/reset lozinke se prikazuju na ekranu (samo za zahtjeve sa ovog racunara). NE koristiti na javnom serveru!")
    elif os.getenv("HOOPEDGE_DEV_SHOW_LINKS") == "1":
        log.warning("HOOPEDGE_DEV_SHOW_LINKS je ignorisan jer je SMTP podesen.")
    if not hasattr(__import__("hashlib"), "scrypt"):
        log.error("Ovaj Python nema scrypt (stari OpenSSL): prijava nece raditi. Instaliraj Python sa python.org.")
    threading.Thread(target=_loop, daemon=True).start()


def all_proj(market="PTS"):
    if not STATE["ready"]:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Model is warming up, try again in a minute",
                "loading": True,
                "errors": provider.last_errors[-5:],
            },
        )
    return STATE["data"][market if market in STATE["data"] else "PTS"]


@app.exception_handler(Exception)
async def api_exception_handler(request: Request, exc: Exception):
    """Keep API failures JSON so the frontend never receives an HTML 500 page."""
    log.exception("Unhandled request error: %s %s", request.method, request.url.path)
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=500,
            content={
                "detail": {
                    "message": "HOOPEDGE backend error",
                    "error": str(exc),
                }
            },
        )
    # Let non-API errors retain FastAPI's normal behavior as much as possible.
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/api/health")
def health():
    return {
        "status": "ready" if STATE["ready"] else "warming_up",
        "product": "HOOPEDGE",
        "provider": "ESPN public free endpoints",
        "real_data": True,
        "stats": provider.last_stats,
        "errors": provider.last_errors[-5:],
        "last_error": STATE["error"],
        "odds": odds.public_status(),
        "gemini_key": key_report(),
        "groq_key": groq_report(),
    }


@app.get("/api/projections")
def projections(request: Request, response: Response, market: str = "PTS"):
    ctx = accounts.get_ctx(request)
    response.headers["Cache-Control"] = "private, no-store"
    market = market.upper()
    if market not in set(MARKETS):
        market = "PTS"
    gating.check_market(ctx.ent, market)
    try:
        return gating.gate_projections(all_proj(market), ctx.ent, market, all_proj("PTS"))
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Projection generation failed")
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Free NBA data provider failed",
                "errors": provider.last_errors[-5:] or [str(exc)],
            },
        )


@app.get("/api/smart-picks")
def smart_picks(request: Request, response: Response, limit: int = 200, market: str = "ALL", min_win: float = 0.0, source: str = "all"):
    """Rang lista pickova po Win Chance kroz sve kategorije (book linije + model-only)."""
    if not STATE["ready"]:
        raise HTTPException(status_code=503, detail={"message": "Model is warming up, try again in a minute", "loading": True})
    rows = STATE.get("smart", [])
    if market.upper() != "ALL":
        rows = [r for r in rows if r["smart_market"] == market.upper()]
    if source in ("book", "model"):
        rows = [r for r in rows if r["smart_source"] == source]
    rows = [r for r in rows if (r.get("win_chance") or 0) >= min_win]
    ctx = accounts.get_ctx(request)
    response.headers["Cache-Control"] = "private, no-store"
    rows = gating.gate_smart(rows, ctx.ent, all_proj("PTS"))
    return rows[: max(1, min(limit, 500))]


@app.get("/api/tracking/summary")
def tracking_summary(request: Request):
    accounts.require_admin(request)
    return tracker.summary()


@app.get("/api/tracking/signals")
def tracking_signals(request: Request, min_n: int = 20):
    accounts.require_admin(request)
    return tracker.signals(min_n)


@app.get("/api/tracking/picks")
def tracking_picks(request: Request, status: str = "", limit: int = 100):
    accounts.require_admin(request)
    return tracker.picks(status or None, min(limit, 500))


@app.get("/api/tracking/export.csv")
def tracking_export(request: Request):
    accounts.require_admin(request)
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(tracker.export_csv(), media_type="text/csv")


@app.get("/api/value-props")
def value_props(request: Request, response: Response, market: str = "PTS", limit: int = 20, min_edge: float = 3.0):
    """Igraci s linijom kladionice, sortirani po prednosti modela (edge)."""
    ctx = accounts.get_ctx(request)
    response.headers["Cache-Control"] = "private, no-store"
    market = market.upper()
    gating.check_market(ctx.ent, market)
    rows = [x for x in all_proj(market) if x.line is not None and x.edge >= min_edge]
    rows = sorted(rows, key=lambda x: x.edge, reverse=True)[:limit]
    return gating.gate_projections(rows, ctx.ent, market, all_proj("PTS"))


@app.get("/api/top-props")
def top_props(request: Request, response: Response, limit: int = 8, market: str = "PTS"):
    ctx = accounts.get_ctx(request)
    response.headers["Cache-Control"] = "private, no-store"
    market = market.upper()
    gating.check_market(ctx.ent, market)
    rows = sorted(all_proj(market), key=lambda x: (x.projection - x.stat_season), reverse=True)[:limit]
    return gating.gate_projections(rows, ctx.ent, market, all_proj("PTS"))


@app.get("/api/players/{player_id}")
def player(request: Request, response: Response, player_id: int, market: str = "PTS"):
    ctx = accounts.get_ctx(request)
    response.headers["Cache-Control"] = "private, no-store"
    market = market.upper()
    gating.check_market(ctx.ent, market)
    x = next(
        (x for x in all_proj(market) if x.player_id == player_id),
        None,
    )
    if not x:
        raise HTTPException(status_code=404, detail="Player not found")
    if not gating.player_allowed(ctx.ent, player_id, all_proj("PTS")):
        if not ctx.user:
            raise gating.upgrade_error(login=True)
        raise HTTPException(403, detail={"message": "This player is locked on your plan.", "upgrade_required": True, "required_plan": "pro"})
    return x


@app.get("/api/debug/player/{athlete_id}")
def debug_player(request: Request, athlete_id: int, opp: str = ""):
    """Provjera ESPN game loga. Dodaj ?opp=CLE da vidis sve H2H utakmice koje aplikacija nalazi."""
    accounts.require_admin(request)
    return provider.debug_player(athlete_id, opp)


@app.get("/api/plans")
def plans():
    return [
        {
            "id": "free",
            "name": "FREE",
            "price": 0,
            "features": [
                "First 5 projections of the day",
                "Points (PTS) market only",
                "Everything else is blurred",
            ],
        },
        {
            "id": "pro",
            "name": "PRO",
            "price": 9.99,
            "features": [
                "All player points projections",
                "Points (PTS) market only",
                "No HOOPEDGE AI assistant",
                "1 month access",
            ],
        },
        {
            "id": "pro_plus",
            "name": "PRO+",
            "price": 39.99,
            "features": [
                "Everything: PTS, AST, REB, 3PM and P+A",
                "Smart Prediction across all markets",
                "HOOPEDGE AI assistant",
                "1 month access",
            ],
        },
    ]


def _ai_guard(request: Request):
    ctx = accounts.get_ctx(request)
    if not ctx.user:
        raise gating.upgrade_error(login=True)
    if not ctx.ent["ai"]:
        raise gating.upgrade_error(ai=True)


app.include_router(accounts.router)
app.include_router(build_router(lambda: STATE, guard=_ai_guard))


# Serve the existing web folder without assuming Render's current working directory.
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/")
def home():
    return FileResponse(str(INDEX_FILE))


@app.get("/account")
def account_page():
    return FileResponse(str(ACCOUNT_FILE), headers={"Cache-Control": "no-store"})


@app.get("/terms")
def terms_page():
    return FileResponse(str(WEB_DIR / "terms.html"), headers={"Cache-Control": "no-store"})


@app.get("/privacy")
def privacy_page():
    return FileResponse(str(WEB_DIR / "privacy.html"), headers={"Cache-Control": "no-store"})
