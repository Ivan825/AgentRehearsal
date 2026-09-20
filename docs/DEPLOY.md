# Deploying AgentRehearsal

Two pieces: the API runs as a container on Amazon ECS (Express Mode) and the UI is a static
Vite build on Amplify Hosting. Amplify proxies `/api/*` and `/mcp/*` to the API, so the browser
only ever talks to one HTTPS origin (no CORS, no mixed content) and the MCP URL that
bring-your-own agents receive is the public Amplify address.

```
browser ── https://<app>.amplifyapp.com ── Amplify Hosting ── /api/*, /mcp/* ──► http://<alb>  (ECS service)
                                                        └── everything else ──► index.html (SPA)
```

## 1. API image → ECR

Requires Docker Desktop running and an IAM user with `AmazonEC2ContainerRegistryPowerUser`
(create the repository `agentrehearsal-api` once in the ECR console).

```bash
./scripts/push_image.sh        # prints IMAGE URI: <account>.dkr.ecr.us-east-1.amazonaws.com/agentrehearsal-api:latest
```

## 2. ECS Express Mode service

Console → ECS → Create (Express). Settings:

| Field | Value |
|---|---|
| Image | the IMAGE URI above |
| Container port | 8000 |
| Task execution role | `ecsTaskExecutionRole` (trust ecs-tasks, `AmazonECSTaskExecutionRolePolicy`) |
| Task role | `agentrehearsal-task-role` (Bedrock invoke/list + DynamoDB on the `agentrehearsal` table) |
| CPU / memory | 1 vCPU / 2 GB |
| Health check | `/api/health` |

Environment variables (no AWS keys — the task role provides credentials):

```
AWS_REGION=us-east-1
AGENTREHEARSAL_DDB_TABLE=agentrehearsal
AGENTREHEARSAL_JWT_SECRET=<openssl rand -hex 32>
AGENTREHEARSAL_TARGET_MODEL=us.amazon.nova-lite-v1:0
AGENTREHEARSAL_AUTHOR_MODEL=global.anthropic.claude-opus-4-6-v1
AGENTREHEARSAL_PUBLIC_URL=https://<app>.amplifyapp.com      # add after step 3; the MCP URL is built from it
```

Check: `http://<service-url>/api/health` → `{"ok": true, "store": "dynamodb", "auth": true}`.

## 3. UI on Amplify Hosting

Amplify → Create new app → GitHub → this repo, branch `main`. The root `amplify.yml` is picked up
(app root `frontend`). Leave `VITE_API_BASE` unset: the UI calls `/api/...` on its own origin.

After the first build, App settings → **Rewrites and redirects** → add, in this order:

| Source | Target | Type |
|---|---|---|
| `/api/<*>` | `http://<service-url>/api/<*>` | 200 (Rewrite) |
| `/mcp/<*>` | `http://<service-url>/mcp/<*>` | 200 (Rewrite) |
| `</^[^.]+$\|\.(?!(css\|gif\|ico\|jpg\|js\|png\|txt\|svg\|woff\|woff2\|ttf\|map\|json)$)([^.]+$)/>` | `/index.html` | 200 (Rewrite) |

`<service-url>` is the ECS service's load-balancer address without a trailing slash. The API
rules come before the SPA rule so they are matched first.

Then set `AGENTREHEARSAL_PUBLIC_URL` on the ECS service to the Amplify URL and redeploy the
service, so the Bring-your-own-agent panel hands out `https://<app>.amplifyapp.com/mcp/<token>`.

Long operations (runs, scenario authoring) are background jobs polled through `/api/jobs/{id}`,
so nothing goes through the proxy for longer than a few seconds.

## 4. Smoke test

1. Open the Amplify URL, create an account, sign in.
2. Define → Load example → Run rehearsal (scripted) → scorecard appears.
3. Define → Generate with Bedrock → new scenarios arrive after 20–60 s.
4. Protect → Replay with enforcement → Replay tab shows the before/after comparison.
5. `GET /api/health` on the Amplify URL returns the API's health (proves the proxy).

## Updating

API: `./scripts/push_image.sh`, then ECS → service → **Update** → Force new deployment.
UI: push to `main`; Amplify rebuilds automatically.
