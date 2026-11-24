-- ============================================================================
-- Migration 0012 — Itemised clearance: assets, access, settlement lines
--
-- Until now "Return laptop and IT-issued hardware" was a single checkbox, and
-- so was "Revoke system access". That is fine as a workflow step and useless as
-- a record: it cannot say which of six devices came back, or whether the VPN
-- certificate was revoked before or after the person left. IT and Finance both
-- asked the same question of the old screen — *which ones?* — and it had no
-- answer.
--
-- Three tables, one per function, rather than one polymorphic table. They look
-- similar from a distance but the useful columns differ: an asset has a serial
-- number and a condition, an access grant has an elevated flag and a revocation
-- time, a settlement line has an amount and a sign. Collapsing them would mean
-- a wide table of mostly-null columns and a `kind` discriminator in every query.
--
-- The existing tasks stay exactly as they are. These itemise a task, they do not
-- replace it: "Return laptop and IT-issued hardware" is still the thing that
-- gates the stage, and it completes when its rows here are all accounted for.
-- Keeping the gate on the task means the stage logic in workflow.py is untouched.
-- ============================================================================

create type asset_status as enum ('pending', 'returned', 'lost', 'not_issued');
create type access_status as enum ('active', 'revoked', 'not_applicable');
create type settlement_status as enum ('pending', 'confirmed', 'not_applicable');
create type settlement_kind as enum ('earning', 'deduction');

-- ----------------------------------------------------------------------------
-- Assets: physical and licensed items issued to the employee
-- ----------------------------------------------------------------------------
create table case_assets (
  id           uuid primary key default gen_random_uuid(),
  case_id      uuid not null references exit_cases (id) on delete cascade,
  name         text not null,
  category     text not null,              -- hardware | access | mobile | other
  identifier   text,                       -- serial, asset tag, number
  status       asset_status not null default 'pending',
  condition    text,                       -- filled on return
  note         text,
  returned_at  timestamptz,
  returned_to  uuid references employees (id) on delete set null,
  sort_order   integer not null default 0,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create index case_assets_case_idx on case_assets (case_id);
create trigger case_assets_touch before update on case_assets
  for each row execute function app.touch_updated_at();

-- ----------------------------------------------------------------------------
-- Access: the systems a person holds, and whether each is still live
-- ----------------------------------------------------------------------------
create table case_access (
  id           uuid primary key default gen_random_uuid(),
  case_id      uuid not null references exit_cases (id) on delete cascade,
  system       text not null,
  category     text not null,              -- identity | mail | collaboration |
                                           -- engineering | physical
  -- Admin rights, production credentials and break-glass accounts are the ones
  -- worth revoking on the last day rather than in the normal sweep, so the
  -- dashboard can pull them to the top.
  is_elevated  boolean not null default false,
  status       access_status not null default 'active',
  note         text,
  revoked_at   timestamptz,
  revoked_by   uuid references employees (id) on delete set null,
  sort_order   integer not null default 0,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create index case_access_case_idx on case_access (case_id);
create index case_access_live_idx on case_access (case_id)
  where status = 'active';
create trigger case_access_touch before update on case_access
  for each row execute function app.touch_updated_at();

-- ----------------------------------------------------------------------------
-- Settlement: the full-and-final breakdown, one row per line
-- ----------------------------------------------------------------------------
create table case_settlement (
  id           uuid primary key default gen_random_uuid(),
  case_id      uuid not null references exit_cases (id) on delete cascade,
  kind         settlement_kind not null,
  label        text not null,
  -- Null until Finance fills it in. Deliberately nullable: an unknown amount
  -- must be visibly unknown rather than silently zero.
  amount       numeric(12, 2),
  status       settlement_status not null default 'pending',
  note         text,
  sort_order   integer not null default 0,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create index case_settlement_case_idx on case_settlement (case_id);
create trigger case_settlement_touch before update on case_settlement
  for each row execute function app.touch_updated_at();

-- ----------------------------------------------------------------------------
-- RLS
--
-- Reading follows the case: anyone who can see the case sees its detail, plus
-- the clearance role that owns the work. Writing is narrower — IT owns assets
-- and access, Finance owns settlement lines, and HR can correct any of it.
--
-- The employee reads their own assets deliberately: they are the one who has to
-- hand the laptop back, and a list they cannot see is not a list. They cannot
-- write, because marking your own laptop returned is IT's call, not yours.
-- ----------------------------------------------------------------------------
alter table case_assets     enable row level security;
alter table case_access     enable row level security;
alter table case_settlement enable row level security;

create policy case_assets_select on case_assets
  for select to authenticated
  using (app.can_read_case(case_id) or app.has_role_work_on_case(case_id));

create policy case_access_select on case_access
  for select to authenticated
  using (app.can_read_case(case_id) or app.has_role_work_on_case(case_id));

create policy case_settlement_select on case_settlement
  for select to authenticated
  using (app.can_read_case(case_id) or app.has_role_work_on_case(case_id));

create policy case_assets_write on case_assets
  for update to authenticated
  using (app.is_hr() or app.owns_stage('ADMIN_ASSET_RETURN') or app.owns_stage('IT_CLEARANCE'))
  with check (app.is_hr() or app.owns_stage('ADMIN_ASSET_RETURN') or app.owns_stage('IT_CLEARANCE'));

create policy case_access_write on case_access
  for update to authenticated
  using (app.is_hr() or app.owns_stage('IT_CLEARANCE'))
  with check (app.is_hr() or app.owns_stage('IT_CLEARANCE'));

create policy case_settlement_write on case_settlement
  for update to authenticated
  using (app.is_hr() or app.owns_stage('FINANCE_CLEARANCE'))
  with check (app.is_hr() or app.owns_stage('FINANCE_CLEARANCE'));

-- Rows are created by the backend when a case opens, never by a user.
-- No INSERT or DELETE policy, matching every other table here.

comment on table case_assets is
  'Itemises the asset-return task. One row per item issued to the employee.';
comment on table case_access is
  'Itemises the access-revocation task. One row per system the person holds.';
comment on table case_settlement is
  'Itemises the full-and-final settlement. One row per earning or deduction.';
