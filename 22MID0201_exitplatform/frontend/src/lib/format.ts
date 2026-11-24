import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'
import type { CaseDocument, CaseTask, TaskStatus } from './types'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** One date format across the whole product: "14 Nov". Year only when it differs. */
export function shortDate(value: string | null | undefined): string {
  if (!value) return '—'
  const d = new Date(value)
  const sameYear = d.getFullYear() === new Date().getFullYear()
  return d.toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    ...(sameYear ? {} : { year: 'numeric' }),
  })
}

export function longDate(value: string | null | undefined): string {
  if (!value) return '—'
  return new Date(value).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })
}

const DAY = 86_400_000

export function daysUntil(value: string): number {
  const target = new Date(value)
  target.setHours(0, 0, 0, 0)
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return Math.round((target.getTime() - today.getTime()) / DAY)
}

/**
 * Relative due date in the interface's voice: says what the reader needs to
 * act on, not a raw timestamp.
 */
export function dueLabel(value: string | null): string {
  if (!value) return 'No date'
  const d = daysUntil(value)
  if (d < -1) return `${Math.abs(d)} days overdue`
  if (d === -1) return 'Overdue since yesterday'
  if (d === 0) return 'Due today'
  if (d === 1) return 'Due tomorrow'
  if (d <= 7) return `Due ${new Date(value).toLocaleDateString('en-GB', { weekday: 'long' })}`
  return `Due ${shortDate(value)}`
}

export function relativeTime(value: string): string {
  const diff = Date.now() - Date.parse(value)
  const mins = Math.round(diff / 60_000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} min ago`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  return days === 1 ? 'yesterday' : `${days} days ago`
}

export function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

/* -------------------------------------------------------------------------- */
/* Status vocabulary                                                           */
/*                                                                            */
/* Status is shown structurally — a rail colour and a marker — not as a pill   */
/* on every row. These are the only four tones in the product.                 */
/* -------------------------------------------------------------------------- */

export type Tone = 'neutral' | 'moss' | 'amber' | 'rust'

export const TASK_STATUS_LABEL: Record<TaskStatus, string> = {
  pending: 'Not started',
  in_progress: 'In progress',
  blocked: 'Blocked',
  completed: 'Done',
  waived: 'Waived',
}

export function taskTone(status: TaskStatus, slaBreached: boolean): Tone {
  if (status === 'completed' || status === 'waived') return 'moss'
  if (slaBreached || status === 'blocked') return 'rust'
  if (status === 'in_progress') return 'amber'
  return 'neutral'
}

export interface TaskDisplayStatus {
  label: string
  tone: Tone
  /** Why it is waiting, or what to do next. Shown under the label. */
  hint?: string
  /** True while the ball is in someone else's court. */
  waiting: boolean
}

/**
 * What to tell the employee about one task.
 *
 * A task that expects a document has two halves — did they submit it, and did
 * the manager accept it — and the task row alone cannot say which. Pass the
 * matching document and the pair produces the real wording: "Submitted —
 * waiting for your manager" rather than a bare "In progress", and "Rejected —
 * please resubmit" with the manager's note rather than the task silently
 * reverting to "Not started".
 *
 * `doc` is the latest document of the task's `doc_type_code`, or undefined for
 * tasks that need no document.
 */
export function taskDisplayStatus(
  task: Pick<CaseTask, 'status' | 'sla_breached' | 'owner_role'>,
  doc?: Pick<CaseDocument, 'status' | 'review_note'>,
): TaskDisplayStatus {
  if (task.status === 'waived') {
    return { label: 'Waived', tone: 'moss', hint: 'HR cleared this', waiting: false }
  }
  if (task.status === 'completed') {
    return doc?.status === 'approved'
      ? { label: 'Completed', tone: 'moss', hint: 'Approved by your manager', waiting: false }
      : { label: 'Completed', tone: 'moss', waiting: false }
  }
  if (doc?.status === 'rejected') {
    return {
      label: 'Rejected — please resubmit',
      tone: 'rust',
      hint: doc.review_note || undefined,
      waiting: false,
    }
  }
  if (doc?.status === 'pending') {
    return {
      label: 'Submitted — waiting for your manager',
      tone: 'amber',
      waiting: true,
    }
  }
  if (task.status === 'blocked') {
    return { label: 'Blocked', tone: 'rust', waiting: true }
  }
  if (task.owner_role !== 'employee') {
    return { label: 'Waiting on someone else', tone: 'neutral', waiting: true }
  }
  if (task.status === 'in_progress') {
    return { label: 'In progress', tone: 'amber', waiting: false }
  }
  return {
    label: 'Not started',
    tone: task.sla_breached ? 'rust' : 'neutral',
    hint: task.sla_breached ? 'Overdue' : undefined,
    waiting: false,
  }
}

/** The latest document of a given type on the case, newest first. */
export function latestDocumentFor(
  documents: CaseDocument[],
  docTypeCode: string | null,
): CaseDocument | undefined {
  if (!docTypeCode) return undefined
  return documents
    .filter((d) => d.doc_type_code === docTypeCode)
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0]
}

export const RAIL: Record<Tone, string> = {
  neutral: 'bg-line-strong',
  moss: 'bg-moss',
  amber: 'bg-amber',
  rust: 'bg-rust',
}

export const TEXT_TONE: Record<Tone, string> = {
  neutral: 'text-muted',
  moss: 'text-moss',
  amber: 'text-amber',
  rust: 'text-rust',
}

export const OWNER_LABEL: Record<string, string> = {
  employee: 'You',
  manager: 'Your manager',
  hr: 'HR',
  it: 'IT',
  finance: 'Finance',
  admin: 'Admin',
}

/** Owner label from a third party's point of view (manager and HR views). */
export const OWNER_LABEL_3P: Record<string, string> = {
  employee: 'Employee',
  manager: 'Manager',
  hr: 'HR',
  it: 'IT',
  finance: 'Finance',
  admin: 'Admin',
}
