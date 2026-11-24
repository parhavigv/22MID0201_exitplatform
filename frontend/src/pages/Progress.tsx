import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { ChevronDown, ChevronRight, RefreshCw } from 'lucide-react'
import { Empty, Loading, PageHeader } from '@/components/ui'
import { api } from '@/lib/api'
import { cn, relativeTime, shortDate, TEXT_TONE, type Tone } from '@/lib/format'
import type { CaseProgress } from '@/lib/types'

/**
 * How far along every exit is, and where each one is stuck.
 *
 * A single completion percentage hides what HR actually needs to act on, so
 * each row expands into a per-stage breakdown, and blocked work is counted
 * separately from not-yet-started — they need different interventions.
 */
function SweepSummary() {
  const { data } = useQuery({
    queryKey: ['sweep-summary'],
    queryFn: () => api.getSweepSummary(),
    refetchInterval: 5 * 60 * 1000,
  })

  const lastRun = data?.last_run
  const pending = data?.pending_actions ?? 0

  return (
    <div className="mb-5 flex items-center gap-4 border border-line bg-surface px-4 py-3">
      <RefreshCw className="size-4 shrink-0 text-muted" />
      <div className="min-w-0 flex-1">
        <p className="text-[13px] text-ink-soft">
          {lastRun
            ? <>Last sweep {relativeTime(lastRun.finished_at)} — {lastRun.status === 'failed' ? <span className="text-rust">failed</span> : 'completed'}</>
            : 'No sweep has run yet. Sweeps run nightly at 02:00 and check all active cases for SLA breaches and compliance gaps.'}
        </p>
      </div>
      {pending > 0 && (
        <Link to="/approvals" className="shrink-0 text-[13px] text-indigo hover:underline">
          {pending} pending {pending === 1 ? 'action' : 'actions'}
        </Link>
      )}
    </div>
  )
}

export function Progress() {
  const { data, isLoading } = useQuery({
    queryKey: ['progress'],
    queryFn: () => api.getProgress(),
  })

  const [expanded, setExpanded] = useState<string | null>(null)

  if (isLoading) return <Loading />

  const rows = data ?? []

  if (rows.length === 0) {
    return (
      <div>
        <PageHeader title="Progress" />
        <SweepSummary />
        <Empty
          title="No exits are in progress."
          hint="Every active case appears here with how much of it is done."
        />
      </div>
    )
  }

  const needingAttention = rows.filter(
    (r) => r.tasks_overdue > 0 || r.tasks_blocked > 0 || r.documents_pending > 0,
  ).length

  return (
    <div>
      <PageHeader
        title="Progress"
        lede={
          needingAttention > 0
            ? `${rows.length} active ${rows.length === 1 ? 'exit' : 'exits'}. ${needingAttention} ${needingAttention === 1 ? 'needs' : 'need'} attention.`
            : `${rows.length} active ${rows.length === 1 ? 'exit' : 'exits'}, all on track.`
        }
      />

      <SweepSummary />

      <div className="space-y-2">
        {rows.map((row) => (
          <ProgressCard
            key={row.case_id}
            row={row}
            open={expanded === row.case_id}
            onToggle={() =>
              setExpanded(expanded === row.case_id ? null : row.case_id)
            }
          />
        ))}
      </div>
    </div>
  )
}

function ProgressCard({
  row,
  open,
  onToggle,
}: {
  row: CaseProgress
  open: boolean
  onToggle: () => void
}) {
  const tone: Tone =
    row.tasks_overdue > 0 ? 'rust' : row.days_remaining <= 14 ? 'amber' : 'moss'

  return (
    <article className="border border-line bg-surface">
      <button
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-sunken"
      >
        {open ? (
          <ChevronDown className="mt-1 size-4 shrink-0 text-muted" />
        ) : (
          <ChevronRight className="mt-1 size-4 shrink-0 text-muted" />
        )}

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <span className="text-ink">{row.employee.full_name}</span>
            <span className="text-[13px] text-muted">
              {row.employee.designation} · {row.employee.department}
            </span>
          </div>

          <Meter percent={row.percent_complete} tone={tone} />

          <p className="mt-1.5 text-[13px] text-muted">
            <span className="tnum text-ink-soft">
              {row.tasks_done}/{row.tasks_total}
            </span>{' '}
            done
            {row.tasks_overdue > 0 && (
              <>
                {' · '}
                <span className={TEXT_TONE.rust}>{row.tasks_overdue} overdue</span>
              </>
            )}
            {row.tasks_blocked > 0 && (
              <>
                {' · '}
                <span className={TEXT_TONE.rust}>{row.tasks_blocked} blocked</span>
              </>
            )}
            {row.documents_pending > 0 && (
              <>
                {' · '}
                <span className={TEXT_TONE.amber}>
                  {row.documents_pending} document
                  {row.documents_pending === 1 ? '' : 's'} to review
                </span>
              </>
            )}
            {' · last day '}
            {shortDate(row.last_working_day)}
          </p>
        </div>

        <div className="shrink-0 text-right">
          <p className={cn('tnum text-lg leading-none', TEXT_TONE[tone])}>
            {row.percent_complete}%
          </p>
          <p className="mt-1 text-[12px] text-muted">
            {row.days_remaining > 0 ? `${row.days_remaining} days` : 'Ended'}
          </p>
        </div>
      </button>

      {open && (
        <div className="border-t border-line">
          {row.stages.map((stage) => {
            const complete = stage.done === stage.total
            return (
              <div
                key={stage.code}
                className={cn(
                  'flex items-center gap-3 border-b border-line px-4 py-2 last:border-b-0',
                  stage.is_current && 'bg-indigo-soft',
                )}
              >
                <span className="min-w-0 flex-1 truncate text-[13px] text-ink-soft">
                  {stage.name}
                  {stage.is_current && (
                    <span className="ml-2 text-indigo">Current</span>
                  )}
                </span>

                {stage.overdue > 0 && (
                  <span className={cn('shrink-0 text-[13px]', TEXT_TONE.rust)}>
                    {stage.overdue} overdue
                  </span>
                )}

                <span
                  className={cn(
                    'tnum w-14 shrink-0 text-right text-[13px]',
                    complete ? TEXT_TONE.moss : 'text-muted',
                  )}
                >
                  {stage.done}/{stage.total}
                </span>
              </div>
            )
          })}

          <div className="flex items-center justify-between gap-3 px-4 py-2.5">
            <span className="text-[13px] text-muted">
              Reporting to {row.manager_name ?? 'nobody on record'}
            </span>
            <Link
              to={`/cases/${row.case_id}`}
              className="text-[13px] text-indigo hover:underline"
            >
              Open case
            </Link>
          </div>
        </div>
      )}
    </article>
  )
}

/** A thin measure rather than a rounded progress bar — same language as StageTrack. */
function Meter({ percent, tone }: { percent: number; tone: Tone }) {
  const fill = { neutral: 'bg-muted', moss: 'bg-moss', amber: 'bg-amber', rust: 'bg-rust' }[
    tone
  ]
  return (
    <div
      className="mt-2 h-1 w-full bg-sunken"
      role="progressbar"
      aria-valuenow={percent}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div className={cn('h-full', fill)} style={{ width: `${percent}%` }} />
    </div>
  )
}
