# MenoMate Core Backend

The central API and domain engine for **MenoMate** — an intelligent, privacy-first women's health and wellness platform. Built with **FastAPI**, **SQLAlchemy**, and **Supabase (PostgreSQL + Auth)**, this service manages cycle predictions, daily health logs, health history, deterministic therapy policy, and AI-assisted care workflows.

---

## 1. System Overview

MenoMate Core acts as the single authoritative backend and database access layer for the MenoMate platform. The mobile client ([menomate-mobile](../menomate-mobile/)) communicates exclusively with this service over authenticated HTTPS endpoints.

### Key Capabilities
- **Authoritative Cycle Prediction**: Robust Weighted Moving Average (`robust_wma_v1`) with MAD outlier trimming, variability tracking, and strict observational training.
- **Offline-First Synchronization Target**: Idempotent REST endpoints with natural keys `(user_id, log_date)` supporting seamless multi-device and offline sync.
- **Safety-First Therapy Policy**: Deterministic calculation engine for wearable thermal/vibration therapy capped at a strict **44.0 °C software ceiling**.
- **Contextual Care & Triage**: Intelligent assistant orchestration integrating symptom context, red-flag emergency triage, and Groq LLM inference with deterministic fallback.
- **Reproductive Health Modeling**: Dedicated modules for fertility observations/estimates, pregnancy tracking mode with clinical dating precedence, and reproductive-aging context.
- **Strict Timezone Semantics**: User-local calendar dates (`DATE`) cleanly separated from UTC timestamps (`TIMESTAMPTZ`).

---

## 2. Architecture & Boundaries

```text
       Flutter Mobile Client (menomate-mobile)
                         |
           HTTPS + Supabase JWT Bearer
                         v
       FastAPI Application (MenoMate Core)
   ┌─────────────────────┬────────────────────────┐
   │ Authentication      │ Cycle & Health Engine  │
   │ (ES256 JWKS Verify) │ (Predictions & Ledger) │
   ├─────────────────────┼────────────────────────┤
   │ Care Orchestration  │ Therapy Safety Policy  │
   │ (Triage + Groq LLM) │ (Deterministic Bounds) │
   └─────────────────────┴────────────────────────┘
                         |
               Async PostgreSQL Engine
                         v
             Supabase PostgreSQL Store
```

### Architectural Boundaries
1. **AI is Not a Hardware Controller**: LLM output is strictly advisory text. Hardware commands and therapy recommendations are generated exclusively by deterministic mathematical equations.
2. **Single Predictive Authority**: The backend owns cycle prediction and phase calculation. The mobile app never performs independent cycle math; it displays and caches server values.
3. **Database Isolation**: The mobile client never connects to PostgreSQL directly. All database access passes through FastAPI, where every query is strictly filtered by the authenticated user's `UUID`.

---

## 3. Core Engine Specifications

### A. Cycle Prediction Engine (`robust_wma_v1`)
- **Algorithm**: Recency-weighted moving average over completed, observed cycles (`period_start <= user-local today`).
- **Outlier Mitigation**: Median Absolute Deviation (MAD) filtering trims anomalous cycles before weighting.
- **Bounds**: Predictions are constrained between 20 and 45 days.
- **Zero-History Behavior**: Falls back to user-declared `usual_cycle_days` with low confidence. If unprovided, cleanly reports `insufficient_data` instead of inventing arbitrary 28-day assumptions.
- **Prediction Ledger**: Each served prediction snapshot is recorded in `prediction_ledger` and evaluated against future observed period starts for historical variance and error calculation.

### B. Therapy Policy & Physical Safety
- **Software Thermal Cap**: Recommendations strictly enforce `MAX_POLICY_TEMP_CELSIUS = 44.0 °C`.
- **Deterministic Scaling**: Calculates target temperature, vibration mode, and session duration based on pain intensity, symptom severity, and user thermal sensitivity (0.80× to 1.20×).
- **Physical Enforcement**: Final safety remains enforced by wearable hardware cutoffs (independent 45.0 °C thermal fuse and firmware timeout).

### C. Contextual Care & Triage Engine
- **Safety Triage**: Every prompt is screened against red-flag clinical symptom patterns (severe pain, fever, hemorrhaging).
- **Semantic Actions**: Recommends structured client actions (`open_logger`, `view_therapy`, `seek_emergency_care`) rather than conversational instructions.
- **LLM Integration**: Powered by Groq (`openai/gpt-oss-120b`). If the external provider is unavailable or unconfigured, the system gracefully falls back to deterministic safe responses.

### D. Timezone & Calendar Discipline
- **Calendar Dates (`DATE`)**: `period_start`, `period_end`, `log_date`, `observation_date`, `estimated_due_date` store the user's wall-clock calendar date without UTC shifting.
- **Instants (`TIMESTAMPTZ`)**: `created_at`, `updated_at`, session start/end are strictly stored in UTC.
- **User-Local "Today"**: The server evaluates "today" using the user's stored IANA timezone (e.g., `Asia/Kolkata`, `America/New_York`).

---

## 4. API Surface

The API exposes **29 resource paths** and **47 operations** under the `/api/v1` prefix. Interactive OpenAPI documentation is accessible at `/docs` (Swagger UI) and `/redoc`.

| Domain | Base Path | Core Responsibilities |
| :--- | :--- | :--- |
| **Auth** | `/api/v1/auth` | User identity validation and token inspection (`/me`) |
| **Profile** | `/api/v1/profile` | Preferences, units, theme, IANA timezone, birth year/month |
| **Onboarding** | `/api/v1/onboarding` | Atomic registration of initial profile and cycle baseline |
| **Cycles** | `/api/v1/cycles` | Period start/end dates, retrospective closures, current cycle state |
| **Daily Logs** | `/api/v1/logs` | Daily wellness, flow, mood, symptoms, and pain scoring |
| **Summary** | `/api/v1/summary` | Aggregated cycle metrics, length variability, symptom trends |
| **Health Context** | `/api/v1/health-context` | Clinical background, medical conditions, current medications |
| **Reproductive** | `/api/v1/reproductive` | Fertility observations, pregnancy mode dating, aging notes |
| **Devices** | `/api/v1/devices` | ESP32 wearable BLE registration and pairing state |
| **Therapy** | `/api/v1/therapy` | Deterministic therapy recommendations and session telemetry |
| **Care** | `/api/v1/care` | Triage and AI assistance (`/interactions`) |
| **System** | `/`, `/health` | Unauthenticated service health and readiness probes |

---

## 5. Database & Data Architecture

- **Engine**: PostgreSQL via async SQLAlchemy and `asyncpg`.
- **Migrations**: Incremental SQL migrations located in `migrations/` applied in numeric order.
- **Schema Reference**: Canonical fresh installation schema defined in `supabase_initial_schema.sql`.

### Core Tables
1. `profiles`: User preferences, stored IANA timezone, birth year/month.
2. `cycles`: Start and end dates with `UNIQUE(user_id, period_start)` constraints.
3. `daily_logs` & `symptom_logs`: Daily tracking indexed by `(user_id, log_date)`.
4. `prediction_ledger`: Historical tracking of predicted vs. observed cycle parameters.
5. `health_contexts`, `health_conditions`, `medications`: User-declared health background.
6. `fertility_observations`: Quantitative logs (LH tests, BBT temperatures, cervical mucus).
7. `pregnancy_contexts`: Singleton pregnancy tracking mode with provenance-based dating.
8. `reproductive_aging_contexts`: User-recorded perimenopause/menopause notes.
9. `devices` & `therapy_sessions`: BLE hardware records and telemetry logs.

---

## 6. Local Development

### Prerequisites
- Python 3.11+ (developed and verified on Python 3.12)
- A Supabase project (or local PostgreSQL instance)
- PowerShell, Bash, or terminal of choice

### Setup Instructions
```bash
# 1. Clone the repository
git clone https://github.com/MenoMate/MenoMate_core.git
cd MenoMate_core

# 2. Create and activate virtual environment
python -m venv .venv
# Windows:
.\.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your Supabase credentials
```

### Running the Server
```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
Once running, navigate to:
- Interactive API Docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- Health Check: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

---

## 7. Testing & Quality Assurance

MenoMate Core maintains comprehensive test coverage using `pytest` and an isolated in-memory SQLite test database.

```bash
# Run the complete test suite
pytest -v

# Run focused domain tests
pytest tests/test_auth.py tests/test_cycle_calculator.py tests/test_therapy_and_devices.py
```

The test suite validates:
- JWT security matrix (ES256, RS256, HS256, audience, issuer, expiration, algorithm spoofing).
- Cycle prediction accuracy, MAD outlier resistance, and boundary clamps.
- Deterministic therapy equations and safety temperature ceilings.
- Multi-turn Care triage, red-flag escalation, and mock provider fallbacks.
- Idempotent onboarding and atomic period transaction rollbacks.

---

## 8. Production Deployment

MenoMate Core is production-ready for deployment on platforms such as **Render**, **Railway**, or containerized **Docker** hosts.

- **Start Command**:
  ```bash
  uvicorn app.main:app --host 0.0.0.0 --port $PORT
  ```
- **Health Check Path**: `/health`

### Environment Variables

| Variable | Required | Description |
| :--- | :---: | :--- |
| `DATABASE_URL` | **Yes** | PostgreSQL connection URI (`postgresql+asyncpg://...`) |
| `SUPABASE_URL` | **Yes** | Supabase project URL (used for ES256 JWKS discovery and issuer checks) |
| `SUPABASE_JWT_SECRET` | *Optional* | Secret string required only when legacy symmetric `HS256` signing is used |
| `SUPABASE_JWKS_URL` | *Optional* | Custom override for the JWKS endpoint (defaults to `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`) |
| `ALLOWED_ORIGINS` | *Optional* | CORS allowed origins (default `*` in development, set to specific domains in production) |
| `AUTO_CREATE_TABLES` | *Optional* | Set to `false` in production (migrations handle schema updates) |
| `GROQ_API_KEY` | *Optional* | API key for Groq AI assistant (uses deterministic fallback when unset) |
| `GROQ_MODEL` | *Optional* | Model identifier (defaults to `openai/gpt-oss-120b`) |

---

## 9. License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details. Third-party algorithm acknowledgments are detailed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
