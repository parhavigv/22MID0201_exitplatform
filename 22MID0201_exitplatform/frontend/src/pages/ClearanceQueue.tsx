import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Check } from 'lucide-react'
import { useSession } from '@/auth/AuthProvider'
import { Button, Count, Empty, Loading, PageHeader, Panel, Row } from '@/components/ui'
import { api } from '@/lib/api'
import { cn, dueLabel, OWNER_LABEL_3P, shortDate, TEXT_TONE } from '@/lib/format'
import type { Tone } from '@/lib/format'
import type {
  CaseAccess,
  CaseAsset,
  CaseSettlementItem,
  ClearancePerson,
  StageCode,
} from '@/lib/types'

/**
 * The IT and Finance work queue.
 *
 * One component for both. The two functions do the same shape of job — a list
 * of people leaving, the tasks this function owns on each, a sign-off when
 * they are done — so the difference is entirely which role is signed in, and
 * that is decided by the database, not here.
 *
 * Ordered by who leaves soonest, with anyone already past their last working
 * day and still not cleared pulled to the top. For IT that ordering is the
 * whole point: a live account belonging to someone who has left is the one
 * thing on this screen that is actually urgent.
 */
export function ClearanceQueue() {
  const { role, employee } = useSession()
  const qc = useQueryClient()
  const [query, setQuery] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['clearance-queue'],
    queryFn: () => api.clearanceQueue(),
  })

  const setTask = useMutation({
    mutationFn: ({ id, done }: { id: string; done: boolean }) =>
      api.setTaskStatus(id, done ? 'completed' : 'pending'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['clearance-queue'] }),
  })

  const refresh = () => qc.invalidateQueries({ queryKey: ['clearance-queue'] })

  const setAsset = useMutation({
    mutationFn: ({ id, status }: { id: string; status: CaseAsset['status'] }) =>
      api.updateAsset(id, { status }),
    onSuccess: refresh,
  })
  const setAccess = useMutation({
    mutationFn: ({ id, status }: { id: string; status: CaseAccess['status'] }) =>
      api.updateAccess(id, { status }),
    onSuccess: refresh,
  })
  const setSettlement = useMutation({
    mutationFn: ({
      id,
      status,
      amount,
    }: {
      id: string
      status: CaseSettlementItem['status']
      amount?: number
    }) => api.updateSettlement(id, { status, amount }),
    onSuccess: refresh,
  })

  // Closing the stage is the point of the screen: ticking the tasks records
  // the work, signing off is what releases the case to the next stage.
  const signOff = useMutation({
    mutationFn: ({ caseId, stageCode }: { caseId: string; stageCode: StageCode }) =>
      api.decideStage(caseId, stageCode, 'approved', employee.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['clearance-queue'] }),
  })

  if (isLoading) return <Loading />

  const all = data?.people ?? []
  const flagged = data?.flagged ?? 0
  const isIT = role === 'it'

  // Filter the list, not the counts. The header still reports the real state
  // of the queue while you are searching — otherwise typing a name would make
  // it look like the backlog had cleared.
  const needle = query.trim().toLowerCase()
  const people = needle
    ? all.filter((p) =>
        [
          p.employee.full_name,
          p.employee.emp_code,
          p.employee.department,
          p.employee.designation,
        ].some((v) => v?.toLowerCase().includes(needle)),
      )
    : all
  const outstanding = all.filter((p) => p.open_count > 0)

  return (
    <div>
      <PageHeader
        title={
          flagged > 0
            ? flagged === 1
              ? '1 person has left and is not cleared'
              : `${flagged} people have left and are not cleared`
            : outstanding.length > 0
              ? `${outstanding.length} ${outstanding.length === 1 ? 'person needs' : 'people need'} your clearance`
              : 'Everything is cleared'
        }
        lede={
          isIT
            ? 'Revoke access and collect hardware before the last working day. Anyone past it with access still live is listed first.'
            : 'Settle dues and release the final payment. Anyone past their last working day is listed first.'
        }
      />

      <div className="mb-8 flex flex-wrap gap-x-8 gap-y-3 border-y border-line py-3">
        <Count value={outstanding.length} label="still to clear" tone={outstanding.length ? 'amber' : 'moss'} />
        <Count value={flagged} label="past last day" tone={flagged ? 'rust' : 'moss'} />
        <Count value={all.length - outstanding.length} label="cleared" tone="moss" />
      </div>

      {all.length > 0 && (
        <div className="mb-6 flex items-baseline gap-3">
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Find a person — name, code, or department"
            aria-label="Search this queue"
            className="w-full max-w-sm border border-line bg-paper px-2.5 py-1.5 text-[13px] text-ink placeholder:text-muted focus:border-line-strong focus:outline-none"
          />
          {needle && (
            <span className="shrink-0 text-[13px] text-muted">
              {people.length} of {all.length}
            </span>
          )}
        </div>
      )}

      {all.length === 0 ? (
        <Empty
          title="Nothing is assigned to you."
          hint="People appear here as soon as an exit reaches a stage your team owns."
        />
      ) : people.length === 0 ? (
        <Empty
          title={`Nobody here matches "${query.trim()}".`}
          hint="Only people whose exit has reached a stage your team owns appear in this queue."
        />
      ) : (
        <div className="space-y-6">
          {people.map((person) => (
            <PersonCard
              key={person.case_id}
              person={person}
              onToggle={(id, done) => setTask.mutate({ id, done })}
              onAsset={(id, status) => setAsset.mutate({ id, status })}
              onAccess={(id, status) => setAccess.mutate({ id, status })}
              onSettlement={(id, status, amount) => setSettlement.mutate({ id, status, amount })}
              onSignOff={() =>
                data?.stage_code &&
                signOff.mutate({ caseId: person.case_id, stageCode: data.stage_code })
              }
              signOffError={
                signOff.isError && signOff.variables?.caseId === person.case_id
                  ? signOff.error instanceof Error
                    ? signOff.error.message
                    : 'Could not sign off.'
                  : null
              }
              busy={setTask.isPending || signOff.isPending}
            />
          ))}
        </div>
      )}
    </div>
  )
}

/** A labelled sub-list inside a person's card, with its own progress count. */
function ItemGroup({
  title,
  done,
  total,
  children,
}: {
  title: string
  done: number
  total: number
  children: React.ReactNode
}) {
  return (
    <>
      <div className="flex items-baseline justify-between border-t border-line bg-sunken px-4 py-1.5">
        <span className="text-[13px] font-medium text-ink-soft">{title}</span>
        <span
          className={cn('text-[13px] tabular-nums', done === total ? TEXT_TONE.moss : 'text-muted')}
        >
          {done}/{total}
        </span>
      </div>
      {children}
    </>
  )
}

/** The settlement breakdown, split the way the policy states it. */
function SettlementGroup({
  items,
  onConfirm,
  busy,
}: {
  items: CaseSettlementItem[]
  onConfirm: (id: string, status: CaseSettlementItem['status'], amount?: number) => void
  busy: boolean
}) {
  const settled = items.filter((i) => i.status !== 'pending').length
  const total = (kind: 'earning' | 'deduction') =>
    items
      .filter((i) => i.kind === kind && i.status === 'confirmed' && i.amount != null)
      .reduce((sum, i) => sum + Number(i.amount), 0)

  const net = total('earning') - total('deduction')
  const anyConfirmed = items.some((i) => i.status === 'confirmed' && i.amount != null)

  return (
    <ItemGroup title="Settlement" done={settled} total={items.length}>
      {/* The field saves on Enter or on leaving it, with no Save button — which
          is not guessable, so say it. */}
      <p className="border-b border-line px-4 py-1.5 text-[13px] text-muted">
        Lines that follow from salary, leave and service are already worked out
        — check the figure and the basis under it, and overwrite if payroll
        disagrees. For the rest, type an amount and press Enter, or use N/A.
      </p>
      {items.map((item) => (
        <Row key={item.id} tone={item.status === 'pending' ? 'amber' : 'moss'}>
          <div className="min-w-0 flex-1">
            <p className={cn('text-ink', item.status === 'not_applicable' && 'text-muted line-through')}>
              {item.label}
            </p>
            <p className="mt-0.5 text-[13px] text-muted">
              {item.kind === 'earning' ? 'Earning' : 'Deduction'}
              {item.amount == null && item.status === 'pending' && ' · amount not set'}
            </p>
            {/* How the figure was arrived at. Finance is signing off on money,
                so a number with no working behind it is not reviewable. */}
            {item.note && (
              <p className="mt-0.5 max-w-[70ch] text-[13px] text-ink-soft">{item.note}</p>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-2 self-center">
            <AmountField
              value={item.amount}
              disabled={busy}
              onCommit={(amount) => onConfirm(item.id, 'confirmed', amount)}
            />
            {item.status === 'pending' ? (
              <Button size="sm" variant="ghost" disabled={busy} onClick={() => onConfirm(item.id, 'not_applicable')}>
                N/A
              </Button>
            ) : (
              <Button size="sm" variant="ghost" disabled={busy} onClick={() => onConfirm(item.id, 'pending')}>
                Undo
              </Button>
            )}
          </div>
        </Row>
      ))}

      {anyConfirmed && (
        <div className="flex items-baseline justify-between px-4 py-2 text-[13px]">
          <span className="text-ink-soft">Net so far, from confirmed lines only</span>
          <span className={cn('tabular-nums', net >= 0 ? TEXT_TONE.moss : TEXT_TONE.rust)}>
            {net.toLocaleString(undefined, { minimumFractionDigits: 2 })}
          </span>
        </div>
      )}
    </ItemGroup>
  )
}

/** Type an amount, press Enter or blur to save. */
function AmountField({
  value,
  disabled,
  onCommit,
}: {
  value: number | null
  disabled: boolean
  onCommit: (amount: number) => void
}) {
  const [draft, setDraft] = useState(value == null ? '' : String(value))

  const commit = () => {
    const parsed = Number(draft)
    if (draft.trim() !== '' && Number.isFinite(parsed) && parsed !== value) onCommit(parsed)
  }

  return (
    <input
      inputMode="decimal"
      value={draft}
      disabled={disabled}
      placeholder="amount"
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
      className="w-28 border border-line bg-paper px-2 py-1 text-right text-[13px] tabular-nums text-ink placeholder:text-muted"
      aria-label="Amount"
    />
  )
}

function PersonCard({
  person,
  onToggle,
  onAsset,
  onAccess,
  onSettlement,
  onSignOff,
  signOffError,
  busy,
}: {
  person: ClearancePerson
  onToggle: (taskId: string, done: boolean) => void
  onAsset: (id: string, status: CaseAsset['status']) => void
  onAccess: (id: string, status: CaseAccess['status']) => void
  onSettlement: (id: string, status: CaseSettlementItem['status'], amount?: number) => void
  onSignOff: () => void
  signOffError: string | null
  busy: boolean
}) {
  const cleared = person.open_count === 0
  const blockers = person.blocked_by ?? []
  const canSignOff = cleared && blockers.length === 0

  const heading = person.at_risk
    ? `Left ${Math.abs(person.days_remaining)} days ago — not cleared`
    : person.days_remaining >= 0
      ? `Last day ${shortDate(person.last_working_day)} · ${person.days_remaining} days left`
      : `Left ${shortDate(person.last_working_day)}`

  return (
    <Panel
      title={
        <span className="flex flex-wrap items-baseline gap-x-2">
          <span>{person.employee.full_name}</span>
          <span className="text-[13px] font-normal text-muted">
            {person.employee.designation} · {person.employee.department} ·{' '}
            {person.employee.emp_code}
          </span>
        </span>
      }
      action={
        <span className="flex items-baseline gap-3">
          <span
            className={cn(
              'text-[13px]',
              person.at_risk ? TEXT_TONE.rust : cleared ? TEXT_TONE.moss : 'text-muted',
            )}
          >
            {cleared ? 'Cleared' : heading}
          </span>
          {/* The full case, including the Issue control for documents this
              role has to release. Without this, Finance could be assigned
              "Share settlement statement" with no way to reach the screen
              that issues it. */}
          <Link
            to={`/cases/${person.case_id}`}
            className="text-[13px] text-ink-soft underline decoration-line-strong underline-offset-2 hover:text-ink"
          >
            Open case
          </Link>
        </span>
      }
    >
      {/* The itemisation sits above the task list on purpose: "which laptop,
          which account" is the work, and the task is the summary of it. */}
      {person.access.length > 0 && (
        <ItemGroup
          title="Access"
          done={person.access.filter((a) => a.status !== 'active').length}
          total={person.access.length}
        >
          {person.access.map((a) => (
            <Row key={a.id} tone={a.status === 'active' ? (a.is_elevated ? 'rust' : 'amber') : 'moss'}>
              <div className="min-w-0 flex-1">
                <p className={cn('text-ink', a.status !== 'active' && 'text-muted line-through')}>
                  {a.system}
                  {a.is_elevated && a.status === 'active' && (
                    <span className={cn('ml-2 text-[13px]', TEXT_TONE.rust)}>elevated</span>
                  )}
                </p>
                <p className="mt-0.5 text-[13px] text-muted">
                  {a.category}
                  {a.revoked_at && ` · revoked ${shortDate(a.revoked_at)}`}
                </p>
              </div>
              <div className="shrink-0 self-center">
                <Button
                  size="sm"
                  variant={a.status === 'active' ? 'secondary' : 'ghost'}
                  disabled={busy}
                  onClick={() =>
                    onAccess(a.id, a.status === 'active' ? 'revoked' : 'active')
                  }
                >
                  {a.status === 'active' ? 'Revoke' : 'Undo'}
                </Button>
              </div>
            </Row>
          ))}
        </ItemGroup>
      )}

      {person.assets.length > 0 && (
        <ItemGroup
          title="Assets"
          done={person.assets.filter((a) => a.status !== 'pending').length}
          total={person.assets.length}
        >
          {person.assets.map((a) => (
            <Row key={a.id} tone={a.status === 'pending' ? 'amber' : a.status === 'lost' ? 'rust' : 'moss'}>
              <div className="min-w-0 flex-1">
                <p className={cn('text-ink', a.status === 'returned' && 'text-muted line-through')}>
                  {a.name}
                </p>
                <p className="mt-0.5 text-[13px] text-muted">
                  {a.category}
                  {a.identifier && ` · ${a.identifier}`}
                  {a.status === 'lost' && ' · not returned'}
                  {a.status === 'not_issued' && ' · never issued'}
                  {a.returned_at && ` · returned ${shortDate(a.returned_at)}`}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-2 self-center">
                {a.status === 'pending' ? (
                  <>
                    <Button size="sm" disabled={busy} onClick={() => onAsset(a.id, 'returned')}>
                      Returned
                    </Button>
                    <Button size="sm" variant="ghost" disabled={busy} onClick={() => onAsset(a.id, 'not_issued')}>
                      Not issued
                    </Button>
                  </>
                ) : (
                  <Button size="sm" variant="ghost" disabled={busy} onClick={() => onAsset(a.id, 'pending')}>
                    Undo
                  </Button>
                )}
              </div>
            </Row>
          ))}
        </ItemGroup>
      )}

      {person.settlement.length > 0 && (
        <SettlementGroup items={person.settlement} onConfirm={onSettlement} busy={busy} />
      )}

      {person.tasks.map((task) => {
        const done = task.status === 'completed' || task.status === 'waived'
        const tone: Tone = done ? 'moss' : task.sla_breached ? 'rust' : 'amber'

        return (
          <Row key={task.id} tone={tone}>
            <div className="min-w-0 flex-1">
              <p className={cn('text-ink', done && 'text-muted line-through')}>{task.title}</p>
              {task.description && (
                <p className="mt-0.5 max-w-[70ch] text-[13px] text-muted">{task.description}</p>
              )}
            </div>
            <div className="flex shrink-0 items-center gap-3 self-center">
              <time className={cn('text-[13px]', TEXT_TONE[tone])}>
                {dueLabel(task.due_date)}
              </time>
              <Button
                size="sm"
                variant={done ? 'ghost' : 'secondary'}
                disabled={busy}
                onClick={() => onToggle(task.id, !done)}
              >
                {done ? 'Reopen' : (<><Check className="size-3.5" />Mark done</>)}
              </Button>
            </div>
          </Row>
        )
      })}

      {/* Ticking tasks records the work; signing off is what advances the case
          to the next stage. Kept apart deliberately — closing a clearance is a
          decision, not a side effect of the last checkbox. */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-3">
        <div className="min-w-0 text-[13px] text-muted">
          {person.signed_off ? (
            <span className={TEXT_TONE.moss}>Clearance signed off.</span>
          ) : !cleared ? (
            `${person.open_count} of your ${person.tasks.length} ${
              person.tasks.length === 1 ? 'task' : 'tasks'
            } still open.`
          ) : blockers.length > 0 ? (
            <>
              <span>Your work is done. The stage still needs:</span>
              <ul className="mt-0.5">
                {blockers.map((b, i) => (
                  <li key={i}>
                    · {b.title} <span className="text-ink-soft">({OWNER_LABEL_3P[b.owner_role] ?? b.owner_role})</span>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            'All tasks in this stage are done — sign off to move this case on.'
          )}
          {signOffError && <p className={cn('mt-0.5', TEXT_TONE.rust)}>{signOffError}</p>}
        </div>

        {!person.signed_off && (
          <Button
            size="sm"
            variant="primary"
            disabled={!canSignOff || busy}
            onClick={onSignOff}
            title={
              !cleared
                ? 'Finish your own tasks first'
                : blockers.length > 0
                  ? 'Someone else still has work in this stage'
                  : undefined
            }
          >
            <Check className="size-3.5" />
            Mark clearance complete
          </Button>
        )}
      </div>
    </Panel>
  )
}
