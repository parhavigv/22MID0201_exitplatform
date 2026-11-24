import { useState, type FormEvent } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useSession } from '@/auth/AuthProvider'
import { Button, PageHeader } from '@/components/ui'
import { api } from '@/lib/api'
import { longDate } from '@/lib/format'

const DEFAULT_NOTICE = 60

/**
 * Opening an exit. Shown to an employee with no case in progress.
 *
 * The last working day is derived from the notice period rather than picked
 * freely — that is the rule in almost every policy, and a free date field
 * invites a number that HR then has to correct. It stays editable for the
 * cases where notice is waived or extended.
 */
export function SubmitResignation() {
  const { employee } = useSession()
  const qc = useQueryClient()

  const today = new Date().toISOString().slice(0, 10)
  const [resignationDate, setResignationDate] = useState(today)
  const [noticeDays, setNoticeDays] = useState(DEFAULT_NOTICE)
  const [lastDay, setLastDay] = useState(() => addDays(today, DEFAULT_NOTICE))
  const [lastDayEdited, setLastDayEdited] = useState(false)
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)

  function syncLastDay(from: string, days: number) {
    if (!lastDayEdited) setLastDay(addDays(from, days))
  }

  const open = useMutation({
    mutationFn: () =>
      api.openCase({
        resignation_date: resignationDate,
        last_working_day: lastDay,
        notice_period_days: noticeDays,
        reason: reason.trim() || undefined,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['my-exit', employee.id] }),
    onError: (err) =>
      setError(err instanceof Error ? err.message : 'Could not submit.'),
  })

  function submit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    if (lastDay < resignationDate) {
      setError('Your last working day cannot be before your resignation date.')
      return
    }
    setConfirming(true)
  }

  return (
    <div className="max-w-xl">
      <PageHeader
        title="Submit your resignation"
        lede="This starts your exit process and creates your checklist. Your manager and HR are notified."
      />

      <form onSubmit={submit} className="border border-line bg-surface p-5">
        <label className="block">
          <span className="text-[13px] text-ink-soft">Resignation date</span>
          <input
            type="date"
            required
            value={resignationDate}
            onChange={(e) => {
              setResignationDate(e.target.value)
              syncLastDay(e.target.value, noticeDays)
            }}
            className={inputClass}
          />
        </label>

        <label className="mt-4 block">
          <span className="text-[13px] text-ink-soft">Notice period (days)</span>
          <input
            type="number"
            min={0}
            max={365}
            required
            value={noticeDays}
            onChange={(e) => {
              const days = Number(e.target.value)
              setNoticeDays(days)
              syncLastDay(resignationDate, days)
            }}
            className={inputClass}
          />
          <span className="mt-1 block text-[13px] text-muted">
            Check your contract. HR will confirm this.
          </span>
        </label>

        <label className="mt-4 block">
          <span className="text-[13px] text-ink-soft">Last working day</span>
          <input
            type="date"
            required
            value={lastDay}
            onChange={(e) => {
              setLastDay(e.target.value)
              setLastDayEdited(true)
            }}
            className={inputClass}
          />
          <span className="mt-1 block text-[13px] text-muted">
            {lastDayEdited
              ? 'Set manually. Clear it to follow the notice period again.'
              : 'Calculated from your notice period. Edit if it has been waived or extended.'}
          </span>
        </label>

        <label className="mt-4 block">
          <span className="text-[13px] text-ink-soft">
            Reason <span className="text-muted">(optional)</span>
          </span>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={3}
            className="mt-1 w-full resize-y border border-line bg-paper px-3 py-2 text-[13px] text-ink focus:border-indigo focus:outline-none"
          />
          <span className="mt-1 block text-[13px] text-muted">
            Your manager and HR can see this. The exit interview later asks in more
            depth.
          </span>
        </label>

        {error && (
          <p role="alert" className="mt-4 border-l-2 border-rust bg-rust-soft px-3 py-2 text-[13px]">
            {error}
          </p>
        )}

        <Button type="submit" variant="primary" className="mt-5 w-full">
          Continue
        </Button>
      </form>

      {confirming && (
        <ConfirmDialog
          lastDay={lastDay}
          busy={open.isPending}
          onCancel={() => setConfirming(false)}
          onConfirm={() => open.mutate()}
        />
      )}
    </div>
  )
}

/**
 * A resignation is not an ordinary form submit. It notifies the manager and HR
 * and cannot be withdrawn in the app, so it gets an explicit confirmation that
 * says both of those things.
 */
function ConfirmDialog({
  lastDay,
  busy,
  onCancel,
  onConfirm,
}: {
  lastDay: string
  busy: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-ink/30 p-4"
      onClick={onCancel}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Confirm your resignation"
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md border border-line bg-surface"
      >
        <div className="px-5 py-4">
          <h2 className="font-serif text-[20px] text-ink">
            Submit your resignation?
          </h2>
          <p className="mt-2 text-ink-soft">
            Your last working day will be {longDate(lastDay)}.
          </p>
          <p className="mt-2 text-[13px] text-muted">
            Your manager and HR are notified immediately, and your exit checklist
            is created. You cannot withdraw this here — speak to HR if you change
            your mind.
          </p>
        </div>
        <div className="flex justify-end gap-2 border-t border-line px-5 py-3">
          <Button size="sm" variant="ghost" onClick={onCancel} disabled={busy}>
            Go back
          </Button>
          <Button size="sm" variant="primary" onClick={onConfirm} disabled={busy}>
            {busy ? 'Submitting…' : 'Submit resignation'}
          </Button>
        </div>
      </div>
    </div>
  )
}

const inputClass =
  'mt-1 w-full border border-line bg-paper px-3 py-2 text-ink focus:border-indigo focus:outline-none'

function addDays(from: string, days: number): string {
  const d = new Date(from)
  d.setDate(d.getDate() + days)
  return d.toISOString().slice(0, 10)
}
