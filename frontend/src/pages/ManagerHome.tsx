import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Button, Count, Empty, Loading, PageHeader, Panel, Row } from '@/components/ui'
import { ReminderComposer } from '@/components/ReminderComposer'
import { api } from '@/lib/api'
import { cn, relativeTime, shortDate, TEXT_TONE } from '@/lib/format'
import type { Tone } from '@/lib/format'
import type { CaseProgress, InboxOverdue } from '@/lib/types'

/**
 * The manager's home. One screen that answers the five questions a manager
 * actually has: who reports to me, how far along is each of them, what is
 * waiting on me right now, what have I already cleared, and what has slipped.
 *
 * Those answers used to be split across three pages, none of which showed
 * progress. `/progress` already returned everything needed and was reachable
 * by managers — RLS scopes it to their own reports — it was simply never
 * shown to them.
 */
export function ManagerHome() {
  const [reminderFor, setReminderFor] = useState<InboxOverdue | null>(null)
  const qc = useQueryClient()

  const { data: inbox, isLoading: inboxLoading } = useQuery({
    queryKey: ['inbox'],
    queryFn: () => api.getInbox(),
  })
  const { data: team, isLoading: teamLoading } = useQuery({
    queryKey: ['progress'],
    queryFn: () => api.getProgress(),
  })
  const { data: approved } = useQuery({
    queryKey: ['recent-approvals'],
    queryFn: () => api.recentApprovals(8),
  })

  if (inboxLoading || teamLoading) return <Loading />

  const documents = inbox?.documents ?? []
  const stages = inbox?.stages ?? []
  const overdue = inbox?.overdue ?? []
  // Finished exits stay listed, at the bottom — the manager should still see
  // who has left, not just who is still in flight.
  const roster = (team ?? []).slice().sort((a, b) => {
    const aDone = a.percent_complete === 100 ? 1 : 0
    const bDone = b.percent_complete === 100 ? 1 : 0
    return aDone - bDone || a.days_remaining - b.days_remaining
  })
  const stillGoing = roster.filter((p) => p.percent_complete < 100).length

  const waitingOnMe = documents.length + stages.length
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['inbox'] })
    qc.invalidateQueries({ queryKey: ['progress'] })
    qc.invalidateQueries({ queryKey: ['recent-approvals'] })
  }

  return (
    <div>
      <PageHeader
        title={
          waitingOnMe > 0
            ? `${waitingOnMe} ${waitingOnMe === 1 ? 'thing needs' : 'things need'} your approval`
            : 'Nothing is waiting on your approval'
        }
        lede="Your team's exits, what you still have to sign, and what you have already cleared."
      />

      <div className="mb-8 flex flex-wrap gap-x-8 gap-y-3 border-y border-line py-3">
        <Count value={stillGoing} label="exits in progress" />
        {roster.length > stillGoing && (
          <Count value={roster.length - stillGoing} label="completed" tone="moss" />
        )}
        <Count value={waitingOnMe} label="waiting on you" tone={waitingOnMe ? 'amber' : 'moss'} />
        <Count
          value={overdue.length}
          label="overdue tasks"
          tone={overdue.length ? 'rust' : 'moss'}
        />
      </div>

      <div className="space-y-8">
        <Panel title="Waiting for your approval">
          {waitingOnMe === 0 ? (
            <Empty
              title="You are up to date."
              hint="New documents and stage sign-offs will appear here as your team submits them."
            />
          ) : (
            <>
              {documents.map((doc) => (
                <Row key={doc.document_id} tone="amber">
                  <div className="min-w-0 flex-1">
                    <p className="text-ink">
                      {doc.document_name}
                      <span className="text-muted"> — {doc.employee.full_name}</span>
                    </p>
                    <p className="mt-0.5 text-[13px] text-muted">
                      Document · submitted {relativeTime(doc.uploaded_at)}
                    </p>
                    {doc.verification && !doc.verification.belongs && (
                      <p className="mt-1.5 border-l-2 border-amber pl-2 text-[13px] text-ink-soft">
                        <span className="text-amber">
                          Automatic check: this may not be a {doc.document_name}.
                        </span>{' '}
                        {doc.verification.reason}
                      </p>
                    )}
                  </div>
                  <Link to={`/cases/${doc.case_id}`} className="shrink-0 self-center">
                    <Button size="sm">Review</Button>
                  </Link>
                </Row>
              ))}

              {stages.map((stage) => (
                <Row key={`${stage.case_id}-${stage.stage_code}`} tone="moss">
                  <div className="min-w-0 flex-1">
                    <p className="text-ink">
                      {stage.stage_name}
                      <span className="text-muted"> — {stage.employee.full_name}</span>
                    </p>
                    <p className="mt-0.5 text-[13px] text-muted">
                      Stage ready to sign off · last day {shortDate(stage.last_working_day)}
                    </p>
                  </div>
                  <Link to={`/cases/${stage.case_id}`} className="shrink-0 self-center">
                    <Button size="sm">Sign off</Button>
                  </Link>
                </Row>
              ))}
            </>
          )}
        </Panel>

        <Panel title="Your team">
          {roster.length === 0 ? (
            <Empty title="Nobody reporting to you is currently exiting." />
          ) : (
            roster.map((person) => <TeamRow key={person.case_id} person={person} />)
          )}
        </Panel>

        {overdue.length > 0 && (
          <Panel title={`Overdue (${overdue.length})`}>
            {overdue.map((task) => (
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

        <Panel title="Already approved by you">
          {!approved || approved.length === 0 ? (
            <Empty
              title="Nothing signed off yet."
              hint="Stages you approve will be listed here so you can see what you have cleared."
            />
          ) : (
            approved.map((item) => (
              <Row key={item.id} tone={item.decision === 'approved' ? 'moss' : 'rust'}>
                <div className="min-w-0 flex-1">
                  <p className="text-ink">
                    {item.kind === 'stage' ? item.stage_name : item.label}
                    <span className="text-muted">
                      {' '}
                      — {item.employee?.full_name ?? 'Unknown'}
                    </span>
                  </p>
                  <p className="mt-0.5 text-[13px] text-muted">
                    {item.kind === 'stage'
                      ? item.decision === 'approved'
                        ? 'Stage signed off'
                        : 'Stage sent back'
                      : item.decision === 'approved'
                        ? 'Approved'
                        : 'Sent back'}{' '}
                    {relativeTime(item.decided_at)}
                    {item.comment ? ` · ${item.comment}` : ''}
                  </p>
                </div>
                <Link to={`/cases/${item.case_id}`} className="shrink-0 self-center">
                  <Button size="sm" variant="ghost">
                    Open case
                  </Button>
                </Link>
              </Row>
            ))
          )}
        </Panel>
      </div>

      {reminderFor && (
        <ReminderComposer
          taskId={reminderFor.task_id}
          onClose={() => setReminderFor(null)}
          onSent={() => {
            setReminderFor(null)
            refresh()
          }}
        />
      )}
    </div>
  )
}

function TeamRow({ person }: { person: CaseProgress }) {
  // Rail tone reads the same way as everywhere else: breached is rust, close
  // to the last day is amber, finished is moss.
  const tone: Tone =
    person.percent_complete === 100
      ? 'moss'
      : person.tasks_overdue > 0
        ? 'rust'
        : person.days_remaining <= 14
          ? 'amber'
          : 'neutral'

  return (
    <Row tone={tone}>
      <div className="min-w-0 flex-1">
        <p className="text-ink">
          {person.employee.full_name}
          <span className="text-muted"> · {person.employee.designation}</span>
        </p>
        <p className="mt-0.5 text-[13px] text-muted">
          {person.percent_complete === 100
            ? `Exited · last day ${shortDate(person.last_working_day)}`
            : `${person.current_stage.replace(/_/g, ' ').toLowerCase()} · last day ${shortDate(
                person.last_working_day,
              )}${
                person.days_remaining >= 0
                  ? ` · ${person.days_remaining} days left`
                  : ' · notice ended'
              }`}
        </p>

        {/* Progress as a measure, not a pill — same idea as the employee's
            StageTrack, scaled down to one line per person. */}
        <div className="mt-2 flex items-center gap-2">
          <div className="h-1 w-40 bg-sunken" aria-hidden>
            <div
              className={cn('h-full', person.percent_complete === 100 ? 'bg-moss' : 'bg-indigo')}
              style={{ width: `${person.percent_complete}%` }}
            />
          </div>
          <span className="text-[13px] tabular-nums text-ink-soft">
            {person.tasks_done}/{person.tasks_total} · {person.percent_complete}%
          </span>
          {person.tasks_overdue > 0 && (
            <span className={cn('text-[13px]', TEXT_TONE.rust)}>
              {person.tasks_overdue} overdue
            </span>
          )}
          {person.documents_pending > 0 && (
            <span className={cn('text-[13px]', TEXT_TONE.amber)}>
              {person.documents_pending} to review
            </span>
          )}
        </div>
      </div>

      <Link to={`/cases/${person.case_id}`} className="shrink-0 self-center">
        <Button size="sm" variant="ghost">
          Open case
        </Button>
      </Link>
    </Row>
  )
}
