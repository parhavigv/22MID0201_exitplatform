-- ============================================================================
-- Row Level Security
-- Phase 0
--
-- This file is the enforcement layer for the whole product. The agent runs its
-- tools through a client built from the caller's JWT, so these policies are
-- what stop the model reading a case the human couldn't read (CLAUDE.md rule 1).
--
-- Visibility model:
--   employee  -> only their own case and its children
--   manager   -> cases of their direct reports (+ their own)
--   hr        -> everything
--
-- Writes are narrower than reads throughout. Anything agent-related is
-- service-role only: `authenticated` never writes agent_runs, agent_actions,
-- or audit_log directly.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Helpers
--
-- SECURITY DEFINER so they bypass RLS on `employees` — without this, a policy
-- on employees that calls a function reading employees recurses infinitely.
-- search_path is pinned to defeat search_path hijacking.
-- ----------------------------------------------------------------------------

create or replace function app.current_employee_id()
returns uuid
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select id from employees where auth_user_id = auth.uid() and is_active
$$;

create or replace function app.current_role_name()
returns app_role
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select app_role from employees where auth_user_id = auth.uid() and is_active
$$;

create or replace function app.is_hr()
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select coalesce(
    (select app_role = 'hr' from employees where auth_user_id = auth.uid() and is_active),
    false
  )
$$;

-- True when the current user manages `target_employee`, or is that employee.
create or replace function app.manages_or_is(target_employee uuid)
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select exists (
    select 1
    from employees e
    join employees me on me.auth_user_id = auth.uid() and me.is_active
    where e.id = target_employee
      and (e.id = me.id or e.manager_id = me.id)
  )
$$;

-- Can the current user see this case at all? The single predicate every
-- case-child table reuses, so visibility can only be changed in one place.
create or replace function app.can_read_case(target_case uuid)
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select app.is_hr() or exists (
    select 1 from exit_cases c
    where c.id = target_case and app.manages_or_is(c.employee_id)
  )
$$;

-- Can the current user act on this case (approve, review, advance)?
-- Managers and HR only — never the exiting employee on their own case.
create or replace function app.can_act_on_case(target_case uuid)
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select app.is_hr() or exists (
    select 1
    from exit_cases c
    join employees e on e.id = c.employee_id
    join employees me on me.auth_user_id = auth.uid() and me.is_active
    where c.id = target_case and e.manager_id = me.id
  )
$$;

grant usage on schema app to authenticated, service_role;
grant execute on all functions in schema app to authenticated, service_role;

-- ----------------------------------------------------------------------------
-- employees
--
-- Read: yourself, your reports, your own manager (so the UI can name them).
-- HR reads all. Nobody but HR writes — employee records are HR-provisioned.
-- ----------------------------------------------------------------------------

create policy employees_select on employees
  for select to authenticated
  using (
    app.is_hr()
    or auth_user_id = auth.uid()
    or manager_id = app.current_employee_id()
    or id = (select manager_id from employees me where me.auth_user_id = auth.uid())
  );

create policy employees_hr_insert on employees
  for insert to authenticated
  with check (app.is_hr());

create policy employees_hr_update on employees
  for update to authenticated
  using (app.is_hr())
  with check (app.is_hr());

-- ----------------------------------------------------------------------------
-- Reference data — readable by everyone signed in, writable by nobody.
-- Seeded via migration; changing it is a deploy, not a runtime action.
-- ----------------------------------------------------------------------------

create policy exit_stages_select on exit_stages
  for select to authenticated using (true);

create policy document_types_select on document_types
  for select to authenticated using (true);

create policy task_templates_select on task_templates
  for select to authenticated using (true);

-- ----------------------------------------------------------------------------
-- exit_cases
-- ----------------------------------------------------------------------------

create policy exit_cases_select on exit_cases
  for select to authenticated
  using (app.is_hr() or app.manages_or_is(employee_id));

-- An employee may open their own case (resignation). HR may open any.
create policy exit_cases_insert on exit_cases
  for insert to authenticated
  with check (
    app.is_hr()
    or employee_id = app.current_employee_id()
  );

-- Only managers-of and HR change a case once it exists. The exiting employee
-- completes tasks; they do not move their own case forward.
create policy exit_cases_update on exit_cases
  for update to authenticated
  using (app.can_act_on_case(id))
  with check (app.can_act_on_case(id));

-- ----------------------------------------------------------------------------
-- case_tasks
--
-- Read follows case visibility. Update is deliberately wider than case update:
-- the exiting employee must be able to tick off their own assigned tasks.
-- Column-level restriction (they must not set sla_breached, etc.) is enforced
-- in the API layer, not here.
-- ----------------------------------------------------------------------------

create policy case_tasks_select on case_tasks
  for select to authenticated
  using (app.can_read_case(case_id));

create policy case_tasks_insert on case_tasks
  for insert to authenticated
  with check (app.can_act_on_case(case_id));

create policy case_tasks_update on case_tasks
  for update to authenticated
  using (
    app.can_act_on_case(case_id)
    or assignee_id = app.current_employee_id()
  )
  with check (
    app.can_act_on_case(case_id)
    or assignee_id = app.current_employee_id()
  );

-- ----------------------------------------------------------------------------
-- documents
--
-- Anyone who can see the case can see its documents. Upload is allowed for the
-- case subject and for actors. Only actors review — you cannot approve your own
-- upload, which is checked in the API (uploaded_by <> reviewed_by).
-- ----------------------------------------------------------------------------

create policy documents_select on documents
  for select to authenticated
  using (app.can_read_case(case_id));

create policy documents_insert on documents
  for insert to authenticated
  with check (
    uploaded_by = app.current_employee_id()
    and app.can_read_case(case_id)
  );

create policy documents_update on documents
  for update to authenticated
  using (app.can_act_on_case(case_id))
  with check (app.can_act_on_case(case_id));

-- ----------------------------------------------------------------------------
-- approvals — insert-only trail, never edited or deleted.
-- ----------------------------------------------------------------------------

create policy approvals_select on approvals
  for select to authenticated
  using (app.can_read_case(case_id));

create policy approvals_insert on approvals
  for insert to authenticated
  with check (
    app.can_act_on_case(case_id)
    and approver_id = app.current_employee_id()
  );

-- ----------------------------------------------------------------------------
-- Knowledge transfer
--
-- The exiting employee authors KT; the manager reviews it.
-- ----------------------------------------------------------------------------

create policy kt_records_select on kt_records
  for select to authenticated
  using (app.can_read_case(case_id));

create policy kt_records_write on kt_records
  for all to authenticated
  using (app.can_read_case(case_id))
  with check (app.can_read_case(case_id));

create policy kt_items_select on kt_items
  for select to authenticated
  using (exists (
    select 1 from kt_records r
    where r.id = kt_record_id and app.can_read_case(r.case_id)
  ));

create policy kt_items_write on kt_items
  for all to authenticated
  using (exists (
    select 1 from kt_records r
    where r.id = kt_record_id and app.can_read_case(r.case_id)
  ))
  with check (exists (
    select 1 from kt_records r
    where r.id = kt_record_id and app.can_read_case(r.case_id)
  ));

-- ----------------------------------------------------------------------------
-- exit_interviews
--
-- Narrower than the rest on purpose. Raw responses are candid feedback, often
-- about the manager. The subject and HR read them; the MANAGER DOES NOT.
-- Managers see the derived summary through an API view, never this table.
-- ----------------------------------------------------------------------------

create policy exit_interviews_select on exit_interviews
  for select to authenticated
  using (
    app.is_hr()
    or exists (
      select 1 from exit_cases c
      where c.id = case_id and c.employee_id = app.current_employee_id()
    )
  );

create policy exit_interviews_write on exit_interviews
  for all to authenticated
  using (exists (
    select 1 from exit_cases c
    where c.id = case_id and c.employee_id = app.current_employee_id()
  ))
  with check (exists (
    select 1 from exit_cases c
    where c.id = case_id and c.employee_id = app.current_employee_id()
  ));

-- ----------------------------------------------------------------------------
-- Agent tables
--
-- Read-only to users; all writes go through the backend service role. A user
-- can never fabricate an approved action or an audit entry.
-- ----------------------------------------------------------------------------

create policy agent_runs_select on agent_runs
  for select to authenticated
  using (
    app.is_hr()
    or actor_id = app.current_employee_id()
    or (case_id is not null and app.can_read_case(case_id))
  );

-- HR sees the whole queue. A manager sees drafts for their reports' cases.
-- The exiting employee never sees drafts about their own exit.
create policy agent_actions_select on agent_actions
  for select to authenticated
  using (
    app.is_hr()
    or (case_id is not null and app.can_act_on_case(case_id))
  );

-- ----------------------------------------------------------------------------
-- notifications — yours only.
-- ----------------------------------------------------------------------------

create policy notifications_select on notifications
  for select to authenticated
  using (recipient_id = app.current_employee_id());

-- Marking read is the only user write. Inserts come from the service role.
create policy notifications_mark_read on notifications
  for update to authenticated
  using (recipient_id = app.current_employee_id())
  with check (recipient_id = app.current_employee_id());

-- ----------------------------------------------------------------------------
-- audit_log — HR reads, nobody writes. Append-only from the service role.
-- ----------------------------------------------------------------------------

create policy audit_log_select on audit_log
  for select to authenticated
  using (
    app.is_hr()
    or (case_id is not null and app.can_act_on_case(case_id))
  );

-- ----------------------------------------------------------------------------
-- Policy documents
--
-- Everyone reads current policy — that is the point of the RAG tool.
-- Superseded versions are HR-only so the agent cannot cite stale rules.
-- ----------------------------------------------------------------------------

create policy policy_docs_select on policy_docs
  for select to authenticated
  using (superseded_at is null or app.is_hr());

create policy policy_docs_hr_write on policy_docs
  for all to authenticated
  using (app.is_hr())
  with check (app.is_hr());

create policy policy_chunks_select on policy_chunks
  for select to authenticated
  using (exists (
    select 1 from policy_docs d
    where d.id = policy_doc_id and (d.superseded_at is null or app.is_hr())
  ));

-- ----------------------------------------------------------------------------
-- Storage buckets
--
-- Private. Downloads go through short-TTL signed URLs issued by the backend
-- after it has checked case visibility (Phase 9 hardening).
-- ----------------------------------------------------------------------------

insert into storage.buckets (id, name, public)
values ('case-documents', 'case-documents', false),
       ('policy-docs', 'policy-docs', false)
on conflict (id) do nothing;
