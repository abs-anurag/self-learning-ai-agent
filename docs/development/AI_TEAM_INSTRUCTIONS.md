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

- Overall technical coordination
- FastAPI
- API routes
- Request validation
- Task creation
- Task lifecycle
- Run lifecycle
- Celery
- Redis integration
- Backend integration
- Docker Compose
- Infrastructure
- Environment configuration
- Deployment support
- GitHub/repository coordination

Primary branch:

`feature/backend-infra`

---

## Technical Member 2
### Agent Core + Memory + Database + Learning

Primary responsibilities:

- LangGraph
- Agent state
- Agent nodes
- Understanding
- Memory retrieval
- Planning
- Execution orchestration
- Observation
- Evaluation
- Reflection
- Replanning
- PostgreSQL
- pgvector
- LangGraph checkpoints
- Episodic experiences
- Candidate recipes
- Trusted recipes
- Recipe retrieval
- Recipe promotion
- Learning logic

Primary branch:

`feature/agent-memory`

---

## Technical Member 3
### Tools + Security + Frontend + Dashboard

Primary responsibilities:

- Calculator
- File reader
- Tavily integration
- Optional code executor
- Tool security
- React frontend
- Dashboard
- Task submission UI
- Run/timeline UI
- Learning visibility
- Frontend state
- API integration
- Client-side authentication handling

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

Expected repository structure:

self-learning-ai-agent/

├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── agent/
│   │   ├── core/
│   │   ├── db/
│   │   ├── events/
│   │   ├── learning/
│   │   ├── tools/
│   │   └── workers/
│   ├── tests/
│   └── alembic/
│
├── frontend/
│
├── scripts/
│
├── docs/
│   ├── architecture/
│   ├── api/
│   └── development/
│       └── AI_TEAM_INSTRUCTIONS.md
│
├── presentation/
│
├── README.md
├── BLUEPRINT.md
├── CONTRIBUTING.md
├── SECURITY.md
├── .env.example
└── .gitignore

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

`feature/backend-infra`

`feature/agent-memory`

`feature/tools-frontend`

The structure is:

main
│
├── feature/backend-infra
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