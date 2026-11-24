import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, Database, ShieldAlert } from 'lucide-react'
import { Empty, Loading, PageHeader } from '@/components/ui'
import { api } from '@/lib/api'
import { cn, relativeTime, TEXT_TONE } from '@/lib/format'

/**
 * What the assistant actually did, and what it read before it answered.
 *
 * This exists to answer one question a reader will always have: did it make
 * that up? Every figure the assistant states should trace to a tool call shown
 * here, with the value the database returned sitting directly underneath. A
 * claim with no call behind it is visible by its absence.
 *
 * Two things it deliberately does not claim. It shows the assistant read real
 * data — not that its judgement was right; a risk score is still an opinion.
 * And a draft is labelled as a draft, because the sensitive tools write a
 * pending row rather than changing anything (CLAUDE.md rule 2).
 *
 * Open to every role. `agent_runs_select` scopes the list: you see runs you
 * triggered, a manager sees their reports', HR sees all.
 */

interface ToolCall {
  worker: string
  tool: string
  input: Record<string, unknown>
  refused: boolean
  result: string
  drafted?: boolean
}

interface WorkerStep {
  worker: string
  status: string
  tokens: number
  tools?: ToolCall[]
}

interface AgentRun {
  id: string
  thread_id: string
  trigger: 'chat' | 'sweep'
  actor_role: string
  case_id: string | null
  status: string
  input_tokens: number | null
  output_tokens: number | null
  error: string | null
  started_at: string
  finished_at: string | null
  worker_history: WorkerStep[]
}

const WORKER_LABELS: Record<string, string> = {
  checklist_generator: 'Checklist',
  email_drafting: 'Email drafting',
  faq_chatbot: 'FAQ chatbot',
  interview_summarizer: 'Interview summary',
  sla_escalation: 'SLA escalation',
  kt_doc_reviewer: 'KT review',
  smart_routing: 'Smart routing',
  risk_assessment: 'Risk assessment',
  compliance_verification: 'Compliance',
  dashboard_insights: 'Insights',
  multi_system_clearance: 'Multi-system clearance',
  document_collection: 'Document collection',
  workflow_optimizer: 'Workflow optimizer',
  it_deprovisioning: 'IT deprovisioning',
  interview_trend_analyst: 'Trend analysis',
  rehire_assessment: 'Rehire assessment',
  policy_compliance_auditor: 'Policy audit',
  predictive_attrition: 'Attrition prediction',
  end_to_end_automation: 'End-to-end automation',
}

const label = (key: string) => WORKER_LABELS[key] ?? key

export function AgentTrace() {
  const { data, isLoading } = useQuery({
    queryKey: ['agent-runs'],
    queryFn: () => api.listAgentRuns(),
  })

  if (isLoading) return <Loading />
  const runs = (data ?? []) as AgentRun[]

  return (
    <div>
      <PageHeader
        title="What the assistant did"
        lede="Every answer it gave, and the database reads behind it. If a number in a reply has no tool call under it here, it was not grounded in your data."
      />

      {runs.length === 0 ? (
        <Empty
          title="The assistant hasn't run yet."
          hint="Ask Exit Copilot something on any page and the trace will appear here."
        />
      ) : (
        <div className="border border-line bg-surface">
          {runs.map((run) => (
            <RunRow key={run.id} run={run} />
          ))}
        </div>
      )}
    </div>
  )
}

function RunRow({ run }: { run: AgentRun }) {
  const [open, setOpen] = useState(false)

  const workers = run.worker_history ?? []
  const allTools = workers.flatMap((w) => w.tools ?? [])
  const reads = allTools.filter((t) => !t.drafted && !t.refused).length
  const drafts = allTools.filter((t) => t.drafted).length
  const refusals = allTools.filter((t) => t.refused).length
  const tokens = (run.input_tokens ?? 0) + (run.output_tokens ?? 0)

  return (
    <div className="border-b border-line last:border-0">
      <button
        className="flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-sunken"
        onClick={() => setOpen((v) => !v)}
      >
        {open ? (
          <ChevronDown className="mt-0.5 size-4 shrink-0 text-muted" />
        ) : (
          <ChevronRight className="mt-0.5 size-4 shrink-0 text-muted" />
        )}

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={cn(
                'rounded-sm px-1.5 py-0.5 text-[11px] font-medium uppercase tracking-wide',
                run.trigger === 'sweep' ? 'bg-indigo/10 text-indigo' : 'bg-amber/10 text-amber',
              )}
            >
              {run.trigger}
            </span>
            <span className="text-[13px] text-ink">
              {workers.map((w) => label(w.worker)).join(' → ') || 'no worker dispatched'}
            </span>
          </div>

          <p className="mt-0.5 text-[13px] text-muted">
            {relativeTime(run.started_at)} · {run.actor_role}
            {reads > 0 && <> · {reads} database {reads === 1 ? 'read' : 'reads'}</>}
            {drafts > 0 && <> · {drafts} drafted</>}
            {refusals > 0 && <> · {refusals} refused</>}
            {tokens > 0 && <> · {tokens.toLocaleString()} tokens</>}
          </p>
        </div>
      </button>

      {open && (
        <div className="border-t border-line bg-paper px-4 py-4 pl-11">
          {run.error && <p className="mb-3 text-[13px] text-rust">{run.error}</p>}

          {workers.length === 0 ? (
            <p className="text-[13px] text-muted">
              No worker ran — the supervisor answered directly without reading anything.
            </p>
          ) : (
            <ol className="space-y-4">
              <li>
                <p className="text-[13px] text-indigo">Supervisor</p>
                <p className="text-[13px] text-muted">
                  chose {workers.length === 1 ? 'one specialist' : `${workers.length} specialists`}
                </p>
              </li>

              {workers.map((w, i) => (
                <li key={i} className="border-l-2 border-line pl-3">
                  <p className="text-[13px] text-ink">{label(w.worker)}</p>

                  {(w.tools ?? []).length === 0 ? (
                    // Not a gap in the record — it is the record. This worker
                    // answered without reading anything, which is the one case
                    // where a reader should be sceptical of any figure in the
                    // reply, so say that rather than leaving a blank line.
                    <p className={cn('mt-1 text-[13px]', TEXT_TONE.amber)}>
                      Read nothing from the database — answered from the
                      conversation and its own knowledge. Treat any specific
                      figures in this reply with care.
                    </p>
                  ) : (
                    <ul className="mt-1.5 space-y-2">
                      {(w.tools ?? []).map((t, j) => (
                        <ToolCallRow key={j} call={t} />
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ol>
          )}

          <p className="mt-4 border-t border-line pt-3 text-[13px] text-muted">
            {drafts > 0 ? (
              <>
                {drafts} {drafts === 1 ? 'action was' : 'actions were'} drafted for a human to
                approve. Nothing was applied to the case by the assistant.
              </>
            ) : (
              <>Read-only. The assistant changed nothing.</>
            )}
          </p>
        </div>
      )}
    </div>
  )
}

function ToolCallRow({ call }: { call: ToolCall }) {
  const args = Object.entries(call.input ?? {})
    .map(([k, v]) => `${k}: ${String(v).slice(0, 40)}`)
    .join(', ')

  return (
    <li className="min-w-0">
      <p className="flex items-center gap-1.5 text-[13px]">
        {call.refused ? (
          <ShieldAlert className="size-3.5 shrink-0 text-rust" />
        ) : (
          <Database className="size-3.5 shrink-0 text-muted" />
        )}
        <code className={cn('font-mono', call.refused ? 'text-rust' : 'text-ink-soft')}>
          {call.tool}
          {args && <span className="text-muted">({args})</span>}
        </code>
        {call.drafted && (
          <span className="text-[12px] text-amber">drafted — not applied</span>
        )}
      </p>
      <p className="mt-0.5 break-words pl-5 text-[12px] text-muted">↳ {call.result}</p>
    </li>
  )
}
