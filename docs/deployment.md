# MenoMate Deployment (Render, Manual)

Actual current deployment model for the production backend on `main`. Nothing here performs a deploy; it describes how the already-deployed service is configured and verified. Do not expose production secrets.

## 1. Render service architecture

- One **Web Service** (`menomate-core`, `runtime: python`) built from this repo.
- Stateless FastAPI (`uvicorn app.main:app`) + external **Supabase PostgreSQL** (data) + Supabase Auth (JWT issuance/verification) + optional Groq LLM (Care only).
- No workers, no cron, no scheduler, no firmware targets in this repo. Local-notification scheduling is planned, not built.
- The Flutter app talks to the service over HTTPS with Supabase JWTs; browsers never talk to it directly (CORS is restrictive in production).

## 2. `render.yaml`

Manual-launch blueprint at the repo root (not an auto-deploy pipeline). Relevant keys:

- `buildCommand: pip install -r requirements.txt`
- `startCommand: uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- `healthCheckPath: /health`
- `autoDeploy: false` — Render does **not** deploy on push. Every production deploy is a manual action in the Render dashboard from a reviewed `main` commit.
- `PYTHON_VERSION: 3.12.0`

Do not claim automatic deployment: `autoDeploy: false` is the current, intentional setting.

## 3. Build command

`pip install -r requirements.txt` on Python 3.12. No system packages, no migrations, no seed scripts run at build time.

## 4. Start command

`uvicorn app.main:app --host 0.0.0.0 --port $PORT`

- Binds `0.0.0.0` and respects Render's injected `$PORT` (the app never assumes port 8000).
- `lifespan` conditionally runs ORM DDL only when `AUTO_CREATE_TABLES=true` or sqlite; production keeps it `false`, so startup never mutates schema.

## 5. Health check

- Path: `/health` (no authentication). Expected: HTTP 200 `{"status": "healthy", ...}`.
- Render uses this for liveness/routing. `/` is a pointer (`docs`/`health`), not a health signal.

## 6. Environment variables

Set secrets in the Render dashboard (`sync: false` in `render.yaml`); never commit values.

| Variable | Render value / source | Notes |
|---|---|---|
| `DATABASE_URL` | Secret (`sync: false`) | `postgresql+asyncpg://…` to Supabase PostgreSQL |
| `SUPABASE_URL` | Secret (`sync: false`) | Project URL; feeds JWKS + issuer check |
| `SUPABASE_JWT_SECRET` | Secret (`sync: false`) | Only for legacy HS256; omit with asymmetric signing |
| `SUPABASE_JWKS_URL` | Secret (`sync: false`) | Optional override; derived from `SUPABASE_URL` by default |
| `ALLOWED_ORIGINS` | `""` | Restrictive; the Flutter app needs no browser CORS. Never pair `*` with credentials. |
| `AUTO_CREATE_TABLES` | `"false"` | Production must keep `false`; schema comes from SQL files |
| `GROQ_API_KEY` | Secret (`sync: false`) | Care LLM; unset → deterministic mock provider |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Non-secret default |
| `PYTHON_VERSION` | `3.12.0` | Runtime pin |

`.env.example` documents the same NAMES with placeholders for local dev; Render values are managed separately.

## 7. `AUTO_CREATE_TABLES=false`

Production keeps `AUTO_CREATE_TABLES=false` (also the code default). Consequences:

- Startup never creates or alters tables.
- Fresh projects are provisioned by executing `supabase_initial_schema.sql` in the Supabase SQL editor.
- Existing databases are advanced by applying `migrations/` in filename order (see `database-and-migrations.md`).
- Any proposal to flip this to `true` in production needs explicit review — it risks schema drift between ORM metadata and the curated SQL files.

## 8. Manual deployment model

1. Land reviewed work on `main` (feature branch → tests → review → merge; never develop directly on `main`).
2. In the Render dashboard, manually deploy the validated `main` commit to the production service (no push-to-deploy).
3. Confirm the service reports healthy before announcing availability.
4. Database changes are a separate manual step (see §10) — deploys never run migrations.

The current production service was deployed this way from `main` (`0baa5e7`); this document does not trigger any further deploy.

## 9. Production verification

After any manual deploy, verify in order:

1. `GET /health` → 200 `{"status": "healthy", ...}`.
2. `GET /docs` → Swagger UI loads; spot-check `/openapi.json` paths (29 API v1 paths expected).
3. Authenticated smoke calls with a real Supabase token: `GET /api/v1/auth/me`, `GET /api/v1/profile`, `GET /api/v1/cycles/current`, `GET /api/v1/summary/current`, `POST /api/v1/care/interactions` (small `user_message`).
4. Confirm `AUTO_CREATE_TABLES=false` in the service env and that no migration ran as part of the deploy.
5. Record the deployed commit hash; roll back by redeploying the prior known-good commit if health/smoke fails.

## 10. Swagger / health verification

- Swagger at `/docs` is the exact contract; this repo's `docs/api-contract.md` is the readable companion. Any drift between them is a docs bug — fix the docs, not the API, unless a reviewed code change is intended.
- `/health` is unauthenticated by design (Render + smoke tooling). All `/api/v1/*` except `GET /api/v1/symptoms` require a Bearer token (401 otherwise).

## 11. Database migration responsibility

- A human owns migrations: backup/snapshot, rehearse on a staging clone, apply missing `migrations/` files in order in the Supabase SQL editor, verify agreement with `supabase_initial_schema.sql`, then deploy/verify the backend.
- Never enable ORM DDL in production to "fix" a missing table; never edit an already-applied migration in place; never apply reproductive/health migrations to reinterpret legacy selections (e.g. no backfill from `health_contexts.pregnancy_context` into `pregnancy_contexts`).
- The repo cannot report the live database baseline — confirm it against Supabase before scheduling migration work.
