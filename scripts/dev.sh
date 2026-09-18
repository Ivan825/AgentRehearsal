#!/usr/bin/env bash
# Start the API and the UI for local development. Ctrl-C stops both.
set -euo pipefail
cd "$(dirname "$0")/.."
(cd backend && uvicorn agentrehearsal.api:app --reload --port 8000) &
API=$!
trap 'kill $API 2>/dev/null' EXIT
(cd frontend && npm run dev)
