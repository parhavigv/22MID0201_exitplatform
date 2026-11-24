import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Bot, CheckCircle, Clock } from 'lucide-react'
import { Button, Count, Empty, Loading, PageHeader, Panel } from '@/components/ui'
import { api } from '@/lib/api'

/**
 * What people say on their way out, read across every submitted interview.
 *
 * Run on demand rather than on page load. It is a model call over every
 * interview on record — several seconds and real tokens — and Analytics is a
 * page people open to glance at case counts. Making it a button means the cost
 * is paid by someone who wants the answer.
 *
 * The result is cached for the session, so switching pages and coming back
 * does not re-run it.
 */
function ExitTrends() {
  const [asked, setAsked] = useState(false)

  const { data, isFetching, error } = useQuery({
    queryKey: ['exit-trends'],
    queryFn: () =>
      api.askAgent(
        'What are the top reasons people are leaving, what did they like, ' +
          'and what changes are they asking for?',
      ),
    enabled: asked,
    staleTime: Infinity,
    retry: false,
  })

  return (
    <Panel
      title="Why people are leaving"
      action={
        <Button size="sm" disabled={isFetching} onClick={() => setAsked(true)}>
          {isFetching ? 'Reading interviews…' : data ? 'Run again' : 'Analyse interviews'}
        </Button>
      }
    >
      {!asked && !data ? (
        <p className="px-4 py-4 text-[13px] text-muted">
          Reads every submitted exit interview and reports the reasons people
          gave, what they valued, and what they asked to change — each with the
          number of people behind it. Nothing is attributed to an individual.
        </p>
      ) : isFetching ? (
        <p className="px-4 py-4 text-[13px] text-muted">
          Reading the interviews on record…
        </p>
      ) : error ? (
        <p className="px-4 py-4 text-[13px] text-rust">
          {error instanceof Error ? error.message : 'Could not run the analysis.'}
        </p>
      ) : (
        <div className="whitespace-pre-wrap px-4 py-4 text-[13px] leading-relaxed text-ink-soft">
          {data}
        </div>
      )}
    </Panel>
  )
}

export function Analytics() {
  const { data, isLoading } = useQuery({
    queryKey: ['analytics'],
    queryFn: () => api.getAnalytics(),
    refetchInterval: 5 * 60_000,
  })

  if (isLoading) return <Loading />
  if (!data) return <Empty title="Analytics unavailable." />

  const { cases, avg_duration_days, bottleneck_stage, by_department, agent } = data

  return (
    <div className="space-y-8">
      <PageHeader
        title="Analytics"
        lede="Aggregate view of all exit cases and AI agent activity."
      />

      {/* ── Headline numbers ─────────────────────────────────────────────── */}
      <div className="flex flex-wrap gap-x-8 gap-y-3 border-y border-line py-4">
        <Count value={cases.active} label="active cases" tone="amber" />
        <Count value={cases.completed} label="completed" tone="moss" />
        <Count value={cases.total} label="total cases" />
        <Count value={Math.round(avg_duration_days)} label="avg. notice period (days)" />
      </div>

      <ExitTrends />

      {/* ── AI agent activity ─────────────────────────────────────────────── */}
      <Panel title="AI agent activity">
        <div className="flex flex-wrap gap-x-8 gap-y-3 px-4 py-4">
          <StatTile icon={Bot} value={agent.total_runs} label="runs total" />
          <StatTile icon={CheckCircle} value={agent.actions_drafted} label="actions drafted" />
          <StatTile icon={CheckCircle} value={agent.actions_executed} label="actions executed" tone="moss" />
          <StatTile icon={Clock} value={agent.actions_pending} label="pending approval" tone="amber" />
        </div>
        {agent.total_runs === 0 && (
          <p className="px-4 pb-4 text-[13px] text-muted">
            No agent runs yet. Use the Exit Copilot chat or wait for a nightly sweep.
          </p>
        )}
      </Panel>

      {/* ── Bottleneck stage ─────────────────────────────────────────────── */}
      {bottleneck_stage && (
        <Panel title="Current bottleneck">
          <div className="px-4 py-4">
            <p className="text-ink">
              <span className="font-medium text-rust">{bottleneck_stage.stage_name}</span>
              {' '}— {bottleneck_stage.overdue_count} overdue task{bottleneck_stage.overdue_count === 1 ? '' : 's'} across all cases.
            </p>
            <p className="mt-1 text-[13px] text-muted">
              This is the stage where cases are stalling most. Review the Overdue page for details.
            </p>
          </div>
        </Panel>
      )}

      {/* ── Department breakdown ─────────────────────────────────────────── */}
      <Panel title="Cases by department">
        {by_department.length === 0 ? (
          <Empty title="No cases yet." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b border-line text-left text-muted">
                  <th className="px-4 py-2.5 font-medium">Department</th>
                  <th className="px-4 py-2.5 text-right font-medium">Active</th>
                  <th className="px-4 py-2.5 text-right font-medium">Completed</th>
                  <th className="px-4 py-2.5 text-right font-medium">Total</th>
                  <th className="px-4 py-2.5 font-medium">Progress</th>
                </tr>
              </thead>
              <tbody>
                {by_department.map((row) => {
                  const pct = row.total > 0 ? Math.round((row.completed / row.total) * 100) : 0
                  return (
                    <tr key={row.department} className="border-b border-line last:border-0">
                      <td className="px-4 py-2.5 text-ink">{row.department}</td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-amber">{row.active}</td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-moss">{row.completed}</td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-ink-soft">{row.total}</td>
                      <td className="px-4 py-2.5">
                        <div className="flex items-center gap-2">
                          <div className="h-1.5 w-24 overflow-hidden rounded-full bg-line">
                            <div
                              className="h-full bg-moss transition-all"
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                          <span className="tabular-nums text-muted">{pct}%</span>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  )
}

function StatTile({
  icon: Icon,
  value,
  label,
  tone,
}: {
  icon: typeof Bot
  value: number
  label: string
  tone?: 'moss' | 'amber' | 'rust'
}) {
  const colorClass =
    tone === 'moss' ? 'text-moss' : tone === 'amber' ? 'text-amber' : tone === 'rust' ? 'text-rust' : 'text-ink'

  return (
    <div className="flex items-center gap-3">
      <Icon className="size-4 shrink-0 text-muted" strokeWidth={1.5} />
      <div>
        <p className={`text-[22px] font-semibold tabular-nums leading-none ${colorClass}`}>{value}</p>
        <p className="mt-0.5 text-[12px] text-muted">{label}</p>
      </div>
    </div>
  )
}
