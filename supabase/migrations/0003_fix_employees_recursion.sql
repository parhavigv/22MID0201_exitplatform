-- ============================================================================
-- Fix: infinite recursion in the employees SELECT policy
--
-- 0002_rls.sql wrote the "I can see my own manager" clause as an inline
-- subquery:
--
--     or id = (select manager_id from employees me where me.auth_user_id = auth.uid())
--
-- That subquery reads `employees`, which re-evaluates `employees_select`,
-- which runs the subquery again — Postgres aborts with
-- "infinite recursion detected in policy for relation employees" (42P17).
--
-- Every other clause in that policy calls a SECURITY DEFINER function in the
-- `app` schema, which bypasses RLS and therefore terminates. The fix is to
-- give this clause the same treatment.
--
-- Lesson for future policies on `employees`: never reference the table
-- directly inside its own policy. Always go through an app.* helper.
-- ============================================================================

create or replace function app.current_manager_id()
returns uuid
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select manager_id from employees where auth_user_id = auth.uid() and is_active
$$;

grant execute on function app.current_manager_id() to authenticated, service_role;

drop policy if exists employees_select on employees;

create policy employees_select on employees
  for select to authenticated
  using (
    app.is_hr()
    or auth_user_id = auth.uid()                 -- myself
    or manager_id = app.current_employee_id()    -- my direct reports
    or id = app.current_manager_id()             -- my own manager
  );
