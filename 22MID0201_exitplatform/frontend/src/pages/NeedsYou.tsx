import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Check, X, CheckSquare } from 'lucide-react'
import { Button, Empty, Loading, PageHeader, Panel, Row } from '@/components/ui'
import { ReminderComposer } from '@/components/ReminderComposer'
import { api } from '@/lib/api'
import { cn, relativeTime, shortDate } from '@/lib/format'
import type { InboxDocument, InboxOverdue, NdaContent } from '@/lib/types'

/** The shape a KT summary is submitted in. Mirrors workflow.py's inline save. */
interface KtInlineContent {
  items_count: number
  topics: { topic: string; detail: string | null; status: string }[]
}

/**
 * Everything waiting on the signed-in person, across every case they oversee.
 *
 * Without this a manager has to open each report's case in turn just to find
 * out there is nothing to do. Scoping is entirely RLS — this screen shows what
 * the API returns and adds no filtering of its own.
 */
export function NeedsYou() {
  const qc = useQueryClient()
  const [reminderFor, setReminderFor] = useState<InboxOverdue | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['inbox'],
    queryFn: () => api.getInbox(),
  })

  const review = useMutation({
    mutationFn: ({ id, status }: { id: string; status: 'approved' | 'rejected' }) =>
      api.reviewDocument(id, status),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['inbox'] })
      qc.invalidateQueries({ queryKey: ['cases'] })
    },
  })

  if (isLoading) return <Loading />

  const inbox = data ?? { documents: [], stages: [], overdue: [], total: 0 }

  if (inbox.total === 0) {
    return (
      <div>
        <PageHeader title="Needs you" />
        <Empty
          title="Nothing is waiting on you."
          hint="Documents to review, stages ready to sign off, and overdue work all appear here."
        />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Needs you"
        lede={`${inbox.total} ${inbox.total === 1 ? 'thing needs' : 'things need'} your attention across your team.`}
      />

      {inbox.documents.length > 0 && (
        <Panel title={`Documents to review (${inbox.documents.length})`}>
          {inbox.documents.map((doc) => (
            <DocumentReviewRow
              key={doc.document_id}
              doc={doc}
              reviewPending={review.isPending && (review.variables as { id: string })?.id === doc.document_id}
              onApprove={() => review.mutate({ id: doc.document_id, status: 'approved' })}
              onReject={() => review.mutate({ id: doc.document_id, status: 'rejected' })}
            />
          ))}
        </Panel>
      )}

      {inbox.stages.length > 0 && (
        <Panel title={`Stages ready to sign off (${inbox.stages.length})`}>
          {inbox.stages.map((stage) => (
            <Row key={`${stage.case_id}-${stage.stage_code}`} tone="moss">
              <div className="min-w-0 flex-1">
                <p className="text-ink">
                  {stage.stage_name}
                  <span className="text-muted"> — {stage.employee.full_name}</span>
                </p>
                <p className="mt-0.5 text-[13px] text-muted">
                  Everything in this stage is cleared · last day{' '}
                  {shortDate(stage.last_working_day)}
                </p>
              </div>
              <Link to={`/cases/${stage.case_id}`} className="shrink-0 self-center">
                <Button size="sm" variant="primary">
                  Review and sign off
                </Button>
              </Link>
            </Row>
          ))}
        </Panel>
      )}

      {inbox.overdue.length > 0 && (
        <Panel title={`Overdue (${inbox.overdue.length})`}>
          {inbox.overdue.map((task) => (
            <Row key={task.task_id} tone="rust">
              <div className="min-w-0 flex-1">
                <p className="text-ink">{task.title}</p>
                <p className="mt-0.5 text-[13px] text-muted">
                  {task.employee.full_name} · {task.stage_name} · due{' '}
                  {shortDate(task.due_date)}
                </p>
              </div>

              <div className="flex shrink-0 items-center gap-3 self-center">
                <span className="text-[13px] text-rust">
                  {task.days_overdue} {task.days_overdue === 1 ? 'day' : 'days'} late
                </span>
                <Button size="sm" onClick={() => setReminderFor(task)}>
                  Send reminder
                </Button>
              </div>
            </Row>
          ))}
        </Panel>
      )}

      {reminderFor && (
        <ReminderComposer
          taskId={reminderFor.task_id}
          onClose={() => setReminderFor(null)}
          onSent={() => {
            setReminderFor(null)
            qc.invalidateQueries({ queryKey: ['inbox'] })
          }}
        />
      )}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Document review row — shows inline content (NDA, KT) or a file reference.  */
/* -------------------------------------------------------------------------- */

const NDA_STATEMENTS = [
  'Has returned all confidential information.',
  'Understands post-employment confidentiality obligations.',
  'Has not taken, and will not take, confidential information elsewhere.',
  'Has disclosed any conflicts of interest with their next employer.',
]

function DocumentReviewRow({
  doc,
  reviewPending,
  onApprove,
  onReject,
}: {
  doc: InboxDocument
  reviewPending: boolean
  onApprove: () => void
  onReject: () => void
}) {
  const [expanded, setExpanded] = useState(doc.is_inline ?? false)

  return (
    <article className="border-b border-line last:border-b-0">
      <Row tone="amber">
        <div className="min-w-0 flex-1">
          <p className="text-ink">
            {doc.document_name}
            <span className="text-muted"> — {doc.employee.full_name}</span>
          </p>
          <p className="mt-0.5 text-[13px] text-muted">
            {doc.is_inline ? 'Filled in online' : doc.file_name} · submitted{' '}
            {relativeTime(doc.uploaded_at)}
          </p>

          {/* Surfaced before you open the file, which is when it saves you the
              trip. Advisory — you are still the one deciding. */}
          {doc.verification && !doc.verification.belongs && (
            <p className="mt-1.5 border-l-2 border-amber pl-2 text-[13px] text-ink-soft">
              <span className="text-amber">
                Automatic check: this may not be a {doc.document_name}.
              </span>{' '}
              {doc.verification.reason}
            </p>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-2 self-center">
          {doc.is_inline && (
            <button
              onClick={() => setExpanded((v) => !v)}
              className="text-[13px] text-indigo underline"
            >
              {expanded ? 'Hide' : 'Read'}
            </button>
          )}
          {!doc.is_inline && (
            <Link to={`/cases/${doc.case_id}`}>
              <Button size="sm" variant="ghost">Open case</Button>
            </Link>
          )}
          <Button
            size="sm"
            variant="ghost"
            disabled={reviewPending}
            onClick={onReject}
            title="Rejecting from here sends it back without a note. Open the case to add one."
          >
            <X className="size-3.5" />
            Reject
          </Button>
          <Button size="sm" variant="primary" disabled={reviewPending} onClick={onApprove}>
            <Check className="size-3.5" />
            Approve
          </Button>
        </div>
      </Row>

      {/* Inline content — NDA acknowledgement */}
      {expanded && doc.is_inline && doc.content && (
        <div className={cn('border-t border-line px-4 py-4 bg-paper')}>
          {'acknowledgements' in doc.content && (
            <div className="space-y-2">
              <p className="text-[12px] font-semibold uppercase tracking-wide text-muted">
                Acknowledgements — signed as{' '}
                <span className="text-ink">{(doc.content as NdaContent).full_name}</span>
              </p>
              {NDA_STATEMENTS.map((statement, i) => {
                const checked = (doc.content as NdaContent).acknowledgements?.[i] ?? false
                return (
                  <div key={i} className="flex items-start gap-2.5">
                    <CheckSquare
                      className={cn('mt-0.5 size-4 shrink-0', checked ? 'text-moss' : 'text-rust')}
                    />
                    <p className={cn('text-[13px]', checked ? 'text-ink' : 'text-rust')}>
                      {statement}
                    </p>
                  </div>
                )
              })}
            </div>
          )}

          {'topics' in doc.content && (
            <div className="space-y-3">
              <p className="text-[12px] font-semibold uppercase tracking-wide text-muted">
                Knowledge Transfer —{' '}
                {(doc.content as unknown as KtInlineContent).items_count ?? 0} topics
              </p>
              {((doc.content as unknown as KtInlineContent).topics ?? []).map(
                (t, i) => (
                  <div key={i} className="border-l-2 border-line pl-3">
                    <p className="text-[13px] font-medium text-ink">{t.topic}</p>
                    {t.detail && (
                      <p className="mt-0.5 text-[13px] text-muted">{t.detail}</p>
                    )}
                    <p className="mt-0.5 text-[12px] text-ink-soft">{t.status}</p>
                  </div>
                ),
              )}
            </div>
          )}
        </div>
      )}
    </article>
  )
}
