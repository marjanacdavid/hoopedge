# HOOPEDGE V2 REAL FREE API — FIXED

This build uses ESPN's public NBA JSON feeds without an API key. It loads today's and tomorrow's schedule, team rosters and player statistics/game logs, with caching and parallel requests.

## Windows
1. Extract the folder.
2. Run `run_windows.bat`.
3. Open http://127.0.0.1:8000

The dashboard now loads `/api/projections` only once, shows API errors in the browser, and writes provider errors to the terminal running uvicorn.

If ESPN blocks a request, the dashboard will explicitly show the HTTP/network error rather than staying on CONNECTING.
