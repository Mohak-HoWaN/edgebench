# Phase 1: Scaffold, database, health, frontend shell

**Goal:** an app that starts with one command, shows a themed shell with every page reachable (empty states), and has a tested
backend skeleton the later phases add to.

## Build
- Repo layout: `server/` (FastAPI, SQLModel, Alembic), `agent/` (empty package with `__init__` only, no stub code), `web/` (Vite),
  `data/` (git-ignored: `edgebench.db`, `artifacts/`), `docs/`, `docker-compose.yml`, `.env.example`, `STATE.md`, `CLAUDE.md`.
- Server: `/api/health` (version, DB ok, queue ok, disk free), settings via Pydantic, structured JSON logging, SQLite in WAL mode,
  first Alembic migration with the tables needed so far (`models`, `datasets`, `devices`, `experiments`, `runs`, `jobs`, `artifacts`
  as empty-but-real tables; add columns in the phase that uses them, via new migrations).
- SQLite-backed queue: `jobs` table with state, attempts, `cancel_requested`, heartbeat; a worker loop claims with an atomic
  `UPDATE ... WHERE state='queued'`; resume on restart (jobs left `running` with a stale heartbeat go back to `queued`).
  Test cancel, retry and crash-resume with a dummy job type that exists only in the tests.
- WebSocket `/ws/events` that broadcasts job progress and log lines (used by Phases 2 to 5).
- Server binds `127.0.0.1` by default; LAN binding is an explicit setting (Phase 5 turns it on with tokens).
- Web: Vite + React + TS strict, Tailwind, shadcn/ui, TanStack Query, Zustand (theme, sidebar), router with code-split pages
  (Dashboard, Models, Datasets, Devices, New Experiment, Live Run, Results, Reports, Settings), command palette (Ctrl/Cmd+K),
  dark/light/system theme, toasts, confirm dialog, skeleton loaders, empty states with a call to action, keyboard shortcuts.
  Colour tokens defined once (needed by Phase 6 charts).
- `docker-compose.yml`: `server` + `web` only. The PC agent is **not** in compose (see README rule 3).
- Ruff, mypy (strict-ish), ESLint, Prettier, pytest, Playwright configs wired; one smoke test per layer.

## Acceptance
```
docker compose up --build      # then http://localhost:8080 loads, /api/health returns ok
cd server && pytest -q && ruff check . && mypy .
cd web && npm run typecheck && npm run lint && npm run build
npx playwright test            # opens the app, toggles theme, visits every page, sees its empty state
```
Plus: kill the server mid-job, restart, and the job resumes; Lighthouse accessibility >= 95 on the shell; contrast checked in both
themes (WCAG AA).

## Skills
`init` (CLAUDE.md), `frontend-design` (tokens and direction first), `update-config` + `fewer-permission-prompts` (allowlist),
`run` + `claude-in-chrome` (look at it), `security-review` (CORS, bind address), `simplify`, `code-review`. `/ponytail lite` for the
shell UI.

## Not in this phase
Models, conversion, datasets, agents, charts. No placeholder pages that pretend to work: pages show an honest empty state.

## Risks
Node 26 package compatibility (found in Phase 0). Docker volume paths on Windows for `data/`: use a bind mount under the repo.
