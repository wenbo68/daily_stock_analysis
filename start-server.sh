#!/usr/bin/env bash
# Start the web server (backend API + the built web app in static/).
#
# Usage:            ./start-server.sh
# Then open:        http://localhost:8000/tiered-alt
# Stop it with:     Ctrl+C
#
# Note: if you changed frontend code, rebuild it first so the server
# serves the new version:  cd apps/dsa-web && npm run build

cd "$(dirname "$0")"
.venv/bin/python main.py --serve-only
