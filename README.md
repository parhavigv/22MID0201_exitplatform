# Exit Process Platform

An internal employee offboarding platform with an AI assistant — **Exit Copilot** — built across the whole workflow.

An exiting employee sees exactly what still has to be done before their last working day. Managers approve knowledge transfer and clearances. HR sees every case, every bottleneck and every agent action. The platform is designed for a pilot with **real HR data**, so row-level security, an audit trail and human approval of AI actions are core requirements rather than afterthoughts.

---

## Table of contents

- [What it does](#what-it-does)
- [Architecture](#architecture)
- [Technology stack](#technology-stack)
- [Repository layout](#repository-layout)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [Demo accounts](#demo-accounts)
- [Database and seed data](#database-and-seed-data)
- [API surface](#api-surface)
- [Exit Copilot (AI agent)](#exit-copilot-ai-agent)
- [Policy RAG](#policy-rag)
- [Security model](#security-model)
- [Verification and utility scripts](#verification-and-utility-scripts)
- [Notes and known limitations](#notes-and-known-limitations)

---

## What it does

**For employees**

- Submit a resignation and follow a ten-stage exit timeline with SLAs
- See a personalised checklist of tasks grouped by stage
- Upload documents, record knowledge transfer (KT), nominate a successor, and complete an exit interview
- Ask Exit Copilot "what's left before my last day?" and get an answer grounded in their own case

**For managers**

- A "Needs you" inbox of documents to review, stages to sign off and overdue work
- Case detail, KT review, approval queue and reminders
- No ability to verify a leaver's own KT items — verification belongs to the manager or HR

**For HR**

- All cases, stage progress and completion percentages, SLA analytics
- Clearance queues for IT, finance and admin/assets
- Policy document management
- An approval queue for every action Exit Copilot proposes, plus a trace of agent runs and tool calls

**Background automation**

- A nightly sweep over active cases can draft escalations and compliance checks; it never executes them without a human decision

---

## Architecture

```
   Browser (React + Vite)
          │  /api (Vite proxy in dev)
          ▼
   FastAPI application
          │            ── JWT ──▶ Supabase Auth
          │
          ├─ RLS-bound Supabase client ──▶ Supabase Postgres / Storage / Realtime
          │
          ├─ LangGraph: supervisor ──▶ specialist workers ──▶ tool allow-list
          │        │                                             │
          │        │                          draft actions ──────┤
          │        │                                             ▼
          │        │                                     agent_actions
          │        │                                    (pending approval)
          │        └──▶ PostgresSaver checkpointer          │
          │                                                 ▼
          │                                          human approve/reject
          │                                                 │
          │                                                 ▼
          │                                        services/executor.py
          │
          ├─ APScheduler ──▶ nightly sweep ──▶ the same graph
          │
          └─ Portkey gateway (or direct Anthropic) ──▶ Claude + embeddings
```

Key properties:

- **One HTTP boundary.** `frontend/src/lib/api.ts` is the only place the UI talks to the backend. It can be backed by fixtures (`VITE_USE_MOCKS=true`) or the live API without changing any screen.
- **One request, one security context.** Every handler builds a Supabase client from the caller's JWT, so Postgres RLS enforces case visibility.
- **Agent writes are drafts.** Sensitive tools create `agent_actions` rows with `pending_approval`; only `services/executor.py` performs the real change after a human approves.
- **The graph is resumable.** A `PostgresSaver` checkpointer keeps a run paused on approval alive across backend restarts.

---

## Technology stack

| Layer | Choice |
| --- | --- |
| Frontend | React 19, Vite 8, TypeScript 6, Tailwind CSS 4, TanStack Query, React Router 7, Oxlint |
| Backend | Python 3.14, FastAPI, Pydantic, Uvicorn, APScheduler |
| AI | LangGraph 1.2, Anthropic SDK (Claude `claude-opus-5`), Portkey gateway, Pydantic-structured analysis |
| Database | Supabase Postgres with Auth, Storage, Realtime, `vector(1024)` (pgvector) |
| Embeddings | `text-embedding-3-small` via the Portkey gateway, 1024 dimensions |
| Testing / ops | Python verification scripts (schema, RLS, live API), migration runner, Vite build |

There is no Docker setup in this repository. The intended Windows dev flow uses a local Python virtualenv and `npm run dev`.

---

## Repository layout

```
.
├── backend/
│   ├── app/
│   │   ├── main.py              FastAPI app, CORS, router registration, scheduler lifespan
│   │   ├── config.py            pydantic-settings configuration
│   │   ├── deps.py              JWT -> ActorContext -> RLS-bound client; service_db()
│   │   ├── db.py                direct psycopg connection helpers
│   │   ├── routers/             health, me, cases, tasks, documents, workflow, inbox,
│   │   │                        clearance, notifications, progress, policy, analytics, agent
│   │   ├── services/            cases, documents, clearance, audit, executor, rag, email,
│   │   │                        letters, pdf, doc_check
│   │   ├── agent/
│   │   │   ├── graph.py         supervisor + workers graph, checkpointing
│   │   │   ├── llm.py           model calls, gateway fallbacks, structured output
│   │   │   ├── workers.py       specialist worker registry
│   │   │   ├── prompts.py       supervisor / worker prompts
│   │   │   ├── schemas.py       Pydantic output models
│   │   │   ├── state.py         agent state and context
│   │   │   └── tools/           reads.py, drafts.py, writes.py, base.py, registry
│   │   └── jobs/sweep.py        nightly autonomous sweep
│   ├── scripts/                 migrations, seeding, verification and diagnostics (25 scripts)
│   ├── data/policies/           9 markdown policy documents used for RAG
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── lib/                 api.ts (mock/live switch), supabase.ts, types.ts,
│   │   │                        mock.ts, format.ts, useLiveSync.ts
│   │   ├── auth/                AuthProvider, RequireRole
│   │   ├── components/          AppShell, StageTrack, AgentChat, NotificationBell,
│   │   │                        ReminderComposer, StageOverride, SuccessorPicker, ui
│   │   └── pages/               18 screens (sign-in, case list/detail, needs-you,
│   │                            progress, analytics, policy docs, clearance queue,
│   │                            approval queue, agent trace, manager home, and
│   │                            employee pages)
│   ├── public/                  favicon and icon sprite
│   └── package.json
├── supabase/
│   ├── migrations/              14 numbered SQL migrations
│   └── seed.sql                 stages, document types, task templates, demo employees
├── CLAUDE.md                    original design/planning document (see note below)
├── start.bat                    Windows one-click launcher
└── README.md                    this file
```

---

## Getting started

### Prerequisites

- **Node.js** with npm (a current LTS release) for the frontend
- **Python 3.14** for the backend (all pinned wheels in `backend/requirements.txt` target 3.14)
- A **Supabase project** with the connection details below, if you want live data instead of mocks
- Optional: access to a **Portkey gateway** (or a direct Anthropic API key) for Exit Copilot

### Windows quick start

The repository includes `start.bat`. It applies migrations with seed data, starts the backend on port 8000 and the frontend on port 5173 in minimised windows, then opens `http://localhost:5173`.

> This script assumes `backend/.venv` already exists and `backend/.env` is configured.

### Manual start

Backend:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env          # fill in your Supabase / LLM values
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Frontend:

```powershell
cd frontend
npm install
copy .env.example .env          # VITE_USE_MOCKS=false to use the live backend
npm run dev                     # http://localhost:5173
```

Useful frontend commands:

```powershell
npm run build                   # tsc -b && vite build
npm run lint
npm run preview
```

The backend can boot without a Supabase project; `/health` then reports `database_configured: false`. The frontend defaults to mocks, so all screens are browsable before any infrastructure exists.

---

## Configuration

Copy the example files and fill in the values you need. **Never commit `.env` files** — they are ignored by Git; only `.env.example` templates are tracked.

### `backend/.env`

| Variable | Purpose |
| --- | --- |
| `SUPABASE_URL`, `SUPABASE_ANON_KEY` | Project URL and public anon key; requests obey RLS |
| `SUPABASE_SERVICE_KEY` | RLS bypass, used only by the executor, sweep job and audit writes |
| `SUPABASE_JWT_SECRET` | Only for projects using legacy HS256 signing; otherwise JWKS is used |
| `DATABASE_URL` | Session-pooler Postgres connection, used by the migration runner and LangGraph checkpointer |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `ANTHROPIC_BASE_URL` | Direct Anthropic setup (or gateway via ANTHROPIC_* names) |
| `PORTKEY_API_KEY`, `PORTKEY_BASE_URL`, `PORTKEY_MODEL` | Gateway setup used by this deployment; takes priority over the ANTHROPIC_* values |
| `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS` | Embedding model slug and vector width (default 1024) |
| `SWEEP_ENABLED`, `SWEEP_HOUR`, `SWEEP_MINUTE` | Nightly sweep toggle and schedule (default 02:00) |
| `CORS_ORIGINS`, `ENVIRONMENT` | Allowed browser origins and deployment label |

### `frontend/.env`

| Variable | Purpose |
| --- | --- |
| `VITE_USE_MOCKS` | `true` (default) serves fixtures from `src/lib/mock.ts`; `false` calls the live API |
| `VITE_API_BASE` | API base path, default `/api` |
| `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` | Client-side Supabase Auth; the anon key is public by design |

`backend/scripts/sync_frontend_env.py` copies the URL and anon key into `frontend/.env` and never copies the service key.

---

## Demo accounts

The seed data creates ten demo users. All share the password `ExitDemo!2026`:

| Role | Email |
| --- | --- |
| Employee | `kirthana.mekala@example.com` |
| Manager | `arjun.menon@example.com` |
| HR | `priya.nair@example.com` |

These are demo credentials. Replace them before using the platform with real employee data.

---

## Database and seed data

`supabase/migrations/` contains 14 ordered SQL migrations. `supabase/seed.sql` seeds the ten exit stages, eight document types, 24 task templates and the demo employees.

Apply everything from the backend directory:

```powershell
.\.venv\Scripts\python.exe scripts/apply_migrations.py --seed
.\.venv\Scripts\python.exe scripts/apply_migrations.py --status
```

Migrations are tracked in `schema_migrations` and are safe to re-run. Applied migration files are treated as immutable: if you need to change something, add a new numbered migration rather than editing an old one.

The main tables cover:

- People and cases: `employees`, `exit_cases`, `case_tasks`, `documents`, `approvals`
- Knowledge transfer and interviews: `kt_records`, `kt_items`, `exit_interviews`
- Clearance: assets, system access and settlement items
- Agent: `agent_runs`, `agent_actions` (with token usage, tool traces, decisions and outcomes)
- Platform: `notifications`, `audit_log`, `policy_docs`, `policy_chunks`

Nothing has a DELETE policy. Cases are cancelled and employees are deactivated rather than erased, so the audit trail remains meaningful.

---

## API surface

All routes except `/health` are mounted under `/api`.

| Router | What it covers |
| --- | --- |
| `health` | Service and configuration status |
| `me` | Session, role and the caller's own exit case; employee directory |
| `cases` | Case list/detail, creation, certificate, tasks and documents |
| `tasks` | Task status updates, reminder drafts and sending reminders |
| `documents` | Upload, inline documents, generated documents, review and signed URLs |
| `workflow` | Stage approvals, KT records/items, exit interviews, recent approvals |
| `inbox` | "Needs you" aggregation |
| `clearance` | IT/finance/admin clearance queue and item updates |
| `notifications` | List and mark as read |
| `progress` | Per-case completion and stage breakdown |
| `policy` | List, read, upload and delete policy documents |
| `analytics` | Dashboard metrics |
| `agent` | SSE chat, agent runs, action queue, approve/reject, sweep summary |

A full route listing is available from FastAPI at `http://localhost:8000/docs` once the backend is running.

---

## Exit Copilot (AI agent)

The agent uses a **supervisor + specialist workers** design implemented with LangGraph:

- `load_context` resolves the caller, case and role
- The supervisor chooses `route_to_agent` for a specialist worker or `finish` when done
- Workers run through one `worker_node` function with their own prompt and tool subset
- `tool_node` validates tool names against the active worker's allow-list before executing
- `finalize` writes run metadata (tokens, tool trace, worker history) to `agent_runs`
- An iteration cap prevents runaway routing

Workers cover case FAQ, checklists, document collection, KT review, risk assessment, compliance, interview summaries and trends, SLA escalation, clearance, deprovisioning, settlement, analytics and other specialist tasks.

Tools are grouped as:

- **Read** (execute immediately): `get_exit_case`, `list_cases`, `get_checklist`, `search_policy_docs`, `get_dashboard_metrics`, `get_employee_profile`, `analyse_exit_interviews`
- **Draft** (require human approval): `generate_exit_checklist`, `draft_notification`, `draft_escalation`, `review_kt_document`, `assess_exit_risk`, `verify_compliance`, `summarize_exit_interview`, `request_document`, `flag_policy_breach`
- **Write** (allow-listed transitions only): `update_task_status`

The nightly sweep (`jobs/sweep.py`, started by APScheduler) calls the same graph with a sweep seed message, restricts itself to escalation and compliance workers, and caps the number of drafted actions per run. Everything it produces lands in the normal approval queue.

---

## Policy RAG

Nine markdown policy documents live in `backend/data/policies/` (notice period, asset return, NDA, IT clearance, final settlement, exit interview, resignation, KT and process overview).

`services/rag.py` handles ingestion:

- Heading-aware chunking with a soft cap of roughly 800 tokens and 100 tokens of overlap
- Embeddings via the Portkey gateway, 1024 dimensions to match `policy_chunks.embedding vector(1024)`
- Idempotent by `(title, version)`: re-ingesting a document replaces its chunks
- `search_policy_docs` lets the agent answer with the source document and version rather than guessing

```powershell
.\.venv\Scripts\python.exe scripts/ingest_policies.py
```

---

## Security model

These rules are enforced in code and in the database:

1. **RLS-bound reads.** Agent tools and request handlers query through a Supabase client built from the caller's JWT. The model cannot read a case the human could not read.
2. **Draft, then approve.** Sensitive tools never act directly; they write a pending `agent_actions` row. A human approves or edits it, and `services/executor.py` performs the effect.
3. **Untrusted content is wrapped.** Document and exit-interview text is treated as untrusted input and marked as such in tool results to resist prompt injection.
4. **Audit everything.** Every state change writes an `audit_log` row with an actor type of `human` or `agent`.
5. **Tool allow-lists.** Workers may only call the tools in their registry entry; unknown or out-of-remit calls are refused.
6. **Service role is rare.** `service_db()` is used only by the executor, sweep and audit paths — never as a general request dependency.
7. **No AI in the critical path.** The manual workflow works with the agent disabled.

Row-level security scopes employees to their own cases, managers to their direct reports, and HR to all rows.

---

## Verification and utility scripts

`backend/scripts/` contains 25 scripts. The most useful ones:

| Script | Purpose |
| --- | --- |
| `apply_migrations.py` | Apply SQL migrations in order, optionally with seed data; `--status` shows state |
| `verify_schema.py` | Check tables, extensions, RLS coverage, policies and seeded rows |
| `verify_rls.py` | Sign in as seeded users and assert cross-role isolation |
| `verify_api.py` | Drive the running API over HTTP with real tokens |
| `agent_smoke_test.py` | Smoke-test the agent path |
| `run_sweep.py` | Run one nightly sweep manually |
| `ingest_policies.py` | Chunk and embed policy documents |
| `sync_frontend_env.py` | Copy safe Supabase values into `frontend/.env` |
| `discover_gateway.py`, `probe_gateway.py` | Diagnose the LLM gateway and model slug |
| `check_env.py`, `fix_dsn.py` | Diagnose and repair `DATABASE_URL` without printing the password |
| `check_frontend_routes.py` | Compare frontend route references with the API |

Run schema/RLS verification after any policy change and API verification after endpoint changes.

---

## Notes and known limitations

- **`CLAUDE.md` is the original planning document.** Parts of it are now out of date: it describes a single agent and marks several phases as unstarted, while the code implements a supervisor with specialist workers, RAG, sweeps and an approval queue. Treat this README and the source as the current description.
- **The SQL has to be applied to a real Supabase project.** Until then the API runs in a degraded mode with `/health` reporting `database_configured: false`.
- **Email is in-app only by default.** `LogSender` records messages without delivering them; `SMTPSender` exists but needs a company relay configuration.
- **The LLM gateway controls the available model slugs.** If the configured model is rejected, `llm.py` raises a clear `LLMConfigError` and degrades optional call parameters gracefully; the fix is to allow-list the correct slug, not to change the model code.
- **Migrations are immutable**, and the platform uses deactivation/cancellation instead of deletion so the audit trail stays intact.

---

*Internal project — handle real employee data according to your organisation's retention and access policies.*
