-- ============================================================================
-- Migration 0011 — What IT and Finance may see and do
--
-- The shape of the permission is narrower than a manager's, and deliberately so.
--
--   READ   a case where their role owns at least one task. IT should see the
--          people they have to deprovision, and nobody else.
--   WRITE  only their own role's tasks, and only the sign-off on their own
--          stage. IT can revoke access and close IT_CLEARANCE. IT cannot
--          approve the employee's resignation letter or close Finance's stage.
--
-- Widening `can_act_on_case` would have been one line, but that function gates
-- document review and every stage sign-off — it would have let IT approve an
-- exit interview. Hence two new, tighter helpers.
--
-- Role-owned tasks carry `assignee_id = null` (see services/cases.py: only the
-- employee's own tasks get a named assignee), so the existing
-- "assignee_id = me" rule in case_tasks_update does not cover them. That is the
-- gap `app.owns_task_role` closes.
-- ============================================================================

-- Does the current user's role own any task on this case?
create or replace function app.has_role_work_on_case(target_case uuid)
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select exists (
    select 1
    from case_tasks t
    join employees me on me.auth_user_id = auth.uid() and me.is_active
    where t.case_id = target_case
      and t.owner_role::text = me.app_role::text
      and me.app_role in ('it', 'finance')
  )
$$;

-- Is this specific task owned by the current user's role?
create or replace function app.owns_task_role(target_task uuid)
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select exists (
    select 1
    from case_tasks t
    join employees me on me.auth_user_id = auth.uid() and me.is_active
    where t.id = target_task
      and t.owner_role::text = me.app_role::text
      and me.app_role in ('it', 'finance')
  )
$$;

-- Does the current user's role own this workflow stage?
create or replace function app.owns_stage(stage text)
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select exists (
    select 1
    from exit_stages s
    join employees me on me.auth_user_id = auth.uid() and me.is_active
    where s.code = stage
      and s.owner_role::text = me.app_role::text
      and me.app_role in ('it', 'finance')
  )
$$;

-- --- reading -----------------------------------------------------------------
-- Cases, and everything hanging off them, for the people they have work on.

drop policy if exists exit_cases_it_finance_select on exit_cases;
create policy exit_cases_it_finance_select on exit_cases
  for select to authenticated
  using (app.has_role_work_on_case(id));

drop policy if exists case_tasks_it_finance_select on case_tasks;
create policy case_tasks_it_finance_select on case_tasks
  for select to authenticated
  using (app.has_role_work_on_case(case_id));

drop policy if exists documents_it_finance_select on documents;
create policy documents_it_finance_select on documents
  for select to authenticated
  using (app.has_role_work_on_case(case_id));

drop policy if exists approvals_it_finance_select on approvals;
create policy approvals_it_finance_select on approvals
  for select to authenticated
  using (app.has_role_work_on_case(case_id));

-- The exiting person's name and department, so a queue is readable. Narrow:
-- only employees who actually have a case this user has work on.
drop policy if exists employees_it_finance_select on employees;
create policy employees_it_finance_select on employees
  for select to authenticated
  using (
    exists (
      select 1 from exit_cases c
      where c.employee_id = employees.id
        and app.has_role_work_on_case(c.id)
    )
  );

-- --- writing -----------------------------------------------------------------

-- Their own role's tasks: mark the clearance done.
drop policy if exists case_tasks_it_finance_update on case_tasks;
create policy case_tasks_it_finance_update on case_tasks
  for update to authenticated
  using (app.owns_task_role(id))
  with check (app.owns_task_role(id));

-- Sign-off, but only on the stage their role owns.
drop policy if exists approvals_it_finance_insert on approvals;
create policy approvals_it_finance_insert on approvals
  for insert to authenticated
  with check (
    app.owns_stage(stage_code)
    and app.has_role_work_on_case(case_id)
    and approver_id = app.current_employee_id()
  );

-- Advancing the case out of their own stage once it is signed off.
drop policy if exists exit_cases_it_finance_update on exit_cases;
create policy exit_cases_it_finance_update on exit_cases
  for update to authenticated
  using (app.owns_stage(current_stage) and app.has_role_work_on_case(id))
  with check (app.has_role_work_on_case(id));
