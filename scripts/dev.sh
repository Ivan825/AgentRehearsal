#!/usr/bin/env bash
# Start the API and the UI for local development. Ctrl-C stops both.
set -euo pipefail
cd "$(dirname "$0")/.."
# No --reload on purpose: a reload kills any run in progress. Restart the script after backend changes.
# Local install: command-line (stdio) MCP servers such as `npx @modelcontextprotocol/server-filesystem` are allowed.
export AGENTREHEARSAL_ALLOW_STDIO=1
(cd backend && uvicorn agentrehearsal.api:app --port 8000) &
API=$!
trap 'kill $API 2>/dev/null' EXIT
(cd frontend && npm run dev)
