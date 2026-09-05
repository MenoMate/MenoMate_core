You are working on the existing MenoMate Core backend repository.

IMPORTANT:
This is a refinement and verification pass, NOT a rewrite.
Do not rebuild the project from scratch.
Do not introduce Firebase, Firestore, a web application, microservices, RAG, vector databases, graph databases, LSTM, or other major technologies that are not already required.
Do not change the core architecture unless a current implementation is demonstrably incorrect.

The intended architecture is:

Flutter mobile app
        |
        v
FastAPI backend (menomate-core)
        |
        +--> Supabase PostgreSQL
        |
        +--> Supabase Auth
        |
        +--> AI/Care layer when actually needed
        |
        +--> deterministic therapy policy
        |
        v
Flutter <---- BLE ----> standalone ESP32 wearable

The AI must NEVER directly control GPIO, temperature, heater power, vibration motors, or arbitrary hardware commands.

The existing repository already contains the implementation from the MenoMate Backend Antigravity Implementation Brief. Your task is to review the CURRENT CODE against that intended architecture and fix only the issues that are actually present.

==================================================
PHASE 1 — FULL REPOSITORY REVIEW
==================================================

Before changing anything:

1. Inspect the complete repository structure.
2. Read:
   - README.md
   - MenoMate_Backend_Antigravity_Implementation_Brief.md
   - requirements.txt
   - .env.example
   - all files under app/
   - supabase_migration.sql
   - all tests
   - THIRD_PARTY_NOTICES.md
3. Compare the implementation against the brief.
4. Identify:
   - actual bugs
   - architectural inconsistencies
   - outdated documentation
   - unsafe assumptions
   - missing validation
   - misleading claims
   - tests that are missing
5. Do not make changes merely because something could theoretically be improved.

After the review, implement the corrections below.

==================================================
PHASE 2 — SUPABASE AUTHENTICATION
==================================================

Review app/core/security.py carefully.

The current implementation may still rely on legacy HS256 JWT decoding using SUPABASE_JWT_SECRET.

Verify how the current Supabase project is configured and determine the correct JWT verification approach for that configuration.

The authentication implementation must:

- verify the JWT signature
- validate expiration
- validate issuer where appropriate
- validate audience where appropriate
- correctly extract the authenticated Supabase user ID
- reject malformed or invalid tokens
- never trust user_id supplied by the client for authorization
- ensure every protected database query is scoped to the authenticated user

Prefer the current Supabase-supported verification approach rather than blindly decoding a JWT.

Do not expose any Supabase service-role secret to Flutter.

Do not place privileged secrets in the mobile application.

Add or update tests for:
- valid token
- invalid token
- expired token
- malformed token
- missing Authorization header
- cross-user access attempts

If the exact Supabase signing configuration cannot be determined automatically, document exactly what must be configured rather than guessing.

==================================================
PHASE 3 — DATABASE / MIGRATION CORRECTNESS
==================================================

Inspect supabase_migration.sql.

There is currently duplicated migration SQL. Remove the duplication.

Determine whether the current SQL is actually safe against the OLD schema.

Important:
The previous database schema used fields such as:
- profiles.id
- cycles.start_date
- cycles.end_date
- cycles.predicted_ovulation
- cycles.is_active

The new schema uses:
- profiles.user_id
- cycles.period_start
- cycles.period_end

CREATE TABLE IF NOT EXISTS does NOT migrate an existing table into a new schema.

Therefore:

A. If this repository assumes a completely fresh Supabase project:
   - create a clean, deterministic initial schema
   - document that it is for a fresh database
   - do not falsely call it a safe migration from the old schema

B. If migration from the previous schema is required:
   - explicitly create a non-destructive migration strategy
   - preserve existing data
   - explicitly rename/copy/transform old fields where necessary
   - never silently destroy data

Do not perform destructive DROP/TRUNCATE operations.

Also review:
- foreign keys
- indexes
- uniqueness constraints
- useful CHECK constraints
- timestamp defaults
- updated_at behavior
- UUID generation

Do not add excessive database constraints that make normal application behavior difficult.

==================================================
PHASE 4 — REMOVE PRODUCTION create_all() ASSUMPTION
==================================================

Inspect app startup.

If Base.metadata.create_all() is being executed automatically against the Supabase production database:

Do not rely on this as the production migration mechanism.

The application should not silently modify production schema every time FastAPI starts.

Use an explicit migration/setup approach.

If Alembic is justified for this repository, use it cleanly.
If adding Alembic would be unnecessary for the current project stage, keep the migration SQL approach but make it explicit and documented.

Do not introduce unnecessary complexity.

==================================================
PHASE 5 — CYCLE PREDICTION CORRECTNESS
==================================================

Review app/services/cycle_calculator.py and summary logic.

Important domain semantics:

A cycle record represents a menstrual period occurrence.

period_start:
first bleeding day

period_end:
last bleeding day

Cycle length:
days between the start of one period and the start of the next period.

Period length:
period_end - period_start + 1

Do not treat period duration as cycle length.

Review prediction behavior carefully.

Current behavior may return a value such as 28 with an "insufficient_data" state.

That is misleading if the user has no cycle history and did not provide a usual cycle length.

Change the behavior so that:

- sufficient history -> provide a prediction
- user-provided usual cycle length -> it may be used as a baseline
- insufficient data and no user baseline -> predicted next-period date should be NULL / unavailable
- do not present an arbitrary 28-day estimate as if it were personalized
- expose confidence/state clearly

A possible result model:

predicted_cycle_length: nullable
predicted_next_period: nullable
confidence: low/medium/high or equivalent
source: history/usual_cycle/insufficient_data
variability: optional

Use the existing weighted moving average approach as the baseline if appropriate.

Do not introduce LSTM.

Also review:
- future period dates
- overlapping periods
- duplicate periods
- impossible date ranges
- unreasonable cycle lengths

Prevent invalid data from corrupting prediction.

Phase estimation may remain approximate, but make sure the API/UI-facing data clearly communicates that it is an estimate and not a medical determination.

==================================================
PHASE 6 — DAILY LOG / SYMPTOM VALIDATION
==================================================

Review daily logs and symptom handling.

Symptoms should use a controlled vocabulary rather than accepting arbitrary strings everywhere.

If SUPPORTED_SYMPTOMS already exists, make sure validation actually uses it.

Validate:
- pain severity 0–10
- symptom severity 0–10
- valid flow values
- valid mood values
- valid dates
- reasonable future-date behavior

Review PATCH semantics carefully.

The API must distinguish between:

1. field not supplied
2. field supplied with NULL intentionally
3. field supplied with a real value

For example, a user should be able to clear an optional note if the API supports clearing it.

Do not accidentally interpret NULL as "field not supplied."

Use Pydantic's appropriate field-set mechanisms if needed.

==================================================
PHASE 7 — CYCLE VALIDATION
==================================================

Review cycle creation/update.

Prevent:
- future period starts unless explicitly supported
- period_end before period_start
- overlapping periods
- duplicate period starts
- obviously impossible period durations

Allow legitimate backfilling of historical periods.

Do not over-restrict historical data entry.

==================================================
PHASE 8 — THERAPY SAFETY
==================================================

Review the therapy architecture.

The following principle MUST remain:

LLM / AI
    ↓
recommendation
    ↓
deterministic therapy policy
    ↓
validated safe profile
    ↓
Flutter/BLE
    ↓
ESP32 safety controller
    ↓
hardware

AI must NOT produce:
- raw GPIO commands
- arbitrary temperatures
- arbitrary PWM values
- unrestricted heater durations
- unrestricted motor commands

The deterministic therapy policy must enforce the backend maximum temperature.

The ESP32 must independently enforce hardware safety.

The backend is NOT the ultimate safety mechanism.

Do not weaken existing safety limits.

Review the existing:
- temperature ceiling
- pain mapping
- vibration mapping
- duration
- sensitivity adjustment
- feedback loop

Make sure values are clamped and validated.

==================================================
PHASE 9 — AI / CARE LAYER
==================================================

Review app/services/ai_context.py
app/services/ai_provider.py
app/services/care.py

Keep the AI provider abstraction.

The mock provider must remain usable without an external API key.

Do not make an external LLM mandatory for normal backend operation.

Improve context selection.

Do not always send "last 3 days" regardless of the question.

Context should depend on intent.

Examples:

cycle question:
- current cycle
- recent cycle history
- usual cycle length

symptom-pattern question:
- relevant symptoms
- recent history
- multi-cycle pattern where available

therapy question:
- current pain
- recent therapy
- therapy feedback
- sensitivity/personalization information

general wellness:
- only the minimum relevant context

Keep context compact.

Also review AI language.

Avoid:
- diagnosis
- claims that a symptom definitely has a hormonal cause
- medical certainty
- medication/supplement recommendations presented as prescriptions
- overconfident physiological explanations

Use cautious language such as:
- "may"
- "can"
- "some people experience"
- "if this is persistent or severe, consider speaking with a healthcare professional"

The assistant should be useful without pretending to be a doctor.

==================================================
PHASE 10 — ACCOUNT / DATA DELETION
==================================================

Review DELETE /profile or account deletion functionality.

Determine whether it actually deletes:

1. application data
2. Supabase Auth user

If it only deletes the application profile, do NOT describe it as complete account deletion or "GDPR compliant."

If true account deletion is implemented:
- privileged Supabase credentials must remain server-side
- Flutter must never receive service-role credentials
- deletion order and foreign-key behavior must be correct

If full Auth-user deletion is not implemented yet:
- rename/document the endpoint accurately
- do not make compliance claims

==================================================
PHASE 11 — RLS / ACCESS CONTROL
==================================================

The current architecture intentionally uses FastAPI as the database access layer.

Do not automatically add RLS everywhere without understanding the architecture.

However:

- every user-owned table must be scoped by authenticated user ID
- no endpoint may allow one authenticated user to access another user's records
- device IDs, therapy sessions, cycles, logs, profile data, and care history must all be user-scoped

Add explicit cross-user tests.

Document the current access-control architecture.

If RLS is intentionally disabled because direct PostgreSQL access is exclusively through FastAPI, say so clearly.

Do not claim database-level isolation if it does not exist.

==================================================
PHASE 12 — TESTING
==================================================

Run the complete test suite.

Do not stop after existing tests pass.

Add tests for the corrections above.

At minimum verify:

AUTH
- valid authentication
- invalid authentication
- expired token
- cross-user access

ONBOARDING
- complete onboarding
- null usual cycle length
- null usual period length
- idempotency

CYCLES
- correct cycle length
- correct period length
- invalid date ranges
- overlapping periods
- insufficient prediction data
- prediction using history
- prediction using user baseline

LOGS
- create
- update
- clear optional field
- invalid pain
- invalid symptom severity
- invalid symptom type
- cross-user isolation

THERAPY
- safe temperature
- temperature ceiling
- vibration clamping
- duration validation
- feedback adjustment
- cross-user device/session isolation

CARE
- deterministic responses
- mock AI provider
- context generation
- no hardware control through AI

Run all tests after modifications.

If tests fail, fix the implementation rather than weakening the tests unless the test itself is genuinely incorrect.

==================================================
PHASE 13 — README REDESIGN
==================================================

Rewrite README.md so it represents the CURRENT MenoMate project, not the old architecture.

IMPORTANT:
No emojis anywhere in README.md.

The README should look like a serious student engineering project / portfolio project.

Use clear sections such as:

# MenoMate Core

One-paragraph project description.

## Overview

Explain that MenoMate is a menstrual wellness system consisting of:
- Flutter mobile application
- FastAPI backend
- Supabase PostgreSQL
- Supabase Auth
- standalone ESP32 wearable
- BLE communication

Do NOT mention the old React web application if it is no longer part of the project.

## System Architecture

Include a simple text/ASCII architecture diagram.

Example:

Flutter Mobile App
       |
       | HTTPS
       v
FastAPI Backend
       |
       +---- Supabase Auth
       |
       +---- PostgreSQL
       |
       +---- AI/Care Layer
       |
       +---- Therapy Policy
       |
       v
    BLE Layer
       |
       v
ESP32 Wearable
       |
       +---- Temperature Sensor
       +---- Heater
       +---- Vibration Motors
       +---- Hardware Safety

Make the safety boundary explicit.

## Core Features

Describe only features that actually exist in the current repository.

Potential areas:
- user authentication
- onboarding
- period/cycle tracking
- daily symptom logging
- cycle prediction
- personalized therapy recommendation
- therapy session tracking
- BLE device management
- contextual care assistant
- safety-constrained therapy policy

Do NOT advertise features that are only planned.

## AI Design

Explain what AI does and what it does NOT do.

Important:
AI provides contextual wellness assistance and personalization.

AI does not directly control the hardware.

Explain the deterministic therapy-policy boundary.

## Database

Briefly explain the major entities:
- profiles
- cycles
- daily_logs
- symptom_logs
- devices
- therapy_sessions
- care/chat data if actually implemented

Do not document tables that do not exist.

## API

Give a concise endpoint overview grouped by domain.

For example:

Auth
Profile
Onboarding
Cycles
Logs
Summary
Devices
Therapy
Care

Do not list endpoints that do not actually exist.

## Local Development

Give accurate setup instructions.

Include:
- Python version if actually required
- virtual environment
- dependency installation
- .env setup
- Supabase configuration
- database migration/setup
- starting FastAPI
- running tests

Use commands that have been verified against the current repository.

Do not invent commands.

## Environment Variables

Document every required variable in .env.example.

Do not expose real secrets.

Explain which variables are server-side only.

## Project Structure

Show the actual current repository structure.

Keep it concise.

## Safety

Explain:
- backend temperature ceiling
- deterministic policy
- ESP32 independent safety
- thermal cutoff
- timeout/watchdog if actually implemented
- why AI cannot directly command the hardware

Only describe protections that actually exist.

## Current Status

Clearly distinguish:

Implemented
In progress
Planned

Do not make the project sound more complete than it is.

## Mobile Application

Explain that the Flutter app is a separate repository/project if that is the current organization.

Use the actual repository name:
menomate-mobile

Do not claim it is already integrated if it is not.

## Hardware

Describe the standalone ESP32 wearable at a high level.

Do not claim final hardware specifications unless they are actually implemented and tested.

## Future Work

This is where planned features can be mentioned.

Potential examples:
- improved cycle prediction
- richer personalization
- production BLE integration
- hardware refinement
- additional sensors
- deployment
- live demo
- mobile release

Do not present these as completed.

## Demo

Add a section:

## Demo

Current status:
Not deployed yet.

Reserve a clean placeholder for a future live demo.

Example:

Live Demo: Coming soon

Later this section can contain:
- deployed backend URL
- API documentation URL
- mobile demo/video
- screenshots
- hardware demonstration video

Do NOT create fake URLs.

Do NOT deploy anything as part of this task.

## License

Use the repository's actual LICENSE.

## Third-Party Notices

Reference THIRD_PARTY_NOTICES.md if appropriate.

==================================================
README QUALITY REQUIREMENTS
==================================================

The README must:

- contain no emojis
- contain no fake claims
- contain no outdated architecture
- contain no references to removed web application
- contain no "GDPR compliant" claim unless genuinely justified
- contain no fake live demo
- contain no fake screenshots
- contain no fake badges
- contain no invented API endpoints
- contain no secrets
- contain no contradictory architecture statements

Use professional technical writing.

The README should be understandable to:
1. another developer joining the project
2. a professor/evaluator
3. a recruiter reviewing the GitHub repository

==================================================
PHASE 14 — FINAL VERIFICATION
==================================================

After all changes:

1. Run the full test suite.
2. Run lint/type checks if the repository already has them.
3. Verify the application imports successfully.
4. Verify FastAPI starts without unexpected schema mutation.
5. Verify all documented environment variables match actual code.
6. Verify README commands match actual repository behavior.
7. Verify every README endpoint actually exists.
8. Verify every claimed feature actually exists.
9. Search the repository for:
   - old React/web references
   - Firebase references
   - Firestore references
   - outdated endpoint names
   - duplicated migration SQL
   - hard-coded secrets
   - "GDPR compliant"
   - fake/demo URLs
10. Remove obsolete documentation only when it clearly refers to the old architecture.

Then perform ONE FINAL REVIEW from the perspective of a strict external reviewer:

"Could a developer clone this repository, configure Supabase, run the migration, start FastAPI, run the tests, and understand exactly how this backend fits into the MenoMate system?"

If the answer is no, fix the remaining documentation or implementation issues.

At the end, provide a concise report containing:

1. Files changed
2. Bugs/issues fixed
3. Security/auth changes
4. Database/migration changes
5. Prediction changes
6. AI/Care changes
7. README changes
8. Tests added/updated
9. Full test result
10. Remaining known limitations

Do not claim something is fixed unless you actually verified it.