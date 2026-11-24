import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { Check, Paperclip, X } from 'lucide-react'
import { useSession } from '@/auth/AuthProvider'
import { StageOverride } from '@/components/StageOverride'
import { StageTrack } from '@/components/StageTrack'
import { SuccessorPicker } from '@/components/SuccessorPicker'
import { Button, Count, Empty, Loading, Panel, Row } from '@/components/ui'
import { api } from '@/lib/api'
import {
  cn,
  dueLabel,
  fileSize,
  longDate,
  OWNER_LABEL_3P,
  relativeTime,
  shortDate,
  taskTone,
  TEXT_TONE,
  type Tone,
} from '@/lib/format'
import type { AgentAction, CaseDocument, DocumentType, KtItem } from '@/lib/types'

/**
 * One exit, whole. The manager's working surface: what's outstanding, what
 * needs reviewing, and the sign-off that moves the case forward.
 */
export function CaseDetail() {
  const { caseId } = useParams<{ caseId: string }>()
  const { employee, role } = useSession()
  const qc = useQueryClient()

  const { data, isLoading, error } = useQuery({
    queryKey: ['case-detail', caseId],
    queryFn: () => api.getCaseDetail(caseId!),
    enabled: !!caseId,
  })

  const { data: complianceActions } = useQuery({
    queryKey: ['compliance-actions', caseId],
    queryFn: () => api.listAgentActions('all', { caseId: caseId!, kind: 'verify_compliance' }),
    enabled: !!caseId,
  })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['case-detail', caseId] })
    qc.invalidateQueries({ queryKey: ['cases'] })
  }

  const review = useMutation({
    mutationFn: ({ id, status, note }: { id: string; status: 'approved' | 'rejected'; note?: string }) =>
      api.reviewDocument(id, status, note),
    onSuccess: invalidate,
  })

  const decideStage = useMutation({
    mutationFn: (decision: 'approved' | 'rejected') =>
      api.decideStage(caseId!, data!.case.current_stage, decision, employee.id),
    onSuccess: invalidate,
  })

  const issue = useMutation({
    mutationFn: ({ docTypeCode, file }: { docTypeCode: string; file?: File }) =>
      file
        ? api.uploadDocument(caseId!, docTypeCode, file)
        : api.generateDocument(caseId!, docTypeCode),
    onSuccess: invalidate,
  })

  // Marking your own task done. IT and Finance have always had this on their
  // clearance queue; HR and managers had it nowhere, so an HR-owned task like
  // "Review exit interview responses" could never be closed and the case
  // simply stopped there, short of the letters it was heading for.
  const completeTask = useMutation({
    mutationFn: (taskId: string) => api.setTaskStatus(taskId, 'completed'),
    onSuccess: invalidate,
  })

  if (isLoading) return <Loading />
  if (error || !data) {
    return (
      <Empty
        title="That case isn't available to you."
        hint="You can only open exits for people who report to you, unless you're in HR."
      />
    )
  }

  const { case: exitCase, employee: subject, stages, tasks, documents, approvals, kt } = data

  const stage = stages.find((s) => s.code === exitCase.current_stage)
  const open = tasks.filter((t) => t.status !== 'completed' && t.status !== 'waived')
  const overdue = open.filter((t) => t.sla_breached)
  const stageTasks = open.filter((t) => t.stage_code === exitCase.current_stage)
  const pendingDocs = documents.filter((d) => d.status === 'pending')

  const canSignOff = stageTasks.length === 0 && pendingDocs.length === 0

  return (
    <div className="space-y-8">
      <header>
        <h1 className="font-serif text-[28px] leading-tight text-ink">{subject.full_name}</h1>
        <p className="mt-1 text-ink-soft">
          {subject.designation} · {subject.department} · {subject.emp_code}
        </p>
        <p className="mt-0.5 text-[13px] text-muted">
          Resigned {shortDate(exitCase.resignation_date)} · last day{' '}
          {longDate(exitCase.last_working_day)}
        </p>
      </header>

      <StageTrack exitCase={exitCase} stages={stages} tasks={tasks} />

      <div className="flex flex-wrap gap-x-8 gap-y-3 border-y border-line py-3">
        <Count value={data.days_remaining} label="days remaining" />
        <Count value={open.length} label="open tasks" />
        {overdue.length > 0 && <Count value={overdue.length} label="overdue" tone="rust" />}
        {pendingDocs.length > 0 && (
          <Count value={pendingDocs.length} label="documents to review" tone="amber" />
        )}
        {exitCase.risk_score !== null && (
          <Count
            value={exitCase.risk_score}
            label="risk score"
            tone={exitCase.risk_score >= 70 ? 'rust' : exitCase.risk_score >= 40 ? 'amber' : 'moss'}
          />
        )}
      </div>

      {/* Sign-off — the action that moves the case on. */}
      <Panel title={`Current stage — ${stage?.name ?? '—'}`}>
        {stageTasks.length === 0 ? (
          <div className="px-4 py-3">
            <p className="text-ink">Everything in this stage is cleared.</p>
          </div>
        ) : (
          stageTasks.map((task) => {
            // A task that produces a document the company issues — a relieving
            // letter, a no-dues certificate — cannot be finished by marking it
            // done: the employee is owed the actual file. Whoever owns it gets
            // an upload here, and HR can cover for any of them.
            const docType = task.doc_type_code
              ? data.document_types.find((t) => t.code === task.doc_type_code)
              : undefined
            const outbound = docType && docType.owner_role !== 'employee'

            // An outbound task is closed by issuing, never by ticking it off
            // — see the panel below. Anything else owned by this role can be
            // marked done here.
            const mine =
              !outbound &&
              (role === 'hr' ||
                (role === 'manager' && task.owner_role === 'manager'))

            return (
              <Row key={task.id} tone={taskTone(task.status, task.sla_breached)}>
                <div className="min-w-0 flex-1">
                  <p className="text-ink">{task.title}</p>
                  <p className="mt-0.5 text-[13px] text-muted">
                    {OWNER_LABEL_3P[task.owner_role]} · {dueLabel(task.due_date)}
                    {outbound && ' · closed by issuing the document, below'}
                  </p>
                </div>
                {mine && (
                  <Button
                    size="sm"
                    variant="secondary"
                    className="shrink-0 self-center"
                    disabled={completeTask.isPending}
                    onClick={() => completeTask.mutate(task.id)}
                  >
                    <Check className="size-3.5" />
                    {completeTask.isPending && completeTask.variables === task.id
                      ? 'Saving'
                      : 'Mark done'}
                  </Button>
                )}
              </Row>
            )
          })
        )}

        {issue.isError && (
          <p className={cn('border-t border-line px-4 py-2 text-[13px]', TEXT_TONE.rust)}>
            {(issue.error as Error).message}
          </p>
        )}

        <div className="flex flex-wrap items-center justify-end gap-2 border-t border-line px-4 py-2.5">
          {!canSignOff && (
            <span className="mr-auto text-[13px] text-muted">
              {stageTasks.length > 0 && `${stageTasks.length} task${stageTasks.length === 1 ? '' : 's'} outstanding`}
              {stageTasks.length > 0 && pendingDocs.length > 0 && ' · '}
              {pendingDocs.length > 0 && `${pendingDocs.length} document${pendingDocs.length === 1 ? '' : 's'} unreviewed`}
            </span>
          )}
          <Button
            variant="danger"
            size="sm"
            disabled={decideStage.isPending}
            onClick={() => decideStage.mutate('rejected')}
          >
            Send back
          </Button>
          <Button
            variant="primary"
            size="sm"
            disabled={decideStage.isPending || !canSignOff}
            onClick={() => decideStage.mutate('approved')}
            title={canSignOff ? undefined : 'Clear everything outstanding first'}
          >
            {decideStage.isPending ? 'Saving' : 'Approve stage'}
          </Button>
        </div>
      </Panel>

      <DocumentsToIssue
        types={data.document_types}
        documents={documents}
        role={role}
        pending={issue.isPending}
        pendingCode={issue.variables?.docTypeCode}
        error={issue.isError ? (issue.error as Error).message : null}
        onIssue={(docTypeCode, file) => issue.mutate({ docTypeCode, file })}
      />

      <Panel title="Documents">
        {documents.length === 0 ? (
          <Empty title="Nothing uploaded yet." />
        ) : (
          documents.map((doc) => (
            <DocumentReviewRow
              key={doc.id}
              doc={doc}
              typeName={
                data.document_types.find((t) => t.code === doc.doc_type_code)?.name ??
                doc.doc_type_code
              }
              busy={review.isPending && review.variables?.id === doc.id}
              onReview={(status, note) => review.mutate({ id: doc.id, status, note })}
            />
          ))
        )}
      </Panel>

      {kt && (
        <Panel title="Knowledge transfer">
          <div className="border-b border-line">
            <SuccessorPicker
              caseId={exitCase.id}
              subjectId={subject.id}
              department={subject.department}
              successorId={kt.successor_id}
              onChange={invalidate}
            />
          </div>

          {kt.items.map((item) => (
            <Row key={item.id} tone={ktTone(item)}>
              <div className="min-w-0 flex-1">
                <p className="text-ink">{item.topic}</p>
                {item.detail && (
                  <p className="mt-0.5 max-w-[70ch] text-[13px] text-muted">{item.detail}</p>
                )}
                {item.gap_note && (
                  <p className="mt-1 text-[13px] text-rust">{item.gap_note}</p>
                )}
              </div>
              <span className={cn('shrink-0 self-center text-[13px]', TEXT_TONE[ktTone(item)])}>
                {item.coverage_status.replace(/_/g, ' ')}
              </span>
            </Row>
          ))}
        </Panel>
      )}

      <CompliancePanel actions={complianceActions ?? []} />

      <Panel title="Sign-off trail">
        {approvals.length === 0 ? (
          <Empty title="No stage has been signed off yet." />
        ) : (
          approvals.map((a) => (
            <Row key={a.id} tone={a.decision === 'approved' ? 'moss' : 'rust'}>
              <div className="min-w-0 flex-1">
                <p className="text-ink">
                  {stages.find((s) => s.code === a.stage_code)?.name ?? a.stage_code}{' '}
                  <span className={TEXT_TONE[a.decision === 'approved' ? 'moss' : 'rust']}>
                    {a.decision}
                  </span>
                </p>
                {a.comment && <p className="mt-0.5 text-[13px] text-muted">{a.comment}</p>}
              </div>
              <time className="shrink-0 self-center text-[13px] text-muted">
                {shortDate(a.decided_at)}
              </time>
            </Row>
          ))
        )}
      </Panel>

      {role === 'hr' && (
        <div className="space-y-4 border-t border-line pt-6">
          <StageOverride
            caseId={exitCase.id}
            stages={stages}
            currentStage={exitCase.current_stage}
            onDone={invalidate}
          />
          <p className="text-[13px] text-muted">
            Exit interview responses are visible to HR in the case record, and are
            never shown to {data.manager?.full_name ?? 'the reporting manager'}.
          </p>
        </div>
      )}
    </div>
  )
}

/** The four documents the platform can write itself. Mirrors services/letters.py. */
const GENERATABLE = new Set([
  'RELIEVING_LETTER',
  'EXPERIENCE_LETTER',
  'NO_DUES_FINANCE',
  'FINAL_SETTLEMENT_STATEMENT',
])

/**
 * Everything the company owes this employee, and the two ways to send it.
 *
 * Deliberately not tied to the current stage. Issuing used to live only on
 * current-stage task rows, so once a task was closed — or the case had moved
 * past it — the letter could never be sent, and a case that slipped through
 * was unrecoverable. This lists all four regardless of stage or task status,
 * so a gap can always be filled.
 *
 * **Generate** writes the letter from the exit record. **Upload** takes HR's
 * own file on company letterhead. Both land the same way: approved, task
 * closed, employee notified.
 */
function DocumentsToIssue({
  types,
  documents,
  role,
  pending,
  pendingCode,
  error,
  onIssue,
}: {
  types: DocumentType[]
  documents: CaseDocument[]
  role: string
  pending: boolean
  pendingCode?: string
  error: string | null
  onIssue: (docTypeCode: string, file?: File) => void
}) {
  const outbound = types.filter((t) => t.owner_role !== 'employee')
  if (outbound.length === 0) return null

  const issuedCount = outbound.filter((t) => latestOf(documents, t.code)).length

  return (
    <Panel
      title="Documents to issue"
      action={
        <span className="text-[13px] text-muted">
          {issuedCount} of {outbound.length} issued
        </span>
      }
    >
      {outbound.map((type) => {
        const doc = latestOf(documents, type.code)
        const canIssue = role === type.owner_role || role === 'hr'
        const busy = pending && pendingCode === type.code

        return (
          <Row key={type.code} tone={doc ? 'moss' : 'amber'} dashed={!doc}>
            <div className="min-w-0 flex-1">
              <p className="text-ink">{type.name}</p>
              <p className="mt-0.5 text-[13px] text-muted">
                {doc ? (
                  <button
                    type="button"
                    onClick={() => api.openDocument(doc.id)}
                    className="underline decoration-line-strong underline-offset-2 hover:text-ink"
                  >
                    {doc.file_name}
                  </button>
                ) : canIssue ? (
                  'Not issued — the employee is waiting on this'
                ) : (
                  `${type.owner_role.toUpperCase()} issues this`
                )}
              </p>
            </div>

            {canIssue && (
              <span className="flex shrink-0 items-center gap-2 self-center">
                {GENERATABLE.has(type.code) && (
                  <Button
                    size="sm"
                    variant={doc ? 'ghost' : 'primary'}
                    disabled={pending}
                    onClick={() => onIssue(type.code)}
                    title="Write it from the exit record — no file needed"
                  >
                    {busy ? 'Working' : doc ? 'Replace' : 'Generate'}
                  </Button>
                )}
                <label
                  className={cn(
                    'cursor-pointer border border-line px-2.5 py-1 text-[13px] text-ink-soft',
                    'transition-colors hover:border-line-strong hover:text-ink',
                    pending && 'pointer-events-none opacity-50',
                  )}
                  title="Upload your own file instead"
                >
                  Upload
                  <input
                    type="file"
                    accept="application/pdf,image/png,image/jpeg"
                    className="sr-only"
                    disabled={pending}
                    onChange={(e) => {
                      const file = e.target.files?.[0]
                      // Reset so picking the same file twice still fires.
                      e.target.value = ''
                      if (file) onIssue(type.code, file)
                    }}
                  />
                </label>
              </span>
            )}
          </Row>
        )
      })}

      {error && (
        <p className={cn('border-t border-line px-4 py-2 text-[13px]', TEXT_TONE.rust)}>
          {error}
        </p>
      )}
      <p className="border-t border-line px-4 py-2 text-[13px] text-muted">
        Issuing sends the document to the employee and closes its task. Generate
        writes it from the exit record; Upload takes your own file.
      </p>
    </Panel>
  )
}

/** The newest document of a given type, if any. */
function latestOf(documents: CaseDocument[], code: string): CaseDocument | undefined {
  return documents
    .filter((d) => d.doc_type_code === code)
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0]
}

function DocumentReviewRow({
  doc,
  typeName,
  busy,
  onReview,
}: {
  doc: CaseDocument
  typeName: string
  busy: boolean
  onReview: (status: 'approved' | 'rejected', note?: string) => void
}) {
  const [rejecting, setRejecting] = useState(false)
  const [note, setNote] = useState('')

  const tone: Tone =
    doc.status === 'approved' ? 'moss' : doc.status === 'rejected' ? 'rust' : 'amber'

  return (
    <Row tone={tone}>
      <div className="min-w-0 flex-1">
        <p className="text-ink">{typeName}</p>
        <p className="mt-0.5 flex items-center gap-1.5 text-[13px] text-muted">
          <Paperclip className="size-3.5 shrink-0" />
          {doc.is_inline ? (
            <span className="truncate">Filled in on the platform</span>
          ) : (
            <>
              {/* Reading the file before deciding on it was not previously
                  possible from any screen — the signed-URL endpoint existed
                  but nothing called it. */}
              <button
                type="button"
                onClick={() => api.openDocument(doc.id)}
                className="truncate underline decoration-line-strong underline-offset-2 hover:text-ink"
              >
                {doc.file_name}
              </button>
              <span>{fileSize(doc.size_bytes)}</span>
            </>
          )}
          <span>· uploaded {relativeTime(doc.created_at)}</span>
        </p>
        {doc.review_note && (
          <p className="mt-1 text-[13px] text-rust">{doc.review_note}</p>
        )}

        {rejecting && (
          <div className="mt-2">
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={2}
              placeholder="What needs to change? The employee sees this."
              className="w-full resize-y border border-line bg-paper px-2.5 py-1.5 text-[13px] text-ink placeholder:text-muted"
              aria-label="Reason for rejection"
            />
            <div className="mt-2 flex justify-end gap-2">
              <Button size="sm" variant="ghost" onClick={() => setRejecting(false)}>
                Cancel
              </Button>
              <Button
                size="sm"
                variant="danger"
                disabled={busy || !note.trim()}
                onClick={() => onReview('rejected', note.trim())}
              >
                Send back
              </Button>
            </div>
          </div>
        )}
      </div>

      {doc.status === 'pending' && !rejecting && (
        <div className="flex shrink-0 items-center gap-2 self-center">
          <Button size="sm" variant="ghost" onClick={() => setRejecting(true)} disabled={busy}>
            <X className="size-3.5" />
            Reject
          </Button>
          <Button size="sm" variant="primary" onClick={() => onReview('approved')} disabled={busy}>
            <Check className="size-3.5" />
            Approve
          </Button>
        </div>
      )}

      {doc.status !== 'pending' && (
        <span className={cn('shrink-0 self-center text-[13px]', TEXT_TONE[tone])}>
          {doc.status === 'approved' ? 'Approved' : 'Rejected'}
        </span>
      )}
    </Row>
  )
}

function CompliancePanel({ actions }: { actions: AgentAction[] }) {
  if (actions.length === 0) return null

  // Most recent first — show the latest result and any pending checks
  const pending = actions.find((a) => a.status === 'pending_approval')
  const executed = actions.find((a) => a.status === 'executed')
  const latest = executed ?? pending

  if (!latest) return null

  const payload = (latest.approved_payload ?? latest.payload) as {
    compliant?: boolean
    gaps?: string[]
    citations?: string[]
  }
  const { compliant, gaps = [], citations = [] } = payload

  const isPending = latest.status === 'pending_approval'
  const tone: Tone = isPending ? 'amber' : compliant ? 'moss' : gaps.length > 0 ? 'rust' : 'moss'

  return (
    <Panel title="Compliance check">
      <Row tone={tone}>
        <div className="min-w-0 flex-1">
          {isPending ? (
            <p className="text-ink">Compliance review is pending approval in the action queue.</p>
          ) : (
            <p className={cn('font-medium', TEXT_TONE[tone])}>
              {compliant ? 'Compliant — no gaps found.' : `${gaps.length} gap${gaps.length === 1 ? '' : 's'} identified.`}
            </p>
          )}

          {!isPending && gaps.length > 0 && (
            <ul className="mt-2 space-y-1 text-[13px] text-rust">
              {gaps.map((g, i) => (
                <li key={i} className="flex gap-1.5">
                  <span className="mt-0.5 shrink-0">·</span>
                  <span>{g}</span>
                </li>
              ))}
            </ul>
          )}

          {!isPending && citations.length > 0 && (
            <ul className="mt-2 space-y-0.5 text-[12px] text-muted">
              {citations.map((c, i) => (
                <li key={i}>
                  <span className="italic">{c}</span>
                </li>
              ))}
            </ul>
          )}

          <p className="mt-1.5 text-[12px] text-muted">
            {isPending ? 'Approve the action to record the compliance result.' : `Checked ${relativeTime(latest.executed_at ?? latest.decided_at ?? latest.created_at)}.`}
          </p>
        </div>
      </Row>
    </Panel>
  )
}

function ktTone(item: KtItem): Tone {
  if (item.coverage_status === 'gap') return 'rust'
  if (item.coverage_status === 'documented' || item.coverage_status === 'verified') return 'moss'
  if (item.coverage_status === 'in_progress') return 'amber'
  return 'neutral'
}
