## 🏢 Organization Architecture

Below is the high-level architecture of the **MenoMate** ecosystem, demonstrating how `menomate-web` sits alongside other repositories in the organization:

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
         ├─ Tailwind v4        ├─ Expo / BLE         ├─ PostgreSQL
         └─ Vite               └─ Native Modules     └─ LangChain/CrewAI
```

---
