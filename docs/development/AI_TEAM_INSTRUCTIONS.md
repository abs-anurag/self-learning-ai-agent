# AI TEAM DEVELOPMENT INSTRUCTIONS
# Self-Learning AI Agent

Version: 1.0
Status: Team Standard

This document defines how AI coding assistants must work on the
Self-Learning AI Agent project.

Every AI coding assistant working on this repository MUST follow these
instructions.

The purpose of this document is to make multiple AI-assisted developers
work safely and consistently in the same repository without overwriting
each other's work or silently changing the architecture.

---

# 1. SOURCE OF TRUTH

Before making ANY code changes, the AI MUST read:

1. `BLUEPRINT.md`
2. `docs/development/AI_TEAM_INSTRUCTIONS.md`

Then the AI MUST:

3. Inspect the current repository structure.
4. Check the current Git branch.
5. Check `git status`.
6. Inspect relevant existing code.
7. Inspect relevant tests.
8. Understand dependencies between modules.
9. Identify exactly which files need to change.
10. Only then begin implementation.

`BLUEPRINT.md` is the primary source of truth for the technical
architecture.

This document is the source of truth for AI development behavior,
collaboration, Git practices, security discipline, and team boundaries.

If the requested task conflicts with `BLUEPRINT.md`, do NOT silently
change the architecture.

First explain:

- What conflicts.
- Why the conflict exists.
- What change is being proposed.
- What parts of the project could be affected.

Major architectural changes require team approval.

---

# 2. PROJECT GOAL

The project is a Self-Learning AI Agent.

The MVP must demonstrate that an AI agent can:

1. Receive a task.
2. Understand the task.
3. Retrieve relevant previously validated knowledge.
4. Plan a solution.
5. Execute tools.
6. Observe results.
7. Evaluate its performance.
8. Reflect when necessary.
9. Retry or replan when necessary.
10. Learn from successful experiences.
11. Store validated reusable task recipes.
12. Retrieve those recipes for future similar tasks.
13. Improve its performance on later similar tasks.

The central demonstration is:

FIRST SIMILAR TASK:

- Agent may require multiple iterations.
- Agent learns from the successful execution.
- A reusable recipe can be promoted.

SECOND SIMILAR TASK:

- Agent retrieves the trusted recipe.
- Agent uses the learned strategy.
- Agent succeeds with fewer iterations and/or tool calls.

The project must demonstrate measurable improvement.

---

# 3. TEAM STRUCTURE

The team has 5 members.

There are 3 technical members and 2 non-technical members.

The technical ownership is:

## Technical Member 1
### Team Lead + Backend API + Worker + Infrastructure

Primary responsibilities:

- Overall technical coordination & architecture integrity
- `backend/core/` (`config.py`, `logging.py`)
- `backend/api/` (`main.py`, `schemas.py`, `dependencies.py`, `security/`, `ws/`, `routes/`)
- `backend/worker/` (`celery_app.py`, `tasks.py`)
- `backend/events/` (`schema.py`, `service.py`, `publisher.py`)
- `backend/scripts/` (`create_demo_user.py`, `mark_stale_runs_failed.py`)
- Infrastructure: `docker-compose.yml`, `Makefile`, `.github/`, `infra/`
- Environment configuration & deployment support
- Tests: `tests/test_events_schema.py`, `tests/test_event_service.py`, `tests/test_api_auth.py`, `tests/test_graph_limits.py` (jointly with TM2)
- Docs: `docs/event-schema.md`, `docs/runbook.md`, `docs/api-reference.md`, `docs/known-limitations.md`

Primary branch:

`feature/backend-api`

---

## Technical Member 2
### Agent Core + Memory + Database + Learning

Primary responsibilities:

- LangGraph graph topology, `AgentState`, runtime, and checkpoint lifecycle
- `backend/agent/` (`graph.py`, `state.py`, `prompts.py`, `runtime.py`, `providers/`, `fixtures/`, `nodes/`)
- `backend/memory/` (`retriever.py`, `embeddings.py`, `experiences.py`)
- `backend/learning/` (`candidate.py`, `quality_gate.py`, `recipes.py`)
- `backend/evaluation/` (`scorer.py`, `metrics.py`)
- `backend/db/` (`models.py`, `session.py`, `migrations/`)
- PostgreSQL 15 & pgvector schema, indexes, and migrations
- Tests: `tests/test_graph_limits.py` (jointly with TM1), `tests/test_quality_gate.py`, `tests/test_learning_loop.py`
- Docs: `docs/architecture.md`

Primary branch:

`feature/agent-memory`

---

## Technical Member 3
### Tools + Security + Frontend + Dashboard

Primary responsibilities:

- `backend/tools/` (`registry.py`, `calculator.py`, `file_reader.py`, `web_search.py`, `code_executor.py`)
- Tool security, AST arithmetic sandboxing, path canonicalization
- `frontend/` (React 18, Vite, Tailwind CSS, Zustand store, mock event player, WebSocket subscribe-then-replay receiver)
- Client-side authentication & dashboard UI components
- Tests: `tests/test_calculator.py`, `tests/test_file_reader.py`, `tests/test_code_executor.py`
- Docs: `docs/security.md`

Primary branch:

`feature/tools-frontend`

---

## Non-Technical Member 1
### Documentation + Architecture + Presentation

Responsibilities:

- Documentation
- Architecture diagrams
- README support
- Project explanation
- PPT
- Technical presentation material
- Demo documentation
- Final report support

This member does not need a permanent Git branch unless they are
actively modifying repository files.

---

## Non-Technical Member 2
### Research + Testing Support + Demo + Presentation

Responsibilities:

- Research
- User testing
- Demo scenarios
- Test-case documentation
- Related-system research
- Feedback collection
- Demo preparation
- Presentation support
- Recording project results

This member does not need a permanent Git branch unless they are
actively modifying repository files.

---

# 4. TEAM OWNERSHIP RULE

Ownership means responsibility, NOT exclusive access.

A developer may need to modify another team's file for integration.

However:

- Do not rewrite another subsystem unnecessarily.
- Do not take over another member's work.
- Do not change interfaces without understanding their impact.
- Keep cross-team changes minimal.
- Inform the relevant teammate when a cross-module change is necessary.

The goal is collaboration, not territorial warfare conducted through Git.

---

# 5. REPOSITORY STRUCTURE

Expected repository structure (matching `BLUEPRINT.md` §19):

```text
self-learning-ai-agent/
├── README.md
├── BLUEPRINT.md
├── CONTRIBUTING.md
├── SECURITY.md
├── .env.example
├── .gitignore
├── docker-compose.yml
├── Makefile
├── .github/
│   └── workflows/
│       └── ci.yml
├── infra/
│   ├── postgres/
│   │   └── init.sql
│   └── redis/
│       └── redis.conf
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── core/
│   │   ├── config.py
│   │   └── logging.py
│   ├── agent/
│   │   ├── graph.py
│   │   ├── state.py
│   │   ├── prompts.py
│   │   ├── runtime.py
│   │   ├── providers/
│   │   │   ├── base.py
│   │   │   ├── anthropic.py
│   │   │   └── fixture.py
│   │   ├── fixtures/
│   │   │   ├── run_a_responses.json
│   │   │   └── run_b_responses.json
│   │   └── nodes/
│   │       ├── understand.py
│   │       ├── retrieve.py
│   │       ├── plan.py
│   │       ├── execute.py
│   │       ├── observe.py
│   │       ├── evaluate.py
│   │       ├── reflect.py
│   │       ├── replan.py
│   │       ├── learn.py
│   │       └── respond.py
│   ├── memory/
│   │   ├── retriever.py
│   │   ├── embeddings.py
│   │   └── experiences.py
│   ├── learning/
│   │   ├── candidate.py
│   │   ├── quality_gate.py
│   │   └── recipes.py
│   ├── evaluation/
│   │   ├── scorer.py
│   │   └── metrics.py
│   ├── tools/
│   │   ├── registry.py
│   │   ├── calculator.py
│   │   ├── file_reader.py
│   │   ├── web_search.py
│   │   └── code_executor.py
│   ├── events/
│   │   ├── schema.py
│   │   ├── service.py
│   │   └── publisher.py
│   ├── worker/
│   │   ├── celery_app.py
│   │   └── tasks.py
│   ├── api/
│   │   ├── main.py
│   │   ├── schemas.py
│   │   ├── dependencies.py
│   │   ├── security/
│   │   │   ├── auth.py
│   │   │   └── rate_limit.py
│   │   ├── ws/
│   │   │   └── manager.py
│   │   └── routes/
│   │       ├── tasks.py
│   │       ├── memory.py
│   │       ├── feedback.py
│   │       ├── metrics.py
│   │       ├── health.py
│   │       └── events.py
│   ├── scripts/
│   │   ├── create_demo_user.py
│   │   └── mark_stale_runs_failed.py
│   └── db/
│       ├── models.py
│       ├── session.py
│       └── migrations/
├── frontend/
│   ├── Dockerfile
│   ├── nginx.conf
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── App.jsx
│       ├── main.jsx
│       ├── api/
│       │   ├── http.js
│       │   └── ws.js
│       ├── mocks/
│       │   └── mockEventStream.js
│       ├── store/
│       │   └── agentStore.js
│       └── components/
│           ├── TaskInput.jsx
│           ├── ExecutionStatus.jsx
│           ├── SafeActivityFeed.jsx
│           ├── CurrentStep.jsx
│           ├── ToolsUsed.jsx
│           ├── EvaluationPanel.jsx
│           ├── LearningEvents.jsx
│           ├── TaskHistory.jsx
│           ├── RecipeBrowser.jsx
│           ├── MetricsDash.jsx
│           └── ErrorBanner.jsx
├── tests/
│   ├── conftest.py
│   ├── test_graph_limits.py
│   ├── test_calculator.py
│   ├── test_file_reader.py
│   ├── test_code_executor.py
│   ├── test_quality_gate.py
│   ├── test_events_schema.py
│   ├── test_event_service.py
│   ├── test_learning_loop.py
│   └── test_api_auth.py
└── docs/
    ├── architecture.md
    ├── api-reference.md
    ├── event-schema.md
    ├── security.md
    ├── runbook.md
    ├── known-limitations.md
    └── development/
        └── AI_TEAM_INSTRUCTIONS.md
```

Do not reorganize the repository without a clear reason.

---

# 6. TECHNOLOGY STACK

## Backend

- Python
- FastAPI
- LangGraph
- Celery
- Redis
- PostgreSQL 15
- pgvector
- Alembic

## Frontend

- React 18
- Vite
- Tailwind CSS
- Zustand

## AI

- Anthropic live provider
- Deterministic fixture provider for testing and demos

## Required Tools

- Calculator
- File reader
- Tavily

## Optional Stretch Feature

- Code executor

## Deployment

Docker Compose with:

- PostgreSQL
- Redis
- API
- Worker
- Frontend/Nginx

Do not introduce alternative frameworks unless the team explicitly
decides to do so.

---

# 7. GIT BRANCH STRATEGY

The stable branch is:

`main`

Technical branches:

`feature/backend-api`

`feature/agent-memory`

`feature/tools-frontend`

The structure is:

main
│
├── feature/backend-api
├── feature/agent-memory
└── feature/tools-frontend

Every feature branch should be created from the latest `main`.

Do NOT create a feature branch from another teammate's unfinished
feature branch unless the dependency is explicitly required.

---

# 8. GIT RULES

NEVER:

- Work directly on `main`.
- Force push.
- Delete another teammate's branch.
- Reset another teammate's work.
- Overwrite code without inspecting it.
- Rewrite history unnecessarily.
- Commit secrets.
- Commit `.env`.
- Disable tests to make them pass.
- Use destructive Git commands casually.

Before starting work:

```bash
git status
git branch
git pull origin main