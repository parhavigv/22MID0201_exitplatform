/**
 * Mirrors supabase/migrations/0001_init.sql.
 *
 * Hand-written for now. Once the Supabase project exists, regenerate with
 * `supabase gen types typescript` and keep the view models below on top of it.
 */

export type AppRole = 'employee' | 'manager' | 'hr' | 'it' | 'finance'

export type TaskOwnerRole = 'employee' | 'manager' | 'hr' | 'it' | 'finance' | 'admin'

export type ExitType = 'resignation' | 'termination' | 'retirement' | 'end_of_contract'

export type CaseStatus = 'draft' | 'active' | 'on_hold' | 'completed' | 'cancelled'

export type TaskStatus = 'pending' | 'in_progress' | 'blocked' | 'completed' | 'waived'

export type DocumentStatus = 'pending' | 'approved' | 'rejected'

export type KtCoverageStatus =
  | 'not_started'
  | 'in_progress'
  | 'documented'
  | 'verified'
  | 'gap'

export type TaskOrigin = 'template' | 'agent' | 'manual'

export type AgentActionStatus =
  | 'pending_approval'
  | 'approved'
  | 'rejected'
  | 'executed'
  | 'failed'

export const STAGE_CODES = [
  'RESIGNATION_SUBMITTED',
  'MANAGER_ACK',
  'KT_PLANNING',
  'KT_EXECUTION',
  'IT_CLEARANCE',
  'FINANCE_CLEARANCE',
  'ADMIN_ASSET_RETURN',
  'EXIT_INTERVIEW',
  'FINAL_SETTLEMENT',
  'RELIEVING_LETTER',
] as const

export type StageCode = (typeof STAGE_CODES)[number]

export interface ExitStage {
  code: StageCode
  name: string
  description: string | null
  owner_role: TaskOwnerRole
  sla_days: number
  sort_order: number
}

export interface Employee {
  id: string
  emp_code: string
  full_name: string
  work_email: string
  department: string
  designation: string
  date_of_joining: string
  manager_id: string | null
  app_role: AppRole
  is_active: boolean
}

export interface ExitCase {
  id: string
  employee_id: string
  exit_type: ExitType
  reason: string | null
  resignation_date: string
  last_working_day: string
  notice_period_days: number
  current_stage: StageCode
  status: CaseStatus
  risk_score: number | null
  risk_assessed_at: string | null
  created_at: string
}

export interface CaseTask {
  id: string
  case_id: string
  stage_code: StageCode
  title: string
  description: string | null
  owner_role: TaskOwnerRole
  assignee_id: string | null
  doc_type_code: string | null
  due_date: string | null
  status: TaskStatus
  origin: TaskOrigin
  sla_breached: boolean
  completed_at: string | null
  sort_order: number
}

export interface NdaContent {
  acknowledgements: boolean[]
  full_name: string
  submitted_at: string
}

/**
 * The model's advisory read on whether an uploaded file is the document type
 * that was requested. Null means the check did not run — an unreadable file or
 * the model being unavailable — and is shown as "not checked", never as a pass.
 */
export interface DocumentVerification {
  belongs: boolean
  detected_type: string
  reason: string
  confidence: 'high' | 'medium' | 'low'
  checked_at: string
  model: string
}

export interface CaseDocument {
  id: string
  case_id: string
  task_id: string | null
  doc_type_code: string
  file_name: string
  storage_path: string
  mime_type: string
  size_bytes: number
  uploaded_by: string
  status: DocumentStatus
  reviewed_by: string | null
  reviewed_at: string | null
  review_note: string | null
  verification: DocumentVerification | null
  created_at: string
  is_inline: boolean
  content: NdaContent | Record<string, unknown> | null
}

export interface DocumentType {
  code: string
  name: string
  description: string | null
  stage_code: StageCode
  owner_role: TaskOwnerRole
  is_required: boolean
  sort_order: number
}

export interface KtItem {
  id: string
  kt_record_id: string
  topic: string
  detail: string | null
  document_id: string | null
  coverage_status: KtCoverageStatus
  gap_note: string | null
  sort_order: number
}

export interface KtRecord {
  id: string
  case_id: string
  successor_id: string | null
  overall_status: KtCoverageStatus
  reviewed_by: string | null
  reviewed_at: string | null
  items: KtItem[]
}

export interface ExitInterviewQuestion {
  key: string
  prompt: string
  kind: 'scale' | 'text'
  help?: string
}

export interface ExitInterview {
  id: string
  case_id: string
  responses: Record<string, string | number>
  submitted_at: string | null
  sentiment: string | null
  themes: string[] | null
  summary: string | null
  analysed_at: string | null
}

export interface Approval {
  id: string
  case_id: string
  stage_code: StageCode
  approver_id: string
  decision: 'approved' | 'rejected'
  comment: string | null
  decided_at: string
}

export interface AgentAction {
  id: string
  case_id: string | null
  kind: string
  summary: string
  payload: Record<string, unknown>
  approved_payload: Record<string, unknown> | null
  status: AgentActionStatus
  self_targeting: boolean
  approver_id: string | null
  decided_at: string | null
  decision_note: string | null
  executed_at: string | null
  failure_reason: string | null
  created_at: string
}

/* ---------------------------------------------------------------------------
 * View models — what screens actually consume. The API joins these server-side
 * so a dashboard is one request, not six.
 * ------------------------------------------------------------------------ */

/** A case with the people and counts every list view needs. */
export interface CaseSummary {
  case: ExitCase
  employee: Pick<
    Employee,
    'id' | 'full_name' | 'emp_code' | 'department' | 'designation' | 'work_email'
  >
  manager: Pick<Employee, 'id' | 'full_name'> | null
  open_tasks: number
  overdue_tasks: number
  pending_documents: number
  days_remaining: number
}

/** Everything the employee's own dashboard renders. */
/**
 * What IT and Finance are tracking about you. Read-only from the employee's
 * side — IT decides when a laptop is back, Finance decides what the settlement
 * says. This is visibility, not a second place to edit it.
 */
export interface MyExitView {
  case: ExitCase
  stages: ExitStage[]
  tasks: CaseTask[]
  documents: CaseDocument[]
  document_types: DocumentType[]
  manager: Pick<Employee, 'id' | 'full_name' | 'work_email'> | null
  assets: CaseAsset[]
  settlement: CaseSettlementItem[]
  days_remaining: number
}

/** The full picture of one exit, for the manager and HR case screen. */
export interface CaseDetailView {
  case: ExitCase
  employee: Employee
  manager: Pick<Employee, 'id' | 'full_name'> | null
  stages: ExitStage[]
  tasks: CaseTask[]
  documents: CaseDocument[]
  document_types: DocumentType[]
  approvals: Approval[]
  kt: KtRecord | null
  days_remaining: number
}

export interface Session {
  employee: Employee
  role: AppRole
}

/* ---------------------------------------------------------------------------
 * "Needs you" — everything awaiting the signed-in person, across all cases.
 * ------------------------------------------------------------------------ */

type InboxPerson = Pick<Employee, 'id' | 'full_name' | 'department'>

export interface InboxDocument {
  document_id: string
  case_id: string
  employee: InboxPerson
  document_name: string
  file_name: string
  uploaded_at: string
  verification: DocumentVerification | null
  /**
   * Inline submissions carry their text here — there is no file to open, so
   * the queue row is the only place the reviewer can read what they are
   * approving.
   */
  is_inline: boolean
  content: NdaContent | Record<string, unknown> | null
}

export interface InboxStage {
  case_id: string
  employee: InboxPerson
  stage_code: StageCode
  stage_name: string
  last_working_day: string
}

export interface InboxOverdue {
  task_id: string
  case_id: string
  employee: InboxPerson
  title: string
  owner_role: TaskOwnerRole
  stage_name: string
  due_date: string
  days_overdue: number
}

export interface Inbox {
  documents: InboxDocument[]
  stages: InboxStage[]
  overdue: InboxOverdue[]
  total: number
}

/* ---------------------------------------------------------------------------
 * Progress
 * ------------------------------------------------------------------------ */

export interface StageProgress {
  code: StageCode
  name: string
  done: number
  total: number
  overdue: number
  is_current: boolean
}

export interface CaseProgress {
  case_id: string
  employee: Pick<
    Employee,
    'id' | 'full_name' | 'emp_code' | 'department' | 'designation'
  >
  manager_name: string | null
  current_stage: StageCode
  last_working_day: string
  days_remaining: number
  risk_score: number | null
  tasks_total: number
  tasks_done: number
  tasks_blocked: number
  tasks_overdue: number
  percent_complete: number
  documents_pending: number
  documents_rejected: number
  stages: StageProgress[]
}

/** One item issued to the employee, tracked back in. */
export interface CaseAsset {
  id: string
  case_id: string
  name: string
  category: string
  identifier: string | null
  status: 'pending' | 'returned' | 'lost' | 'not_issued'
  condition: string | null
  note: string | null
  returned_at: string | null
}

/** One system the employee holds, tracked until revoked. */
export interface CaseAccess {
  id: string
  case_id: string
  system: string
  category: string
  /** Admin rights or production credentials — revoke on the last day. */
  is_elevated: boolean
  status: 'active' | 'revoked' | 'not_applicable'
  note: string | null
  revoked_at: string | null
}

/** One line of the full-and-final settlement. */
export interface CaseSettlementItem {
  id: string
  case_id: string
  kind: 'earning' | 'deduction'
  label: string
  /** Null until Finance fills it in — unknown, not zero. */
  amount: number | null
  status: 'pending' | 'confirmed' | 'not_applicable'
  note: string | null
}

/** One person in the IT or Finance clearance queue. */
export interface ClearancePerson {
  case_id: string
  employee: Pick<Employee, 'id' | 'full_name' | 'emp_code' | 'department' | 'designation'>
  current_stage: StageCode
  last_working_day: string
  days_remaining: number
  tasks: CaseTask[]
  open_count: number
  done_count: number
  /** Past their last working day with clearance still outstanding. */
  at_risk: boolean
  signed_off: boolean
  /**
   * Open tasks in this stage belonging to someone else. The stage gate covers
   * every task in the stage, not just this role's, so these are what stand
   * between "my work is done" and being able to sign off.
   */
  blocked_by: { title: string; owner_role: string }[]
  /** Populated for IT only. Finance receives the settlement lines instead. */
  assets: CaseAsset[]
  access: CaseAccess[]
  settlement: CaseSettlementItem[]
  live_access: number
  elevated_live: number
}

export interface ClearanceQueue {
  role: AppRole
  stage_code: StageCode | null
  people: ClearancePerson[]
  flagged: number
}

/**
 * Something the signed-in approver decided — a stage sign-off, a document
 * review, or a KT topic verification. The three live in different tables, so
 * `kind` says which this was and `stage_name` is only meaningful for stages.
 */
export interface RecentApproval {
  id: string
  case_id: string
  kind: 'stage' | 'document' | 'kt'
  stage_code: StageCode | null
  stage_name: string
  label: string
  decision: 'approved' | 'rejected'
  comment: string | null
  decided_at: string
  employee: Pick<Employee, 'id' | 'full_name'> | null
}

/* ---------------------------------------------------------------------------
 * Reminders and notifications
 * ------------------------------------------------------------------------ */

export interface ReminderDraft {
  task_id: string
  recipient: Pick<Employee, 'id' | 'full_name' | 'work_email'>
  subject: string
  body: string
  days_overdue: number
}

export interface AppNotification {
  id: string
  case_id: string | null
  title: string
  body: string
  read_at: string | null
  created_at: string
}

export interface PolicyDoc {
  id: string
  title: string
  version: string
  effective_from: string
  uploaded_by: string
  created_at: string
  chunk_count?: number
}
