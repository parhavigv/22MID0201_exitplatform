import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Button } from '@/components/ui'
import { api } from '@/lib/api'
import type { ExitStage, StageCode } from '@/lib/types'

/**
 * HR's escape hatch for a stuck case.
 *
 * Normal sign-off refuses while anything in the stage is open. Sometimes that
 * is the wrong answer: the leaver has already gone, or the person who owned a
 * clearance has themselves left. This skips the gate — so it is HR-only,
 * collapsed by default, demands a written reason, and is audited under its own
 * action rather than looking like an ordinary advance.
 */
export function StageOverride({
  caseId,
  stages,
  currentStage,
  onDone,
}: {
  caseId: string
  stages: ExitStage[]
  currentStage: StageCode
  onDone: () => void
}) {
  const [open, setOpen] = useState(false)
  const [target, setTarget] = useState<StageCode>(currentStage)
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)

  const override = useMutation({
    mutationFn: () => api.overrideStage(caseId, target, reason.trim()),
    onSuccess: () => {
      setOpen(false)
      setReason('')
      onDone()
    },
    onError: (err) =>
      setError(err instanceof Error ? err.message : 'Could not move the case.'),
  })

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="text-[13px] text-muted underline-offset-2 hover:text-ink hover:underline"
      >
        Move this case to another stage
      </button>
    )
  }

  const currentIndex = stages.findIndex((s) => s.code === currentStage)
  const targetIndex = stages.findIndex((s) => s.code === target)
  const goingBack = targetIndex < currentIndex

  return (
    <div className="border border-line-strong bg-sunken p-4">
      <p className="text-ink">Move this case to another stage</p>
      <p className="mt-0.5 max-w-[62ch] text-[13px] text-muted">
        This skips the usual checks, so outstanding tasks and unreviewed
        documents stay outstanding. Use it when a case is genuinely stuck.
      </p>

      <label className="mt-3 block">
        <span className="text-[13px] text-ink-soft">Move to</span>
        <select
          value={target}
          onChange={(e) => setTarget(e.target.value as StageCode)}
          className="mt-1 w-full border border-line bg-paper px-3 py-2 text-ink"
        >
          {stages.map((s) => (
            <option key={s.code} value={s.code} disabled={s.code === currentStage}>
              {s.name}
              {s.code === currentStage ? ' — current' : ''}
            </option>
          ))}
        </select>
      </label>

      {goingBack && (
        <p className="mt-2 text-[13px] text-amber">
          This moves the case backwards. Work already signed off stays signed off.
        </p>
      )}

      <label className="mt-3 block">
        <span className="text-[13px] text-ink-soft">Why</span>
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={2}
          placeholder="Recorded in the audit trail against your name."
          className="mt-1 w-full resize-y border border-line bg-paper px-3 py-2 text-[13px] text-ink placeholder:text-muted"
        />
      </label>

      {error && (
        <p role="alert" className="mt-3 border-l-2 border-rust bg-rust-soft px-3 py-2 text-[13px]">
          {error}
        </p>
      )}

      <div className="mt-3 flex justify-end gap-2">
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            setOpen(false)
            setError(null)
          }}
        >
          Cancel
        </Button>
        <Button
          size="sm"
          variant="primary"
          disabled={
            override.isPending || reason.trim().length < 3 || target === currentStage
          }
          onClick={() => {
            setError(null)
            override.mutate()
          }}
        >
          {override.isPending ? 'Moving…' : 'Move case'}
        </Button>
      </div>
    </div>
  )
}
