/**
 * Mock fixtures for frontend-first development.
 *
 * Dates are generated relative to today so the demo always looks live — a case
 * mid-notice-period, some tasks overdue, some documents awaiting review.
 *
 * Deleted once the backend lands; `api.ts` is the only file that imports this.
 */

import type {
  AgentAction,
  Approval,
  CaseDetailView,
  CaseDocument,
  CaseSummary,
  CaseTask,
  DocumentType,
  Employee,
  ExitCase,
  ExitInterview,
  ExitInterviewQuestion,
  ExitStage,
  KtRecord,
  MyExitView,
  StageCode,
} from './types'

const DAY = 86_400_000

function iso(offsetDays: number): string {
  return new Date(Date.now() + offsetDays * DAY).toISOString().slice(0, 10)
}

function stamp(offsetDays: number): string {
  return new Date(Date.now() + offsetDays * DAY).toISOString()
}

export const STAGES: ExitStage[] = [
  {
    code: 'RESIGNATION_SUBMITTED',
    name: 'Resignation Submitted',
    description: 'Employee has submitted their resignation and it is recorded.',
    owner_role: 'employee',
    sla_days: 1,
    sort_order: 1,
  },
  {
    code: 'MANAGER_ACK',
    name: 'Manager Acknowledgement',
    description: 'Reporting manager acknowledges the resignation and confirms the last working day.',
    owner_role: 'manager',
    sla_days: 2,
    sort_order: 2,
  },
  {
    code: 'KT_PLANNING',
    name: 'Knowledge Transfer Planning',
    description: 'Manager identifies a successor and agrees the KT topics to be covered.',
    owner_role: 'manager',
    sla_days: 3,
    sort_order: 3,
  },
  {
    code: 'KT_EXECUTION',
    name: 'Knowledge Transfer Execution',
    description: 'Employee documents their handover and completes KT sessions.',
    owner_role: 'employee',
    sla_days: 10,
    sort_order: 4,
  },
  {
    code: 'IT_CLEARANCE',
    name: 'IT Clearance',
    description: 'Return of IT assets, access revocation, and NDA acknowledgement.',
    owner_role: 'it',
    sla_days: 5,
    sort_order: 5,
  },
  {
    code: 'FINANCE_CLEARANCE',
    name: 'Finance Clearance',
    description: 'Outstanding advances, reimbursements, and no-dues confirmation.',
    owner_role: 'finance',
    sla_days: 5,
    sort_order: 6,
  },
  {
    code: 'ADMIN_ASSET_RETURN',
    name: 'Admin & Asset Return',
    description: 'Return of ID card, access card, and any facilities-issued equipment.',
    owner_role: 'admin',
    sla_days: 5,
    sort_order: 7,
  },
  {
    code: 'EXIT_INTERVIEW',
    name: 'Exit Interview',
    description: 'Employee completes the exit interview; HR reviews the responses.',
    owner_role: 'hr',
    sla_days: 3,
    sort_order: 8,
  },
  {
    code: 'FINAL_SETTLEMENT',
    name: 'Full & Final Settlement',
    description: 'Final salary, leave encashment, and deductions are computed and paid.',
    owner_role: 'finance',
    sla_days: 15,
    sort_order: 9,
  },
  {
    code: 'RELIEVING_LETTER',
    name: 'Relieving Letter',
    description: 'Relieving and experience letters are issued. Case closes.',
    owner_role: 'hr',
    sla_days: 3,
    sort_order: 10,
  },
]

export const DOCUMENT_TYPES: DocumentType[] = [
  { code: 'RESIGNATION_LETTER', name: 'Resignation Letter', description: 'Signed resignation letter stating the intended last working day.', stage_code: 'RESIGNATION_SUBMITTED', owner_role: 'employee', is_required: true, sort_order: 1 },
  { code: 'KT_DOCUMENT', name: 'Knowledge Transfer Document', description: 'Written handover covering systems, credentials owned, runbooks, and open work.', stage_code: 'KT_EXECUTION', owner_role: 'employee', is_required: true, sort_order: 2 },
  { code: 'NDA_ACKNOWLEDGEMENT', name: 'NDA Acknowledgement', description: 'Signed confirmation that post-employment confidentiality obligations are understood.', stage_code: 'IT_CLEARANCE', owner_role: 'employee', is_required: true, sort_order: 3 },
  { code: 'ASSET_RETURN_FORM', name: 'Asset Return Form', description: 'Itemised list of returned hardware, signed off by IT or Admin.', stage_code: 'ADMIN_ASSET_RETURN', owner_role: 'employee', is_required: true, sort_order: 4 },
  { code: 'NO_DUES_FINANCE', name: 'Finance No-Dues Certificate', description: 'Confirmation that no advances or reimbursements are outstanding.', stage_code: 'FINANCE_CLEARANCE', owner_role: 'finance', is_required: true, sort_order: 5 },
  { code: 'FINAL_SETTLEMENT_STATEMENT', name: 'Full & Final Settlement Statement', description: 'Breakdown of final pay, leave encashment, and deductions.', stage_code: 'FINAL_SETTLEMENT', owner_role: 'finance', is_required: true, sort_order: 6 },
  { code: 'RELIEVING_LETTER', name: 'Relieving Letter', description: 'Formal confirmation of release from employment.', stage_code: 'RELIEVING_LETTER', owner_role: 'hr', is_required: true, sort_order: 7 },
  { code: 'EXPERIENCE_LETTER', name: 'Experience Letter', description: 'Statement of tenure and designation held.', stage_code: 'RELIEVING_LETTER', owner_role: 'hr', is_required: false, sort_order: 8 },
]

/* -------------------------------------------------------------------------- */
/* People — mirrors supabase/seed.sql                                          */
/* -------------------------------------------------------------------------- */

const E = (
  id: string,
  emp_code: string,
  full_name: string,
  work_email: string,
  department: string,
  designation: string,
  date_of_joining: string,
  manager_id: string | null,
  app_role: Employee['app_role'],
): Employee => ({
  id,
  emp_code,
  full_name,
  work_email,
  department,
  designation,
  date_of_joining,
  manager_id,
  app_role,
  is_active: true,
})

export const EMPLOYEES: Employee[] = [
  E('a0000000-0000-4000-8000-000000000001', 'EMP-0001', 'Priya Nair', 'priya.nair@example.com', 'Human Resources', 'HR Business Partner', '2019-04-15', null, 'hr'),
  E('a0000000-0000-4000-8000-000000000002', 'EMP-0002', 'Arjun Menon', 'arjun.menon@example.com', 'Engineering', 'Engineering Manager', '2018-01-08', null, 'manager'),
  E('a0000000-0000-4000-8000-000000000003', 'EMP-0003', 'Vikram Rao', 'vikram.rao@example.com', 'Sales', 'Regional Sales Head', '2017-09-01', null, 'manager'),
  E('a0000000-0000-4000-8000-000000000004', 'EMP-0004', 'Meera Krishnan', 'meera.krishnan@example.com', 'Finance', 'Finance Manager', '2020-06-22', null, 'manager'),
  E('a0000000-0000-4000-8000-000000000005', 'EMP-0005', 'Kirthana Mekala', 'kirthana.mekala@example.com', 'Engineering', 'Senior Engineer', '2021-03-01', 'a0000000-0000-4000-8000-000000000002', 'employee'),
  E('a0000000-0000-4000-8000-000000000006', 'EMP-0006', 'Rahul Verma', 'rahul.verma@example.com', 'Engineering', 'Engineer II', '2022-07-11', 'a0000000-0000-4000-8000-000000000002', 'employee'),
  E('a0000000-0000-4000-8000-000000000007', 'EMP-0007', 'Sneha Iyer', 'sneha.iyer@example.com', 'Engineering', 'Staff Engineer', '2019-11-04', 'a0000000-0000-4000-8000-000000000002', 'employee'),
  E('a0000000-0000-4000-8000-000000000008', 'EMP-0008', 'Anita Desai', 'anita.desai@example.com', 'Sales', 'Account Executive', '2023-02-13', 'a0000000-0000-4000-8000-000000000003', 'employee'),
  E('a0000000-0000-4000-8000-000000000009', 'EMP-0009', 'Karan Shah', 'karan.shah@example.com', 'Sales', 'Sales Development Rep', '2024-01-29', 'a0000000-0000-4000-8000-000000000003', 'employee'),
  E('a0000000-0000-4000-8000-00000000000a', 'EMP-0010', 'Deepak Joshi', 'deepak.joshi@example.com', 'Finance', 'Financial Analyst', '2022-10-17', 'a0000000-0000-4000-8000-000000000004', 'employee'),
]

export const byId = (id: string) => EMPLOYEES.find((e) => e.id === id) ?? null

/* -------------------------------------------------------------------------- */
/* Cases                                                                       */
/* -------------------------------------------------------------------------- */

const KIRTHANA = 'a0000000-0000-4000-8000-000000000005'
const ANITA = 'a0000000-0000-4000-8000-000000000008'
const DEEPAK = 'a0000000-0000-4000-8000-00000000000a'
const SNEHA = 'a0000000-0000-4000-8000-000000000007'

const CASES: ExitCase[] = [
  {
    // Mid-notice, KT overdue. The demo's main case.
    id: 'c0000000-0000-4000-8000-000000000001',
    employee_id: KIRTHANA,
    exit_type: 'resignation',
    reason: 'Accepted an offer elsewhere.',
    resignation_date: iso(-24),
    last_working_day: iso(36),
    notice_period_days: 60,
    current_stage: 'KT_EXECUTION',
    status: 'active',
    risk_score: 72,
    risk_assessed_at: stamp(-2),
    created_at: stamp(-24),
  },
  {
    // Nearly finished.
    id: 'c0000000-0000-4000-8000-000000000002',
    employee_id: ANITA,
    exit_type: 'resignation',
    reason: 'Relocating.',
    resignation_date: iso(-52),
    last_working_day: iso(8),
    notice_period_days: 60,
    current_stage: 'FINAL_SETTLEMENT',
    status: 'active',
    risk_score: 24,
    risk_assessed_at: stamp(-9),
    created_at: stamp(-52),
  },
  {
    // Just opened, manager has not acknowledged — SLA about to breach.
    id: 'c0000000-0000-4000-8000-000000000003',
    employee_id: DEEPAK,
    exit_type: 'resignation',
    reason: null,
    resignation_date: iso(-4),
    last_working_day: iso(26),
    notice_period_days: 30,
    current_stage: 'MANAGER_ACK',
    status: 'active',
    risk_score: null,
    risk_assessed_at: null,
    created_at: stamp(-4),
  },
  {
    // Closed, for the completed filter.
    id: 'c0000000-0000-4000-8000-000000000004',
    employee_id: SNEHA,
    exit_type: 'retirement',
    reason: 'Retirement.',
    resignation_date: iso(-120),
    last_working_day: iso(-30),
    notice_period_days: 90,
    current_stage: 'RELIEVING_LETTER',
    status: 'completed',
    risk_score: 41,
    risk_assessed_at: stamp(-80),
    created_at: stamp(-120),
  },
]

/* Tasks for the main case. Deliberately mixed: two overdue, one blocked on
   someone else, several already cleared. */
const T = (
  n: number,
  stage_code: StageCode,
  title: string,
  owner_role: CaseTask['owner_role'],
  status: CaseTask['status'],
  dueOffset: number | null,
  opts: Partial<CaseTask> = {},
): CaseTask => ({
  id: `t0000000-0000-4000-8000-${String(n).padStart(12, '0')}`,
  case_id: 'c0000000-0000-4000-8000-000000000001',
  stage_code,
  title,
  description: null,
  owner_role,
  assignee_id: owner_role === 'employee' ? KIRTHANA : null,
  doc_type_code: null,
  due_date: dueOffset === null ? null : iso(dueOffset),
  status,
  origin: 'template',
  sla_breached: dueOffset !== null && dueOffset < 0 && status !== 'completed',
  completed_at: status === 'completed' ? stamp(-10) : null,
  sort_order: n,
  ...opts,
})

const MAIN_TASKS: CaseTask[] = [
  T(1, 'RESIGNATION_SUBMITTED', 'Upload signed resignation letter', 'employee', 'completed', -23, { doc_type_code: 'RESIGNATION_LETTER' }),
  T(2, 'RESIGNATION_SUBMITTED', 'Confirm personal contact details', 'employee', 'completed', -22),
  T(3, 'MANAGER_ACK', 'Acknowledge resignation', 'manager', 'completed', -21),
  T(4, 'MANAGER_ACK', 'Confirm notice period and any waiver', 'manager', 'completed', -21),
  T(5, 'KT_PLANNING', 'Nominate successor or interim owner', 'manager', 'completed', -19),
  T(6, 'KT_PLANNING', 'Agree KT topic list', 'manager', 'completed', -18),
  T(7, 'KT_EXECUTION', 'Upload knowledge transfer document', 'employee', 'in_progress', -2, { doc_type_code: 'KT_DOCUMENT', description: 'Document systems owned, credentials held, runbooks, open work, and key contacts.' }),
  T(8, 'KT_EXECUTION', 'Complete KT sessions with successor', 'employee', 'pending', 3),
  T(9, 'KT_EXECUTION', 'Hand over shared credentials and ownership', 'employee', 'pending', 3),
  T(10, 'IT_CLEARANCE', 'Return laptop and IT-issued hardware', 'employee', 'pending', 12),
  T(11, 'IT_CLEARANCE', 'Sign NDA acknowledgement', 'employee', 'pending', -1, { doc_type_code: 'NDA_ACKNOWLEDGEMENT' }),
  T(12, 'IT_CLEARANCE', 'Revoke system access', 'it', 'pending', 15),
  T(13, 'FINANCE_CLEARANCE', 'Settle outstanding advances', 'employee', 'completed', -5),
  T(14, 'FINANCE_CLEARANCE', 'Submit pending reimbursement claims', 'employee', 'pending', 12),
  T(15, 'FINANCE_CLEARANCE', 'Issue no-dues certificate', 'finance', 'blocked', 15, { doc_type_code: 'NO_DUES_FINANCE' }),
  T(16, 'ADMIN_ASSET_RETURN', 'Return ID and access cards', 'employee', 'pending', 15),
  T(17, 'ADMIN_ASSET_RETURN', 'Vacate desk and clear locker', 'employee', 'pending', 15),
  T(18, 'ADMIN_ASSET_RETURN', 'Sign off asset return form', 'admin', 'pending', 16, { doc_type_code: 'ASSET_RETURN_FORM' }),
  T(19, 'EXIT_INTERVIEW', 'Complete exit interview', 'employee', 'pending', 14),
  T(20, 'EXIT_INTERVIEW', 'Review exit interview responses', 'hr', 'pending', 17),
  T(21, 'FINAL_SETTLEMENT', 'Compute full and final settlement', 'finance', 'pending', 22),
  T(22, 'FINAL_SETTLEMENT', 'Share settlement statement with employee', 'finance', 'pending', 27, { doc_type_code: 'FINAL_SETTLEMENT_STATEMENT' }),
  T(23, 'RELIEVING_LETTER', 'Issue relieving letter', 'hr', 'pending', 29, { doc_type_code: 'RELIEVING_LETTER' }),
  T(24, 'RELIEVING_LETTER', 'Issue experience letter', 'hr', 'pending', 29, { doc_type_code: 'EXPERIENCE_LETTER' }),
]

const MAIN_DOCS: CaseDocument[] = [
  {
    id: 'd0000000-0000-4000-8000-000000000001',
    case_id: 'c0000000-0000-4000-8000-000000000001',
    task_id: MAIN_TASKS[0].id,
    doc_type_code: 'RESIGNATION_LETTER',
    file_name: 'resignation-letter.pdf',
    storage_path: 'case-documents/c000.../resignation-letter.pdf',
    mime_type: 'application/pdf',
    size_bytes: 148_221,
    uploaded_by: KIRTHANA,
    status: 'approved',
    reviewed_by: 'a0000000-0000-4000-8000-000000000002',
    reviewed_at: stamp(-22),
    review_note: null,
    created_at: stamp(-23),
    verification: null,
    is_inline: false,
    content: null,
  },
  {
    id: 'd0000000-0000-4000-8000-000000000002',
    case_id: 'c0000000-0000-4000-8000-000000000001',
    task_id: MAIN_TASKS[6].id,
    doc_type_code: 'KT_DOCUMENT',
    file_name: 'kt-handover-draft.pdf',
    storage_path: 'case-documents/c000.../kt-handover-draft.pdf',
    mime_type: 'application/pdf',
    size_bytes: 512_904,
    uploaded_by: KIRTHANA,
    status: 'pending',
    reviewed_by: null,
    reviewed_at: null,
    review_note: null,
    created_at: stamp(-1),
    verification: null,
    is_inline: false,
    content: null,
  },
]

const MAIN_KT: KtRecord = {
  id: 'k0000000-0000-4000-8000-000000000001',
  case_id: 'c0000000-0000-4000-8000-000000000001',
  successor_id: 'a0000000-0000-4000-8000-000000000006',
  overall_status: 'in_progress',
  reviewed_by: null,
  reviewed_at: null,
  items: [
    { id: 'ki-1', kt_record_id: 'k0000000-0000-4000-8000-000000000001', topic: 'Billing service ownership', detail: 'Deploys, on-call runbook, and the reconciliation cron.', document_id: null, coverage_status: 'documented', gap_note: null, sort_order: 1 },
    { id: 'ki-2', kt_record_id: 'k0000000-0000-4000-8000-000000000001', topic: 'Payment gateway vendor relationship', detail: 'Primary contact and escalation path.', document_id: null, coverage_status: 'in_progress', gap_note: null, sort_order: 2 },
    { id: 'ki-3', kt_record_id: 'k0000000-0000-4000-8000-000000000001', topic: 'Data warehouse access grants', detail: null, document_id: null, coverage_status: 'gap', gap_note: 'No named successor for grant approvals after the last working day.', sort_order: 3 },
    { id: 'ki-4', kt_record_id: 'k0000000-0000-4000-8000-000000000001', topic: 'Quarterly audit export process', detail: null, document_id: null, coverage_status: 'not_started', gap_note: null, sort_order: 4 },
  ],
}

/* Drafts waiting in the approval queue. Nothing here has taken effect —
   see CLAUDE.md rule 2. */
const AGENT_ACTIONS: AgentAction[] = [
  {
    id: 'aa-1',
    case_id: 'c0000000-0000-4000-8000-000000000001',
    kind: 'draft_notification',
    summary: 'Remind Kirthana Mekala that the KT document is 2 days overdue',
    payload: {
      recipient: 'kirthana.mekala@example.com',
      subject: 'Knowledge transfer document is overdue',
      body: 'Hi Kirthana,\n\nYour knowledge transfer document was due on Monday and is still marked in progress. Your last working day is in 36 days, and KT execution needs to close before IT clearance can start.\n\nCould you upload the completed document by end of week?\n\nThanks,\nExit Process',
    },
    status: 'pending_approval',
    self_targeting: false,
    approver_id: null,
    decided_at: null,
    decision_note: null,
    approved_payload: null,
    executed_at: null,
    failure_reason: null,
    created_at: stamp(-0.4),
  },
  {
    id: 'aa-2',
    case_id: 'c0000000-0000-4000-8000-000000000003',
    kind: 'draft_escalation',
    summary: 'Escalate unacknowledged resignation to Meera Krishnan — 4 days, SLA is 2',
    payload: {
      recipient: 'meera.krishnan@example.com',
      subject: 'Resignation awaiting your acknowledgement',
      body: 'Deepak Joshi submitted his resignation 4 days ago. Manager acknowledgement has a 2-day SLA and is now 2 days over.\n\nUntil this is acknowledged, KT planning cannot begin and the remaining 26 days of notice period are compressed.',
    },
    status: 'pending_approval',
    self_targeting: false,
    approver_id: null,
    decided_at: null,
    decision_note: null,
    approved_payload: null,
    executed_at: null,
    failure_reason: null,
    created_at: stamp(-0.2),
  },
  {
    id: 'aa-3',
    case_id: 'c0000000-0000-4000-8000-000000000001',
    kind: 'flag_policy_breach',
    summary: 'NDA acknowledgement is overdue and blocks IT clearance',
    payload: {
      rule: 'IT clearance cannot complete without a signed NDA acknowledgement.',
      observed: 'Task "Sign NDA acknowledgement" is pending, 1 day past due.',
    },
    status: 'pending_approval',
    self_targeting: false,
    approver_id: null,
    decided_at: null,
    decision_note: null,
    approved_payload: null,
    executed_at: null,
    failure_reason: null,
    created_at: stamp(-1.1),
  },
]

const APPROVALS: Approval[] = [
  {
    id: 'ap-1',
    case_id: 'c0000000-0000-4000-8000-000000000001',
    stage_code: 'MANAGER_ACK',
    approver_id: 'a0000000-0000-4000-8000-000000000002',
    decision: 'approved',
    comment: 'Last working day confirmed. Full notice period applies.',
    decided_at: stamp(-21),
  },
  {
    id: 'ap-2',
    case_id: 'c0000000-0000-4000-8000-000000000001',
    stage_code: 'KT_PLANNING',
    approver_id: 'a0000000-0000-4000-8000-000000000002',
    decision: 'approved',
    comment: 'Rahul Verma takes over billing. Topic list agreed.',
    decided_at: stamp(-18),
  },
]

/* The exit interview. Questions are fixed in v1 — same set for everyone, so
   responses stay comparable across departments in the HR trend view. */
export const INTERVIEW_QUESTIONS: ExitInterviewQuestion[] = [
  {
    key: 'reason',
    prompt: 'What led you to decide to leave?',
    kind: 'text',
    help: 'The single most useful answer on this form. Be as direct as you want to be.',
  },
  { key: 'role_clarity', prompt: 'How clear were your responsibilities?', kind: 'scale' },
  { key: 'manager_support', prompt: 'How well supported were you by your manager?', kind: 'scale' },
  { key: 'growth', prompt: 'How were your opportunities to grow?', kind: 'scale' },
  { key: 'compensation', prompt: 'How fair did your compensation feel?', kind: 'scale' },
  { key: 'would_recommend', prompt: 'Would you recommend working here to a friend?', kind: 'scale' },
  {
    key: 'what_to_change',
    prompt: 'If you could change one thing about working here, what would it be?',
    kind: 'text',
  },
  {
    key: 'what_to_keep',
    prompt: 'What is the best part working here? ',
    kind: 'text',
  },
]

const INTERVIEWS: ExitInterview[] = [
  {
    id: 'ei-1',
    case_id: 'c0000000-0000-4000-8000-000000000001',
    responses: {},
    submitted_at: null,
    sentiment: null,
    themes: null,
    summary: null,
    analysed_at: null,
  },
]

/* -------------------------------------------------------------------------- */
/* Derived helpers                                                             */
/* -------------------------------------------------------------------------- */

export function daysBetween(from: string, to: string): number {
  return Math.round((Date.parse(to) - Date.parse(from)) / DAY)
}

function tasksFor(caseId: string): CaseTask[] {
  if (caseId === 'c0000000-0000-4000-8000-000000000001') return MAIN_TASKS
  // Other cases get a thin slice so list views have plausible counts.
  return MAIN_TASKS.slice(0, 8).map((t, i) => ({
    ...t,
    id: `${caseId}-t${i}`,
    case_id: caseId,
    status: i < 4 ? 'completed' : 'pending',
    sla_breached: false,
  }))
}

function summarise(c: ExitCase): CaseSummary {
  const employee = byId(c.employee_id)!
  const tasks = tasksFor(c.id)
  const open = tasks.filter((t) => t.status !== 'completed' && t.status !== 'waived')
  return {
    case: c,
    employee: {
      id: employee.id,
      full_name: employee.full_name,
      emp_code: employee.emp_code,
      department: employee.department,
      designation: employee.designation,
      work_email: employee.work_email,
    },
    manager: employee.manager_id
      ? { id: employee.manager_id, full_name: byId(employee.manager_id)!.full_name }
      : null,
    open_tasks: open.length,
    overdue_tasks: open.filter((t) => t.sla_breached).length,
    pending_documents: c.id === 'c0000000-0000-4000-8000-000000000001' ? 1 : 0,
    days_remaining: daysBetween(iso(0), c.last_working_day),
  }
}

export const mockDb = {
  stages: STAGES,
  documentTypes: DOCUMENT_TYPES,
  employees: EMPLOYEES,
  cases: CASES,
  agentActions: AGENT_ACTIONS,
  ktRecord: MAIN_KT,
  tasksFor,
  summarise,

  myExitView(employeeId: string): MyExitView | null {
    const c = CASES.find((x) => x.employee_id === employeeId && x.status !== 'completed')
    if (!c) return null
    const employee = byId(employeeId)!
    return {
      case: c,
      stages: STAGES,
      tasks: tasksFor(c.id),
      documents: c.id === 'c0000000-0000-4000-8000-000000000001' ? MAIN_DOCS : [],
      document_types: DOCUMENT_TYPES,
      manager: employee.manager_id
        ? {
            id: employee.manager_id,
            full_name: byId(employee.manager_id)!.full_name,
            work_email: byId(employee.manager_id)!.work_email,
          }
        : null,
      // Fixtures only — the live view fills these from case_assets and
      // case_settlement. Empty here means the Tracked panel simply does not
      // render, which is the right behaviour for a case with no IT or
      // Finance detail attached.
      assets: [],
      settlement: [],
      days_remaining: daysBetween(iso(0), c.last_working_day),
    }
  },

  documentsFor(caseId: string): CaseDocument[] {
    return caseId === 'c0000000-0000-4000-8000-000000000001' ? MAIN_DOCS : []
  },

  detailFor(caseId: string): CaseDetailView | null {
    const c = CASES.find((x) => x.id === caseId)
    if (!c) return null
    const employee = byId(c.employee_id)!
    return {
      case: c,
      employee,
      manager: employee.manager_id
        ? { id: employee.manager_id, full_name: byId(employee.manager_id)!.full_name }
        : null,
      stages: STAGES,
      tasks: tasksFor(caseId),
      documents: this.documentsFor(caseId),
      document_types: DOCUMENT_TYPES,
      approvals: APPROVALS.filter((a) => a.case_id === caseId),
      kt: caseId === 'c0000000-0000-4000-8000-000000000001' ? MAIN_KT : null,
      days_remaining: daysBetween(iso(0), c.last_working_day),
    }
  },

  reviewDocument(docId: string, status: 'approved' | 'rejected', note: string | null) {
    const doc = MAIN_DOCS.find((d) => d.id === docId)
    if (!doc) return
    doc.status = status
    doc.reviewed_at = new Date().toISOString()
    doc.review_note = note
  },

  addDocument(caseId: string, docTypeCode: string, file: { name: string; size: number; type: string }) {
    const doc: CaseDocument = {
      id: `d-${Math.random().toString(36).slice(2, 10)}`,
      case_id: caseId,
      task_id: null,
      doc_type_code: docTypeCode,
      file_name: file.name,
      storage_path: `case-documents/${caseId}/${file.name}`,
      mime_type: file.type || 'application/octet-stream',
      size_bytes: file.size,
      uploaded_by: KIRTHANA,
      status: 'pending',
      reviewed_by: null,
      reviewed_at: null,
      review_note: null,
      verification: null,
      created_at: new Date().toISOString(),
      is_inline: false,
      content: null,
    }
    MAIN_DOCS.push(doc)
    return doc
  },

  advanceStage(caseId: string) {
    const c = CASES.find((x) => x.id === caseId)
    if (!c) return
    const i = STAGES.findIndex((s) => s.code === c.current_stage)
    if (i < STAGES.length - 1) {
      c.current_stage = STAGES[i + 1].code
    } else {
      c.status = 'completed'
    }
  },

  recordApproval(caseId: string, stageCode: StageCode, approverId: string, decision: 'approved' | 'rejected', comment: string | null) {
    APPROVALS.push({
      id: `ap-${Math.random().toString(36).slice(2, 8)}`,
      case_id: caseId,
      stage_code: stageCode,
      approver_id: approverId,
      decision,
      comment,
      decided_at: new Date().toISOString(),
    })
    if (decision === 'approved') this.advanceStage(caseId)
  },

  ktFor(caseId: string): KtRecord | null {
    return caseId === 'c0000000-0000-4000-8000-000000000001' ? MAIN_KT : null
  },

  saveKtItem(itemId: string, patch: Partial<KtRecord['items'][number]>) {
    const item = MAIN_KT.items.find((i) => i.id === itemId)
    if (item) Object.assign(item, patch)
  },

  addKtItem(topic: string, detail: string) {
    MAIN_KT.items.push({
      id: `ki-${Math.random().toString(36).slice(2, 8)}`,
      kt_record_id: MAIN_KT.id,
      topic,
      detail,
      document_id: null,
      coverage_status: 'not_started',
      gap_note: null,
      sort_order: MAIN_KT.items.length + 1,
    })
  },

  interviewFor(caseId: string): ExitInterview | null {
    return INTERVIEWS.find((i) => i.case_id === caseId) ?? null
  },

  saveInterview(caseId: string, responses: Record<string, string | number>, submit: boolean) {
    const interview = INTERVIEWS.find((i) => i.case_id === caseId)
    if (!interview) return
    interview.responses = responses
    if (submit) interview.submitted_at = new Date().toISOString()
  },
}
