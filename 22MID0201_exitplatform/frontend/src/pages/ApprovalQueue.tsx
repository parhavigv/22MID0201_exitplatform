import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle } from 'lucide-react'
import { Button, Empty, Loading, PageHeader, Row } from '@/components/ui'
import { api } from '@/lib/api'
import { relativeTime } from '@/lib/format'
import type { AgentAction } from '@/lib/types'

const KIND_LABEL: Record<string, string> = {
  draft_notification: 'Notification',
  draft_escalation: 'Escalation',
  flag_policy_breach: 'Policy breach',
  request_document: 'Document request',
  generate_exit_checklist: 'Checklist',
}

/**
 * Every outward-facing thing the agent produces stops here first. Nothing in
 * this queue has taken effect — approving is what sends it.
 */
export function ApprovalQueue() {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['agent-actions'],
    queryFn: () => api.listAgentActions('pending_approval'),
  })

  const decide = useMutation({
    mutationFn: ({
      id,
      decision,
      payload,
    }: {
      id: string
      decision: 'approved' | 'rejected'
      payload?: Record<string, unknown>
    }) => api.decideAgentAction(id, decision, undefined, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agent-actions'] }),
  })

  const actions = data ?? []

  return (
    <div>
      <PageHeader
        title="Approvals"
        lede="Drafts the assistant has prepared. Nothing here has been sent — review the wording, then approve or reject."
      />

      {isLoading ? (
        <Loading />
      ) : actions.length === 0 ? (
        <Empty
          title="Nothing is waiting for you."
          hint="Drafts appear here when the assistant spots an overdue task, a missing document, or a stalled approval."
        />
      ) : (
        <div className="space-y-3">
          {actions.map((action) => (
            <ActionCard
              key={action.id}
              action={action}
              onDecide={(decision, payload) =>
                decide.mutate({ id: action.id, decision, payload })
              }
              busy={decide.isPending && decide.variables?.id === action.id}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function ActionCard({
  action,
  onDecide,
  busy,
}: {
  action: AgentAction
  onDecide: (decision: 'approved' | 'rejected', payload?: Record<string, unknown>) => void
  busy: boolean
}) {
  const body = typeof action.payload.body === 'string' ? action.payload.body : null
  const subject = typeof action.payload.subject === 'string' ? action.payload.subject : null
  const recipient =
    typeof action.payload.recipient === 'string' ? action.payload.recipient : null

  const [draft, setDraft] = useState(body ?? '')
  const edited = body !== null && draft !== body

  return (
    <article className="border border-line bg-surface">
      <header className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b border-line px-4 py-2.5">
        <div className="min-w-0">
          <p className="text-ink">{action.summary}</p>
          <p className="mt-0.5 text-[13px] text-muted">
            {KIND_LABEL[action.kind] ?? action.kind}
            {recipient && ` · to ${recipient}`} · drafted {relativeTime(action.created_at)}
          </p>
        </div>
      </header>

      {action.self_targeting && (
        <Row tone="rust">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-rust" />
          <p className="text-[13px] text-ink-soft">
            This draft affects the clearance of the person who asked for it. Check it
            carefully before approving.
          </p>
        </Row>
      )}

      <div className="px-4 py-3">
        {subject && (
          <p className="mb-2 text-[13px] text-ink-soft">
            <span className="text-muted">Subject: </span>
            {subject}
          </p>
        )}

        {body !== null ? (
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={Math.min(14, draft.split('\n').length + 2)}
            className="w-full resize-y border border-line bg-paper px-3 py-2 font-sans text-[13px] leading-relaxed text-ink"
            aria-label="Message body"
          />
        ) : (
          <dl className="space-y-1.5 text-[13px]">
            {Object.entries(action.payload).map(([key, value]) => (
              <div key={key} className="flex gap-2">
                <dt className="w-28 shrink-0 text-muted">{humanise(key)}</dt>
                <dd className="text-ink-soft">{String(value)}</dd>
              </div>
            ))}
          </dl>
        )}
      </div>

      <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-line px-4 py-2.5">
        {edited && <span className="mr-auto text-[13px] text-muted">Edited</span>}
        <Button variant="danger" size="sm" disabled={busy} onClick={() => onDecide('rejected')}>
          Reject
        </Button>
        <Button
          variant="primary"
          size="sm"
          disabled={busy}
          onClick={() =>
            onDecide('approved', edited ? { ...action.payload, body: draft } : undefined)
          }
        >
          {busy ? 'Saving' : edited ? 'Approve edited' : 'Approve and send'}
        </Button>
      </footer>
    </article>
  )
}

function humanise(key: string): string {
  const s = key.replace(/_/g, ' ')
  return s[0].toUpperCase() + s.slice(1)
}
