# Exit Process Platform

Internal employee offboarding platform. An exiting employee sees exactly what they must complete before their last working day; managers approve KT and clearances; HR sees every case and every bottleneck. A single AI agent ("Exit Copilot") sits across all of it.

**Target: internal pilot with real employee data.** RLS, audit trail, and retention are first-class requirements, not polish.

---

## Stack

| Layer | Choice |
|---|---|
| Frontend | React 18 + Vite + TypeScript, TailwindCSS, shadcn/ui, TanStack Query, React Router |
| Backend | Python 3.12, FastAPI, LangGraph |
| LLM | `claude-opus-5` via the official `anthropic` Python SDK |
| Database | Supabase Postgres + Auth + Storage + pgvector + Realtime |
| Embeddings | Voyage AI `voyage-3-large` (1024-dim); fallback `bge-m3` locally |
| Scheduler | APScheduler (pilot) → `pg_cron` (prod) |

### Environment status

- Node **v24.19.0** / npm 11.17.0, installed via winget as a portable package. It is on the **user** PATH but shells launched before the install will not see it. If `node` is not found, prefix with:
  `$env:Path = "C:\Users\Kirthana.mekala\AppData\Local\Microsoft\WinGet\Packages\OpenJS.NodeJS.LTS_Microsoft.Winget.Source_8wekyb3d8bbwe\node-v24.19.0-win-x64;$env:Path"`
- **Python 3.14.6** is the only version installed, so the backend targets 3.14, not the 3.12 in the original plan. Every dependency — FastAPI, supabase-py, LangGraph 1.2.11, anthropic 1.6.0 — resolves to a native cp314 wheel. venv at `backend/.venv`.
- No Docker, no `psql`, no Supabase CLI on this machine. **The SQL in `supabase/` has never been executed.** Treat it as unverified until someone runs it.
- No Supabase project yet. The backend boots without one and serves `/health` with `database_configured: false`.

### Running the backend

```
cd backend
.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

Vite proxies `/api` to port 8000 in dev.

### Database scripts (`backend/scripts/`)

| Script | Purpose |
|---|---|
| `apply_migrations.py` | Applies `supabase/migrations/*.sql` in order, tracked in `schema_migrations`. `--seed` also runs `seed.sql`. `--status` lists state. Re-running is safe |
| `verify_schema.py` | Structural check: tables, extensions, RLS coverage, policy counts, seeded row counts |
| `verify_rls.py` | **The important one.** Signs in as real seeded users and asserts isolation. Run after any policy change |
| `verify_api.py` | End-to-end: signs in for real and drives the running API over HTTP. Needs the backend on :8000 |
| `sync_frontend_env.py` | Writes `frontend/.env` from `backend/.env` — URL + anon key only, never the service key. `--mocks` to switch back to fixtures |
| `check_env.py` / `fix_dsn.py` | Diagnose and repair `DATABASE_URL` without printing the password |

Migrations are immutable — the runner warns if an applied file changed. Fix a
mistake with a new numbered migration, never by editing an old one.

**Demo logins** — all 10 seeded users share the password `ExitDemo!2026`:
`kirthana.mekala@example.com` (employee), `arjun.menon@example.com` (manager),
`priya.nair@example.com` (HR).

### Running the frontend

```
cd frontend
npm run dev     # http://localhost:5173
npm run build   # tsc -b && vite build
```

`VITE_USE_MOCKS` defaults to true. Every screen is served from `src/lib/mock.ts`; set it to `false` once the backend is up. The sign-in screen is a role picker while mocks are on — Kirthana Mekala (employee) has a live case mid-notice-period with two overdue tasks.

Note: `tsconfig.app.json` sets `erasableSyntaxOnly`, so **constructor parameter properties are a compile error**. Declare and assign fields explicitly.

---

## Non-negotiable rules

These exist because this system holds real HR data. Do not relax them without an explicit decision.

1. **Every agent tool queries through an RLS-bound Supabase client built from the caller's JWT.** Never the service-role key inside a tool. The model must not be able to read a case the human couldn't read.
2. **Sensitive tools never act — they draft.** They write `agent_actions` with `status='pending_approval'` and return a draft id. A human approves; `services/executor.py` performs the real effect.
3. **Document and exit-interview text is untrusted input.** Wrap it in `<untrusted_content>` in tool results. The exiting employee writes it and has a motive to influence their own clearance.
4. **Every state change writes an `audit_log` row** with `actor_type` of `human` or `agent`.
5. **One agent, not many.** One LangGraph graph, one system prompt, one tool belt. New capabilities become tools, never new agents.
6. **No AI in the critical path.** The platform must remain fully usable by hand if the agent is disabled.

---

## Architecture

### Agent graph

```
chat request ─┐
              ├─▶ load_context ─▶ agent(claude-opus-5) ⇄ tool_node
cron sweep ───┘                          │                  ▲
                                         │            approval_gate
                                         │            (interrupt())
                                         ▼
                                      finalize
```

Two entry points, **one graph**: conversational (SSE to a dashboard) and autonomous (nightly sweep). They differ only in the seed message and actor context.

`PostgresSaver` checkpointer on Supabase — a run paused waiting for a manager's approval must survive a backend restart.

### Model call shape

```python
client.messages.create(
    model="claude-opus-5",
    max_tokens=16000,
    thinking={"type": "adaptive"},
    output_config={"effort": "high"},   # xhigh: risk/compliance. low: routine chat
    betas=["server-side-fallback-2026-07-01"],
    fallbacks="default",
    system=[...],                        # cache breakpoint here
    tools=TOOLS,
    messages=messages,
)
```

Build the LLM node on the `anthropic` SDK directly — a LangGraph node is just a function and does not need a LangChain model object. Analysis tools use `client.messages.parse()` with Pydantic models so results are DB-writable.

Cache order is `tools` → `system` → `messages`. Stable prompt first, per-request case JSON after. If `usage.cache_read_input_tokens` is 0 across repeat calls, something volatile leaked into the prefix.

### Tools

Read (execute immediately): `get_exit_case`, `list_cases`, `get_checklist`, `search_policy_docs`, `get_dashboard_metrics`, `get_employee_profile`

Draft (approval-gated): `generate_exit_checklist`, `draft_notification`, `draft_escalation`, `review_kt_document`, `assess_exit_risk`, `verify_compliance`, `summarize_exit_interview`, `request_document`, `flag_policy_breach`

Unguarded write: `update_task_status` (allow-listed transitions only)

### Workflow stages (seeded, not HR-editable in v1)

`RESIGNATION_SUBMITTED → MANAGER_ACK → KT_PLANNING → KT_EXECUTION → IT_CLEARANCE → FINANCE_CLEARANCE → ADMIN_ASSET_RETURN → EXIT_INTERVIEW → FINAL_SETTLEMENT → RELIEVING_LETTER`

Each stage has an owner role and SLA days.

---

## Build order

**Frontend first within each phase.** Build React screens against `frontend/src/lib/api.ts` backed by mock fixtures, get the UI reviewed, then implement FastAPI endpoints and flip the `USE_MOCKS` switch.

Exception: **Phase 0 is DB-first** — the schema defines the TypeScript types every screen consumes.

---

## Phases

### Phase 0 — Foundations *(~3 days)* — DONE
- [x] Supabase project `fccdactaterkdeephcyg`, Mumbai (`ap-south-1`), free tier
- [x] Full schema migration — `supabase/migrations/0001_init.sql`
- [x] RLS policies on every table — `supabase/migrations/0002_rls.sql`
- [x] Seed `exit_stages` (10) + `document_types` (8) + `task_templates` (24) — `supabase/seed.sql`
- [x] Seed 10 employees across 3 departments with manager hierarchy + auth users
- [x] Vite skeleton — React 19, Vite 8, Tailwind v4, TanStack Query, React Router
- [x] FastAPI skeleton, `.env` handling — `backend/app/`, boots and serves `/health`
- [x] Shared TS types — `frontend/src/lib/types.ts` (hand-written; regenerate with `supabase gen types` once the project exists)

**Done:** `scripts/apply_migrations.py --seed` builds everything from scratch, and `scripts/verify_rls.py` proves isolation with 16 assertions against real signed-in users — 16/16 passing. Both are idempotent and safe to re-run.

**Bug this caught:** `employees_select` in `0002_rls.sql` recursed infinitely (Postgres 42P17). The "I can see my own manager" clause was an inline subquery against `employees`, which re-triggered its own policy. Fixed in `0003_fix_employees_recursion.sql` by moving it into `app.current_manager_id()`.
**Rule that follows:** never reference `employees` directly inside a policy on `employees`. Always go through an `app.*` SECURITY DEFINER helper.

**No table has a DELETE policy, deliberately.** A case is `cancelled`, an employee is `is_active = false`; nothing is erased, because the audit trail has to stay meaningful. Test fixtures therefore cannot clean up through PostgREST — `verify_rls.py` uses a direct psycopg connection for teardown.

### Phase 1 — Auth & role routing *(~3 days)* — DONE
- [x] Supabase Auth email/password on the client — `lib/supabase.ts`, real form in `pages/SignIn.tsx`
- [x] HR-provisioned `employees` rows linked via `auth_user_id` (schema + seed)
- [x] Sign-in page + `AuthProvider` resolving `app_role`
- [x] `RequireRole` router guard (works as layout route *or* element wrapper) + three dashboard shells
- [x] FastAPI `deps.py`: bearer JWT → `ActorContext` → RLS-bound client. Verifies both HS256 (legacy secret) and asymmetric JWKS signing. `service_db()` is the only RLS bypass and is deliberately not a request dependency, so every bypass is greppable.
- [x] First real endpoints: `/api/me`, `/api/me/exit`, `/api/cases`, `/api/cases/{id}`(+`/tasks`,`/documents`)

**Done:** `scripts/verify_api.py` drives the running API with real Supabase tokens — 31 assertions, all passing. Covers JWT rejection, role resolution, case scoping across five users, task-update permissions, and the audit trail.

Two things that matter for anyone touching auth:
- **Never cache the access token.** `api.ts` reads it from `supabase.auth.getSession()` on every request. supabase-js refreshes in the background; a cached copy 401s about an hour into a session.
- **`AuthProvider` subscribes to `onAuthStateChange`.** Without it, a sign-out in another tab leaves this one showing a dashboard whose requests have started failing.

### Phase 2 — Core workflow, zero AI *(~1.5 weeks)* — DONE
The backbone. The platform must be fully usable before any agent exists.
- [x] Employee UI: resignation form, stage stepper, task list by stage, document upload (drag-drop), KT record, exit interview
- [x] Manager/HR UI: **Needs you** inbox (documents to review, stages ready to sign off, overdue work), case detail, sign-off trail
- [x] HR: **Progress** view — completion % per case with a per-stage breakdown
- [x] **Reminders** — pre-filled, editable, audited; lands in the recipient's notification bell. `EmailSender` interface ready for Phase 8's SMTP
- [x] Case creation + task template expansion (`services/cases.py`)
- [x] HR stage override — skips the gates, HR-only, written reason required, own audit action
- [x] Successor nomination + KT sign-off (manager or HR, never the leaver)
- [x] 26 RLS-bound routes, `audit_log` on every state change

**Done:** `scripts/verify_api.py` — 77 assertions against the live API, all passing; `verify_rls.py` — 16/16.

Two bugs this phase caught, both worth remembering:
- **System-generated rows need the service role.** Task expansion failed under RLS because `case_tasks_insert` requires `can_act_on_case`, which correctly excludes the exiting employee — and `exit_interviews_write` requires you to *be* the subject, which excludes HR. The fix was to treat template expansion as a system action, not to loosen either policy.
- **`create_case` is not atomic.** PostgREST cannot span a transaction across calls, so a failure mid-way left a case with no checklist — which then blocked the person from retrying via `exit_cases_one_open_per_employee`. There is now a compensating delete; the durable fix is a single Postgres function.

Authorisation rules that live in handlers, not RLS, because SQL policies cannot express them:
- You cannot review a document you uploaded yourself (`documents.py`)
- The exiting employee cannot mark their own KT topic `verified` or `gap` (`workflow.py`)
- Only HR can `waive` a task (`tasks.py`)
- A stage cannot be approved while any task in it is open or any document is unreviewed (`workflow.py`)

### Phase 3 — Agent core, read-only *(~1 week)* — NOT STARTED
- [ ] LangGraph `StateGraph` + `PostgresSaver`
- [ ] `agent/llm.py`: caching, adaptive thinking, effort, refusal fallbacks
- [ ] Six read tools
- [ ] System prompt with per-role framing
- [ ] `POST /agent/chat` SSE streaming + `AgentChat` component in all three dashboards
- [ ] `agent_runs` logging with token usage

**Done when:** an employee asks "what's left before my last day?" and gets an answer grounded in real tool calls; a manager asking about an out-of-team case gets nothing because RLS returned nothing.

### Phase 4 — Draft tools + approval queue *(~1 week)* — NOT STARTED
- [ ] `agent_actions` lifecycle + `interrupt()` on sensitive tools
- [ ] `generate_exit_checklist`, `draft_notification`, `draft_escalation`, `request_document`, `update_task_status`
- [ ] Approval queue UI (manager + HR): view draft → edit → approve/reject
- [ ] `services/executor.py` performing approved actions
- [ ] Audit rows for both the draft and the execution

**Done when:** the agent drafts a KT reminder, HR edits the wording and approves, the action executes, and both steps appear in the audit log.

### Phase 5 — RAG over policy docs *(~4 days)* — NOT STARTED
- [ ] Policy doc upload UI (HR)
- [ ] Chunking (~800 tokens, 100 overlap, heading-aware)
- [ ] Voyage embeddings into `policy_chunks`
- [ ] `search_policy_docs` returning content + doc title + version
- [ ] System prompt rule: cite the policy doc on any policy claim

**Done when:** "what's my notice period as a senior engineer?" answers with the document and version named, and an uncovered question returns "not covered in current policy" rather than a guess.

### Phase 6 — Analysis tools *(~1 week)* — NOT STARTED
- [ ] Pydantic schemas + `messages.parse()` for `assess_exit_risk`, `review_kt_document`, `verify_compliance`, `summarize_exit_interview`
- [ ] Persist results to their tables
- [ ] `<untrusted_content>` wrapping on all document and interview text
- [ ] Risk badge on case cards, KT gap list in manager review, compliance checklist gating final clearance

**Done when:** an exit interview submission produces a stored sentiment + theme summary, and a KT doc with an obvious gap gets that gap named specifically.

### Phase 7 — Autonomous sweeps *(~4 days)* — NOT STARTED
- [ ] `jobs/sweep.py` invoking the same graph with a sweep seed message
- [ ] APScheduler nightly trigger, scoped to active cases, per-run action cap
- [ ] Sweep output lands in the same approval queue
- [ ] HR "last sweep" summary panel

**Done when:** a deliberately overdue case is picked up overnight and a drafted escalation waits in HR's queue.

### Phase 8 — Notifications & email *(~3 days)* — NOT STARTED
- [ ] `EmailSender` protocol + `SMTPSender` (company relay) + `LogSender` (dev)
- [ ] In-app notification bell via Supabase Realtime
- [ ] Templated emails rendered from approved `agent_actions`
- [ ] Retry + `agent_actions.failure_reason` on failure

**Done when:** approving a drafted notification sends a real email and writes a notification + audit row; a relay failure marks the action `failed` with a reason instead of silently dropping.

### Phase 9 — Pilot hardening *(~1 week)* — NOT STARTED
- [ ] RLS pytest matrix: every role × table × operation, including the agent path
- [ ] Injection tests: adversarial KT/interview text drafts no action against the author's own clearance
- [ ] Agent eval set: ~30 scenarios with expected tool-call sequences
- [ ] Observability: token/cost per run, cache hit rate, p95 latency
- [ ] Retention policy on exit interviews, PII redaction in logs, short-TTL signed URLs
- [ ] Deploy: frontend Vercel, backend containerised, secrets in platform vault, `pg_cron` replaces APScheduler

**Done when:** RLS suite green, eval set passes, and a dry-run pilot with 3 real cases completes without manual DB intervention.

**Total: ~8 weeks.**

---

## Schema

```
employees        id, auth_user_id→auth.users, emp_code, full_name, work_email,
                 department, designation, date_of_joining, manager_id→employees,
                 app_role enum('employee','manager','hr'), is_active

exit_stages      code PK, name, owner_role, sla_days, sort_order          -- seeded
exit_cases       id, employee_id, exit_type, resignation_date, last_working_day,
                 notice_period_days, current_stage→exit_stages,
                 status enum('draft','active','on_hold','completed','cancelled')

case_tasks       id, case_id, stage_code, title, description, owner_role, assignee_id,
                 due_date, status, completed_at, sla_breached,
                 generated_by enum('template','agent')
documents        id, case_id, doc_type, storage_path, uploaded_by,
                 status enum('pending','approved','rejected'), reviewed_by, review_note
approvals        id, case_id, stage_code, approver_id, decision, comment, decided_at

kt_records       id, case_id, successor_id, overall_status
kt_items         id, kt_record_id, topic, detail, document_id, coverage_status
exit_interviews  id, case_id, responses jsonb, sentiment, themes jsonb, summary, analysed_at

agent_runs       id, thread_id, trigger enum('chat','sweep'), actor_id, actor_role,
                 case_id, status, input_tokens, output_tokens, cache_read_tokens, cost_usd
agent_actions    id, run_id, case_id, kind, payload jsonb,
                 status enum('pending_approval','approved','rejected','executed','failed'),
                 approver_id, decided_at, executed_at, failure_reason
notifications    id, recipient_id, title, body, source_action_id, read_at
audit_log        id, actor_id, actor_type enum('human','agent'), action,
                 entity_table, entity_id, before jsonb, after jsonb, at

policy_docs      id, title, version, storage_path, effective_from, uploaded_by
policy_chunks    id, policy_doc_id, chunk_index, content, embedding vector(1024)
```

### RLS

- `employee` — rows where `exit_cases.employee_id = my_employee_id`
- `manager` — rows where the case's employee has `manager_id = my_employee_id`
- `hr` — all rows
- `agent_actions` — HR reads all; manager reads actions targeting their reports; backend service writes
- `audit_log` — backend inserts only; HR reads

---

## Design language

Offboarding is a countdown against a fixed last working day that ends in a signed clearance. The interface borrows from records and sign-off sheets, not from dashboard templates.

- **Status is structural, not decorative.** Every list row carries a 3px left rail (`<Row tone>` in `components/ui.tsx`), so a long list reads as a vertical progress barcode. A dashed rail means "waiting on someone else". Do not add coloured status pills to rows.
- **Four tones only:** neutral, moss (cleared), amber (in progress / due soon), rust (breached / rejected). Defined as CSS vars in `index.css`; never hardcode a hex in a component.
- **Two typefaces.** Newsreader (serif) carries the one human statement per screen — *"Your last working day is 14 November"*. IBM Plex Sans carries all data, with tabular figures so date and count columns align.
- **Flat surfaces.** One hairline border, 2–3px radius, no card shadows, no gradient washes. Depth is reserved for overlays.
- **Copy is direct and active.** "Mark done", not "Submit". Empty states say what to do next; they never say "no data".
- The employee dashboard hero is `StageTrack` — the notice period drawn as a measure with the ten stages plotted on it and today marked. It is deliberately not a stat card.

## Repo layout

```
exitplatform/
├─ frontend/src/
│  ├─ lib/          supabase.ts, api.ts (USE_MOCKS switch), types.ts
│  ├─ auth/         AuthProvider, RequireRole, useSession
│  ├─ components/   StageStepper, TaskCard, DocUploader, ApprovalCard, AgentChat
│  └─ pages/
│     ├─ employee/  MyExit, MyTasks, Documents, KTForm, ExitInterview
│     ├─ manager/   TeamExits, CaseReview, ApprovalQueue
│     └─ hr/        AllCases, SLABoard, AgentActionQueue, PolicyDocs, Insights
└─ backend/app/
   ├─ main.py       FastAPI, CORS, SSE
   ├─ deps.py       JWT → actor_context → RLS-bound client
   ├─ routers/      cases, tasks, documents, approvals, agent, policy, metrics
   ├─ agent/        graph.py, llm.py, prompts.py, schemas.py, tools/
   ├─ services/     email.py, executor.py, rag.py, audit.py
   └─ jobs/         sweep.py
```

---

## Out of scope for v1

Deliberately deferred — they need a multi-agent supervisor, which contradicts rule 5 above. Revisit once the single agent is proven and the audit log has real traffic.

- Exit Process Orchestrator (per-stage agents under a supervisor)
- Predictive Attrition pipeline
- End-to-end autonomous exit handling
- OCR/vision document validation

---

## Open questions

- SMTP relay host, auth method, and whether the backend's egress IP needs IT allow-listing
- Whether Voyage AI is an approved vendor, or we run `bge-m3` locally
- Retention period for exit interview responses (drives the Phase 9 retention job)
