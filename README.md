# 🌸 MenoMate Core (`menomate-core`)

The central API and intelligence service for the **MenoMate Autonomous Menstrual Wellness System**. Built with **FastAPI**, **SQLAlchemy 2.x async (`asyncpg`)**, and **Supabase (PostgreSQL)**, adhering strictly to the [Antigravity Backend Implementation Brief](file:///c:/Everything/MenoMate_core/MenoMate_Backend_Antigravity_Implementation_Brief.md).

---

## 🏢 Ecosystem Architecture

```text
========================================================================
                         🏢 MENOMATE ARCHITECTURE
========================================================================
                               │
         ┌─────────────────────┼─────────────────────┐
         ▼                     ▼                     ▼
┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│  menomate-web   │   │  menomate-app   │   │  menomate-core  │
│ (Desktop/Admin) │   │ (Flutter/Mobile)│   │  (FastAPI Brain)│
└────────┬────────┘   └────────┬────────┘   └────────┬────────┘
         │                     │                     │
         ├─ React 18+          ├─ Flutter 3.x        ├─ Python 3.11+
         ├─ TypeScript         ├─ Dart               ├─ FastAPI
         └─ Vite               ├─ BLE (ESP32)        ├─ SQLAlchemy 2.0 async
                               └─ Supabase Auth      └─ PostgreSQL (Supabase)
```

The ESP32 wearable is standalone and communicates directly with the Flutter app over BLE. FastAPI provides safe, deterministic policy-checked recommendations, while the ESP32 remains the final hardware safety authority.

---

## 🚀 Core Features

1. **Supabase JWT Authentication & Scoping**:
   - Claims verification (`aud="authenticated"`, signature, expiration, and UUID `sub`).
   - Every database query strictly scoped to the authenticated user UUID.
   - Profile management and account/data deletion (`DELETE /api/v1/profile`).

2. **Cycle & Period Tracking Engine**:
   - **Correct Period Semantics**: A cycle record represents a menstrual bleeding occurrence (`period_start`, nullable `period_end`).
   - **Start-to-Start Math**: Cycle length is calculated from the start of one period to the start of the next period (`current_period_start - previous_period_start`).
   - **Transparent Weighted Prediction**: Weighted Moving Average (WMA) giving higher weight to recent cycles, with fallback to user's usual cycle length, or an `insufficient_data` indicator.
   - **Phase Estimation**: 4-phase approximation (menstrual, follicular, ovulation, luteal) dynamically estimated without database clutter.

3. **Atomic Onboarding**:
   - `POST /api/v1/onboarding/complete`: Atomically initializes the user profile and initial period record.
   - Supports `"I'm not sure"` by safely accepting `null` for usual cycle and period days.
   - Fully idempotent to prevent duplicate starting period records.

4. **Relational Daily Wellness & Symptom Logging**:
   - Captures `pain` ($0\text{--}10$), `mood`, `discharge`, `flow`, `notes`, and relational child `symptom_logs` (`symptom_type` + `severity` $0\text{--}10$).
   - Static semantic symptom metadata served via `GET /api/v1/symptoms`.

5. **Home & History Summaries**:
   - `GET /api/v1/summary/current`: Real-time dashboard with cycle day, estimated phase, days until next period, prediction confidence, active bleeding status, and today's logged symptoms.
   - `GET /api/v1/summary/history`: Historical period occurrences, cycle lengths, variability standard deviation, and symptom frequency ranking.

6. **Deterministic Therapy Policy & Hardware Safety**:
   - Hard policy ceiling strictly capped at $44.0^\circ\text{C}$ (under the $45.0^\circ\text{C}$ hardware safety limit).
   - Adaptive feedback loop tuning user's `sensitivity_index` ($0.80\text{--}1.20$).

7. **MenoMate Care Guided Assistance**:
   - Deterministic resolution for cycle, phase, period date, and device inquiries without LLM latency.
   - Pluggable `AIProvider` interface with compact, question-specific context for personalized guidance.
   - Non-diagnostic guardrails and mandatory medical disclaimer.

---

## 📡 Complete API Endpoints

| Category | Method | Endpoint | Description |
|---|---|---|---|
| **Auth** | `GET` | `/api/v1/auth/me` | Authenticated user profile and identity |
| **Profile** | `GET` | `/api/v1/profile` | Get user profile preferences |
| | `PATCH` | `/api/v1/profile` | Update profile preferences / usual cycle lengths |
| | `DELETE` | `/api/v1/profile` | Delete profile and all user data (GDPR compliant) |
| **Onboarding** | `POST` | `/api/v1/onboarding/complete` | Atomic profile + first period setup (idempotent) |
| **Cycles** | `GET` | `/api/v1/cycles/current` | Active cycle day, bleeding status, next period prediction |
| | `GET` | `/api/v1/cycles` | List all logged menstrual bleeding occurrences |
| | `POST` | `/api/v1/cycles` | Log a new period occurrence |
| | `PATCH` | `/api/v1/cycles/{cycle_id}` | Update or close an ongoing period |
| **Daily Logs** | `GET` | `/api/v1/symptoms` | Supported semantic symptom metadata catalogue |
| | `GET` | `/api/v1/logs/{date}` | Daily log and child symptoms for specific date |
| | `GET` | `/api/v1/logs` | Query logs within optional date range |
| | `POST` | `/api/v1/logs` | Create or update daily log with child symptoms |
| | `PATCH` | `/api/v1/logs/{log_id}` | Partially update daily log entry |
| **Summary** | `GET` | `/api/v1/summary/current` | Home screen summary metrics |
| | `GET` | `/api/v1/summary/history` | Historical cycle analytics & symptom distributions |
| **Devices** | `GET` | `/api/v1/devices` | List paired wearable devices |
| | `POST` | `/api/v1/devices` | Register / pair wearable device |
| | `DELETE` | `/api/v1/devices/{device_id}` | Unpair device |
| **Therapy** | `POST` | `/api/v1/therapy/recommend` | Deterministic thermal/vibration recommendation |
| | `POST` | `/api/v1/therapy/sessions` | Save a completed wearable therapy session |
| | `PATCH` | `/api/v1/therapy/sessions/{id}` | Update post-session relief and adjust sensitivity |
| **Care** | `POST` | `/api/v1/care/interactions` | Guided Care interaction (deterministic / compact AI) |

---

## 🛠️ Installation & Verification

### 1. Setup Virtual Environment
```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt  # Windows
# or source .venv/bin/activate && pip install -r requirements.txt
```

### 2. Run Test Suite
```bash
.venv/Scripts/pytest -v
```

### 3. Start Development Server
```bash
.venv/Scripts/uvicorn app.main:app --reload --port 8000
```
- Interactive Swagger UI: `http://localhost:8000/docs`
- Redoc Documentation: `http://localhost:8000/redoc`
- Health Check: `http://localhost:8000/health`

---

## 💾 Supabase Database Migration

To apply the schema changes to your Supabase PostgreSQL database safely without data loss, execute the provided SQL script in the **Supabase SQL Editor**:
- [supabase_migration.sql](file:///c:/Everything/MenoMate_core/supabase_migration.sql)

---

## 📜 Attribution & Open Source

Attributions and architectural inspirations are documented in [THIRD_PARTY_NOTICES.md](file:///c:/Everything/MenoMate_core/THIRD_PARTY_NOTICES.md).
