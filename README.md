# 🌸 MenoMate Core (`menomate-core`)

The central API and intelligence service for the **MenoMate Autonomous Menstrual Wellness System**. Built with **FastAPI**, **SQLAlchemy 2.0 (asyncpg)**, and **Supabase (PostgreSQL)**.

---

## 🏢 Organization Architecture

Below is the high-level architecture of the **MenoMate** ecosystem:

```text
========================================================================
                         🏢 MENOMATE ORGANIZATION
========================================================================
                               │
         ┌─────────────────────┼─────────────────────┐
         ▼                     ▼                     ▼
┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│  menomate-web   │   │ menomate-mobile │   │  menomate-core  │
│ (Desktop/Admin) │   │  (User & BLE)   │   │  (The Brain)    │
└────────┬────────┘   └────────┬────────┘   └────────┬────────┘
         │                     │                     │
         ├─ React 18+          ├─ React Native       ├─ Python 3.11+
         ├─ TypeScript         ├─ TypeScript         ├─ FastAPI
         ├─ Tailwind v4        ├─ Expo / BLE         ├─ PostgreSQL / Supabase
         └─ Vite               └─ Native Modules     └─ Recommendation Engine
```

---

## 🚀 Key Features

1. **Supabase JWT Authentication**:
   - Seamless token verification using `SUPABASE_JWT_SECRET` (HS256).
   - Injected `get_current_user` dependency providing the user's Supabase UUID context across all endpoints.

2. **Cycle Prediction Engine**:
   - Estimates next period date (`start_date + cycle_length_avg`).
   - Estimates ovulation window (`predicted_next_period - 14 days`).
   - Automatically maintains a rolling 3-cycle average whenever completed cycles are logged.

3. **Daily Symptom & Pain Logging**:
   - Daily cramp severity ($0\text{--}10$), flow intensity, mood, notes, and structured symptoms JSON.
   - Upsert support per day and 30-day history retrieval.

4. **Deterministic & Adaptive Hardware Calibrator**:
   - Computes real-time thermal ($^\circ\text{C}$) and vibration (mode + intensity percentage) parameters for wearable hardware.
   - **Strict Safety Constraint**: Hard temperature ceiling strictly limited to $44.0^\circ\text{C}$ (well below the $45.0^\circ\text{C}$ skin threshold).
   - **Adaptive Feedback Loop**: Post-session feedback (`insufficient_relief` / `too_hot`) automatically tunes the user's `sensitivity_index` ($0.80\text{--}1.20$).

---

## ⚙️ Environment Configuration

Copy the example environment file:
```bash
cp .env.example .env
```

Configure your variables in `.env`:
```env
PROJECT_NAME="MenoMate Core Backend"
DATABASE_URL="postgresql+asyncpg://postgres:[YOUR-PASSWORD]@[YOUR-DB-HOST]:5432/postgres"
SUPABASE_JWT_SECRET="your-supabase-jwt-secret"
SUPABASE_URL="https://your-project-ref.supabase.co"
ALLOWED_ORIGINS="*"
```

---

## 🛠️ Installation & Running

### 1. Set Up Virtual Environment & Dependencies
```bash
# Using .venv
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt  # Windows
# or source .venv/bin/activate && pip install -r requirements.txt  # Linux/macOS
```

### 2. Start the Development Server
```bash
.venv/Scripts/uvicorn app.main:app --reload --port 8000
```
- Interactive API Documentation (Swagger UI): `http://localhost:8000/docs`
- Redoc Documentation: `http://localhost:8000/redoc`
- Health Check: `http://localhost:8000/health`

### 3. Run Automated Tests
```bash
.venv/Scripts/pytest -v
```

---

## 📡 API Endpoints Overview

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/auth/sync-profile` | Upsert / initialize profile row for Supabase user |
| `GET` | `/api/v1/cycles/current` | Active cycle status, phase indicators & days until next period |
| `POST` | `/api/v1/cycles/start` | Starts a new menstrual cycle |
| `PUT` | `/api/v1/cycles/{id}/end` | Closes cycle and updates rolling 3-cycle average |
| `POST` | `/api/v1/logs/daily` | Upserts daily symptom, mood & cramp severity entry |
| `GET` | `/api/v1/logs/history` | Fetches past $N$ days of symptom history (default 30) |
| `POST` | `/api/v1/therapy/recommend` | Generates hardware thermal/vibration calibration |
| `POST` | `/api/v1/therapy/session` | Logs a completed wearable therapy session |
| `PATCH` | `/api/v1/therapy/session/{id}/feedback` | Updates session feedback and updates user `sensitivity_index` |

---

## 🌡️ Hardware Calibration Logic

| Cramp Severity | Target Temp ($^\circ\text{C}$) | Vibration Mode | Vibration Intensity | Duration |
|---|---|---|---|---|
| **0** (None) | $0.0^\circ\text{C}$ (OFF) | `off` | $0\%$ | $0$ min |
| **1 – 4** (Mild) | $37.0 \times \text{sens}$ (clamped $35\text{--}38^\circ\text{C}$) | `pulse` | $40\%$ | $20$ min |
| **5 – 7** (Moderate) | $39.5 \times \text{sens}$ (clamped $38\text{--}41^\circ\text{C}$) | `wave` | $70\%$ | $25$ min |
| **8 – 10** (Severe) | $42.0 \times \text{sens}$ (clamped $40\text{--}44^\circ\text{C}$) | `wave` | $90\%$ | $30$ min |

### Feedback Loop
- **`insufficient_relief`**: Sensitivity Index $+0.05$ (max $1.20$)
- **`too_hot`**: Sensitivity Index $-0.08$ (min $0.80$)
- **`just_right`**: Unchanged
