# AgentRehearsal UI

React 19 + Vite + Tailwind 4. Five stages: Define, Rehearse, Diagnose, Protect, Replay.

```bash
npm install
npm run dev        # http://localhost:5173, /api proxied to http://127.0.0.1:8000
npm run build      # dist/
```

For a hosted build see `docs/DEPLOY.md`: on Amplify the UI is served from the same origin as the API (rewrites proxy `/api` and `/mcp`), so `VITE_API_BASE` stays unset. Set it only when the UI is hosted somewhere that cannot proxy.

The app uses client-side routes (`/`, `/guides/...`, `/app`). On Amplify Hosting add a rewrite rule so every path serves `index.html`:
source `</^[^.]+$|\.(?!(css|gif|ico|jpg|js|png|txt|svg|woff|woff2|ttf|map|json)$)([^.]+$)/>`, target `/index.html`, type `200 (Rewrite)`.
