#!/usr/bin/env bash
# Lokalno testiranje na Linux/Mac (ekvivalent run_windows.bat + local.bat). NE koristiti na javnom serveru.
cd "$(dirname "$0")"
[ -f keys.sh ] && source keys.sh          # export GEMINI_API_KEY=...  export ODDS_API_KEY=...
export HOOPEDGE_ADMIN_USER="AdminHoopEd8"
export HOOPEDGE_ADMIN_PASSWORD_HASH="scrypt:16384:8:1:ZDuxHAZgMHC2pRMrgJeBcA:6JGyaIXky36llh697Wh9qkdWqLfuOL1bJS_2RoOwLio"
export HOOPEDGE_BASE_URL="http://127.0.0.1:8000"
export HOOPEDGE_DEV_SHOW_LINKS=1
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
exec python -m uvicorn app.main:app --reload --port 8000
