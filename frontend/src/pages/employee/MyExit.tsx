import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Check, Download } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useSession } from '@/auth/AuthProvider'
import { StageTrack } from '@/components/StageTrack'
import { Button, Count, Empty, Loading, Panel, Row } from '@/components/ui'
import { SubmitResignation } from './SubmitResignation'
import { api } from '@/lib/api'
import {
  cn,
  dueLabel,
  latestDocumentFor,
  longDate,
  OWNER_LABEL,
  shortDate,
  taskDisplayStatus,
  taskTone,
  TEXT_TONE,
} from '@/lib/format'
import type {
  CaseAsset,
  CaseDocument,
  CaseSettlementItem,
  CaseTask,
} from '@/lib/types'

export function MyExit() {
  const { employee } = useSession()
  const qc = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['my-exit', employee.id],
    queryFn: () => api.myExit(employee.id),
  })

  // What was just ticked off, so the action can be acknowledged.
  //
  // "What needs you" lists open tasks only, so completing one removes its row
  // and the next task slides up into the same place — still showing a "Mark
  // done" button. The click worked, but it reads as though nothing happened
  // and you are now looking at a different task. Naming what was completed is
  // what makes the difference visible.
  const [justDone, setJustDone] = useState<string | null>(null)

  const complete = useMutation({
    mutationFn: (taskId: string) => api.setTaskStatus(taskId, 'completed'),
    onSuccess: (_result, taskId) => {
      const task = data?.tasks.find((t) => t.id === taskId)
      setJustDone(task?.title ?? 'Task')
      qc.invalidateQueries({ queryKey: ['my-exit', employee.id] })
    },
  })

  if (isLoading) return <Loading />

  // No case yet: this screen becomes the way to start one.
  if (!data) return <SubmitResignation />

  const {
    case: exitCase,
    stages,
    tasks,
    documents,
    assets,
    settlement,
    days_remaining,
    manager,
  } = data

  const open = tasks.filter((t) => t.status !== 'completed' && t.status !== 'waived')
  const mine = open.filter((t) => t.owner_role === 'employee')
  const others = open.filter((t) => t.owner_role !== 'employee')
  const overdue = mine.filter((t) => t.sla_breached)

  // Counted the same way /progress counts it on HR's screen — waived is done,
  // because the obligation was cleared — so the two never disagree.
  const done = tasks.filter(
    (t) => t.status === 'completed' || t.status === 'waived',
  ).length
  const percent = tasks.length ? Math.round((done / tasks.length) * 100) : 0
  const allDone = tasks.length > 0 && done === tasks.length

  return (
    <div className="space-y-8">
      {/* The statement, in the serif voice. The one sentence that matters. */}
      <header>
        <h1 className="font-serif text-[32px] leading-tight text-ink">
          Your last working day is {longDate(exitCase.last_working_day)}
        </h1>
        <p className="mt-1.5 text-ink-soft">
          {days_remaining > 0
            ? `${days_remaining} days left. ${mine.length} things still need you.`
            : 'Your notice period has ended.'}
        </p>
      </header>

      {allDone && <ExitComplete caseId={exitCase.id} />}

      {/* The hero: the notice period as a measure. */}
      <StageTrack exitCase={exitCase} stages={stages} tasks={tasks} />

      <div className="flex flex-wrap gap-x-8 gap-y-3 border-y border-line py-3">
        <Count value={`${done}/${tasks.length}`} label={`cleared · ${percent}%`} tone="moss" />
        <Count value={mine.length} label="waiting on you" />
        {overdue.length > 0 && (
          <Count value={overdue.length} label="overdue" tone="rust" />
        )}
        <Count value={others.length} label="waiting on others" />
      </div>

      <Panel title="What needs you">
        {justDone && (
          <p className="border-b border-line bg-moss-soft px-4 py-2 text-[13px] text-ink-soft">
            <span className={TEXT_TONE.moss}>Done.</span> “{justDone}” is
            complete and has moved off this list — you can see it under Tasks.
          </p>
        )}
        {mine.length === 0 ? (
          <Empty
            title="Nothing is waiting on you right now."
            hint="You'll see new tasks here as your exit moves through its stages."
          />
        ) : (
          mine
            .slice()
            .sort(byDueDate)
            .map((task) => (
              <TaskRow
                key={task.id}
                task={task}
                doc={latestDocumentFor(documents, task.doc_type_code)}
                stageName={stages.find((s) => s.code === task.stage_code)?.name ?? ''}
                onComplete={() => complete.mutate(task.id)}
                pending={complete.isPending && complete.variables === task.id}
              />
            ))
        )}
      </Panel>

      <Panel title="Waiting on others">
        {others.length === 0 ? (
          <Empty title="Nothing is with anyone else." />
        ) : (
          others
            .slice()
            .sort(byDueDate)
            .map((task) => (
              <Row key={task.id} tone={taskTone(task.status, task.sla_breached)} dashed>
                <div className="min-w-0 flex-1">
                  <p className="text-ink">{task.title}</p>
                  <p className="mt-0.5 text-[13px] text-muted">
                    {OWNER_LABEL[task.owner_role]} ·{' '}
                    {stages.find((s) => s.code === task.stage_code)?.name}
                  </p>
                </div>
                <time
                  className={cn(
                    'shrink-0 text-[13px]',
                    TEXT_TONE[taskTone(task.status, task.sla_breached)],
                  )}
                >
                  {dueLabel(task.due_date)}
                </time>
              </Row>
            ))
        )}
      </Panel>

      <Tracked assets={assets} settlement={settlement} />

      {manager && (
        <p className="text-[13px] text-muted">
          Your manager for this exit is {manager.full_name}. Questions about a
          specific clearance go to them first.
        </p>
      )}
    </div>
  )
}

function TaskRow({
  task,
  doc,
  stageName,
  onComplete,
  pending,
}: {
  task: CaseTask
  doc?: CaseDocument
  stageName: string
  onComplete: () => void
  pending: boolean
}) {
  const display = taskDisplayStatus(task, doc)

  // A task that expects a document is finished by uploading it and having the
  // manager approve — not by the employee ticking it off. Offering "Mark done"
  // here would let someone clear the task without ever submitting anything.
  const needsDocument = Boolean(task.doc_type_code)

  return (
    <Row tone={display.tone}>
      <div className="min-w-0 flex-1">
        <p className="text-ink">{task.title}</p>
        {task.description && (
          <p className="mt-0.5 max-w-[68ch] text-[13px] text-muted">{task.description}</p>
        )}
        <p className="mt-0.5 text-[13px] text-muted">{stageName}</p>
        <p className={cn('mt-0.5 text-[13px]', TEXT_TONE[display.tone])}>{display.label}</p>
        {display.hint && (
          <p className="mt-0.5 max-w-[68ch] text-[13px] text-ink-soft">{display.hint}</p>
        )}
      </div>

      <div className="flex shrink-0 items-center gap-3">
        <time className={cn('text-[13px]', TEXT_TONE[display.tone])}>
          {dueLabel(task.due_date)}
        </time>
        {needsDocument ? (
          <Link to="/my-documents">
            <Button size="sm" variant="ghost">
              {doc?.status === 'rejected' ? 'Resubmit' : 'Go to documents'}
            </Button>
          </Link>
        ) : (
          <Button size="sm" onClick={onComplete} disabled={pending}>
            <Check className="size-3.5" />
            {pending ? 'Saving' : 'Mark done'}
          </Button>
        )}
      </div>
    </Row>
  )
}

/**
 * What IT and Finance are tracking about you.
 *
 * Both lists already existed; only the teams working them could see them, so
 * IT recorded that you still had a laptop and you had no way to find out.
 *
 * Read-only on purpose. Whether a laptop is back is IT's call and what the
 * settlement says is Finance's — this answers "what is being tracked about
 * me", it is not a second place to change it.
 */
function Tracked({
  assets,
  settlement,
}: {
  assets: CaseAsset[]
  settlement: CaseSettlementItem[]
}) {
  if (assets.length === 0 && settlement.length === 0) return null

  const back = assets.filter((a) => a.status !== 'pending')
  const confirmed = settlement.filter((s) => s.status === 'confirmed' && s.amount != null)
  const net = confirmed.reduce(
    (sum, s) => sum + (s.kind === 'earning' ? Number(s.amount) : -Number(s.amount)),
    0,
  )

  return (
    <div className="grid gap-6 md:grid-cols-2">
      {assets.length > 0 && (
        <Panel title={`Company items · ${back.length} of ${assets.length} returned`}>
          {assets.map((a) => {
            const done = a.status === 'returned' || a.status === 'not_issued'
            return (
              <Row key={a.id} tone={done ? 'moss' : a.status === 'lost' ? 'rust' : 'amber'}>
                <div className="min-w-0 flex-1">
                  <p className={cn('text-ink', a.status === 'returned' && 'text-muted line-through')}>
                    {a.name}
                  </p>
                  <p className="mt-0.5 text-[13px] text-muted">
                    {a.identifier ?? a.category}
                  </p>
                </div>
                <span className={cn('shrink-0 self-center text-[13px]', TEXT_TONE[done ? 'moss' : 'amber'])}>
                  {a.status === 'returned'
                    ? `returned ${shortDate(a.returned_at)}`
                    : a.status === 'not_issued'
                      ? 'never issued'
                      : a.status === 'lost'
                        ? 'not returned'
                        : 'still with you'}
                </span>
              </Row>
            )
          })}
          <p className="px-4 py-2 text-[13px] text-muted">
            IT marks each item received. Hand them in before your last day.
          </p>
        </Panel>
      )}

      {settlement.length > 0 && (
        <Panel title={`Your settlement · ${confirmed.length} of ${settlement.length} confirmed`}>
          {confirmed.length === 0 ? (
            <p className="px-4 py-4 text-[13px] text-muted">
              Finance has not worked through your figures yet. It is released
              once IT, Finance and Admin clearances are all complete.
            </p>
          ) : (
            <>
              {confirmed.map((s) => (
                <Row key={s.id} tone="moss">
                  <div className="min-w-0 flex-1">
                    <p className="text-ink">{s.label}</p>
                    <p className="mt-0.5 text-[13px] text-muted">
                      {s.kind === 'earning' ? 'Earning' : 'Deduction'}
                    </p>
                  </div>
                  <span className="shrink-0 self-center text-[13px] tabular-nums text-ink-soft">
                    {s.kind === 'deduction' && '−'}
                    {Number(s.amount).toLocaleString(undefined, { minimumFractionDigits: 2 })}
                  </span>
                </Row>
              ))}
              <div className="flex items-baseline justify-between px-4 py-2 text-[13px]">
                <span className="text-ink-soft">
                  Confirmed so far
                  {confirmed.length < settlement.length && ' — more lines still to come'}
                </span>
                <span className={cn('tabular-nums', TEXT_TONE.moss)}>
                  {net.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                </span>
              </div>
            </>
          )}
        </Panel>
      )}
    </div>
  )
}

/**
 * Shown once every task on the case is closed. The download is generated
 * server-side from the case record, so it always matches what the database
 * says rather than what this screen happened to render.
 */
function ExitComplete({ caseId }: { caseId: string }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function download() {
    setBusy(true)
    setError(null)
    try {
      await api.downloadExitCertificate(caseId)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not download the confirmation.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="border border-moss/40 bg-moss-soft px-5 py-4">
      <h2 className="font-serif text-[22px] leading-tight text-ink">
        Your exit process is complete
      </h2>
      <p className="mt-1.5 max-w-[68ch] text-ink-soft">
        Every task is closed, and all required documents have been submitted and
        approved. Thank you for your contributions — we wish you all the best in
        what comes next.
      </p>
      <div className="mt-3 flex items-center gap-3">
        <Button size="sm" onClick={download} disabled={busy}>
          <Download className="size-3.5" />
          {busy ? 'Preparing…' : 'Download confirmation'}
        </Button>
        {error && <span className="text-[13px] text-rust">{error}</span>}
      </div>
    </section>
  )
}

function byDueDate(a: CaseTask, b: CaseTask): number {
  if (!a.due_date) return 1
  if (!b.due_date) return -1
  return a.due_date.localeCompare(b.due_date)
}
