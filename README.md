# LLD Practice Platform

A small end-to-end prototype: pick an LLD problem, write a text design,
submit it, get structured rubric-based feedback (deterministic checks +
AI), and review your attempt history.

See `RESEARCH_NOTE.md` for the problem/market research and
`DESIGN_NOTE.md` for the MVP scope, domain model, and design rationale.

## Requirements

- Python 3.11+
- An Anthropic API key (for AI-evaluated feedback). Without one, problem
  browsing / submission / history all still work, but evaluations will
  end up `FAILED` with an auth error from the evaluator.

## Setup

```bash
cd lld-practice
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY=sk-ant-...
```

## Run

```bash
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 — the app serves both the API and the
frontend from the same process. The database (`lld_practice.db`, SQLite)
and the 3 seed problems are created automatically on first startup.

## Run tests

```bash
pytest -v
```

Tests use an isolated in-memory SQLite DB and a fake Evaluator (no real
API calls, no network needed, no API key required).

## Project structure

```
app/
  main.py                       FastAPI app, startup/seed, static mount
  database.py                   SQLAlchemy engine/session
  schemas.py                    Pydantic request/response models
  seed.py                       The 3 fixed practice problems
  models/domain.py              Problem, Attempt, Submission, Evaluation, FeedbackItem
  services/rubric.py            Fixed rubric criteria (single source of truth)
  services/evaluator.py         Evaluator interface + deterministic checks + AIRubricEvaluator
  services/evaluation_service.py  Evaluation state machine orchestration
  routers/problems.py           GET /api/problems, /api/problems/{id}
  routers/attempts.py           Start attempt, submit, get evaluation
  routers/history.py            GET /api/history
  static/index.html             Minimal frontend (no build step)
tests/                          pytest suite (deterministic checks, AI parsing, state machine, full API flow)
DESIGN_NOTE.md                  MVP scope, domain model, extensibility, trade-offs
RESEARCH_NOTE.md                Learner problem, existing tools, gaps, product direction
AI_USAGE.md                     AI-assisted decisions during this project
```

## API overview

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/problems` | List the 3 seeded problems |
| GET | `/api/problems/{id}` | Get one problem |
| POST | `/api/attempts` | Start an attempt (`{problem_id}`) |
| POST | `/api/attempts/{id}/submissions` | Submit a design (`{content}`) — creates a new versioned Submission and kicks off async evaluation |
| GET | `/api/attempts/{id}/submissions` | List submissions on an attempt |
| GET | `/api/attempts/{id}/submissions/{sub_id}/evaluation` | Poll evaluation status/result |
| GET | `/api/history` | All attempts with latest submission + evaluation |

## Known limitations

See DESIGN_NOTE.md §8 — single demo learner (no auth), text-only
submissions, no admin UI for editing problems/rubric, no automatic retry
on AI evaluator failure, no cross-attempt trend analysis yet.
