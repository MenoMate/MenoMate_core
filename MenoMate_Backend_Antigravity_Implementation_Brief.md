# MenoMate Core - Antigravity Backend Implementation Brief

**Version:** 1.0  
**Prepared:** 2026-09-05  
**Purpose:** Give the coding agent one authoritative implementation brief for the current MenoMate backend.  
**Target:** Existing FastAPI + async SQLAlchemy + asyncpg backend in `MenoMate_core-main`  
**Do not use this document as a request to build the Flutter UI.**

---

## 0. EXECUTIVE DIRECTIVE

You are modifying an existing FastAPI backend for **MenoMate**, not creating a greenfield project.

The backend is already connected successfully to a Supabase PostgreSQL database through the **Supabase Session Pooler** using:

- FastAPI
- SQLAlchemy 2.x async
- `asyncpg`
- Supabase Auth for user identity
- PostgreSQL on Supabase

Your job is to **study the existing repository, refactor only what is necessary, and implement a small, clean, modular API that directly serves the planned Flutter application.**

Do not add code, packages, endpoints, models, services, abstractions, AI frameworks, vector databases, graph databases, ML models, notification systems, or hardware-network code unless this brief explicitly requires them.

The goal is a backend that is:

- small enough for a student project;
- easy to understand and maintain;
- loosely coupled where change is likely;
- strongly relational where the underlying data is naturally relational;
- safe around health data and therapy controls;
- cheap/free to operate;
- straightforward for a Flutter developer to consume;
- easy to extend later without rewriting the API.

**Do not redesign the application around buzzwords such as agentic AI, LSTM, RAG, graph databases, microservices, or ML unless a concrete requirement below calls for them.**

---

# 1. IMPORTANT PRODUCT CONTEXT

MenoMate is planned as a mobile menstrual wellness application with an optional standalone ESP32 wearable.

The mobile application is expected to have roughly these areas:

1. Home / cycle page
2. Daily logging
3. Cycle history and summary
4. Profile/settings
5. MenoMate Care / guided assistance rather than a generic chatbot
6. Device connection and therapy controls

The main cycle screen should show things such as:

- next predicted period;
- current cycle day;
- current phase;
- a compact calendar that can expand when selected;
- period logging;
- today's mood/pain/symptom information;
- cycle summary/history.

Daily logging should support at least:

- pain score;
- symptoms such as cramps, nausea, back pain, low energy, etc.;
- mood;
- discharge;
- period flow;
- optional notes.

The profile area should remain small and practical:

- name;
- usual cycle length (optional / can be unknown);
- usual period length (optional / can be unknown);
- app preferences such as theme and units;
- account actions are primarily handled through Supabase Auth, with backend support for account deletion where required.

The user should be able to answer "I'm not sure" during onboarding instead of being forced to invent a cycle/period length.

---

# 2. IMPORTANT CORRECTION TO THE OLD CODEBASE

The existing repository uses `Cycle.start_date` and `Cycle.end_date` in a way that is effectively acting like the boundary of the entire cycle. That is **not the intended product model**.

For MenoMate, a cycle record represents a **menstrual period occurrence**:

- `period_start` = first day of bleeding
- `period_end` = last day of bleeding, nullable while the period is ongoing

The **cycle length is not `period_end - period_start`**.

It is calculated from the start of one period to the start of the next period.

Example:

```text
Period A: Aug 10 - Aug 14
Period B: Sep 08 - Sep 12

Period A length = 5 days
Cycle length between A and B = 29 days
```

This is a critical correction. Do not preserve the old calculation simply because existing tests happen to pass.

Similarly:

- period length = `period_end - period_start + 1` when ended;
- cycle length = `current_period_start - previous_period_start`;
- the current cycle's future length is unknown and should not be stored as if it were completed.

---

# 3. RESEARCHED OPEN-SOURCE REFERENCES

The following repositories were reviewed before preparing this brief. Their purpose is to give implementation and product-design inspiration so the agent does not need to independently search GitHub for basic menstrual-tracking patterns.

## 3.1 Mensinator - use as the strongest reusable-code reference

Repository:
https://github.com/EmmaTellblom/Mensinator

License: **MIT**.

Relevant ideas:

- period and ovulation tracking;
- statistics;
- customizable symptoms;
- cycle prediction;
- data export/import;
- deliberately simple, non-bloated tracking design.

Because it is MIT licensed, source-level reuse can be considered when it is genuinely useful, **but only with license/attribution obligations preserved**. Do not copy unrelated portions merely because they exist.

Primary source: GitHub repository and README.

## 3.2 Mētra - use for architecture/UX/algorithmic inspiration only

Repository:
https://github.com/paolo-santucci/metra/

License: **GPL-3.0**.

Relevant ideas:

- very small daily log;
- monthly calendar;
- timeline/history;
- statistics;
- transparent weighted-moving-average prediction over recent cycles;
- privacy-focused architecture;
- Flutter implementation ideas.

**Do not copy Mētra source code into MenoMate unless the licensing implications have been deliberately reviewed.** For this student project, treat Mētra primarily as a source of design and algorithmic ideas and implement equivalent logic ourselves.

## 3.3 YIMA - use for onboarding and cycle UX ideas

Repository:
https://github.com/Novawerk/YIMA

Relevant ideas:

- simple period-start / period-end logging;
- backfilling historical periods;
- cycle predictions from actual history with an onboarding fallback;
- anomaly filtering;
- cycle phase presentation.

YIMA is also useful as a reminder that the onboarding question set should collect enough information to make the first experience useful. Do **not** fabricate historical cycles merely to make graphs look populated.

## 3.4 Other reference

A small MIT-licensed full-stack menstrual tracker was also reviewed:
https://github.com/AmanCrafts/Menstrual-Health-Tracker

It demonstrates common concepts such as period logs, symptoms, moods, analytics, and API separation. Its feature list contains many things MenoMate deliberately does **not** need yet, so use it only as a secondary reference.

---

# 4. LICENSING RULES FOR REUSE

When borrowing open-source work:

1. Prefer MIT/BSD/Apache-2.0 compatible sources for direct code reuse.
2. Preserve required license notices and attribution.
3. Do not copy GPL-3.0 source into this repository simply because it implements something convenient.
4. Do not import an entire repository when only one algorithm/pattern is needed.
5. Prefer reimplementing small algorithms from the documented behavior rather than copying unrelated code.
6. Record any direct third-party code reuse in a small `THIRD_PARTY_NOTICES.md` file if needed.

The agent does not need to perform new web searches for these references. The research has already been done for this implementation brief.

---

# 5. ARCHITECTURE TO IMPLEMENT

Keep one backend application.

```text
Flutter
   |
   | HTTPS + Supabase access token
   v
FastAPI
   |
   +--> Auth verification
   +--> Profile service
   +--> Cycle service
   +--> Daily log service
   +--> Summary/calculation services
   +--> Care / AI orchestration
   +--> Device/therapy service
   |
   +--> SQLAlchemy async
          |
          v
       PostgreSQL
       (Supabase)
```

The ESP32 wearable is standalone:

```text
Flutter <---- BLE ----> ESP32
```

Do **not** make the wearable dependent on FastAPI or internet access.

The backend may provide a safe therapy recommendation, but the ESP32 remains the final hardware safety authority.

---

# 6. DATABASE MODEL

Implement these core application entities.

## 6.1 `profiles`

One application profile per Supabase Auth user.

Recommended fields:

```text
user_id              UUID PRIMARY KEY
name                 TEXT NULL
usual_cycle_days     INTEGER NULL
usual_period_days    INTEGER NULL
theme                TEXT NULL/default
units                TEXT NULL/default
created_at           TIMESTAMPTZ
updated_at           TIMESTAMPTZ
```

Important:

- `user_id` must correspond to the authenticated Supabase user's UUID.
- Do not store password/email authentication data in this table.
- Supabase Auth owns authentication.
- Do not force `usual_cycle_days` or `usual_period_days` to defaults merely because onboarding allows `I'm not sure`.

Current project has `Profile`; modify it rather than creating a second profile concept.

The old `sensitivity_index` may remain only if the therapy implementation still genuinely uses it. Do not keep unused fields just for historical compatibility.

## 6.2 `cycles`

This table represents menstrual period occurrences.

```text
id             UUID or existing integer PK
user_id        UUID FK -> profiles.user_id
period_start   DATE NOT NULL
period_end     DATE NULL
created_at     TIMESTAMPTZ
updated_at     TIMESTAMPTZ
```

Rules:

- one user owns many period records;
- `period_end` may be null while ongoing;
- `period_end >= period_start` when non-null;
- do not store `predicted_next_period` in this table;
- do not store phase rows;
- do not store a fake completed cycle length.

Derived values should come from services.

## 6.3 `daily_logs`

One record per user per calendar day.

```text
id            UUID or existing integer PK
user_id       UUID FK -> profiles.user_id
log_date      DATE NOT NULL
pain          INTEGER NOT NULL/default 0
mood          TEXT NULL
discharge     TEXT NULL
flow          TEXT NULL
notes         TEXT NULL
created_at    TIMESTAMPTZ
updated_at    TIMESTAMPTZ
```

Database constraint:

```text
UNIQUE(user_id, log_date)
```

Use one request to create/update the entire daily entry instead of forcing Flutter to make one HTTP request for pain, another for mood, another for discharge, etc.

## 6.4 `symptom_logs`

Symptoms are child records of a daily log.

```text
id             UUID or existing integer PK
daily_log_id   FK -> daily_logs.id
symptom_type   TEXT NOT NULL
severity       INTEGER NOT NULL
```

Example:

```text
2026-09-05
  cramps       7
  nausea       3
  back_pain    5
  low_energy   8
```

Do not create a database column for every symptom.

Do not store icon filenames/asset paths in PostgreSQL.

Flutter owns visual presentation. The backend owns the semantic symptom identifier.

## 6.5 `devices`

Persistent device association only.

```text
id                  UUID
user_id             UUID FK
 device_identifier  TEXT UNIQUE
name                TEXT NULL
firmware_version    TEXT NULL
last_connected_at   TIMESTAMPTZ NULL
created_at          TIMESTAMPTZ
updated_at          TIMESTAMPTZ
```

Do not store second-by-second temperature/battery telemetry in PostgreSQL.

## 6.6 `therapy_sessions`

Store completed/meaningful therapy events.

```text
id                    UUID/int
user_id               UUID FK
device_id             UUID FK NULL
started_at             TIMESTAMPTZ
ended_at               TIMESTAMPTZ NULL
mode                   TEXT
target_temperature_c   NUMERIC NULL
vibration_intensity    INTEGER NULL
vibration_mode         TEXT NULL
pain_before            INTEGER NULL
pain_after             INTEGER NULL
feedback               TEXT NULL
created_at             TIMESTAMPTZ
```

The exact fields can be adjusted to the already-supported hardware contract, but do not store a high-frequency stream of sensor samples.

## 6.7 `chat_conversations`

Use only if persistent AI conversation history is genuinely needed by the app.

```text
id          UUID
user_id     UUID FK
title       TEXT NULL
created_at  TIMESTAMPTZ
updated_at  TIMESTAMPTZ
```

## 6.8 `chat_messages`

```text
id               UUID
conversation_id  UUID FK
role             TEXT
content          TEXT
created_at       TIMESTAMPTZ
```

Keep this minimal.

Do not permanently store full AI context packages unless there is a demonstrated product requirement.

---

# 7. WHAT SHOULD NOT BE DATABASE TABLES

Do **not** create these tables at this stage:

- `phases`
- `predictions`
- `ai_insights`
- `symptom_types`
- `wellness_scores`
- `daily_ai_context`
- `llm_requests`
- `cycle_prediction_history`
- graph/vector/RAG storage

These are either derived data, configuration, or premature infrastructure.

---

# 8. CALCULATION RULES

Create dedicated service modules instead of putting calculations inside FastAPI route handlers.

## 8.1 Cycle calculation service

The service should calculate:

- cycle day;
- current phase;
- previous completed cycle lengths;
- average cycle length;
- cycle variability;
- estimated next period;
- prediction confidence.

Do not permanently store these derived values unless a later requirement explicitly proves that historical prediction snapshots are needed.

## 8.2 Cycle-length calculation

Given consecutive period starts:

```text
cycle_length = current_period_start - previous_period_start
```

This is the critical distinction from period duration.

## 8.3 Period-length calculation

For a completed period:

```text
period_length = period_end - period_start + 1
```

## 8.4 Initial prediction approach

Use a transparent statistical baseline first.

A reasonable starting point is a weighted moving average over recent completed cycle lengths, inspired by Mētra's published approach, but implement it independently.

Do not call an LLM to calculate dates.

Do not claim ML is being used merely because the project report mentions LSTM.

If insufficient historical data exists:

- use the user's stated usual cycle length if available;
- otherwise return a low-confidence / insufficient-data state rather than inventing certainty.

Do not fabricate historical cycles.

## 8.5 Phase calculation

Do not create a `phases` table.

Use a small, explicit phase calculation service. It may use an approximate standard cycle model, but the API must clearly represent that phases are estimates rather than clinical measurements.

Avoid fertility-focused features unless specifically requested later.

---

# 9. DAILY LOG ENUMS / VALIDATION

Use backend validation for controlled values.

Suggested flow values:

```text
none
spotting
light
medium
heavy
```

Suggested mood values:

```text
happy
calm
neutral
sad
irritable
anxious
tired
```

The exact names may be adjusted for consistency with the Flutter UI, but keep the set small.

Suggested discharge values:

```text
none
light
moderate
heavy
```

Symptoms should be semantic IDs such as:

```text
cramps
headache
nausea
back_pain
low_energy
bloating
breast_tenderness
acne
sleep_difficulty
appetite_change
dizziness
```

This list is intentionally easy to extend.

Do not store UI icon data with these identifiers.

Severity should normally be `0-10`.

---

# 10. ONBOARDING

Add a small onboarding flow to the backend contract.

Required initial information:

```text
name                         optional
last period start            required
last period end              optional if still ongoing
usual cycle length           optional
usual period length          optional
```

The Flutter app must be able to represent:

```text
"I'm not sure"
```

by sending `null` for the corresponding usual-length field.

Do not replace unknown values with fake defaults in persistent user data.

A dedicated endpoint is preferred:

```http
POST /api/v1/onboarding/complete
```

This should atomically initialize the user's profile and initial period record.

Do not make Flutter coordinate four independent requests if one transaction can safely establish the user's initial state.

If onboarding is submitted twice, make the behavior safe and predictable; do not silently create duplicate starting periods.

---

# 11. API CONTRACT

Use `/api/v1`.

Keep endpoint names resource-oriented and unsurprising.

## 11.1 Authentication

```http
GET /api/v1/auth/me
```

Returns the authenticated user identity and enough application state for the Flutter app to know who is signed in.

Supabase handles signup/login/password change/session management on the client side.

Do not implement a second custom password system.

## 11.2 Profile

```http
GET /api/v1/profile
PATCH /api/v1/profile
```

## 11.3 Onboarding

```http
POST /api/v1/onboarding/complete
```

## 11.4 Cycles

```http
GET   /api/v1/cycles/current
GET   /api/v1/cycles
POST  /api/v1/cycles
PATCH /api/v1/cycles/{cycle_id}
```

For `POST /cycles`, starting a period means creating a period occurrence, not starting an abstract multi-week cycle.

For `PATCH /cycles/{cycle_id}`, allow correction of the period end/start as appropriate and validate date consistency.

Avoid silently rewriting history.

## 11.5 Daily logs

```http
GET   /api/v1/logs/{date}
GET   /api/v1/logs?start_date=...&end_date=...
POST  /api/v1/logs
PATCH /api/v1/logs/{log_id}
```

A daily-log response should include its child symptoms so Flutter can render one day from one API response.

## 11.6 Supported symptoms

```http
GET /api/v1/symptoms
```

This returns the currently supported symptom IDs and display labels.

Do not create a database table just to serve this static list.

## 11.7 Summary/history

```http
GET /api/v1/summary/current
GET /api/v1/summary/history
```

These are calculation endpoints. They should assemble useful data for the home and history screens.

Examples of derived values:

- current cycle day;
- phase estimate;
- next-period estimate;
- prediction confidence;
- average cycle length;
- average period length;
- recent pain average;
- frequent recent symptoms.

## 11.8 Devices

```http
GET    /api/v1/devices
POST   /api/v1/devices
DELETE /api/v1/devices/{device_id}
```

Actual live BLE is Flutter <-> ESP32.

## 11.9 Therapy

```http
POST /api/v1/therapy/recommend
POST /api/v1/therapy/sessions
PATCH /api/v1/therapy/sessions/{session_id}
```

The recommendation route may use the existing deterministic calibrator, but it must be reviewed against the corrected product model.

**AI must not directly control heater temperature, vibration GPIO, PWM, or low-level device commands.**

The chain is:

```text
user data
   -> recommendation logic
   -> deterministic safety/policy validation
   -> Flutter BLE command
   -> ESP32 safety checks
   -> hardware
```

## 11.10 Care / AI

Do not present this backend as a generic ChatGPT clone.

Prefer:

```http
POST /api/v1/care/interactions
```

or an equivalent name that communicates guided assistance.

An interaction may contain an intent such as:

```text
cycle_insight
symptom_insight
pain_help
wellness_help
device_help
other
```

The backend decides whether the interaction needs:

1. a predefined response;
2. a deterministic calculation;
3. a targeted AI request.

Do not call the LLM for simple questions such as:

- "When is my next period?"
- "What cycle day am I on?"
- "What is my average cycle length?"
- "Is my device linked?"

Those should use backend logic.

---

# 12. CARE / AI ARCHITECTURE

The product intentionally avoids becoming another generic chatbot.

Use this flow:

```text
User taps/selects intent
          |
          v
Intent handling
          |
   +------+------+
   |             |
Simple       Personalized/ambiguous
   |             |
   v             v
Preset       Context builder
answer           |
                  v
                LLM
```

The Flutter app should be able to show predetermined options such as:

```text
I'm in pain
I'm feeling tired
My mood has changed
I have nausea
Help me understand my cycle
Something feels different
Device help
Ask something else
```

These options are a product/UI concern, but the backend should understand the intent IDs.

---

# 13. AI CONTEXT BUILDER

Create an `ai_context`/`care_context` service, but keep it lightweight.

The AI should receive only the context relevant to the current question.

Example for a fatigue question:

```json
{
  "cycle_day": 24,
  "phase": "luteal",
  "predicted_next_period": "2026-09-13",
  "recent_logs": [
    {"date": "2026-09-04", "pain": 5, "mood": "tired", "symptoms": ["fatigue"]},
    {"date": "2026-09-05", "pain": 6, "mood": "tired", "symptoms": ["nausea", "low_energy"]}
  ]
}
```

Do not send all historical data on every request.

Do not introduce RAG, vectors, embeddings, Neo4j, or a graph database for v1.

PostgreSQL queries plus a small context builder are sufficient.

---

# 14. AI PROVIDER ABSTRACTION

Do not hard-code MenoMate to one LLM provider.

Create a very small interface/adapter such as:

```text
AIService
  generate_response(context, user_message)
```

or an equivalent clean abstraction.

For now:

- do not require a paid model;
- do not embed an API key in code;
- do not put an API key in Flutter;
- allow a mock provider for tests/development;
- leave the real provider integration configurable through environment variables.

Most common interactions should not consume AI at all.

A future provider can be swapped without changing cycle/log/device routes.

---

# 15. PRIVACY AND DATA MINIMIZATION

Health/cycle data is sensitive.

Do not log health records, auth tokens, passwords, API keys, or AI context to ordinary application logs.

Do not return another user's data under any circumstances.

Every database query involving user-owned data must scope by the authenticated user's UUID.

Avoid accepting `user_id` from the client as an authority signal.

The authenticated token determines the user.

---

# 16. SUPABASE AUTH VERIFICATION - IMPORTANT

The existing codebase currently decodes Supabase JWTs using a configured shared secret and HS256.

That is legacy-style behavior and should **not simply be preserved without review**.

Current Supabase documentation recommends verified JWT claims via the project's signing-key/JWKS mechanisms for asymmetric signing keys, and when using symmetric legacy signing keys it recommends validating the access token with the Auth server rather than blindly decoding it. Supabase also explicitly emphasizes validating issuer, audience, and expiration.

Primary references:

- https://supabase.com/docs/guides/auth/jwts
- https://supabase.com/docs/reference/python/auth-getclaims
- https://supabase.com/docs/reference/python/auth-getuser

For this repository, implement the smallest robust server-side verification path that matches the actual Supabase project configuration.

Do not invent a custom authentication protocol.

At minimum, authenticated routes must validate:

- signature/authenticity;
- issuer where applicable;
- audience (`authenticated`) where applicable;
- expiration;
- presence and UUID validity of `sub`.

If the project uses asymmetric signing keys, prefer JWKS-based verification. If the project still uses a symmetric legacy signing key, use an appropriately verified Auth-server path rather than pretending a locally configured secret is automatically correct.

Also update tests so authentication behavior is realistic and not dependent on production secrets.

---

# 17. EXISTING REPOSITORY - STUDY BEFORE MODIFYING

Before making code changes, inspect:

```text
app/main.py
app/api/router.py
app/api/v1/auth.py
app/api/v1/cycle.py
app/api/v1/logs.py
app/api/v1/therapy.py
app/core/config.py
app/core/security.py
app/db/base.py
app/db/session.py
app/models/*.py
app/schemas/*.py
app/services/*.py
tests/*.py
requirements.txt
```

Current known repository behavior includes:

- `Profile` currently uses `cycle_length_avg`, `period_length_avg`, and `sensitivity_index`;
- `Cycle` currently stores `start_date`, `end_date`, `predicted_ovulation`, and `is_active`;
- `DailyLog` currently stores symptoms as a JSON list and uses `cramp_severity`/`flow_intensity`/`mood`;
- therapy calibration already exists;
- tests currently use SQLite + a test JWT secret;
- startup currently calls `Base.metadata.create_all`.

Do not assume every existing field/test is correct just because it exists.

---

# 18. REQUIRED MIGRATION MAP BEFORE EDITING

Before writing implementation code, create a small internal plan mapping the old system to the new one.

Example format:

```text
Existing Profile model
    -> modify

Existing Cycle model
    -> modify semantics

Existing DailyLog model
    -> split symptoms into child records and add discharge

Existing TherapySession
    -> keep/modify only required fields

Existing /auth/sync-profile
    -> replace/retain only if justified by onboarding/profile contract

Existing cycle_engine.py
    -> rewrite because current cycle-length semantics are incorrect
```

Do not produce a long architecture document inside the repo unless useful. The actual implementation should remain lean.

---

# 19. DATABASE / MIGRATION STRATEGY

The repository currently uses `create_all()` at startup. This is acceptable as a development bootstrap, but do not rely on it as a sophisticated production migration system.

Because the schema is changing, handle the transition safely.

Preferred approach:

- keep schema creation simple for local/test environments;
- introduce a proper migration mechanism only if needed to migrate the existing Supabase schema safely;
- do not destroy the user's existing Supabase data during development;
- never add code that drops all tables automatically;
- never run destructive migration commands without explicit authorization.

Do not make the agent assume the Supabase database is disposable.

---

# 20. RESPONSE SHAPES

Flutter should receive predictable, clean JSON.

Do not expose SQLAlchemy objects or internal database implementation details directly unless Pydantic serialization is correctly configured.

Responses should be designed around use cases rather than raw tables.

For example, `/cycles/current` should return calculated current state, not simply dump the cycle row.

Similarly, `/logs/{date}` should return the complete day's logging information including symptoms.

Use consistent error structure through FastAPI's normal HTTP exception mechanisms.

---

# 21. ERROR AND VALIDATION RULES

Validate at the API boundary and again where domain logic requires it.

Examples:

- pain must be `0-10`;
- symptom severity must be `0-10`;
- period end cannot precede period start;
- a daily log date must be valid;
- duplicate `(user_id, log_date)` daily logs should be handled cleanly;
- a therapy target temperature must never bypass safety bounds;
- a user can only access their own cycles/logs/devices/therapy sessions/conversations.

Do not silently clamp bad user input unless there is a deliberate domain reason.

For safety-critical therapy values, deterministic safety clamping is appropriate.

---

# 22. THERAPY SAFETY

The current project contains a deterministic calibrator with a 44.0 C backend ceiling.

Treat the backend ceiling as a policy constraint, not a substitute for ESP32 hardware safety.

Never allow:

```text
LLM -> heater temperature
LLM -> GPIO
LLM -> raw BLE command
```

The LLM may recommend a therapy *intent* or explain a safe predefined option.

The deterministic policy layer produces the actual allowed profile.

The ESP32 independently enforces its own:

- maximum temperature;
- timer;
- watchdog;
- sensor fault behavior;
- physical thermal cutoff.

---

# 23. TESTING REQUIREMENTS

Preserve the existing test suite where tests remain valid, but **rewrite invalid tests whose assumptions reflect the old data model**.

Add tests for:

### Authentication

- missing token -> 401;
- invalid token -> 401;
- valid test token -> authenticated user UUID;
- wrong subject/user cannot access another user's data.

### Onboarding

- normal onboarding creates profile + first period;
- `null` usual cycle/period values are accepted;
- repeated onboarding is safe.

### Cycles

- period start/end validation;
- completed period length calculation;
- consecutive period starts produce correct cycle length;
- current cycle day is correct;
- insufficient history gives low-confidence/unknown prediction state;
- real history overrides onboarding average as data becomes available.

### Daily logs

- pain validation;
- symptom severity validation;
- create/read/update;
- one log per user/date;
- symptom replacement/update behaves predictably.

### Summary

- averages are correct;
- symptom frequencies are correct;
- no fabricated historical cycles;
- current and historical calculations use correct date semantics.

### Therapy

- safe ceiling cannot be exceeded;
- sensitivity/feedback behavior remains bounded;
- malformed/unsafe inputs are rejected.

### Care

- deterministic questions do not invoke the AI provider;
- AI-required questions receive only the intended compact context;
- mock AI provider is testable without an external API key.

Use isolated test fixtures; do not use the real Supabase production database for automated tests.

---

# 24. DEPENDENCY DISCIPLINE

Do not run `pip freeze` and copy the result into `requirements.txt`.

Maintain intentional direct dependencies only.

Known relevant production dependencies from the existing project include:

```text
fastapi
uvicorn[standard]
sqlalchemy
asyncpg
pydantic
pydantic-settings
```

Existing test/support packages may include:

```text
pytest
pytest-asyncio
httpx
aio-sqlite
```

Keep only packages that are actually imported or required by the chosen implementation/test strategy.

Do not add an LLM SDK, LangChain, LangGraph, vector database client, graph database client, or ML package just to create an empty abstraction.

---

# 25. CODE ORGANIZATION

Prefer this general organization:

```text
app/
  api/v1/
      auth.py
      profile.py
      onboarding.py
      cycles.py
      logs.py
      summary.py
      care.py
      devices.py
      therapy.py

  core/
      config.py
      security.py

  db/
      base.py
      session.py

  models/
      profile.py
      cycle.py
      daily_log.py
      symptom_log.py
      device.py
      therapy_session.py
      chat.py

  schemas/
      profile.py
      onboarding.py
      cycle.py
      daily_log.py
      summary.py
      device.py
      therapy.py
      care.py
      chat.py

  services/
      cycle_calculator.py
      summary.py
      therapy_policy.py
      care.py
      ai_context.py
      ai_provider.py
```

The exact file split may differ if the existing repository has a cleaner equivalent. Do not split tiny one-function files merely for the sake of having many files.

The rule is **cohesion + low coupling, not maximum file count**.

---

# 26. LOCAL CACHE VS SERVER SOURCE OF TRUTH

Do not build a second complete database inside FastAPI or treat Flutter local storage as another authoritative health database.

For the planned architecture:

### Server/PostgreSQL source of truth

- cycles
- daily logs
- symptoms
- profile data required by backend
- therapy sessions
- device associations
- persistent AI conversations if enabled

### Flutter local storage

- theme/UI settings;
- cached values for responsiveness;
- onboarding/UI state;
- other presentation preferences.

Do not require every BLE telemetry sample to reach the server.

---

# 27. WHAT IS INTENTIONALLY DEFERRED

Do not implement these as part of this refactor unless they are already required for the current API contract:

- LSTM cycle prediction;
- ML ensemble cycle prediction;
- TinyML on ESP32;
- graph database;
- vector database;
- RAG framework;
- multi-agent system;
- paid cloud AI infrastructure;
- custom-hosted LLM;
- push notification infrastructure;
- fertility/ovulation product features beyond the minimal phase estimate;
- medical diagnosis;
- giant health profile;
- wellness score gamification;
- social/community features;
- analytics/telemetry unrelated to the application.

A later milestone can add ML after there is a defensible dataset and a baseline to compare against.

---

# 28. MEDICAL / SAFETY LANGUAGE

MenoMate is a student wellness project, not a diagnostic system.

AI responses must avoid presenting uncertain symptom interpretations as diagnoses.

Discharge information may be used as context for a wellness response, but the system must not diagnose infections or other medical conditions from discharge alone.

For potentially concerning symptoms, return conservative guidance recommending appropriate professional medical evaluation rather than generating confident diagnoses.

Avoid claims of medical-grade prediction accuracy unless supported by actual validation.

---

# 29. IMPLEMENTATION ORDER

Follow this order.

## Phase 1 - inspect

1. Read the complete existing repository.
2. Map current models/routes/services/tests against this brief.
3. Identify outdated assumptions.
4. Confirm current Supabase DB connection configuration is not changed unnecessarily.

## Phase 2 - schema/domain

5. Correct the Profile model.
6. Correct the Cycle model semantics.
7. Add/modify DailyLog and SymptomLog.
8. Add Device and modify TherapySession only as required.
9. Add chat models only if the Care API needs persistent conversations now.

## Phase 3 - services

10. Rewrite cycle calculation logic with correct period/cycle semantics.
11. Create summary calculations.
12. Keep therapy safety deterministic.
13. Create the Care intent routing/context layer.
14. Create a mockable AI provider abstraction without requiring a real paid provider.

## Phase 4 - API

15. Implement/refactor profile and onboarding.
16. Implement cycle endpoints.
17. Implement daily log endpoints.
18. Implement summary endpoints.
19. Implement device/therapy endpoints.
20. Implement Care interactions at the minimum useful level.

## Phase 5 - security

21. Replace the legacy auth implementation with a currently appropriate Supabase JWT verification flow for the project's actual signing configuration.
22. Ensure every resource query is scoped to the authenticated user.
23. Remove accidental sensitive logging.

## Phase 6 - tests

24. Update/add comprehensive unit and endpoint tests.
25. Run the full suite.
26. Fix failures without weakening tests just to get green status.

## Phase 7 - cleanup

27. Remove dead endpoints/models/schemas/services/imports.
28. Remove dependencies that are no longer needed.
29. Keep comments only where they explain domain/security decisions.
30. Run a final repository-wide search for references to deleted/renamed fields.

---

# 30. DEFINITION OF DONE

The implementation is done only when all of the following are true:

### Database

- Supabase PostgreSQL remains the database.
- No accidental destructive operation was performed.
- The relational model matches this brief.
- User ownership is enforced by authenticated UUID scoping.

### API

- Routes are small and predictable.
- Responses match Flutter use cases.
- No unnecessary API proliferation.
- Derived cycle/summary values are calculated rather than redundantly persisted.

### Domain correctness

- A period record means bleeding start/end.
- Cycle length is measured start-to-start between periods.
- Period length is measured end-to-start inclusively.
- No fake historical cycles are created.
- Unknown onboarding values remain unknown.

### AI

- AI is an escalation layer, not the default path.
- Simple calculations use backend logic.
- Common guided interactions can use predetermined responses.
- AI context is compact and question-specific.
- Provider credentials never reach Flutter.
- Provider implementation is replaceable.

### Hardware

- FastAPI does not directly control GPIO/BLE commands.
- Therapy recommendations are deterministic and bounded.
- ESP32 remains the final hardware safety authority.

### Quality

- Existing valid tests continue to pass.
- New tests cover the changed domain behavior.
- No dead code remains from the old model.
- No unnecessary packages were added.
- API documentation is accurate.

---

# 31. FINAL AGENT BEHAVIOR RULES

When implementing:

**DO**

- inspect before editing;
- reuse existing working pieces when they fit;
- write small domain services;
- use Pydantic schemas at API boundaries;
- use async SQLAlchemy correctly;
- make database operations transactional where a request changes multiple related records;
- write tests before/alongside significant domain changes;
- reuse MIT-compatible open-source ideas/code only when useful and legally appropriate;
- keep the implementation understandable to a student developer.

**DO NOT**

- rewrite the whole project because a new architecture looks prettier;
- copy an entire open-source application;
- copy GPL code into the project casually;
- add libraries because an AI coding agent knows them;
- create endpoints no Flutter feature needs;
- store derived values everywhere;
- use JSON as a substitute for all relational modeling;
- use relational tables for UI icon metadata;
- send all user history to an LLM;
- let an LLM set raw hardware controls;
- silently fabricate user history;
- weaken validation because tests are inconvenient;
- log secrets or private health information;
- modify infrastructure configuration that is already working unless required.

---

# 32. EXPECTED AGENT OUTPUT AFTER IMPLEMENTATION

At the end, provide a concise implementation report containing:

1. Files created/modified/deleted.
2. Database model changes.
3. Endpoint changes.
4. Auth verification approach used and why.
5. AI/Care behavior implemented.
6. Tests added/changed and final result.
7. Dependencies added/removed and why.
8. Any decisions that remain deliberately deferred.
9. Any migration command or manual Supabase SQL that the developer must run.

Do not claim an external AI provider is working unless an actual API key/configuration was provided and a real request was successfully tested.

Do not claim hardware integration is working unless a real BLE/device test was performed.

---

# 33. AUTHORITATIVE REFERENCES

Supabase JWT/auth verification:

- https://supabase.com/docs/guides/auth/jwts
- https://supabase.com/docs/reference/python/auth-getclaims
- https://supabase.com/docs/reference/python/auth-getuser

Open-source menstrual tracking references:

- https://github.com/EmmaTellblom/Mensinator
- https://github.com/paolo-santucci/metra/
- https://github.com/Novawerk/YIMA
- https://github.com/AmanCrafts/Menstrual-Health-Tracker

These references are for informed implementation. MenoMate's own requirements in this document take precedence over feature lists in any reference repository.

---

# 34. ONE-SENTENCE PRIORITY

**Build the smallest correct backend that Flutter can rely on, make PostgreSQL the source of truth, calculate what can be calculated, use AI only when interpretation is actually useful, keep the wearable independent and safe, and leave everything else out until a real feature requires it.**
