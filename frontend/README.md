# AgentRehearsal UI

React 19 + Vite + Tailwind 4. Five stages: Define, Rehearse, Diagnose, Protect, Replay.

```bash
npm install
npm run dev        # http://localhost:5173, /api proxied to http://127.0.0.1:8000
npm run build      # dist/
```

For a hosted build (Amplify), set `VITE_API_BASE` to the API's URL at build time.

The app uses client-side routes (`/`, `/guides/...`, `/app`). On Amplify Hosting add a rewrite rule so every path serves `index.html`:
source `</^[^.]+$|\.(?!(css|gif|ico|jpg|js|png|txt|svg|woff|woff2|ttf|map|json)$)([^.]+$)/>`, target `/index.html`, type `200 (Rewrite)`.
