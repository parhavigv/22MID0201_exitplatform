-- ============================================================================
-- Seed data
-- Phase 0
--
-- Two parts:
--   1. Reference data (stages, document types, task templates) — REQUIRED in
--      every environment including production. This is workflow definition.
--   2. Demo employees + auth users — LOCAL/DEV ONLY. The `demo data` section
--      is guarded; do not run it against the pilot database.
--
-- IDEMPOTENT. Safe to run any number of times: reference rows are upserted,
-- and demo people reuse their existing auth account rather than failing on a
-- duplicate key. Re-running refreshes the data and resets the demo password.
--
-- Run with:  python backend/scripts/apply_migrations.py --seed
-- ============================================================================

-- ============================================================================
-- PART 1 — Reference data (all environments)
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Stages. SLA days are measured from when the case enters the stage.
-- ----------------------------------------------------------------------------

insert into exit_stages (code, name, description, owner_role, sla_days, sort_order) values
  ('RESIGNATION_SUBMITTED', 'Resignation Submitted',
   'Employee has submitted their resignation and it is recorded.', 'employee', 1, 1),
  ('MANAGER_ACK', 'Manager Acknowledgement',
   'Reporting manager acknowledges the resignation and confirms the last working day.', 'manager', 2, 2),
  ('KT_PLANNING', 'Knowledge Transfer Planning',
   'Manager identifies a successor and agrees the KT topics to be covered.', 'manager', 3, 3),
  ('KT_EXECUTION', 'Knowledge Transfer Execution',
   'Employee documents their handover and completes KT sessions.', 'employee', 10, 4),
  ('IT_CLEARANCE', 'IT Clearance',
   'Return of IT assets, access revocation, and NDA acknowledgement.', 'it', 5, 5),
  ('FINANCE_CLEARANCE', 'Finance Clearance',
   'Outstanding advances, reimbursements, and no-dues confirmation.', 'finance', 5, 6),
  ('ADMIN_ASSET_RETURN', 'Admin & Asset Return',
   'Return of ID card, access card, and any facilities-issued equipment.', 'admin', 5, 7),
  ('EXIT_INTERVIEW', 'Exit Interview',
   'Employee completes the exit interview; HR reviews the responses.', 'hr', 3, 8),
  ('FINAL_SETTLEMENT', 'Full & Final Settlement',
   'Final salary, leave encashment, and deductions are computed and paid.', 'finance', 15, 9),
  ('RELIEVING_LETTER', 'Relieving Letter',
   'Relieving and experience letters are issued. Case closes.', 'hr', 3, 10)
on conflict (code) do update set
  name        = excluded.name,
  description = excluded.description,
  owner_role  = excluded.owner_role,
  sla_days    = excluded.sla_days,
  sort_order  = excluded.sort_order;

-- ----------------------------------------------------------------------------
-- Document types. `is_required` drives the agent's missing-document checks.
-- ----------------------------------------------------------------------------

insert into document_types (code, name, description, stage_code, owner_role, is_required, sort_order) values
  ('RESIGNATION_LETTER', 'Resignation Letter',
   'Signed resignation letter stating the intended last working day.',
   'RESIGNATION_SUBMITTED', 'employee', true, 1),
  ('KT_DOCUMENT', 'Knowledge Transfer Document',
   'Written handover covering systems, credentials owned, runbooks, and open work.',
   'KT_EXECUTION', 'employee', true, 2),
  ('NDA_ACKNOWLEDGEMENT', 'NDA Acknowledgement',
   'Signed confirmation that post-employment confidentiality obligations are understood.',
   'IT_CLEARANCE', 'employee', true, 3),
  ('ASSET_RETURN_FORM', 'Asset Return Form',
   'Itemised list of returned hardware, signed off by IT or Admin.',
   'ADMIN_ASSET_RETURN', 'employee', true, 4),
  ('NO_DUES_FINANCE', 'Finance No-Dues Certificate',
   'Confirmation that no advances or reimbursements are outstanding.',
   'FINANCE_CLEARANCE', 'finance', true, 5),
  ('FINAL_SETTLEMENT_STATEMENT', 'Full & Final Settlement Statement',
   'Breakdown of final pay, leave encashment, and deductions.',
   'FINAL_SETTLEMENT', 'finance', true, 6),
  ('RELIEVING_LETTER', 'Relieving Letter',
   'Formal confirmation of release from employment.',
   'RELIEVING_LETTER', 'hr', true, 7),
  ('EXPERIENCE_LETTER', 'Experience Letter',
   'Statement of tenure and designation held.',
   'RELIEVING_LETTER', 'hr', false, 8)
on conflict (code) do update set
  name        = excluded.name,
  description = excluded.description,
  stage_code  = excluded.stage_code,
  owner_role  = excluded.owner_role,
  is_required = excluded.is_required,
  sort_order  = excluded.sort_order;

-- ----------------------------------------------------------------------------
-- Task templates. Every new case expands these into case_tasks.
-- offset_days is relative to the resignation date.
-- ----------------------------------------------------------------------------

insert into task_templates (stage_code, title, description, owner_role, doc_type_code, offset_days, sort_order) values
  -- Stage 1
  ('RESIGNATION_SUBMITTED', 'Upload signed resignation letter',
   'Attach your signed resignation letter stating your intended last working day.',
   'employee', 'RESIGNATION_LETTER', 1, 1),
  ('RESIGNATION_SUBMITTED', 'Confirm personal contact details',
   'Provide a personal email and phone number for post-exit correspondence.',
   'employee', null, 2, 2),

  -- Stage 2
  ('MANAGER_ACK', 'Acknowledge resignation',
   'Confirm receipt of the resignation and agree the last working day.',
   'manager', null, 3, 3),
  ('MANAGER_ACK', 'Confirm notice period and any waiver',
   'Record whether the full notice period applies or part of it is waived.',
   'manager', null, 3, 4),

  -- Stage 3
  ('KT_PLANNING', 'Nominate successor or interim owner',
   'Identify who takes over each area of responsibility.',
   'manager', null, 5, 5),
  ('KT_PLANNING', 'Agree KT topic list',
   'Agree with the employee the list of systems, processes, and relationships to hand over.',
   'manager', null, 6, 6),

  -- Stage 4
  ('KT_EXECUTION', 'Upload knowledge transfer document',
   'Document systems owned, credentials held, runbooks, open work, and key contacts.',
   'employee', 'KT_DOCUMENT', 14, 7),
  ('KT_EXECUTION', 'Complete KT sessions with successor',
   'Walk the successor through each agreed topic and record completion.',
   'employee', null, 18, 8),
  ('KT_EXECUTION', 'Hand over shared credentials and ownership',
   'Transfer ownership of shared accounts, mailing lists, and on-call rotations.',
   'employee', null, 18, 9),

  -- Stage 5
  ('IT_CLEARANCE', 'Return laptop and IT-issued hardware',
   'Return all company laptops, monitors, docks, and peripherals.',
   'employee', null, 25, 10),
  ('IT_CLEARANCE', 'Sign NDA acknowledgement',
   'Confirm you understand your post-employment confidentiality obligations.',
   'employee', 'NDA_ACKNOWLEDGEMENT', 25, 11),
  ('IT_CLEARANCE', 'Revoke system access',
   'Disable SSO, VPN, email, code repositories, and production access.',
   'it', null, 28, 12),

  -- Stage 6
  ('FINANCE_CLEARANCE', 'Settle outstanding advances',
   'Clear any travel advances or salary advances.',
   'employee', null, 25, 13),
  ('FINANCE_CLEARANCE', 'Submit pending reimbursement claims',
   'Submit any remaining expense claims before the cut-off.',
   'employee', null, 25, 14),
  ('FINANCE_CLEARANCE', 'Issue no-dues certificate',
   'Confirm no financial obligations remain outstanding.',
   'finance', 'NO_DUES_FINANCE', 28, 15),

  -- Stage 7
  ('ADMIN_ASSET_RETURN', 'Return ID and access cards',
   'Hand back the employee ID card and building access card.',
   'employee', null, 28, 16),
  ('ADMIN_ASSET_RETURN', 'Vacate desk and clear locker',
   'Remove personal belongings and return locker keys.',
   'employee', null, 28, 17),
  ('ADMIN_ASSET_RETURN', 'Sign off asset return form',
   'Verify the returned asset list and sign it off.',
   'admin', 'ASSET_RETURN_FORM', 29, 18),

  -- Stage 8
  ('EXIT_INTERVIEW', 'Complete exit interview',
   'Share your feedback on the role, team, and organisation.',
   'employee', null, 27, 19),
  ('EXIT_INTERVIEW', 'Review exit interview responses',
   'Read the submitted responses and flag anything needing follow-up.',
   'hr', null, 30, 20),

  -- Stage 9
  ('FINAL_SETTLEMENT', 'Compute full and final settlement',
   'Calculate final salary, leave encashment, gratuity, and deductions.',
   'finance', null, 35, 21),
  ('FINAL_SETTLEMENT', 'Share settlement statement with employee',
   'Send the settlement breakdown and obtain acknowledgement.',
   'finance', 'FINAL_SETTLEMENT_STATEMENT', 40, 22),

  -- Stage 10
  ('RELIEVING_LETTER', 'Issue relieving letter',
   'Generate and send the relieving letter.',
   'hr', 'RELIEVING_LETTER', 42, 23),
  ('RELIEVING_LETTER', 'Issue experience letter',
   'Generate and send the experience letter stating tenure and designation.',
   'hr', 'EXPERIENCE_LETTER', 42, 24)
on conflict (stage_code, sort_order) do update set
  title         = excluded.title,
  description   = excluded.description,
  owner_role    = excluded.owner_role,
  doc_type_code = excluded.doc_type_code,
  offset_days   = excluded.offset_days;


-- ============================================================================
-- PART 2 — Demo data (LOCAL / DEV ONLY)
--
-- Creates 10 employees across 3 departments with a real reporting hierarchy,
-- each with a Supabase Auth account.
--
-- All demo accounts use the password: ExitDemo!2026
--
-- Guard: set `select set_config('app.seed_demo', 'off', false);` before running
-- this file in any environment that must not receive demo users.
-- ============================================================================

do $$
declare
  demo_password constant text := 'ExitDemo!2026';
  instance      constant uuid := '00000000-0000-0000-0000-000000000000';

  -- Fixed UUIDs so tests can reference people by constant.
  --
  -- This seed deliberately creates one HR partner, one manager, and one
  -- exiting employee — the smallest cast that still exercises all three
  -- roles. The remaining demo population (ten more exiting employees spread
  -- across the workflow stages) comes from scripts/seed_more_employees.py,
  -- which is re-runnable and easier to adjust than this file. Everyone it
  -- adds reports to Arjun.
  --
  -- IT and Finance became sign-in roles in migration 0010. Every case already
  -- carried their tasks ("Revoke system access", "Issue no-dues certificate");
  -- until then there was nobody to do them and HR signed off on their behalf.
  hr_priya    constant uuid := 'a0000000-0000-4000-8000-000000000001';
  mgr_arjun   constant uuid := 'a0000000-0000-4000-8000-000000000002';
  emp_kirthana constant uuid := 'a0000000-0000-4000-8000-000000000005';
  it_rakesh   constant uuid := 'a0000000-0000-4000-8000-00000000000b';
  fin_lakshmi constant uuid := 'a0000000-0000-4000-8000-00000000000c';

  person record;
  auth_id uuid;
  created integer := 0;
  reused  integer := 0;
begin
  if current_setting('app.seed_demo', true) = 'off' then
    raise notice 'app.seed_demo is off — skipping demo data';
    return;
  end if;

  -- People, in dependency order (managers before their reports).
  for person in
    select * from (values
      (hr_priya,     'EMP-0001', 'Priya Nair',      'priya.nair@example.com',      'Human Resources', 'HR Business Partner',   date '2019-04-15', null::uuid,  'hr'::app_role),
      (mgr_arjun,    'EMP-0002', 'Arjun Menon',     'arjun.menon@example.com',     'Engineering',     'Engineering Manager',   date '2018-01-08', null::uuid,  'manager'::app_role),
      (emp_kirthana, 'EMP-0005', 'Kirthana Mekala', 'kirthana.mekala@example.com', 'Engineering',     'Senior Engineer',       date '2021-03-01', mgr_arjun,   'employee'::app_role),
      (it_rakesh,    'EMP-0021', 'Rakesh Iyer',     'rakesh.iyer@example.com',     'IT',              'IT Systems Administrator', date '2019-02-11', null::uuid, 'it'::app_role),
      (fin_lakshmi,  'EMP-0022', 'Lakshmi Menon',   'lakshmi.menon@example.com',   'Finance',         'Payroll & Settlements Lead', date '2018-07-30', null::uuid, 'finance'::app_role)
    ) as t(emp_id, emp_code, full_name, email, department, designation, doj, manager_id, app_role)
  loop
    -- Idempotent: reuse the existing auth account if this email is already
    -- registered, so re-running the seed refreshes data instead of failing on
    -- a duplicate key.
    select id into auth_id from auth.users where email = person.email;

    if auth_id is null then
      auth_id := gen_random_uuid();
      created := created + 1;

      insert into auth.users (
        instance_id, id, aud, role, email, encrypted_password,
        email_confirmed_at, raw_app_meta_data, raw_user_meta_data,
        created_at, updated_at,
        confirmation_token, email_change, email_change_token_new, recovery_token
      ) values (
        instance, auth_id, 'authenticated', 'authenticated', person.email,
        crypt(demo_password, gen_salt('bf')),
        now(),
        '{"provider":"email","providers":["email"]}'::jsonb,
        jsonb_build_object('full_name', person.full_name),
        now(), now(),
        '', '', '', ''
      );

      -- Required for email/password sign-in on current Supabase Auth.
      insert into auth.identities (
        id, user_id, provider_id, identity_data, provider,
        last_sign_in_at, created_at, updated_at
      ) values (
        gen_random_uuid(), auth_id, auth_id::text,
        jsonb_build_object('sub', auth_id::text, 'email', person.email, 'email_verified', true),
        'email', now(), now(), now()
      );
    else
      reused := reused + 1;
      -- Reset the password so the documented demo credentials always work,
      -- even if someone changed it while testing.
      update auth.users
         set encrypted_password = crypt(demo_password, gen_salt('bf')),
             email_confirmed_at = coalesce(email_confirmed_at, now()),
             updated_at         = now()
       where id = auth_id;
    end if;

    insert into employees (
      id, auth_user_id, emp_code, full_name, work_email,
      department, designation, date_of_joining, manager_id, app_role
    ) values (
      person.emp_id, auth_id, person.emp_code, person.full_name, person.email,
      person.department, person.designation, person.doj, person.manager_id, person.app_role
    )
    on conflict (id) do update set
      auth_user_id    = excluded.auth_user_id,
      emp_code        = excluded.emp_code,
      full_name       = excluded.full_name,
      work_email      = excluded.work_email,
      department      = excluded.department,
      designation     = excluded.designation,
      date_of_joining = excluded.date_of_joining,
      manager_id      = excluded.manager_id,
      app_role        = excluded.app_role,
      is_active       = true;
  end loop;

  raise notice
    'Demo employees ready: % created, % refreshed. Password for all: %',
    created, reused, demo_password;
end
$$;


-- ============================================================================
-- PART 3 — A demo exit case (LOCAL / DEV ONLY)
--
-- Kirthana Mekala, mid-notice-period, so every dashboard has something real to
-- show: tasks part-done, two overdue, a document waiting on her manager.
--
-- Dates are relative to today, so the demo never goes stale.
-- Idempotent: the case is rebuilt from scratch each run.
-- ============================================================================

-- NOTE: every local variable is v_-prefixed. A plpgsql variable named `case_id`
-- would shadow the column of the same name, making `where case_id = case_id`
-- always true — silently updating every row in the table.
do $$
declare
  v_subject   constant uuid := 'a0000000-0000-4000-8000-000000000005';  -- Kirthana
  -- Arjun is both manager and interim successor. Everyone else in this demo
  -- is themselves exiting, so the manager is the only person who can actually
  -- receive a handover.
  v_successor constant uuid := 'a0000000-0000-4000-8000-000000000002';  -- Arjun
  v_manager   constant uuid := 'a0000000-0000-4000-8000-000000000002';  -- Arjun
  v_resigned  constant date := current_date - 24;
  v_last_day  constant date := current_date + 36;
  v_case_id   uuid;
  v_kt_id     uuid;
begin
  if current_setting('app.seed_demo', true) = 'off' then
    return;
  end if;

  -- Leave an existing case alone.
  --
  -- This used to delete and rebuild the case every run, which was harmless
  -- while the seed was the only thing that ever wrote data. It stopped being
  -- harmless once people started using the app: `start.bat` runs this seed on
  -- every startup, the delete cascades to documents, and the rebuilt case came
  -- back with its tasks marked complete and the documents behind them gone.
  -- Every restart quietly corrupted the demo, and `verify_data.py` caught it
  -- three separate times before anyone noticed the pattern.
  --
  -- To deliberately rebuild it, delete the case first and re-run this.
  if exists (select 1 from exit_cases where employee_id = v_subject) then
    raise notice 'demo case already exists for the subject — left untouched';
    return;
  end if;

  insert into exit_cases (
    employee_id, exit_type, reason, resignation_date, last_working_day,
    notice_period_days, current_stage, status, created_by
  ) values (
    v_subject, 'resignation', 'Accepted an offer elsewhere.',
    v_resigned, v_last_day, 60, 'KT_EXECUTION', 'active', v_subject
  )
  returning id into v_case_id;

  -- Expand the template into real tasks. This is what the Phase 2
  -- case-creation service will do when a resignation is submitted.
  insert into case_tasks (
    case_id, stage_code, template_id, title, description, owner_role,
    assignee_id, doc_type_code, due_date, sort_order
  )
  select
    v_case_id, t.stage_code, t.id, t.title, t.description, t.owner_role,
    case when t.owner_role = 'employee' then v_subject end,
    t.doc_type_code,
    least(v_resigned + t.offset_days, v_last_day),
    t.sort_order
  from task_templates t
  where t.is_active;

  -- Everything up to knowledge transfer is already cleared.
  update case_tasks
     set status       = 'completed',
         completed_at = now() - interval '5 days',
         completed_by = coalesce(assignee_id, v_subject)
   where case_id = v_case_id
     and stage_code in ('RESIGNATION_SUBMITTED', 'MANAGER_ACK', 'KT_PLANNING');

  -- The KT document is in progress and overdue — the case's live problem.
  update case_tasks
     set status = 'in_progress', sla_breached = true
   where case_id = v_case_id and doc_type_code = 'KT_DOCUMENT';

  -- NDA acknowledgement is overdue too, which blocks IT clearance.
  update case_tasks
     set sla_breached = true
   where case_id = v_case_id and doc_type_code = 'NDA_ACKNOWLEDGEMENT';

  -- Finance is blocked waiting on someone else.
  update case_tasks
     set status = 'blocked'
   where case_id = v_case_id and doc_type_code = 'NO_DUES_FINANCE';

  -- Stage sign-offs already given.
  insert into approvals (case_id, stage_code, approver_id, decision, comment, decided_at)
  values
    (v_case_id, 'MANAGER_ACK', v_manager, 'approved',
     'Last working day confirmed. Full notice period applies.', now() - interval '21 days'),
    (v_case_id, 'KT_PLANNING', v_manager, 'approved',
     'Arjun Menon takes over billing as interim owner. Topic list agreed.', now() - interval '18 days');

  -- Knowledge transfer, part-done with one real gap.
  insert into kt_records (case_id, successor_id, overall_status)
  values (v_case_id, v_successor, 'in_progress')
  returning id into v_kt_id;

  insert into kt_items (kt_record_id, topic, detail, coverage_status, gap_note, sort_order)
  values
    (v_kt_id, 'Billing service ownership',
     'Deploys, on-call runbook, and the reconciliation cron.', 'documented', null, 1),
    (v_kt_id, 'Payment gateway vendor relationship',
     'Primary contact and escalation path.', 'in_progress', null, 2),
    (v_kt_id, 'Data warehouse access grants', null, 'gap',
     'No named successor for grant approvals after the last working day.', 3),
    (v_kt_id, 'Quarterly audit export process', null, 'not_started', null, 4);

  -- An empty interview, so the employee has a form to fill in.
  insert into exit_interviews (case_id) values (v_case_id);

  raise notice 'Demo case ready for Kirthana Mekala: % days of notice left.',
    v_last_day - current_date;
end
$$;
