import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useSession } from '@/auth/AuthProvider'
import { Empty, Loading, PageHeader, Row } from '@/components/ui'
import { api } from '@/lib/api'
import { cn, shortDate, TEXT_TONE, type Tone } from '@/lib/format'
import type { CaseSummary } from '@/lib/types'

/**
 * Shared by the manager's team view and HR's all-cases view. Scope is enforced
 * server-side by RLS; the prop only shapes the request.
 */
export function CaseList({
  scope,
  title,
  lede,
  onlyOverdue = false,
}: {
  scope: 'team' | 'all'
  title: string
  lede: string
  onlyOverdue?: boolean
}) {
  const { employee } = useSession()

  const { data, isLoading } = useQuery({
    queryKey: ['cases', scope, employee.id],
    queryFn: () => api.listCases(scope, employee.id),
  })

  // Completed exits stay in the list. Hiding them made someone who finished
  // disappear from every management view at once — no record that they had
  // exited at all. They sort to the bottom and read as done rather than
  // needing attention. The overdue board is the exception: a finished case by
  // definition has nothing outstanding.
  const cases = (data ?? [])
    .filter((c) => (onlyOverdue ? c.overdue_tasks > 0 : true))
    .sort((a, b) => {
      const aDone = a.case.status === 'completed' ? 1 : 0
      const bDone = b.case.status === 'completed' ? 1 : 0
      return aDone - bDone || a.days_remaining - b.days_remaining
    })

  return (
    <div>
      <PageHeader title={title} lede={lede} />

      {isLoading ? (
        <Loading />
      ) : cases.length === 0 ? (
        <Empty
          title={onlyOverdue ? 'Nothing is overdue.' : 'No exits in progress.'}
          hint={
            onlyOverdue
              ? 'Cases appear here the moment a task passes its SLA.'
              : 'A case appears here as soon as someone submits a resignation.'
          }
        />
      ) : (
        <div className="border border-line bg-surface">
          <div className="hidden items-center gap-3 border-b border-line px-4 py-2 text-[12px] text-muted md:flex">
            <span className="flex-1">Employee</span>
            <span className="w-40">Stage</span>
            <span className="w-24 text-right">Open</span>
            <span className="w-28 text-right">Last day</span>
            <span className="w-24 text-right">Remaining</span>
          </div>

          {cases.map((summary) => (
            <CaseRow key={summary.case.id} summary={summary} />
          ))}
        </div>
      )}
    </div>
  )
}

function RiskBadge({ score }: { score: number | null }) {
  if (score === null) return null
  const label = score >= 0.7 ? 'High risk' : score >= 0.4 ? 'Medium' : 'Low'
  const cls =
    score >= 0.7
      ? 'bg-rust/10 text-rust border-rust/30'
      : score >= 0.4
        ? 'bg-amber/10 text-amber border-amber/30'
        : 'bg-moss/10 text-moss border-moss/30'
  return (
    <span className={cn('shrink-0 border px-1.5 py-0.5 text-[11px] font-medium', cls)}>
      {label}
    </span>
  )
}

function CaseRow({ summary }: { summary: CaseSummary }) {
  const { case: c, employee, open_tasks, overdue_tasks, days_remaining } = summary

  const done = c.status === 'completed'

  // The rail encodes urgency: finished, then overdue work, then a tight
  // deadline, then normal.
  const tone: Tone = done
    ? 'moss'
    : overdue_tasks > 0
      ? 'rust'
      : days_remaining <= 14
        ? 'amber'
        : 'neutral'

  return (
    <Row tone={tone} className="hover:bg-sunken">
      <Link
        to={`/cases/${c.id}`}
        className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-3 gap-y-1 md:flex-nowrap"
      >
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2 truncate text-ink">
            {employee.full_name}
            <RiskBadge score={c.risk_score} />
          </span>
          <span className="block truncate text-[13px] text-muted">
            {employee.designation} · {employee.department}
          </span>
        </span>

        <span className="w-40 shrink-0 text-[13px] text-ink-soft">
          {done ? 'Exited' : stageName(c.current_stage)}
        </span>

        <span className="w-24 shrink-0 text-right text-[13px]">
          {done ? (
            <span className={TEXT_TONE.moss}>All cleared</span>
          ) : overdue_tasks > 0 ? (
            <span className={TEXT_TONE.rust}>{overdue_tasks} overdue</span>
          ) : (
            <span className="text-muted">{open_tasks} open</span>
          )}
        </span>

        <time className="w-28 shrink-0 text-right text-[13px] text-ink-soft">
          {shortDate(c.last_working_day)}
        </time>

        <span
          className={cn(
            'tnum w-24 shrink-0 text-right text-[13px]',
            done ? TEXT_TONE.moss : days_remaining <= 14 ? TEXT_TONE.amber : 'text-muted',
          )}
        >
          {done ? 'Completed' : days_remaining > 0 ? `${days_remaining} days` : 'Ended'}
        </span>
      </Link>
    </Row>
  )
}

function stageName(code: string): string {
  return code
    .toLowerCase()
    .split('_')
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(' ')
}
