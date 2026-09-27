# Study Intelligence Platform

Turns unstructured educational material into structured study intelligence,
manageable work packages and an executable study plan.

**This is a study planning and workload management system.** It is not a chatbot
and not a generic AI assistant.

---

## The hard rule: no LLM plans anything

This is the single most important design decision in the codebase.

| Concern | Who decides it |
|---|---|
| Text extraction (PDF/DOCX/TXT) | PyMuPDF / python-docx / native |
| Heading, module and topic detection | Deterministic heuristics |
| **Difficulty (easy/medium/hard)** | **Deterministic scoring** |
| **Time estimation** | **Deterministic formula** |
| **Work package grouping (90 min cap)** | **Deterministic packing** |
| **Priority scoring and scheduling** | **Deterministic planner** |
| **Work distribution across a team** | **Deterministic bin-packing** |
| Content structuring (better topic names, objectives) | *Optionally* Gemini or a self-hosted model |

The LLM may only reorganise and enrich *content*. Its output never feeds
difficulty, time estimates, scheduling or workload splits. That is enforced in
`app/engine/knowledge.py::merge_llm_result`, which discards any time or
difficulty value the model returns and recomputes them locally.

Consequence: with no API key configured, the platform works fully offline, and
re-running analysis produces byte-identical plans.

---

## Quick start (Windows)

Double-click **`run-local.bat`**, or from a terminal:

```
run-local.bat
```

It checks prerequisites, installs dependencies on first run, starts both
servers in separate windows, and opens the app in your browser.

- Web app: <http://localhost:5173>
- API docs: <http://127.0.0.1:8000/docs>

Other launchers:

| File | What it does |
|---|---|
| `run-local.bat` | Both API and UI (start here) |
| `run-api.bat` | API only, on port 8000 |
| `run-ui.bat` | Frontend only, on port 5173 |
| `check.bat` | Full quality gate: tests, lint, types, build |

### Prerequisites

- [uv](https://docs.astral.sh/uv/) — `pip install uv`
- [Node.js LTS](https://nodejs.org/) (20.19+)

### Manual start

```bash
# API
cd backend
uv sync --extra dev
uv run uvicorn app.main:app --reload --port 8000

# UI (second terminal)
cd frontend
npm install
npm run dev
```

On first run the backend database is created automatically and
`backend/.env` is copied from `.env.example`.

---

## Configuration

Everything has a working default. To customise, edit `backend/.env`:

```ini
# Required in production. run-local.bat generates this automatically.
# Minimum 32 bytes (RFC 7518 s3.2); the app REFUSES TO START in production
# with a short or placeholder value.
SECRET_KEY=change-me-in-production

# SQLite now, PostgreSQL later:
# DATABASE_URL=postgresql+psycopg://user:pass@localhost/study
DATABASE_URL=sqlite:///./study_intelligence.db

# Optional Phase 1. Blank = fully offline structural analysis.
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.0-flash

# Optional Phase 2: self-hosted structured generation (llama.cpp / vLLM / Ollama,
# OpenAI-compatible /v1/chat/completions). Used for content structuring only.
LOCAL_LLM_URL=
LOCAL_LLM_MODEL=qwen2.5-0.5b-instruct

CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
MAX_UPLOAD_MB=25
```

`SECRET_KEY` signs every JWT the service issues, so it is validated on startup:
under 32 bytes logs a loud warning in development and **raises in production**.
Roll your own any time with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

`GET /api/health` reports which provider is active and restates the planner
rules, so you can always confirm the model is not planning anything:

```json
{
  "llm_provider": "none",
  "planner_rules": {
    "max_daily_minutes": 240,
    "block_minutes": [10, 30],
    "break_minutes_after_blocks": 10,
    "max_package_minutes": 90,
    "llm_used": false
  }
}
```

---

## Architecture

```text
React + TypeScript + Tailwind
        |
        v
     FastAPI
        |
        +--> Study Intelligence Engine      --> work packages
        |      extraction -> knowledge -> difficulty -> time -> packages -> splits
        |
        +--> Planner Engine                --> study plan
               rules -> priority -> scheduler -> adaptive replanning
```

The engines (`app/engine`, `app/planner`) import no SQLAlchemy and no FastAPI.
They take plain dataclasses and return plain dataclasses, which is what makes
them directly unit-testable and fully deterministic.

```text
backend/
  app/
    core/           config, enums, password hashing, JWT
    db/             SQLAlchemy models + session
    schemas/        Pydantic request/response contracts
    api/
      routes/       auth, subjects, planner, progress, teams
      services.py   orchestration; the only place engines meet the database
    engine/         STUDY INTELLIGENCE ENGINE (deterministic + optional LLM)
      extraction/   PDF / DOCX / TXT
      heuristics.py heading, module and concept detection
      estimation.py difficulty scoring and time estimation
      knowledge.py  the pipeline, and the LLM trust boundary
      packages.py   90-minute work packages, 10-30 minute units
      splits.py     five distribution strategies
      team_intel.py knowledge matrix, expert/learner ranking
      llm.py        Gemini + self-hosted gateway
    planner/        PLANNER ENGINE (deterministic, no LLM anywhere)
      rules.py      hard limits and the priority formula
      scheduler.py  two-pass packing into days
      adaptive.py   behind / ahead / availability-changed replanning
  tests/            73 tests: engines, planner rules, full API flows
```

---

## How the engines work

### Study Intelligence Engine

1. **Extract.** PyMuPDF, python-docx or a native reader. Text is normalised
   (ligatures, typographic quotes, whitespace). Scanned PDFs are rejected with
   a clear message rather than silently producing nothing.
2. **Structure.** Headings are detected with a verb-marker guard so that
   `"Algorithm: the scheduler must minimise waiting time"` is not mistaken for a
   title and split a chapter in half. Container headings (`Unit 3`, a bare
   subject name above a heading) become modules rather than topics.
3. **Mine.** Definitions, procedures, formulas, important facts, keywords,
   learning objectives, subtopics and concepts per topic.
4. **Score.** Difficulty is a weighted sum of eight density signals (volume,
   formal language, mathematical load, practice demand, structure, syntax,
   vocabulary, and combinations), all measured **per 100 words** so a short dense
   section is not scored as easier than a long thin one. Declared knowledge level
   scales the result.
5. **Estimate.** Time is driven by *comprehension* cost, not reading speed —
   skimming 1000 words takes six minutes, understanding and noting them takes
   half an hour.
6. **Package.** Greedy module-aware packing to a 90-minute cap, split into
   10–30 minute units, with learn and practice units plus revision mirrors.
7. **Optionally enrich.** If a provider is configured, Gemini restructures the
   content; deterministic scoring is then re-applied from scratch.

### Planner Engine

Two deterministic passes:

1. **Learn pass.** Every unit is scored by the priority formula (deadline
   proximity, knowledge gap, existing mastery, importance, study mode). Units
   pack into each day up to its budget, honouring prerequisites, with a
   10-minute break after every two blocks. Units longer than 30 minutes are
   split across days and resumed.
2. **Revision pass.** Each completed learn block queues spaced revisions at
   `+1/+3/+7` days when cramming, or `+3/+10/+21` when following college pace,
   compressed as the exam approaches. Revisions compete for leftover capacity
   on the same priority formula.

Hard limits enforced and tested: 240 min/day, 10–30 min blocks, 10 min break
every two blocks, 90 min package cap, and nothing scheduled after the exam date
in fast-exam mode.

### Adaptive replanning

Compares planned vs completed minutes and reports one of `on_track`, `behind`,
`ahead`, `availability_changed` or `complete`, with concrete suggested changes.
Lowering your daily budget re-plans the future while preserving completed
history.

### Team intelligence

Five deterministic distribution strategies — topic (whole modules), difficulty
(balanced bands), time (levelled minutes), teaching (suggested presenters) and
revision (ownership separated from learning). Then a Topic × Member knowledge
matrix and peer-teaching recommendations.

**Recommendations only.** Nothing is ever assigned automatically; a team lead
must explicitly accept a suggestion.

---

## Quality

```
backend   ruff format/check · mypy · 73 pytest tests
frontend  tsc --noEmit · eslint · vite production build
```

Run everything with `check.bat`. The test suite covers the spec's stated limits
as executable assertions, e.g.:

- no package exceeds 90 minutes
- every study block is 10–30 minutes
- a break follows every two study blocks
- no day exceeds the daily budget
- nothing is scheduled past the exam in fast-exam mode
- scheduling is byte-identical across runs with no model configured
- the LLM's time and difficulty values are discarded

---

## API

Full interactive docs at `/docs`. Key routes:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/auth/register`, `/api/auth/login` | Accounts |
| `GET/POST` | `/api/subjects` | List / create subjects |
| `POST` | `/api/subjects/{id}/documents` | Upload PDF / DOCX / TXT |
| `POST` | `/api/subjects/{id}/analyze` | Extract study intelligence |
| `GET` | `/api/subjects/{id}/analysis` | Everything the Analysis screen needs |
| `GET/POST` | `/api/subjects/{id}/packages` | Work packages (90 min cap) |
| `GET/POST` | `/api/subjects/{id}/plan` | Study plan (deterministic) |
| `GET` | `/api/subjects/{id}/plan/week` | Weekly summary |
| `GET` | `/api/subjects/{id}/plan/adaptive` | Behind / ahead review |
| `PATCH` | `/api/blocks/{id}` | Log a block as done / partial / missed |
| `POST` | `/api/progress` | Log a topic event |
| `GET` | `/api/dashboard` | Dashboard projection |
| `GET/POST` | `/api/teams`, `/api/teams/join` | Teams |
| `GET` | `/api/subjects/{id}/split` | Five distribution suggestions |
| `POST` | `/api/subjects/{id}/split/apply` | Accept a suggestion |
| `GET` | `/api/subjects/{id}/matrix` | Knowledge matrix |
| `GET` | `/api/subjects/{id}/peers` | Peer teaching recommendations |

---

## Screens

| Route | Screen |
|---|---|
| `/` | Landing |
| `/login`, `/register` | Authentication |
| `/dashboard` | Subjects, today's blocks, progress, deadlines, plans |
| `/subjects/new` | Subject creation: knowledge level 1–5, exam date, study mode, availability, rest days, team |
| `/upload` | Drag-and-drop upload centre |
| `/subjects/:id` | Subject overview |
| `/subjects/:id/analysis` | Topics, difficulty, time estimates, feasibility, work packages |
| `/subjects/:id/planner` | Daily blocks, weekly summary, availability, adaptive review |
| `/team` | Teams, distribution suggestions, knowledge matrix, peer teaching |

---

## Data model

SQLite today, PostgreSQL later — change `DATABASE_URL` and the models are
portable.

`users`, `teams`, `team_members`, `subjects`, `documents`, `study_intelligence`,
`topics`, `work_packages`, `study_units`, `study_plans`, `study_blocks`,
`study_sessions`, `progress_records`, `topic_ownership`, `peer_signals`.

Enum columns use a value-storing SQLAlchemy `Enum`, so rows round-trip back into
Python enums and `subject.knowledge_level.rank` works after a commit.

---

## Known limitations

- **Scanned PDFs are not supported.** There is no OCR pass; such uploads are
  rejected with an explanatory message rather than producing empty output.
- **No OCR, no video, no slides.** PDF, DOCX and TXT only.
- **Difficulty and time are heuristics**, tuned and unit-tested against
  representative material, not a learning model. They are stable and
  explainable, not perfect.
- **A second upload re-analyses the whole subject.** Concatenated documents are
  analysed together, so a module boundary between two files is inferred rather
  than declared.
- **Adaptive replanning advises, it does not auto-apply.** Accepting a change is
  an explicit action.
- **One active plan per subject.** Regenerating replaces the future while
  preserving completed history.
