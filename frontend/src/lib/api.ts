/**
 * The single boundary between the UI and the backend.
 *
 * While `USE_MOCKS` is on, every call is served from `mock.ts`. When the
 * FastAPI backend lands, set VITE_USE_MOCKS=false and only the private
 * `request()` path below changes — no screen is touched.
 */

import { mockDb } from './mock'
import { supabase } from './supabase'
import type {
  AgentAction,
  AppNotification,
  CaseDocument,
  CaseAccess,
  CaseAsset,
  CaseProgress,
  CaseSettlementItem,
  ClearanceQueue,
  RecentApproval,
  CaseSummary,
  CaseTask,
  DocumentStatus,
  Employee,
  ExitCase,
  ExitInterview,
  Inbox,
  KtRecord,
  MyExitView,
  PolicyDoc,
  ReminderDraft,
  Session,
  StageCode,
  TaskStatus,
} from './types'

export const USE_MOCKS = import.meta.env.VITE_USE_MOCKS !== 'false'

const BASE = import.meta.env.VITE_API_BASE ?? '/api'

/** Network latency simulation so loading states are real during mock dev. */
const settle = <T>(value: T, ms = 220): Promise<T> =>
  new Promise((resolve) => setTimeout(() => resolve(value), ms))

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/**
 * Read the access token from Supabase on every request rather than caching it.
 * supabase-js refreshes tokens in the background; a cached copy goes stale and
 * produces 401s an hour into a session.
 */
async function authHeader(): Promise<Record<string, string>> {
  if (USE_MOCKS) return {}
  const { data } = await supabase.auth.getSession()
  const token = data.session?.access_token
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function request<T>(path: string, init: RequestInit & { skipContentType?: boolean } = {}): Promise<T> {
  const { skipContentType, ...fetchInit } = init
  const contentHeaders: Record<string, string> = skipContentType ? {} : { 'Content-Type': 'application/json' }
  const res = await fetch(`${BASE}${path}`, {
    ...fetchInit,
    headers: {
      ...contentHeaders,
      ...(await authHeader()),
      ...fetchInit.headers,
    },
  })

  if (!res.ok) {
    throw new ApiError(await errorMessage(res), res.status)
  }

  return res.status === 204 ? (undefined as T) : ((await res.json()) as T)
}

/** FastAPI puts the human-readable reason in `detail`. Surface that, not JSON. */
async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json()
    if (typeof body?.detail === 'string') return body.detail
    return JSON.stringify(body)
  } catch {
    return `Request failed (${res.status})`
  }
}

/* -------------------------------------------------------------------------- */
/* Mock session — replaced by Supabase Auth in Phase 1.                        */
/*                                                                            */
/* Lets you switch roles from the login screen without a backend, so all three */
/* dashboards are reviewable now.                                              */
/* -------------------------------------------------------------------------- */

const SESSION_KEY = 'exit.mockSession'

function readMockSession(): Session | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY)
    if (!raw) return null
    const employee = mockDb.employees.find((e) => e.id === JSON.parse(raw))
    return employee ? { employee, role: employee.app_role } : null
  } catch {
    return null
  }
}

/* -------------------------------------------------------------------------- */
/* API                                                                         */
/* -------------------------------------------------------------------------- */

export const api = {
  /* --- session ----------------------------------------------------------- */

  async currentSession(): Promise<Session | null> {
    if (USE_MOCKS) return settle(readMockSession(), 80)

    const { data } = await supabase.auth.getSession()
    if (!data.session) return null

    try {
      return await request<Session>('/me')
    } catch (err) {
      // Signed in to Supabase but with no employee record, or a stale token.
      // Drop the session so the user lands back on sign-in with an explanation
      // rather than an empty dashboard.
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
        await supabase.auth.signOut()
        return null
      }
      throw err
    }
  },

  async signIn(email: string, password: string): Promise<Session> {
    if (USE_MOCKS) {
      const employee = mockDb.employees.find((e) => e.work_email === email)
      if (!employee) throw new ApiError('No such employee', 404)
      localStorage.setItem(SESSION_KEY, JSON.stringify(employee.id))
      return settle({ employee, role: employee.app_role }, 160)
    }

    const { data, error } = await supabase.auth.signInWithPassword({ email, password })
    if (error) {
      throw new ApiError(
        error.message === 'Invalid login credentials'
          ? 'That email and password do not match an account.'
          : error.message,
        400,
      )
    }

    // Use the token this call just returned rather than letting `request` read
    // it back via getSession(). supabase-js persists the session to storage
    // asynchronously, so immediately after signing in getSession() can still
    // return the previous value — or nothing. That sent /me out unauthenticated
    // and surfaced as "Not signed in" until you clicked Sign in a few more
    // times and one of the attempts happened to win the race.
    const token = data.session?.access_token
    if (!token) {
      throw new ApiError('Signed in, but no session was returned. Try again.', 500)
    }

    return request<Session>('/me', {
      headers: { Authorization: `Bearer ${token}` },
    })
  },

  /** Mock-only shortcut, kept so the role picker still works with mocks on. */
  async signInAs(employeeId: string): Promise<Session> {
    if (!USE_MOCKS) throw new ApiError('signInAs is mock-only', 400)
    const employee = mockDb.employees.find((e) => e.id === employeeId)
    if (!employee) throw new ApiError('No such employee', 404)
    localStorage.setItem(SESSION_KEY, JSON.stringify(employeeId))
    return settle({ employee, role: employee.app_role }, 160)
  },

  async signOut(): Promise<void> {
    if (USE_MOCKS) {
      localStorage.removeItem(SESSION_KEY)
      return settle(undefined, 60)
    }
    await supabase.auth.signOut()
  },

  /* --- employee ---------------------------------------------------------- */

  async myExit(employeeId: string): Promise<MyExitView | null> {
    if (USE_MOCKS) return settle(mockDb.myExitView(employeeId))
    return request<MyExitView | null>('/me/exit')
  },

  /* --- cases ------------------------------------------------------------- */

  /** Scope is enforced server-side by RLS; the param only shapes the query. */
  async listCases(scope: 'mine' | 'team' | 'all', actorId: string): Promise<CaseSummary[]> {
    if (USE_MOCKS) {
      const all = mockDb.cases.map(mockDb.summarise)
      const filtered =
        scope === 'all'
          ? all
          : scope === 'team'
            ? all.filter((s) => s.manager?.id === actorId)
            : all.filter((s) => s.employee.id === actorId)
      return settle(filtered.sort((a, b) => a.days_remaining - b.days_remaining))
    }
    return request<CaseSummary[]>(`/cases?scope=${scope}`)
  },

  async getCase(caseId: string): Promise<CaseSummary> {
    if (USE_MOCKS) {
      const c = mockDb.cases.find((x) => x.id === caseId)
      if (!c) throw new ApiError('Case not found', 404)
      return settle(mockDb.summarise(c))
    }
    return request<CaseSummary>(`/cases/${caseId}`)
  },

  async getCaseTasks(caseId: string): Promise<CaseTask[]> {
    if (USE_MOCKS) return settle(mockDb.tasksFor(caseId))
    return request<CaseTask[]>(`/cases/${caseId}/tasks`)
  },

  async getCaseDocuments(caseId: string): Promise<CaseDocument[]> {
    if (USE_MOCKS) return settle(mockDb.documentsFor(caseId))
    return request<CaseDocument[]>(`/cases/${caseId}/documents`)
  },

  async setTaskStatus(taskId: string, status: TaskStatus): Promise<void> {
    if (USE_MOCKS) {
      const task = mockDb.cases
        .flatMap((c) => mockDb.tasksFor(c.id))
        .find((t) => t.id === taskId)
      if (task) {
        task.status = status
        task.completed_at = status === 'completed' ? new Date().toISOString() : null
        if (status === 'completed') task.sla_breached = false
      }
      return settle(undefined, 180)
    }
    await request<void>(`/tasks/${taskId}`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    })
  },

  async getCaseDetail(caseId: string) {
    if (USE_MOCKS) {
      const detail = mockDb.detailFor(caseId)
      if (!detail) throw new ApiError('Case not found', 404)
      return settle(detail)
    }
    return request<import('./types').CaseDetailView>(`/cases/${caseId}/detail`)
  },

  /* --- documents --------------------------------------------------------- */

  async uploadDocument(
    caseId: string,
    docTypeCode: string,
    file: File,
  ): Promise<CaseDocument> {
    if (USE_MOCKS) {
      return settle(
        mockDb.addDocument(caseId, docTypeCode, {
          name: file.name,
          size: file.size,
          type: file.type,
        }),
        600,
      )
    }
    // multipart/form-data — let the browser set Content-Type so it can add the
    // boundary. Setting it by hand here silently breaks the upload.
    const form = new FormData()
    form.append('file', file)
    form.append('doc_type_code', docTypeCode)

    const res = await fetch(`${BASE}/cases/${caseId}/documents`, {
      method: 'POST',
      headers: await authHeader(),
      body: form,
    })
    if (!res.ok) throw new ApiError(await errorMessage(res), res.status)
    return (await res.json()) as CaseDocument
  },

  async submitInlineDocument(
    caseId: string,
    docTypeCode: string,
    content: Record<string, unknown>,
  ): Promise<CaseDocument> {
    if (USE_MOCKS) {
      return settle(
        mockDb.addDocument(caseId, docTypeCode, {
          name: `${docTypeCode}_inline`,
          size: 0,
          type: 'application/json',
        }),
        400,
      )
    }
    return request<CaseDocument>(`/cases/${caseId}/documents/inline`, {
      method: 'POST',
      body: JSON.stringify({ doc_type_code: docTypeCode, content }),
    })
  },

  async reviewDocument(
    docId: string,
    status: DocumentStatus,
    note?: string,
  ): Promise<void> {
    if (USE_MOCKS) {
      mockDb.reviewDocument(docId, status as 'approved' | 'rejected', note ?? null)
      return settle(undefined, 200)
    }
    await request<void>(`/documents/${docId}/review`, {
      method: 'POST',
      body: JSON.stringify({ status, note }),
    })
  },

  /* --- stage approval ---------------------------------------------------- */

  async decideStage(
    caseId: string,
    stageCode: StageCode,
    decision: 'approved' | 'rejected',
    approverId: string,
    comment?: string,
  ): Promise<void> {
    if (USE_MOCKS) {
      mockDb.recordApproval(caseId, stageCode, approverId, decision, comment ?? null)
      return settle(undefined, 250)
    }
    await request<void>(`/cases/${caseId}/stages/${stageCode}/decide`, {
      method: 'POST',
      body: JSON.stringify({ decision, comment }),
    })
  },

  async overrideStage(
    caseId: string,
    stageCode: StageCode,
    reason: string,
  ): Promise<void> {
    await request<void>(`/cases/${caseId}/override-stage`, {
      method: 'POST',
      body: JSON.stringify({ stage_code: stageCode, reason }),
    })
  },

  /* --- knowledge transfer ------------------------------------------------ */

  async patchKtRecord(
    caseId: string,
    patch: { successor_id?: string; overall_status?: KtRecord['overall_status'] },
  ): Promise<void> {
    await request<void>(`/cases/${caseId}/kt`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    })
  },

  async getKt(caseId: string): Promise<KtRecord | null> {
    if (USE_MOCKS) return settle(mockDb.ktFor(caseId))
    return request<KtRecord | null>(`/cases/${caseId}/kt`)
  },

  async saveKtItem(
    caseId: string,
    itemId: string,
    patch: Partial<KtRecord['items'][number]>,
  ): Promise<void> {
    if (USE_MOCKS) {
      mockDb.saveKtItem(itemId, patch)
      return settle(undefined, 150)
    }
    await request<void>(`/cases/${caseId}/kt/items/${itemId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    })
  },

  async addKtItem(caseId: string, topic: string, detail: string): Promise<void> {
    if (USE_MOCKS) {
      mockDb.addKtItem(topic, detail)
      return settle(undefined, 200)
    }
    await request<void>(`/cases/${caseId}/kt/items`, {
      method: 'POST',
      body: JSON.stringify({ topic, detail }),
    })
  },

  /* --- exit interview ---------------------------------------------------- */

  async getInterview(caseId: string): Promise<ExitInterview | null> {
    if (USE_MOCKS) return settle(mockDb.interviewFor(caseId))
    return request<ExitInterview | null>(`/cases/${caseId}/interview`)
  },

  async saveInterview(
    caseId: string,
    responses: Record<string, string | number>,
    submit: boolean,
  ): Promise<void> {
    if (USE_MOCKS) {
      mockDb.saveInterview(caseId, responses, submit)
      return settle(undefined, 300)
    }
    await request<void>(`/cases/${caseId}/interview`, {
      method: 'PUT',
      body: JSON.stringify({ responses, submit }),
    })
  },

  /* --- needs you --------------------------------------------------------- */

  async getInbox(): Promise<Inbox> {
    if (USE_MOCKS) {
      return settle({ documents: [], stages: [], overdue: [], total: 0 })
    }
    return request<Inbox>('/inbox')
  },

  /* --- progress ---------------------------------------------------------- */

  async getProgress(): Promise<CaseProgress[]> {
    if (USE_MOCKS) return settle([])
    return request<CaseProgress[]>('/progress')
  },

  /**
   * Ask Exit Copilot one question and wait for the whole reply.
   *
   * The chat panel streams the same endpoint token by token; this collects the
   * SSE frames and returns the finished text, for places that want an answer
   * rendered into the page rather than a conversation.
   */
  async askAgent(message: string, caseId?: string): Promise<string> {
    if (USE_MOCKS) return settle('The assistant is not available with mocks on.')

    const res = await fetch(`${BASE}/agent/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(await authHeader()) },
      body: JSON.stringify({ message, case_id: caseId ?? null }),
    })
    if (!res.ok) throw new ApiError(await errorMessage(res), res.status)

    const raw = await res.text()
    return raw
      .split('\n')
      .filter((line) => line.startsWith('data: ') && !line.includes('[DONE]'))
      .map((line) => line.slice(6))
      .join('\n')
      .trim()
  },

  /** The IT or Finance work queue — which one depends on who is signed in. */
  async clearanceQueue(): Promise<ClearanceQueue> {
    if (USE_MOCKS) return settle({ role: 'it', stage_code: null, people: [], flagged: 0 })
    return request<ClearanceQueue>('/clearance/queue')
  },

  /** Record an issued item as returned, lost, or never issued. */
  async updateAsset(
    assetId: string,
    patch: { status: CaseAsset['status']; identifier?: string; condition?: string; note?: string },
  ): Promise<CaseAsset> {
    return request<CaseAsset>(`/clearance/assets/${assetId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    })
  },

  /** Record a system as revoked, still live, or not applicable. */
  async updateAccess(
    accessId: string,
    patch: { status: CaseAccess['status']; note?: string },
  ): Promise<CaseAccess> {
    return request<CaseAccess>(`/clearance/access/${accessId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    })
  },

  /** Fill in or confirm one line of the settlement. */
  async updateSettlement(
    itemId: string,
    patch: { status: CaseSettlementItem['status']; amount?: number; note?: string },
  ): Promise<CaseSettlementItem> {
    return request<CaseSettlementItem>(`/clearance/settlement/${itemId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    })
  },

  /** Sign-offs the signed-in approver has already made, newest first. */
  async recentApprovals(limit = 20): Promise<RecentApproval[]> {
    if (USE_MOCKS) return settle([])
    return request<RecentApproval[]>(`/approvals/recent?limit=${limit}`)
  },

  /* --- reminders --------------------------------------------------------- */

  async getReminderDraft(taskId: string): Promise<ReminderDraft> {
    return request<ReminderDraft>(`/tasks/${taskId}/reminder-draft`)
  },

  async sendReminder(taskId: string, subject: string, body: string): Promise<void> {
    await request<void>(`/tasks/${taskId}/remind`, {
      method: 'POST',
      body: JSON.stringify({ subject, body }),
    })
  },

  /* --- notifications ----------------------------------------------------- */

  async listNotifications(): Promise<AppNotification[]> {
    if (USE_MOCKS) return settle([])
    return request<AppNotification[]>('/notifications')
  },

  async markNotificationRead(id: string): Promise<void> {
    await request<void>(`/notifications/${id}/read`, { method: 'POST' })
  },

  /* --- opening a case ---------------------------------------------------- */

  async openCase(input: {
    employee_id?: string
    exit_type?: string
    resignation_date: string
    last_working_day: string
    notice_period_days: number
    reason?: string
  }): Promise<ExitCase> {
    return request<ExitCase>('/cases', {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },

  /* --- approval queue ---------------------------------------------------- */

  async listAgentActions(
    status = 'pending_approval',
    opts: { caseId?: string; kind?: string } = {},
  ): Promise<AgentAction[]> {
    if (USE_MOCKS) {
      let rows = mockDb.agentActions.filter((a) => status === 'all' || a.status === status)
      if (opts.caseId) rows = rows.filter((a) => a.case_id === opts.caseId)
      if (opts.kind) rows = rows.filter((a) => a.kind === opts.kind)
      return settle(rows)
    }
    const params = new URLSearchParams({ status })
    if (opts.caseId) params.set('case_id', opts.caseId)
    if (opts.kind) params.set('kind', opts.kind)
    return request<AgentAction[]>(`/agent/actions?${params}`)
  },

  async decideAgentAction(
    actionId: string,
    decision: 'approved' | 'rejected',
    note?: string,
    editedPayload?: Record<string, unknown>,
  ): Promise<void> {
    if (USE_MOCKS) {
      const action = mockDb.agentActions.find((a) => a.id === actionId)
      if (action) {
        action.status = decision
        action.decided_at = new Date().toISOString()
        action.decision_note = note ?? null
        if (editedPayload) action.payload = editedPayload
      }
      return settle(undefined, 220)
    }
    await request<void>(`/agent/actions/${actionId}/decide`, {
      method: 'POST',
      body: JSON.stringify({ decision, note, payload: editedPayload }),
    })
  },

  async getSweepSummary(): Promise<{ last_run: { finished_at: string; status: string; error: string | null } | null; pending_actions: number }> {
    if (USE_MOCKS) return settle({ last_run: null, pending_actions: 0 })
    return request('/agent/sweep-summary')
  },

  async listAgentRuns(limit = 50): Promise<unknown[]> {
    if (USE_MOCKS) return settle([])
    return request(`/agent/runs?limit=${limit}`)
  },

  /* --- analytics ------------------------------------------------------------- */

  async getAnalytics(): Promise<{
    cases: { active: number; completed: number; on_hold: number; cancelled: number; total: number }
    avg_duration_days: number
    bottleneck_stage: { stage_code: string; stage_name: string; overdue_count: number } | null
    by_department: { department: string; active: number; completed: number; on_hold: number; total: number }[]
    agent: { total_runs: number; actions_drafted: number; actions_executed: number; actions_pending: number }
  }> {
    if (USE_MOCKS) return settle({
      cases: { active: 3, completed: 7, on_hold: 0, cancelled: 0, total: 10 },
      avg_duration_days: 30,
      bottleneck_stage: { stage_code: 'KT_EXECUTION', stage_name: 'KT execution', overdue_count: 4 },
      by_department: [
        { department: 'Engineering', active: 2, completed: 4, on_hold: 0, total: 6 },
        { department: 'Finance', active: 1, completed: 2, on_hold: 0, total: 3 },
        { department: 'HR', active: 0, completed: 1, on_hold: 0, total: 1 },
      ],
      agent: { total_runs: 12, actions_drafted: 35, actions_executed: 28, actions_pending: 7 },
    })
    return request('/analytics')
  },

  /* --- policy docs (Phase 5) --------------------------------------------- */

  async listPolicies(): Promise<PolicyDoc[]> {
    if (USE_MOCKS) return settle([])
    return request<PolicyDoc[]>('/policies')
  },

  async uploadPolicy(title: string, version: string, effectiveFrom: string, file: File): Promise<{ doc_id: string; chunks_ingested: number }> {
    if (USE_MOCKS) return settle({ doc_id: 'mock', chunks_ingested: 0 }, 1500)
    const form = new FormData()
    form.append('title', title)
    form.append('version', version)
    form.append('effective_from', effectiveFrom)
    form.append('file', file)
    return request('/policies', { method: 'POST', body: form, skipContentType: true })
  },

  async deletePolicy(id: string): Promise<void> {
    if (USE_MOCKS) return settle(undefined)
    await request<void>(`/policies/${id}`, { method: 'DELETE' })
  },

  /* --- directory --------------------------------------------------------- */

  async listEmployees(): Promise<Employee[]> {
    if (USE_MOCKS) return settle(mockDb.employees)
    return request<Employee[]>('/employees')
  },

  /**
   * Save the exit-completion confirmation as a PDF.
   *
   * Not via `request`, which assumes a JSON body — this response is bytes. The
   * blob is handed to a synthetic link because the endpoint needs an
   * Authorization header, so a plain <a href> would come back 401.
   */
  async downloadExitCertificate(caseId: string): Promise<void> {
    if (USE_MOCKS) throw new ApiError('Not available with mocks on', 400)

    const res = await fetch(`${BASE}/cases/${caseId}/certificate`, {
      headers: await authHeader(),
    })
    if (!res.ok) throw new ApiError(await errorMessage(res), res.status)

    const url = URL.createObjectURL(await res.blob())
    const link = document.createElement('a')
    link.href = url
    link.download = 'exit-process-completion.pdf'
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  },

  /**
   * Open an uploaded file in a new tab.
   *
   * The backend has served short-lived signed URLs since Phase 2, but nothing
   * on the client ever asked for one — so every uploaded file was
   * write-only. A manager could see that a KT document existed and could
   * approve it, without ever being able to read it.
   *
   * The URL is fetched on click rather than rendered into an href: it expires
   * in two minutes, so one minted at render time would be dead by the time
   * anyone pressed it.
   */
  /**
   * Write an outbound letter from the case record and issue it.
   *
   * The alternative is `uploadDocument`, which needs HR to already have a
   * PDF. Often they do not, and then the employee receives nothing — so the
   * platform writes the standard four itself.
   */
  async generateDocument(
    caseId: string,
    docTypeCode: string,
  ): Promise<CaseDocument> {
    return request<CaseDocument>(`/cases/${caseId}/documents/generate`, {
      method: 'POST',
      body: JSON.stringify({ doc_type_code: docTypeCode }),
    })
  },

  async openDocument(documentId: string): Promise<void> {
    const { url } = await request<{ url: string }>(`/documents/${documentId}/url`)
    window.open(url, '_blank', 'noopener,noreferrer')
  },
}
