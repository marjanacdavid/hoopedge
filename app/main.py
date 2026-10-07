from pathlib import Path
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .provider import ESPNFreeProvider
from .engine import project

log = logging.getLogger("hoopedge.main")

# Resolve paths from this file instead of the process working directory.
# This works both locally (run_windows.bat) and on Render.
APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
WEB_DIR = PROJECT_DIR / "web"
INDEX_FILE = WEB_DIR / "index.html"

app = FastAPI(title="HOOPEDGE API", version="2.1.0")
provider = ESPNFreeProvider()


def all_proj(market="PTS"):
    return [project(p, market=market) for p in provider.players()]


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
        "status": "ready",
        "product": "HOOPEDGE",
        "provider": "ESPN public free endpoints",
        "real_data": True,
        "stats": provider.last_stats,
        "errors": provider.last_errors[-5:],
    }


@app.get("/api/projections")
def projections(market: str = "PTS"):
    market = market.upper()
    if market not in {"PTS", "AST", "REB"}:
        market = "PTS"
    try:
        return all_proj(market)
    except Exception as exc:
        log.exception("Projection generation failed")
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Free NBA data provider failed",
                "errors": provider.last_errors[-5:] or [str(exc)],
            },
        )


@app.get("/api/top-props")
def top_props(limit: int = 8, market: str = "PTS"):
    return sorted(
        all_proj(market.upper()),
        key=lambda x: (x.projection - x.stat_season),
        reverse=True,
    )[:limit]


@app.get("/api/players/{player_id}")
def player(player_id: int, market: str = "PTS"):
    x = next(
        (x for x in all_proj(market.upper()) if x.player_id == player_id),
        None,
    )
    if not x:
        raise HTTPException(status_code=404, detail="Player not found")
    return x


@app.get("/api/plans")
def plans():
    return [
        {
            "name": "FREE",
            "price": 0,
            "features": ["5 analyses/day", "Real NBA schedule", "Real player game logs"],
        },
        {
            "name": "PRO",
            "price": 9.99,
            "features": ["Unlimited", "Player projections", "Top Props", "Advanced stats"],
        },
        {
            "name": "PRO+",
            "price": 19.99,
            "features": ["Everything in PRO", "Future prop-line integration", "Alerts"],
        },
    ]


# Serve the existing web folder without assuming Render's current working directory.
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/")
def home():
    return FileResponse(str(INDEX_FILE))
