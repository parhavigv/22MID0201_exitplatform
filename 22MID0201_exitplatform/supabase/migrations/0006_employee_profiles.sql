-- ============================================================================
-- Migration 0006 — Extended employee profiles
--
-- Adds the data the 20 agent tasks need beyond the base employees table:
-- salary, grade, leave balance, contact details, assigned assets,
-- system access list, performance rating, and contract type.
--
-- Kept in a separate table (1-to-1 with employees) so the base employees
-- table stays clean and RLS on it is unchanged.
-- ============================================================================

create table if not exists employee_profiles (
  employee_id          uuid primary key references employees(id),

  -- Compensation (needed by Final Settlement agent)
  basic_salary         numeric(12,2)  not null default 0,
  grade                text           not null default 'L3',  -- L1..L6
  employment_type      text           not null default 'permanent',  -- permanent / contract
  notice_period_days   int            not null default 60,

  -- Leave (needed by Final Settlement agent)
  leave_balance_days   int            not null default 0,  -- accrued earned leave

  -- Contact (needed by Email Drafting agent)
  personal_email       text,
  phone                text,
  work_location        text           not null default 'Bangalore',

  -- IT assets (needed by IT Deprovisioning + Asset Return agents)
  assigned_assets      jsonb          not null default '[]',
  -- e.g. [{"type":"laptop","model":"Dell XPS 15","serial":"SN-001234","condition":"good"}]

  -- System access (needed by IT Deprovisioning + Compliance agents)
  system_access        jsonb          not null default '[]',
  -- e.g. [{"system":"GitHub","role":"admin"},{"system":"AWS Production","role":"read"}]

  -- Performance (needed by Rehire Assessment agent)
  last_performance_rating  text,       -- Exceptional / Meets / Below / PIP
  years_of_service     numeric(4,1),  -- computed from DOJ, but stored for agent queries

  updated_at           timestamptz    not null default now()
);

-- RLS: same visibility as the employees table
alter table employee_profiles enable row level security;

-- HR sees all profiles
create policy employee_profiles_hr_select on employee_profiles
  for select to authenticated
  using (
    exists (
      select 1 from employees where id = auth.uid()::text::uuid and app_role = 'hr'
    )
    or
    exists (
      select 1 from employees e where e.auth_user_id = auth.uid() and e.id = employee_profiles.employee_id
    )
    or
    exists (
      select 1 from employees me
      join employees emp on emp.manager_id = me.id
      where me.auth_user_id = auth.uid()
        and emp.id = employee_profiles.employee_id
    )
  );

-- Only backend service role writes profiles
create policy employee_profiles_service_insert on employee_profiles
  for insert to service_role with check (true);

create policy employee_profiles_service_update on employee_profiles
  for update to service_role using (true);


-- ============================================================================
-- Seed: extended profiles for all 10 demo employees
-- ============================================================================

insert into employee_profiles (
  employee_id, basic_salary, grade, employment_type, notice_period_days,
  leave_balance_days, personal_email, phone, work_location,
  assigned_assets, system_access, last_performance_rating, years_of_service
) values

-- EMP-0001 Priya Nair (HR)
(
  'a0000000-0000-4000-8000-000000000001',
  95000.00, 'L5', 'permanent', 60,
  18,
  'priya.nair.personal@gmail.com', '+91-98400-00001', 'Bangalore',
  '[
    {"type":"laptop","model":"MacBook Pro 14","serial":"MBP-HR-001","condition":"good"},
    {"type":"mobile","model":"iPhone 14","serial":"IPH-HR-001","condition":"good"}
  ]',
  '[
    {"system":"Workday HRMS","role":"admin"},
    {"system":"Darwinbox","role":"admin"},
    {"system":"GitHub (org)","role":"member"},
    {"system":"Google Workspace","role":"user"},
    {"system":"Slack","role":"user"},
    {"system":"Jira","role":"admin"}
  ]',
  'Exceptional', 7.2
),

-- EMP-0002 Arjun Menon (Engineering Manager)
(
  'a0000000-0000-4000-8000-000000000002',
  130000.00, 'L6', 'permanent', 90,
  22,
  'arjun.menon.personal@gmail.com', '+91-98400-00002', 'Bangalore',
  '[
    {"type":"laptop","model":"MacBook Pro 16","serial":"MBP-ENG-002","condition":"good"},
    {"type":"monitor","model":"Dell 27\" 4K","serial":"MON-ENG-002","condition":"good"},
    {"type":"mobile","model":"iPhone 14 Pro","serial":"IPH-ENG-002","condition":"good"}
  ]',
  '[
    {"system":"GitHub (org)","role":"admin"},
    {"system":"AWS Production","role":"admin"},
    {"system":"PagerDuty","role":"admin"},
    {"system":"Datadog","role":"admin"},
    {"system":"Google Workspace","role":"user"},
    {"system":"Slack","role":"admin"},
    {"system":"Jira","role":"admin"},
    {"system":"Confluence","role":"admin"}
  ]',
  'Exceptional', 8.7
),

-- EMP-0003 Vikram Rao (Sales Manager)
(
  'a0000000-0000-4000-8000-000000000003',
  120000.00, 'L6', 'permanent', 90,
  14,
  'vikram.rao.personal@gmail.com', '+91-98400-00003', 'Mumbai',
  '[
    {"type":"laptop","model":"Dell XPS 15","serial":"DEL-SALES-003","condition":"good"},
    {"type":"mobile","model":"Samsung Galaxy S24","serial":"SAM-SALES-003","condition":"good"}
  ]',
  '[
    {"system":"Salesforce","role":"admin"},
    {"system":"HubSpot","role":"admin"},
    {"system":"Google Workspace","role":"user"},
    {"system":"Slack","role":"user"},
    {"system":"Zoom","role":"user"},
    {"system":"Tableau","role":"viewer"}
  ]',
  'Meets Expectations', 9.1
),

-- EMP-0004 Meera Krishnan (Finance Manager)
(
  'a0000000-0000-4000-8000-000000000004',
  110000.00, 'L5', 'permanent', 60,
  20,
  'meera.krishnan.personal@gmail.com', '+91-98400-00004', 'Bangalore',
  '[
    {"type":"laptop","model":"Lenovo ThinkPad X1","serial":"LEN-FIN-004","condition":"good"},
    {"type":"monitor","model":"LG 24\" FHD","serial":"MON-FIN-004","condition":"good"}
  ]',
  '[
    {"system":"QuickBooks","role":"admin"},
    {"system":"Tally ERP","role":"admin"},
    {"system":"Google Workspace","role":"user"},
    {"system":"Slack","role":"user"},
    {"system":"Tableau","role":"admin"},
    {"system":"Workday HRMS","role":"viewer"}
  ]',
  'Meets Expectations', 6.2
),

-- EMP-0005 Kirthana Mekala (Senior Engineer — has active exit case)
(
  'a0000000-0000-4000-8000-000000000005',
  95000.00, 'L4', 'permanent', 60,
  12,
  'kirthana.mekala.personal@gmail.com', '+91-98400-00005', 'Bangalore',
  '[
    {"type":"laptop","model":"MacBook Pro 14","serial":"MBP-ENG-005","condition":"good"},
    {"type":"monitor","model":"Dell 24\" FHD","serial":"MON-ENG-005","condition":"fair"},
    {"type":"access_card","model":"Building + Server Room","serial":"ACC-ENG-005","condition":"good"}
  ]',
  '[
    {"system":"GitHub (org)","role":"admin"},
    {"system":"AWS Production","role":"read"},
    {"system":"AWS Staging","role":"admin"},
    {"system":"PagerDuty","role":"responder"},
    {"system":"Datadog","role":"editor"},
    {"system":"Google Workspace","role":"user"},
    {"system":"Slack","role":"user"},
    {"system":"Jira","role":"admin"},
    {"system":"Confluence","role":"editor"},
    {"system":"Data Warehouse (BigQuery)","role":"editor"}
  ]',
  'Exceptional', 5.4
),

-- EMP-0006 Rahul Verma (Engineer II)
(
  'a0000000-0000-4000-8000-000000000006',
  70000.00, 'L3', 'permanent', 30,
  8,
  'rahul.verma.personal@gmail.com', '+91-98400-00006', 'Bangalore',
  '[
    {"type":"laptop","model":"MacBook Air M2","serial":"MBA-ENG-006","condition":"good"}
  ]',
  '[
    {"system":"GitHub (org)","role":"member"},
    {"system":"AWS Staging","role":"read"},
    {"system":"Google Workspace","role":"user"},
    {"system":"Slack","role":"user"},
    {"system":"Jira","role":"member"},
    {"system":"Confluence","role":"viewer"}
  ]',
  'Meets Expectations', 4.1
),

-- EMP-0007 Sneha Iyer (Staff Engineer)
(
  'a0000000-0000-4000-8000-000000000007',
  110000.00, 'L5', 'permanent', 60,
  16,
  'sneha.iyer.personal@gmail.com', '+91-98400-00007', 'Hyderabad',
  '[
    {"type":"laptop","model":"MacBook Pro 14","serial":"MBP-ENG-007","condition":"good"},
    {"type":"monitor","model":"Dell 27\" 4K","serial":"MON-ENG-007","condition":"good"}
  ]',
  '[
    {"system":"GitHub (org)","role":"admin"},
    {"system":"AWS Production","role":"admin"},
    {"system":"Kubernetes (prod)","role":"admin"},
    {"system":"PagerDuty","role":"admin"},
    {"system":"Datadog","role":"admin"},
    {"system":"Google Workspace","role":"user"},
    {"system":"Slack","role":"user"},
    {"system":"Jira","role":"admin"}
  ]',
  'Exceptional', 7.0
),

-- EMP-0008 Anita Desai (Account Executive)
(
  'a0000000-0000-4000-8000-000000000008',
  75000.00, 'L3', 'permanent', 30,
  5,
  'anita.desai.personal@gmail.com', '+91-98400-00008', 'Mumbai',
  '[
    {"type":"laptop","model":"Dell XPS 13","serial":"DEL-SALES-008","condition":"good"},
    {"type":"mobile","model":"iPhone 13","serial":"IPH-SALES-008","condition":"good"}
  ]',
  '[
    {"system":"Salesforce","role":"standard"},
    {"system":"HubSpot","role":"user"},
    {"system":"Google Workspace","role":"user"},
    {"system":"Slack","role":"user"},
    {"system":"Zoom","role":"user"}
  ]',
  'Meets Expectations', 3.5
),

-- EMP-0009 Karan Shah (Sales Development Rep)
(
  'a0000000-0000-4000-8000-000000000009',
  55000.00, 'L2', 'permanent', 30,
  3,
  'karan.shah.personal@gmail.com', '+91-98400-00009', 'Delhi',
  '[
    {"type":"laptop","model":"HP EliteBook","serial":"HP-SALES-009","condition":"good"}
  ]',
  '[
    {"system":"Salesforce","role":"standard"},
    {"system":"LinkedIn Sales Navigator","role":"user"},
    {"system":"Google Workspace","role":"user"},
    {"system":"Slack","role":"user"}
  ]',
  'Meets Expectations', 2.6
),

-- EMP-0010 Deepak Joshi (Financial Analyst)
(
  'a0000000-0000-4000-8000-00000000000a',
  68000.00, 'L3', 'permanent', 30,
  10,
  'deepak.joshi.personal@gmail.com', '+91-98400-00010', 'Bangalore',
  '[
    {"type":"laptop","model":"Lenovo ThinkPad E14","serial":"LEN-FIN-010","condition":"good"}
  ]',
  '[
    {"system":"QuickBooks","role":"analyst"},
    {"system":"Tally ERP","role":"viewer"},
    {"system":"Tableau","role":"creator"},
    {"system":"Google Workspace","role":"user"},
    {"system":"Slack","role":"user"}
  ]',
  'Meets Expectations', 3.9
)

on conflict (employee_id) do update set
  basic_salary             = excluded.basic_salary,
  grade                    = excluded.grade,
  employment_type          = excluded.employment_type,
  notice_period_days       = excluded.notice_period_days,
  leave_balance_days       = excluded.leave_balance_days,
  personal_email           = excluded.personal_email,
  phone                    = excluded.phone,
  work_location            = excluded.work_location,
  assigned_assets          = excluded.assigned_assets,
  system_access            = excluded.system_access,
  last_performance_rating  = excluded.last_performance_rating,
  years_of_service         = excluded.years_of_service,
  updated_at               = now();
