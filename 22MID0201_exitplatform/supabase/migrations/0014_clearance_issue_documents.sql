-- ============================================================================
-- Migration 0014 — Let Finance issue the documents it owns
--
-- 0011 gave IT and Finance SELECT on documents and stopped there, because at
-- the time they only ever needed to read. They now have tasks that produce a
-- document — "Issue no-dues certificate", "Share settlement statement" — and
-- `documents_insert` requires `app.can_read_case`, which is manager-or-HR
-- only. So Finance was assigned work it was structurally incapable of doing:
-- the upload failed with a bare RLS violation.
--
-- The obvious fix is to widen `can_read_case`, and it is the wrong one for the
-- same reason 0011 gave: that function gates document review and every stage
-- sign-off, so widening it would let IT approve an exit interview. This adds a
-- third narrow helper instead, in the same style.
--
-- What this permits, and nothing more: insert a document whose *type* your own
-- role owns, on a case where your role already has work, under your own name.
-- Finance cannot issue a relieving letter. Nobody can issue an employee-owned
-- document this way, because `document_types.owner_role` for those is
-- 'employee' and no signed-in user has that role here.
-- ============================================================================

-- Does the current user's role own this document type?
create or replace function app.owns_document_type(target_code text)
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select exists (
    select 1
    from document_types dt
    join employees me on me.auth_user_id = auth.uid() and me.is_active
    where dt.code = target_code
      and dt.owner_role::text = me.app_role::text
      and me.app_role in ('it', 'finance')
  )
$$;

drop policy if exists documents_it_finance_issue on documents;
create policy documents_it_finance_issue on documents
  for insert to authenticated
  with check (
    uploaded_by = app.current_employee_id()
    and app.has_role_work_on_case(case_id)
    and app.owns_document_type(doc_type_code)
  );

grant execute on all functions in schema app to authenticated, service_role;
