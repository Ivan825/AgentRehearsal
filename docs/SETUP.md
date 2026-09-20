# Team setup: from zero to a working AgentRehearsal in ~20 minutes

Everything below is for macOS (the team's machines). Steps marked **AWS** need a key; everyone else can
skip them and still run the whole product with the offline simulation.

## 0. What you are setting up

```
backend/    FastAPI API + the rehearsal engine (Python 3.12, Strands Agents, cedarpy)
frontend/   React UI (Vite, Tailwind)                     → http://localhost:5173
scripts/    dev.sh (runs both), push_image.sh (deploy), aws_whoami.py (check keys)
docs/       PRODUCT_GUIDE (what every screen does), DEMO_SCRIPT, DEPLOY, WRITEUP
```

## 1. Tools (once)

```bash
xcode-select --install                     # skip if you already have git
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"   # skip if brew exists
brew install python@3.12 node@22 git
echo 'export PATH="/opt/homebrew/opt/node@22/bin:/opt/homebrew/opt/python@3.12/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
python3.12 --version    # 3.12.x   (NOT 3.13/3.14: the venv hangs and cedarpy has no wheel)
node --version          # v22.x    (Vite 8 needs 22+)
```

Docker Desktop is only needed by whoever deploys the API image. Skip it otherwise.

## 2. Clone and install

```bash
git clone https://github.com/Ivan825/AgentRehearsal.git
cd AgentRehearsal

# backend
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
cd ..

# frontend
cd frontend && npm install && cd ..
```

If your prompt shows `(.venv)` twice, that is harmless; it is the same venv activated twice.

## 3. Run it (no AWS needed)

```bash
./scripts/dev.sh
```

Open http://localhost:5173, create an account (local file store, your laptop only), then in the app:
**Start from an example… → SupportBot**, tick **offline sim** in the header, **▶ Run Rehearsal**, then
follow the **next** bar: Protect → Replay. That is the entire loop running on the scripted agent, no
credentials involved. Ctrl-C stops both servers. Restart the script after backend changes (it deliberately
does not auto-reload, because a reload kills a run in progress).

Terminal equivalent, useful for quick checks:

```bash
cd backend && source .venv/bin/activate
python -m agentrehearsal.cli demo --model scripted
pytest -q            # 24 tests, ~15 s, no network
```

## 4. AWS (only if you will run live Bedrock or deploy)

Ask Ivan for an IAM user of your own (IAM → Users → Create user, same policies as `agentrehearsal`:
Bedrock, DynamoDB, plus ECR PowerUser for whoever deploys). Never share keys over chat; never commit them.
`backend/.env` is gitignored. Put in it:

```
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1
AGENTREHEARSAL_TARGET_MODEL=us.amazon.nova-lite-v1:0
AGENTREHEARSAL_AUTHOR_MODEL=global.anthropic.claude-opus-4-6-v1
# AGENTREHEARSAL_DDB_TABLE=agentrehearsal    # leave commented: local file store, so you do not share accounts/runs with others
```

Then:

```bash
cd backend && source .venv/bin/activate
python ../scripts/aws_whoami.py       # identity + OK/DENIED per service
python -m agentrehearsal.cli doctor   # Bedrock model access
python -m agentrehearsal.cli demo --model bedrock   # ~3 min, real Nova Lite agent
```

With `.env` filled, untick **offline sim** in the UI and every run, Generate with Bedrock and
Validate on unseen attacks go against real models. If you see "model identifier is invalid", check that
`.env` has one variable per line (a glued line is the usual cause). If a key ever leaks, deactivate it in
IAM immediately; do not just rotate the file.

## 5. Working together

* One branch per person: `git checkout -b <name>/<topic>`. Commit small, often.
* Before every push: `git pull --rebase origin main`. Merge to `main` yourself as soon as it works, so
  the others get it. Nobody edits `main` directly.
* Run `pytest -q` in `backend/` and `npm run build` in `frontend/` before merging. Both must be clean.
* If git says `index.lock exists`: `rm .git/index.lock` (a crashed process left it).
* Stored runs for the demo live in `backend/examples/runs/`; your local runs are in `backend/runs/`
  (gitignored). Copy a run into `examples/runs/` only if it is one we will show.

## 6. Ownership for the rest of the hackathon

| Who | Area | Files |
|---|---|---|
| Ivan | Deployment: ECR image, ECS Express service, Amplify + proxy rewrites, `AGENTREHEARSAL_PUBLIC_URL`, smoke test | `docs/DEPLOY.md`, `scripts/`, `amplify.yml`, `backend/Dockerfile` |
| Jayant | Evidence: TravelDesk live on Bedrock (`generate` → `examples/traveldesk.scenarios.json`, rehearse → replay → validate), `agentrehearsal validate` on SupportBot, copy good runs to `examples/runs/`, record the video from `docs/DEMO_SCRIPT.md` | `backend/examples/`, video |
| Shive | AgentCore Gateway Path B, time-boxed 3 h. Goal: one script that sends the same tool call to the local evaluator and the Gateway and prints both decisions. If it does not come up, stop and help Jayant | `infra/`, `backend/agentrehearsal/target/` |
| Nirbhay | Submission: real numbers into `docs/WRITEUP.md`, update the team PDF, click through the deployed UI as a first-time user and file every confusing moment as a GitHub issue | `docs/`, `README.md` |

## 7. Where things are, when you need to change them

| Want to change | Look in |
|---|---|
| A screen in the app | `frontend/src/components/<Stage>.tsx`; `App.tsx` is the shell and the next-step logic |
| The public website / guides | `frontend/src/site/` |
| An API endpoint | `backend/agentrehearsal/api.py` |
| How scenarios are authored | `backend/agentrehearsal/scenarios/generator.py` (reads the world from the spec) |
| Seed scenarios | `backend/agentrehearsal/scenarios/seeds.json` |
| The verdict rules | `backend/agentrehearsal/verdict.py` |
| Constraints → Cedar | `backend/agentrehearsal/policy/cedar.py` |
| An example agent | `backend/examples/*.spec.json`; register it in `EXAMPLES` in `api.py` |
| The offline naive agent | `backend/agentrehearsal/models/scripted.py` (SupportBot only, labelled as a simulation) |

## 8. Common problems

| Symptom | Fix |
|---|---|
| `Address already in use :8000` | `lsof -ti :8000 \| xargs kill -9` |
| Blank page at :5173 | Check the browser console; usually a component threw. `npm run build` shows the TypeScript error |
| UI says "The API restarted while this run was in progress" | You restarted `dev.sh` mid-run. Start the run again |
| Login says "No account with that email" | Accounts are per store: a fresh clone has none. Create one |
| Bedrock `AccessDenied` on first call | Model access is enabled on first invoke in this account; run `doctor` again after a minute |
| Anthropic model "use case details required" | Already approved on the shared account; on your own account, Bedrock console → the model → submit the form |
| Docker build stuck on a layer | Ctrl-C and rerun; it resumes. Base image comes from `public.ecr.aws`, not Docker Hub |
