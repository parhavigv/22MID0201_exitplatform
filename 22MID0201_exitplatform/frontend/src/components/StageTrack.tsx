import { cn, shortDate } from '@/lib/format'
import type { CaseTask, ExitCase, ExitStage } from '@/lib/types'

/**
 * The notice period rendered as a measure, not a stat card.
 *
 * Offboarding is a countdown against a fixed last working day, so the primary
 * object on the page is the span itself: resignation on the left, last day on
 * the right, the ten stages plotted as markers, and today's position marked on
 * the line. Filled marker = cleared, ringed = in progress, hollow = ahead.
 */
export function StageTrack({
  exitCase,
  stages,
  tasks,
  compact = false,
}: {
  exitCase: ExitCase
  stages: ExitStage[]
  tasks: CaseTask[]
  compact?: boolean
}) {
  const start = Date.parse(exitCase.resignation_date)
  const end = Date.parse(exitCase.last_working_day)
  const span = Math.max(end - start, 1)
  const todayPct = clamp(((Date.now() - start) / span) * 100)

  const currentIndex = stages.findIndex((s) => s.code === exitCase.current_stage)

  return (
    <div className={cn('w-full', compact ? 'py-2' : 'py-1')}>
      {/* The line itself */}
      <div className="relative mx-1 h-6">
        <div className="absolute top-1/2 right-0 left-0 h-px -translate-y-1/2 bg-line-strong" />
        {/* Elapsed portion */}
        <div
          className="absolute top-1/2 left-0 h-px -translate-y-1/2 bg-indigo"
          style={{ width: `${todayPct}%` }}
        />

        {/* Today */}
        <div
          className="absolute top-0 bottom-0 w-px bg-rust"
          style={{ left: `${todayPct}%` }}
          aria-hidden
        />

        {stages.map((stage, i) => {
          const pct = (i / (stages.length - 1)) * 100
          const state =
            i < currentIndex ? 'done' : i === currentIndex ? 'current' : 'ahead'
          const stageTasks = tasks.filter((t) => t.stage_code === stage.code)
          const breached = stageTasks.some((t) => t.sla_breached)

          return (
            <div
              key={stage.code}
              className="group absolute top-1/2 -translate-x-1/2 -translate-y-1/2"
              style={{ left: `${pct}%` }}
            >
              <span
                className={cn(
                  'block rounded-full border-2 transition-colors',
                  state === 'current' ? 'size-3.5' : 'size-2.5',
                  state === 'done' && !breached && 'border-moss bg-moss',
                  state === 'done' && breached && 'border-rust bg-rust',
                  state === 'current' && 'border-indigo bg-paper',
                  state === 'ahead' && 'border-line-strong bg-paper',
                )}
              />
              {/* Name on hover/focus — keeps the line clean at ten stages. */}
              <span
                role="tooltip"
                className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-2 hidden -translate-x-1/2 border border-line bg-surface px-2 py-1 text-[12px] whitespace-nowrap text-ink shadow-sm group-hover:block"
              >
                {stage.name}
              </span>
            </div>
          )
        })}
      </div>

      {/* Endpoints and current stage.
          Labelled in full rather than "Resigned" / "Last day". The middle item
          is a stage name, not a date, and with terse labels either side it read
          as though all three were dates. */}
      <div className="mt-1 flex items-baseline justify-between gap-3 text-[12px] text-muted">
        <span>
          Resignation submitted{' '}
          <time dateTime={exitCase.resignation_date} className="text-ink-soft">
            {shortDate(exitCase.resignation_date)}
          </time>
        </span>
        {!compact && (
          <span className="shrink-0 text-ink-soft">
            Now: {stages[currentIndex]?.name ?? 'Not started'}
          </span>
        )}
        <span>
          Last working day{' '}
          <time dateTime={exitCase.last_working_day} className="text-ink-soft">
            {shortDate(exitCase.last_working_day)}
          </time>
        </span>
      </div>
    </div>
  )
}

function clamp(n: number): number {
  return Math.min(100, Math.max(0, n))
}
