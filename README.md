# MenoMate Core

MenoMate Core is the central API and intelligence service for the MenoMate autonomous menstrual wellness system. Built with FastAPI, SQLAlchemy 2.0 asynchronous ORM, and Supabase PostgreSQL, the backend provides cycle analytics, daily symptom and mood tracking, wearable therapy session management, and a deterministic safety-constrained recommendation engine for dynamic thermal and vibration relief.

## Overview

MenoMate is an integrated menstrual wellness platform designed to address dysmenorrhea through real-time symptom tracking and personalized, non-invasive physical therapy. The ecosystem consists of:

- Flutter mobile application (`menomate-mobile`): Cross-platform client interfacing with end users and communicating locally with wearable hardware via Bluetooth Low Energy (BLE).
- FastAPI backend (`menomate-core`): Central service responsible for authenticated business logic, cycle projection, daily logging, data aggregation, and safety-bound therapy policy calculation.
- Supabase PostgreSQL: Managed relational database storing user profiles, cycle occurrences, daily symptom logs, device associations, therapy sessions, and conversation threads.
- Supabase Auth: Secure user authentication issuing JSON Web Tokens (JWT) verified on every protected API endpoint.
- Standalone ESP32 wearable: Hardware band with integrated heating elements, vibration actuators, and onboard thermal regulation.
- BLE communication: Direct wireless link between the mobile handset and the wearable, keeping hardware control local and responsive.

## System Architecture

```text
Flutter Mobile App (menomate-mobile)
       |
       | HTTPS (Bearer JWT)
       v
FastAPI Backend (menomate-core)
       |
       +---- Supabase Auth (JWT signature, expiration, audience verification)
       |
       +---- Supabase PostgreSQL (User-scoped persistence)
       |
       +---- AI / Care Layer (Contextual assistance, non-diagnostic guidance)
       |
       +---- Deterministic Therapy Policy (Strict 44.0 C ceiling)
       |
       v
Flutter Mobile Handset
       |
       | Bluetooth Low Energy (BLE)
       v
ESP32 Wearable Controller
       |
       +---- Temperature Sensor (Continuous monitoring)
       +---- Heating Pad (PID-regulated thermal delivery)
       +---- Vibration Motors (Pulse and wave stimulation)
       +---- Independent Hardware Thermal Cutoff (45.0 C fail-safe)
```

### Safety Boundary

The architecture enforces a strict separation between artificial intelligence and hardware actuation:
- The AI layer is completely decoupled from hardware control. It has no access to GPIOs, PWM duty cycles, or heating element switches.
- Therapy recommendations are computed exclusively by a deterministic policy engine that caps target temperatures at 44.0 degrees Celsius.
- The ESP32 wearable runs an independent hardware-level safety loop that shuts down heating if temperature exceeds 45.0 degrees Celsius or if BLE heartbeat fails.

## Core Features

- Supabase JWT Authentication: Validates token signature, expiration, audience (`authenticated`), and extracts UUID `sub`. Every protected query is explicitly scoped to the authenticated user ID.
- Atomic Onboarding: Initializes user profile settings and optional baseline period record in a single transaction with idempotency safeguards.
- Menstrual Cycle Tracking: Records period occurrences (`period_start`, `period_end`). Calculates cycle lengths using start-to-start biological math (`current_period_start - previous_period_start`).
- Transparent Cycle Prediction: Weighted Moving Average (WMA) giving higher weight to recent completed cycles. Falls back to user-provided baseline or returns an explicit `insufficient_data` status with null dates rather than arbitrary estimates.
- Phase Estimation: Four-phase menstrual cycle approximation (menstrual, follicular, ovulation, luteal) presented clearly as an educational estimate.
- Relational Daily Wellness Logging: Records daily pain ratings (0 to 10), flow, mood, discharge, notes, and child symptom items validated against a controlled clinical taxonomy.
- Partial Updates: PATCH endpoints respect explicit null values to allow clearing optional fields such as notes or mood.
- Home and History Analytics: Summaries providing cycle phase, days remaining, prediction confidence, variability standard deviation, and symptom frequency rankings.
- Device Association: Links wearable hardware identifiers to user accounts with strict ownership checks.
- Adaptive Therapy Policy: Maps reported pain levels to target temperatures and vibration modes, with an adaptive sensitivity index tuned by post-session user feedback.
- Contextual Care Assistant: Intent-tailored context builder and non-diagnostic guidance using cautious phrasing and mandatory medical disclaimers.

## AI Design

The AI assistant provides educational wellness insights and empathetic conversational guidance. It adheres to strict design principles:

- Non-Diagnostic Language: Uses cautious phrasing ("may", "can", "some people experience") and never offers clinical diagnoses or prescriptive medical advice.
- Intent-Specific Context: Inquiries dynamically assemble only the minimal necessary context (cycle status for cycle questions, therapy history for pain relief, recent logs for symptom queries) rather than dumping full user history.
- Offline Capability: A mock provider is included out of the box, allowing full local testing without requiring external LLM API keys.
- Zero Direct Hardware Influence: AI cannot override therapy limits, command hardware actuators, or alter firmware settings.

## Database Schema

The database is structured in PostgreSQL with foreign keys cascading from `profiles.user_id`:

- `profiles`: User preferences, usual cycle baseline, display units, theme, and adaptive sensitivity index. Primary key references `auth.users(id)`.
- `cycles`: Menstrual period bleeding occurrences with `period_start` and nullable `period_end`.
- `daily_logs`: One daily wellness entry per user per calendar date containing pain score (0 to 10), mood, discharge, flow, and notes.
- `symptom_logs`: Child records attached to `daily_logs` identifying specific symptoms and severity scores (0 to 10).
- `devices`: BLE wearable hardware identifiers, paired firmware version, and connection timestamps.
- `therapy_sessions`: Log of completed therapy sessions recording mode, applied temperature, vibration parameters, pre/post pain scores, and relief feedback.
- `chat_conversations` and `chat_messages`: Multi-turn conversational care threads.

## API Endpoints

All endpoints except `/health` and OpenAPI documentation require a valid Supabase JWT Bearer token in the `Authorization` header.

### Authentication & Profile
- `GET /api/v1/auth/me`: Retrieve authenticated user identity and profile.
- `GET /api/v1/profile`: Retrieve user profile settings.
- `PATCH /api/v1/profile`: Update profile preferences, usual cycle days, or sensitivity index.
- `DELETE /api/v1/profile`: Delete user application records (cascades across all user tables). Note: Auth user deletion requires Supabase Admin API.

### Onboarding
- `POST /api/v1/onboarding/complete`: Atomically create profile and optional initial period record.

### Cycles
- `GET /api/v1/cycles/current`: Retrieve active cycle status, phase, bleeding flag, and next period prediction.
- `GET /api/v1/cycles`: List all logged menstrual bleeding occurrences for the user.
- `POST /api/v1/cycles`: Log a new period occurrence with overlap and future-date validation.
- `PATCH /api/v1/cycles/{cycle_id}`: Update or close an ongoing period occurrence.

### Daily Logs & Symptoms
- `GET /api/v1/symptoms`: Static catalogue of supported symptom types and metadata.
- `GET /api/v1/logs/{log_date}`: Retrieve daily log and child symptoms for a calendar date.
- `GET /api/v1/logs`: Query daily logs within an optional start and end date range.
- `POST /api/v1/logs`: Create or upsert a daily log entry with child symptoms.
- `PATCH /api/v1/logs/{log_id}`: Partially update a daily log entry (supports clearing fields with null).

### Analytics & Summary
- `GET /api/v1/summary/current`: High-level dashboard summary metrics for the active cycle.
- `GET /api/v1/summary/history`: Longitudinal cycle history, variability, and symptom distributions.

### Wearable Devices
- `GET /api/v1/devices`: List all wearable devices associated with the authenticated user.
- `POST /api/v1/devices`: Register a new wearable hardware identifier.
- `DELETE /api/v1/devices/{device_id}`: Unpair and delete a wearable device.

### Therapy Controls
- `POST /api/v1/therapy/recommend`: Compute deterministic thermal and vibration recommendations.
- `GET /api/v1/therapy/sessions`: List past wearable therapy sessions for the user.
- `POST /api/v1/therapy/sessions`: Record a completed therapy session.
- `PATCH /api/v1/therapy/sessions/{session_id}`: Update post-session relief score and tune adaptive sensitivity.

### Care Assistant
- `POST /api/v1/care/interactions`: Process care inquiries through deterministic rules or AI guidance.

## Local Development

### Prerequisites

- Python 3.11 or 3.12
- PostgreSQL (or local SQLite for automated tests)
- Git

### Setup Steps

1. Clone the repository and navigate to the project root:
   ```bash
   git clone https://github.com/your-org/menomate-core.git
   cd menomate-core
   ```

2. Create and activate a Python virtual environment:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate  # Windows PowerShell / CMD
   # or source .venv/bin/activate on macOS / Linux
   ```

3. Install project dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Configure environment variables:
   ```bash
   copy .env.example .env  # Windows
   # or cp .env.example .env on macOS / Linux
   ```
   Update `.env` with your Supabase project credentials.

5. Database setup:
   - For fresh Supabase setups: Run `supabase_initial_schema.sql` in the Supabase SQL Editor.
   - For existing databases migrating from previous schema versions: Run `supabase_migration.sql` in the Supabase SQL Editor.

6. Run the automated test suite:
   ```bash
   pytest -v
   ```

7. Start the FastAPI development server:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

8. Access interactive documentation:
   - Swagger UI: `http://localhost:8000/docs`
   - ReDoc: `http://localhost:8000/redoc`
   - Health check: `http://localhost:8000/health`

## Environment Variables

| Variable | Required | Description | Scope |
|---|---|---|---|
| `DATABASE_URL` | Yes | PostgreSQL connection string (`postgresql+asyncpg://...`) | Server-side only |
| `SUPABASE_JWT_SECRET` | Yes | Supabase JWT secret used to verify HS256 signatures | Server-side only |
| `SUPABASE_URL` | Optional | Base URL of the Supabase project | Server-side only |
| `SUPABASE_KEY` | Optional | Supabase anon key | Server-side only |
| `ENVIRONMENT` | No | Runtime environment (`development`, `staging`, `production`) | Server-side only |
| `AUTO_CREATE_TABLES` | No | Automatically run DDL on startup (default `false`) | Server-side only |

Never expose `DATABASE_URL` or `SUPABASE_JWT_SECRET` to client applications.

## Project Structure

```text
menomate-core/
├── app/
│   ├── api/
│   │   └── v1/
│   │       ├── auth.py              # Identity verification and session info
│   │       ├── care.py              # Guided care assistant interaction
│   │       ├── cycles.py            # Period logging and cycle status
│   │       ├── devices.py           # Wearable device management
│   │       ├── logs.py              # Daily wellness logs and symptoms
│   │       ├── onboarding.py        # First-time profile initialization
│   │       ├── profile.py           # User preferences and data deletion
│   │       ├── summary.py           # Active cycle and historical analytics
│   │       └── therapy.py           # Recommendation policy and sessions
│   ├── core/
│   │   ├── config.py                # Pydantic BaseSettings configuration
│   │   └── security.py              # Supabase JWT signature and claims check
│   ├── db/
│   │   ├── base.py                  # Declarative SQLAlchemy Base
│   │   └── session.py               # Async engine and session generator
│   ├── models/                      # SQLAlchemy ORM models
│   ├── schemas/                     # Pydantic request and response contracts
│   ├── services/                    # Cycle math, therapy policy, AI router
│   └── main.py                      # FastAPI application entry point
├── tests/                           # Pytest test suite
├── supabase_initial_schema.sql      # Canonical DDL for fresh databases
├── supabase_migration.sql           # Non-destructive migration script
├── THIRD_PARTY_NOTICES.md           # Open-source attributions and licenses
├── requirements.txt                 # Pinned dependencies
├── pytest.ini                       # Test runner configuration
└── README.md                        # Documentation
```

## Safety Architecture

Patient safety is fundamental to the MenoMate platform:

- Temperature Ceiling: The backend recommendation engine enforces a strict mathematical ceiling of 44.0 degrees Celsius. Under no circumstances will a recommendation exceed this threshold.
- Deterministic Policy: Thermal and vibration setpoints are produced through deterministic equations rather than opaque neural network outputs.
- Independent Wearable Protection: The standalone ESP32 firmware incorporates hardware thermistor monitoring with a hard thermal cutoff at 45.0 degrees Celsius, independent of application software.
- Activity Timeouts: Therapy sessions are time-bounded to prevent prolonged continuous exposure to heat.
- Data Ownership: All database queries enforce strict user scoping using validated JWT claims, preventing cross-user data leakage.

## Current Status

- Implemented:
  - Supabase JWT authentication with expiration and audience checks
  - Cycle tracking engine with start-to-start cycle length math
  - Weighted moving average prediction with fallback handling
  - Relational daily wellness logging with validated symptoms taxonomy
  - Deterministic therapy recommendation engine with 44.0 C safety ceiling
  - Wearable device association and therapy session tracking
  - Modular AI care assistant with intent-tailored context and cautious phrasing
  - Clean separation between fresh schema DDL and legacy migration scripts
  - Comprehensive automated test suite (32 tests covering auth, cycles, logs, therapy, care)

- In Progress:
  - Integration with the Flutter mobile client (`menomate-mobile`)
  - End-to-end BLE communication validation with ESP32 prototype

- Planned:
  - Long-term cycle regularity modeling
  - Additional sensor telemetry processing (e.g. skin temperature trends)
  - Production deployment pipeline

## Mobile Application

The user-facing mobile client is developed as a separate project:
- Repository: `menomate-mobile`
- Framework: Flutter 3.x (Dart)
- Responsibilities: User interface, local BLE communication with the ESP32 wearable, authenticated HTTPS requests to `menomate-core`.

## Hardware

The MenoMate physical device is a standalone wearable designed for abdominal or lumbar placement:
- Microcontroller: ESP32 with integrated Bluetooth Low Energy
- Thermal Module: Flexible heating element regulated via PWM
- Actuation: Precision vibration motors for wave-based mechanical relief
- Safety: Hardware thermistor with independent thermal interrupt at 45.0 degrees Celsius

## Future Work

- Deployment to managed cloud container infrastructure
- Advanced non-linear cycle variability modeling across multi-year intervals
- Direct BLE diagnostic tools within the mobile client
- Clinical evaluation of combined thermal and vibrational therapy protocols

## Demo

- Current status: Not deployed yet.
- Live Demo: Coming soon

Future updates to this section will link to the deployed backend documentation, mobile demonstration recordings, and hardware walkthroughs.

## License

This project is developed under the MIT License. See `LICENSE` for details.

## Third-Party Notices

This project incorporates architectural patterns and algorithmic inspirations from open-source biomedical and wellness projects:
- Mensinator (MIT License): Concepts for start-to-start cycle math and weighted moving average prediction.
- Metra (GPL-3.0 License): Inspiration for transparent mathematical prediction without neural network opacity.
- YIMA: Reference for relational symptom tracking schema design.

Detailed license texts and notices are documented in `THIRD_PARTY_NOTICES.md`.
