-- ============================================================================
-- Exit Process Platform — core schema
-- Phase 0
--
-- Conventions:
--   * uuid primary keys, gen_random_uuid()
--   * all timestamps timestamptz
--   * every mutable table has created_at / updated_at with a trigger
--   * RLS is enabled here but policies live in 0002_rls.sql
-- ============================================================================

create extension if not exists "pgcrypto";
create extension if not exists "citext";
create extension if not exists "vector";

-- Private schema for RLS helper functions. Never exposed via PostgREST.
create schema if not exists app;

-- ----------------------------------------------------------------------------
-- Enums
-- ----------------------------------------------------------------------------

-- Who can log in and what dashboard they get. Only three dashboards in v1.
create type app_role as enum ('employee', 'manager', 'hr');

-- Who owns a task or stage. Broader than app_role: IT/Finance/Admin clearances
-- are real workflow owners but have no dashboard in v1 — HR actions them.
create type task_owner_role as enum ('employee', 'manager', 'hr', 'it', 'finance', 'admin');

create type exit_type as enum ('resignation', 'termination', 'retirement', 'end_of_contract');
create type case_status as enum ('draft', 'active', 'on_hold', 'completed', 'cancelled');
create type task_status as enum ('pending', 'in_progress', 'blocked', 'completed', 'waived');
create type document_status as enum ('pending', 'approved', 'rejected');
create type approval_decision as enum ('approved', 'rejected');
create type kt_coverage_status as enum ('not_started', 'in_progress', 'documented', 'verified', 'gap');
create type task_origin as enum ('template', 'agent', 'manual');

create type agent_trigger as enum ('chat', 'sweep');
create type agent_run_status as enum ('running', 'awaiting_approval', 'completed', 'failed');
create type agent_action_status as enum ('pending_approval', 'approved', 'rejected', 'executed', 'failed');
create type actor_type as enum ('human', 'agent', 'system');

-- ----------------------------------------------------------------------------
-- updated_at trigger
-- ----------------------------------------------------------------------------

create or replace function app.touch_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- ----------------------------------------------------------------------------
-- employees
--
-- The identity spine. Every person in the system is a row here; auth_user_id
-- links to Supabase Auth. HR provisions the row, then the person signs up /
-- is invited against the same work_email.
-- ----------------------------------------------------------------------------

create table employees (
  id                uuid primary key default gen_random_uuid(),
  auth_user_id      uuid unique references auth.users (id) on delete set null,
  emp_code          text not null unique,
  full_name         text not null,
  work_email        citext not null unique,
  department        text not null,
  designation       text not null,
  date_of_joining   date not null,
  manager_id        uuid references employees (id) on delete set null,
  app_role          app_role not null default 'employee',
  is_active         boolean not null default true,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),

  constraint employees_not_own_manager check (manager_id is null or manager_id <> id)
);

create index employees_manager_idx on employees (manager_id);
create index employees_auth_user_idx on employees (auth_user_id);
create index employees_department_idx on employees (department);

create trigger employees_touch before update on employees
  for each row execute function app.touch_updated_at();

-- ----------------------------------------------------------------------------
-- Reference data: stages, task templates, document types
--
-- Seeded in seed.sql. Not HR-editable in v1 (see CLAUDE.md).
-- ----------------------------------------------------------------------------

create table exit_stages (
  code          text primary key,
  name          text not null,
  description   text,
  owner_role    task_owner_role not null,
  sla_days      integer not null check (sla_days > 0),
  sort_order    integer not null unique
);

create table document_types (
  code              text primary key,
  name              text not null,
  description       text,
  stage_code        text not null references exit_stages (code),
  owner_role        task_owner_role not null,
  is_required       boolean not null default true,
  accepts_mime      text[] not null default array['application/pdf', 'image/png', 'image/jpeg'],
  sort_order        integer not null
);

create index document_types_stage_idx on document_types (stage_code);

-- Base checklist. Every new case is expanded from these rows; the agent may
-- add role-specific tasks on top (case_tasks.origin = 'agent').
create table task_templates (
  id            uuid primary key default gen_random_uuid(),
  stage_code    text not null references exit_stages (code),
  title         text not null,
  description   text,
  owner_role    task_owner_role not null,
  doc_type_code text references document_types (code),
  offset_days   integer not null default 0,   -- due date = case start + offset_days
  sort_order    integer not null,
  is_active     boolean not null default true,

  unique (stage_code, sort_order)
);

create index task_templates_stage_idx on task_templates (stage_code);

-- ----------------------------------------------------------------------------
-- exit_cases
-- ----------------------------------------------------------------------------

create table exit_cases (
  id                  uuid primary key default gen_random_uuid(),
  employee_id         uuid not null references employees (id) on delete restrict,
  exit_type           exit_type not null default 'resignation',
  reason              text,
  resignation_date    date not null,
  last_working_day    date not null,
  notice_period_days  integer not null default 30 check (notice_period_days >= 0),
  current_stage       text not null references exit_stages (code),
  status              case_status not null default 'draft',
  risk_score          integer check (risk_score between 0 and 100),
  risk_assessed_at    timestamptz,
  created_by          uuid references employees (id) on delete set null,
  completed_at        timestamptz,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),

  constraint exit_cases_lwd_after_resignation check (last_working_day >= resignation_date)
);

-- An employee may only have one case that is not finished.
create unique index exit_cases_one_open_per_employee
  on exit_cases (employee_id)
  where status in ('draft', 'active', 'on_hold');

create index exit_cases_employee_idx on exit_cases (employee_id);
create index exit_cases_status_idx on exit_cases (status);
create index exit_cases_lwd_idx on exit_cases (last_working_day);

create trigger exit_cases_touch before update on exit_cases
  for each row execute function app.touch_updated_at();

-- ----------------------------------------------------------------------------
-- case_tasks
-- ----------------------------------------------------------------------------

create table case_tasks (
  id            uuid primary key default gen_random_uuid(),
  case_id       uuid not null references exit_cases (id) on delete cascade,
  stage_code    text not null references exit_stages (code),
  template_id   uuid references task_templates (id) on delete set null,
  title         text not null,
  description   text,
  owner_role    task_owner_role not null,
  assignee_id   uuid references employees (id) on delete set null,
  doc_type_code text references document_types (code),
  due_date      date,
  status        task_status not null default 'pending',
  origin        task_origin not null default 'template',
  sla_breached  boolean not null default false,
  completed_at  timestamptz,
  completed_by  uuid references employees (id) on delete set null,
  sort_order    integer not null default 0,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index case_tasks_case_idx on case_tasks (case_id);
create index case_tasks_assignee_idx on case_tasks (assignee_id);
create index case_tasks_status_idx on case_tasks (status);
-- Drives the nightly SLA sweep.
create index case_tasks_overdue_idx on case_tasks (due_date)
  where status in ('pending', 'in_progress', 'blocked');

create trigger case_tasks_touch before update on case_tasks
  for each row execute function app.touch_updated_at();

-- ----------------------------------------------------------------------------
-- documents
-- ----------------------------------------------------------------------------

create table documents (
  id            uuid primary key default gen_random_uuid(),
  case_id       uuid not null references exit_cases (id) on delete cascade,
  task_id       uuid references case_tasks (id) on delete set null,
  doc_type_code text not null references document_types (code),
  file_name     text not null,
  storage_path  text not null unique,
  mime_type     text not null,
  size_bytes    bigint not null check (size_bytes > 0),
  uploaded_by   uuid not null references employees (id) on delete restrict,
  status        document_status not null default 'pending',
  reviewed_by   uuid references employees (id) on delete set null,
  reviewed_at   timestamptz,
  review_note   text,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index documents_case_idx on documents (case_id);
create index documents_status_idx on documents (status);

create trigger documents_touch before update on documents
  for each row execute function app.touch_updated_at();

-- ----------------------------------------------------------------------------
-- approvals — stage sign-off trail
-- ----------------------------------------------------------------------------

create table approvals (
  id           uuid primary key default gen_random_uuid(),
  case_id      uuid not null references exit_cases (id) on delete cascade,
  stage_code   text not null references exit_stages (code),
  approver_id  uuid not null references employees (id) on delete restrict,
  decision     approval_decision not null,
  comment      text,
  decided_at   timestamptz not null default now()
);

create index approvals_case_idx on approvals (case_id);

-- ----------------------------------------------------------------------------
-- Knowledge transfer
-- ----------------------------------------------------------------------------

create table kt_records (
  id              uuid primary key default gen_random_uuid(),
  case_id         uuid not null unique references exit_cases (id) on delete cascade,
  successor_id    uuid references employees (id) on delete set null,
  overall_status  kt_coverage_status not null default 'not_started',
  reviewed_by     uuid references employees (id) on delete set null,
  reviewed_at     timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create trigger kt_records_touch before update on kt_records
  for each row execute function app.touch_updated_at();

create table kt_items (
  id              uuid primary key default gen_random_uuid(),
  kt_record_id    uuid not null references kt_records (id) on delete cascade,
  topic           text not null,
  detail          text,
  document_id     uuid references documents (id) on delete set null,
  coverage_status kt_coverage_status not null default 'not_started',
  -- Set by review_kt_document. Free text from the model, not a status.
  gap_note        text,
  sort_order      integer not null default 0,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index kt_items_record_idx on kt_items (kt_record_id);

create trigger kt_items_touch before update on kt_items
  for each row execute function app.touch_updated_at();

-- ----------------------------------------------------------------------------
-- exit_interviews
--
-- `responses` is employee-authored free text. Treat as UNTRUSTED input when it
-- reaches the agent — see CLAUDE.md rule 3.
-- ----------------------------------------------------------------------------

create table exit_interviews (
  id            uuid primary key default gen_random_uuid(),
  case_id       uuid not null unique references exit_cases (id) on delete cascade,
  responses     jsonb not null default '{}'::jsonb,
  submitted_at  timestamptz,
  -- Populated by summarize_exit_interview (structured output).
  sentiment     text,
  themes        jsonb,
  summary       text,
  recommendations jsonb,
  analysed_at   timestamptz,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create trigger exit_interviews_touch before update on exit_interviews
  for each row execute function app.touch_updated_at();

-- ----------------------------------------------------------------------------
-- Agent runs and the approval queue
-- ----------------------------------------------------------------------------

create table agent_runs (
  id                 uuid primary key default gen_random_uuid(),
  thread_id          text not null,          -- LangGraph checkpointer thread
  trigger            agent_trigger not null,
  actor_id           uuid references employees (id) on delete set null,
  actor_role         app_role,
  case_id            uuid references exit_cases (id) on delete set null,
  status             agent_run_status not null default 'running',
  model              text not null default 'claude-opus-5',
  input_tokens       integer not null default 0,
  output_tokens      integer not null default 0,
  cache_read_tokens  integer not null default 0,
  cost_usd           numeric(10, 6) not null default 0,
  error              text,
  started_at         timestamptz not null default now(),
  finished_at        timestamptz
);

create index agent_runs_thread_idx on agent_runs (thread_id);
create index agent_runs_case_idx on agent_runs (case_id);
create index agent_runs_actor_idx on agent_runs (actor_id);

-- The approval queue. Sensitive tools write here instead of acting.
-- Nothing in this table has an effect until a human approves and the executor
-- runs it. See CLAUDE.md rule 2.
create table agent_actions (
  id               uuid primary key default gen_random_uuid(),
  run_id           uuid references agent_runs (id) on delete set null,
  case_id          uuid references exit_cases (id) on delete cascade,
  kind             text not null,            -- e.g. 'draft_notification'
  summary          text not null,            -- one-line description for the queue UI
  payload          jsonb not null,           -- tool-specific; executor knows the shape
  status           agent_action_status not null default 'pending_approval',
  -- Set when the action targets the requesting employee's own clearance.
  -- Forces HR review regardless of who would normally approve. Rule 3 defence.
  self_targeting   boolean not null default false,
  approver_id      uuid references employees (id) on delete set null,
  approved_payload jsonb,                    -- human-edited version, if edited
  decided_at       timestamptz,
  decision_note    text,
  executed_at      timestamptz,
  failure_reason   text,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

create index agent_actions_case_idx on agent_actions (case_id);
create index agent_actions_status_idx on agent_actions (status);
create index agent_actions_pending_idx on agent_actions (created_at)
  where status = 'pending_approval';

create trigger agent_actions_touch before update on agent_actions
  for each row execute function app.touch_updated_at();

-- ----------------------------------------------------------------------------
-- notifications
-- ----------------------------------------------------------------------------

create table notifications (
  id                uuid primary key default gen_random_uuid(),
  recipient_id      uuid not null references employees (id) on delete cascade,
  case_id           uuid references exit_cases (id) on delete cascade,
  title             text not null,
  body              text not null,
  source_action_id  uuid references agent_actions (id) on delete set null,
  read_at           timestamptz,
  created_at        timestamptz not null default now()
);

create index notifications_recipient_idx on notifications (recipient_id, read_at);

-- ----------------------------------------------------------------------------
-- audit_log — append only. Every state change, human or agent.
-- ----------------------------------------------------------------------------

create table audit_log (
  id            bigserial primary key,
  actor_id      uuid references employees (id) on delete set null,
  actor_type    actor_type not null,
  run_id        uuid references agent_runs (id) on delete set null,
  action        text not null,               -- e.g. 'case_tasks.status_changed'
  entity_table  text not null,
  entity_id     text not null,
  case_id       uuid references exit_cases (id) on delete set null,
  before        jsonb,
  after         jsonb,
  at            timestamptz not null default now()
);

create index audit_log_entity_idx on audit_log (entity_table, entity_id);
create index audit_log_case_idx on audit_log (case_id, at desc);
create index audit_log_at_idx on audit_log (at desc);

-- ----------------------------------------------------------------------------
-- Policy documents + RAG chunks
-- ----------------------------------------------------------------------------

create table policy_docs (
  id              uuid primary key default gen_random_uuid(),
  title           text not null,
  version         text not null,
  storage_path    text not null unique,
  effective_from  date not null,
  superseded_at   timestamptz,
  uploaded_by     uuid references employees (id) on delete set null,
  indexed_at      timestamptz,
  created_at      timestamptz not null default now(),

  unique (title, version)
);

create table policy_chunks (
  id             uuid primary key default gen_random_uuid(),
  policy_doc_id  uuid not null references policy_docs (id) on delete cascade,
  chunk_index    integer not null,
  heading        text,
  content        text not null,
  token_count    integer,
  -- voyage-3-large. If switching to bge-m3 (1024) the dimension still fits;
  -- any other model means a migration.
  embedding      vector(1024),

  unique (policy_doc_id, chunk_index)
);

create index policy_chunks_doc_idx on policy_chunks (policy_doc_id);
create index policy_chunks_embedding_idx on policy_chunks
  using hnsw (embedding vector_cosine_ops);

-- ----------------------------------------------------------------------------
-- Enable RLS everywhere. Policies are in 0002_rls.sql.
-- Default-deny until then: a table with RLS on and no policy returns nothing.
-- ----------------------------------------------------------------------------

alter table employees        enable row level security;
alter table exit_stages      enable row level security;
alter table document_types   enable row level security;
alter table task_templates   enable row level security;
alter table exit_cases       enable row level security;
alter table case_tasks       enable row level security;
alter table documents        enable row level security;
alter table approvals        enable row level security;
alter table kt_records       enable row level security;
alter table kt_items         enable row level security;
alter table exit_interviews  enable row level security;
alter table agent_runs       enable row level security;
alter table agent_actions    enable row level security;
alter table notifications    enable row level security;
alter table audit_log        enable row level security;
alter table policy_docs      enable row level security;
alter table policy_chunks    enable row level security;
