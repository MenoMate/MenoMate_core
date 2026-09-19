# MenoMate Backend Development Guide

For a new team member joining the production backend on `main`. Companion docs: `../README.md` (overview), `api-contract.md` (endpoints), `database-and-migrations.md` (schema), `deployment.md` (Render).

## 1. Prerequisites

- Python 3.11+ (developed on 3.12; `tzdata` in `requirements.txt` covers Windows zoneinfo).
- A Supabase project (URL + keys) for any work touching a real database. Tests need none (in-memory sqlite).
- Git, PowerShell (Windows) or a POSIX shell, and optionally `adb` for mobile-on-USB testing.

## 2. Clone / setup

```bash
git clone <MenoMate_core URL>
cd MenoMate_core
python -m venv .venv
.venv\Scripts\activate          # (source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env          # (cp .env.example .env) then fill Supabase values
```

Never commit the filled `.env` (it is gitignored). `.env.example` holds variable NAMES with placeholders only.

## 3. Python environment

- Always work inside `.venv`. Dependencies are pinned loosely in `requirements.txt` (`fastapi`, `uvicorn[standard]`, `sqlalchemy`, `asyncpg`, `pydantic`, `pydantic-settings`, `pyjwt[crypto]`, `python-dotenv`, `tzdata`, `aiosqlite`, `pytest`, `pytest-asyncio`, `httpx`, `groq`).
- Do not change `requirements.txt` in a docs task; dependency changes need review + test runs.

## 4. `.env` setup

Copy `.env.example` → `.env` and set at minimum:

- `DATABASE_URL` (`postgresql+asyncpg://…` for local Postgres work; tests override with sqlite automatically).
- `SUPABASE_URL` (`https://your-project-ref.supabase.co`; feeds JWKS discovery + issuer check).
- `SUPABASE_JWT_SECRET` only for legacy HS256; omit with asymmetric signing.
- `GROQ_API_KEY` only to exercise the real Care LLM; unset → deterministic mock provider.

Keep `AUTO_CREATE_TABLES=false` for any Postgres-backed run; use the SQL files for schema (see §9).

## 5. Local server

```bash
.venv\Scripts\activate
uvicorn app.main:app --reload --port 8000
# (Production instead runs: uvicorn app.main:app --host 0.0.0.0 --port $PORT)
```

## 6. Swagger

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- Raw contract: `http://localhost:8000/openapi.json`

Swagger is the exact machine-readable contract; `docs/api-contract.md` is the readable companion. Do not duplicate full schemas into docs by hand.

## 7. Health endpoint

```bash
curl http://localhost:8000/health
# {"status": "healthy", "service": "...", "version": "1.0.0"}
```

No auth. Render uses this as `healthCheckPath`. `/` returns `docs`/`health` pointers.

## 8. Test command

```bash
pytest -q
# Locked-down Windows checkout with read-only .pytest_cache:
pytest -q -p no:cacheprovider
```

Current validation: **373 collected, 373 passed, 0 failed, 0 skipped/errors** (`pytest.ini`: `testpaths = tests`, `asyncio_mode = auto`). Tests use in-memory sqlite + frozen clocks; they never touch Supabase. Run the suite before every review; do not modify tests to hit a target count.

Useful slices: `pytest tests/test_cycles.py -q`, `pytest tests/test_care_topics.py -q`, `pytest --collect-only -q`.

## 9. Useful development workflow

1. Activate `.venv`, pull latest `main`, create a feature branch (never develop on `main`).
2. Make the smallest change that satisfies the contract; keep `supabase_initial_schema.sql` + `migrations/` + models + tests agreeing.
3. Run the focused tests, then the full `pytest -q`.
4. Verify `/health` + `/docs` locally; exercise new routes with a Supabase JWT (401/404/422/409 semantics per `api-contract.md`).
5. `git diff --stat` + `git diff --name-only` to confirm scope; open a review; merge only after green tests.

`scratch/` holds throwaway manual probes — never import it from `app/` or `tests/`.

## 10. Branch workflow

**DO NOT work directly on `main` for normal feature development.**

Recommended: `feature branch → implementation → tests → review → merge`. `main` stays deployable; production deploys are manual from `main` (see `deployment.md`). Documentation-only work follows the same path (e.g. `docs/...` branches).

## 11. Coding / security rules

- Every new query filters by the authenticated user (`get_current_user` → JWT `sub`); no client-supplied `user_id` for ownership; cross-user id → 404.
- DATE stays DATE (user calendar dates, never through UTC); instants stay `TIMESTAMPTZ`; resolve "today" via `user_today` / `user_today_for` (stored IANA zone), never `date.today()` on the server in production paths.
- No LLM output reaches hardware paths; therapy stays deterministic equations with the 44.0 °C ceiling; only `GENTLE`/`MODERATE`/`STRONG` profile names (or null) cross the Care boundary.
- No second predictor: mobile displays server values; `calculate_cycle_lengths(today=…)` always takes an explicit user-local date.
- Health/fertility/pregnancy/aging values are stored verbatim and returned to the owner only; never diagnose, never infer, never let context silently move predictions (except the specified pregnancy `SUPPRESSED` estimate state).
- Never log intimate-health values at INFO, include them in error details, or emit them in analytics.

## 12. What must never be committed

- Real secrets or filled `.env` files (`SUPABASE_JWT_SECRET`, `DATABASE_URL` credentials, `GROQ_API_KEY`), tokens, or production URLs.
- Production database contents, dumps, or PostgREST keys.
- Unreviewed migrations applied to production; `render.yaml` / `requirements.txt` drive-by edits in unrelated changes.
- Hardware-safety validation claims without evidence in the repo.

## 13. How to add a new endpoint safely

1. Define Pydantic schemas in `app/schemas/` (strict enums, length/range guards; coarse server-relative future guards only — routes enforce exact user-local bounds).
2. Add the route in `app/api/v1/<domain>.py` with `Depends(get_current_user)` + `Depends(get_db)`; filter every query by `current_user_id`; return 404 on miss, 422/400/409 per contract.
3. Wire the router in `app/api/router.py` if it is a new file.
4. Add frozen-clock + isolation tests (401 unauthenticated, cross-user 404, `user_id`-ignored, validation codes).
5. Update Swagger implicitly (via FastAPI) + `docs/api-contract.md` by hand.

## 14. How to add a new database field safely

1. Update the SQLAlchemy model (`app/models/`), the Pydantic schemas, and the route/service validation together.
2. Update `supabase_initial_schema.sql` (fresh-DB canonical) in the same change.
3. Add a new numbered migration in `migrations/` (never edit an applied migration; never reuse numbers).
4. Cover the field with tests (validation, persistence, isolation, cascade where applicable).

## 15. How to add a migration

1. Pick the next `NNNN_` number after the current max (`0009` today); use a descriptive suffix.
2. Make it additive + idempotent (`IF NOT EXISTS`), no backfill, no data rewrite, no existing-column semantic change unless explicitly reviewed.
3. Create new tables with indexes + default-deny RLS (`ENABLE ROW LEVEL SECURITY`, no policies) in the same file; document why in the header comment.
4. Keep `supabase_initial_schema.sql` agreeing; rehearse on a staging clone (backup first); record rollback as `DROP TABLE IF EXISTS …` in reverse order.
5. Never apply a migration to production from this repo — that is a manual human step in the Supabase SQL editor (see `deployment.md`).

## 16. How to add tests

- Put tests in `tests/test_<domain>.py` on the existing sqlite + `async_client` harness (`tests/conftest.py`); use frozen clocks for any date logic, never the machine timezone.
- Cover: happy path, validation codes (422/400/409), auth (401), isolation (404 + `user_id`-ignored), cascade on profile delete where applicable, and prediction-independence where relevant.
- Keep the suite deterministic and offline; run `pytest -q` (full) before review.
