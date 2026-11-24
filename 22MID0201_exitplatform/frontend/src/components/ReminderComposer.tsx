import { useEffect, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Button } from '@/components/ui'
import { api } from '@/lib/api'

/**
 * Compose a reminder for an overdue task.
 *
 * The message arrives pre-filled and specific — it names the task, how late it
 * is, and what it blocks — because a reminder saying "you have an overdue task"
 * gets ignored. The sender edits and sends; they never face a blank box.
 *
 * Phase 4's agent will draft into this same endpoint, so there is one send
 * path and one audit shape whether a human or the agent started it.
 */
export function ReminderComposer({
  taskId,
  onClose,
  onSent,
}: {
  taskId: string
  onClose: () => void
  onSent: () => void
}) {
  const { data: draft, isLoading } = useQuery({
    queryKey: ['reminder-draft', taskId],
    queryFn: () => api.getReminderDraft(taskId),
  })

  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (draft) {
      setSubject(draft.subject)
      setBody(draft.body)
    }
  }, [draft])

  const send = useMutation({
    mutationFn: () => api.sendReminder(taskId, subject, body),
    onSuccess: onSent,
    onError: (err) => setError(err instanceof Error ? err.message : 'Could not send.'),
  })

  // Escape closes, as in any dialog.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-ink/30 p-4"
      onClick={onClose}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Send a reminder"
        onClick={(e) => e.stopPropagation()}
        className="max-h-[90dvh] w-full max-w-xl overflow-y-auto border border-line bg-surface shadow-lg"
      >
        <header className="border-b border-line px-4 py-3">
          <h2 className="text-ink">Send a reminder</h2>
          <p className="mt-0.5 text-[13px] text-muted">
            {isLoading
              ? 'Preparing…'
              : draft
                ? `To ${draft.recipient.full_name} · ${draft.recipient.work_email}`
                : ''}
          </p>
        </header>

        {isLoading ? (
          <p className="px-4 py-10 text-center text-muted">Loading…</p>
        ) : (
          <div className="space-y-3 px-4 py-4">
            <label className="block">
              <span className="text-[13px] text-ink-soft">Subject</span>
              <input
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                className="mt-1 w-full border border-line bg-paper px-3 py-2 text-ink focus:border-indigo focus:outline-none"
              />
            </label>

            <label className="block">
              <span className="text-[13px] text-ink-soft">Message</span>
              <textarea
                value={body}
                onChange={(e) => setBody(e.target.value)}
                rows={12}
                className="mt-1 w-full resize-y border border-line bg-paper px-3 py-2 text-[13px] leading-relaxed text-ink focus:border-indigo focus:outline-none"
              />
            </label>

            {error && (
              <p role="alert" className="border-l-2 border-rust bg-rust-soft px-3 py-2 text-[13px]">
                {error}
              </p>
            )}

            <p className="text-[13px] text-muted">
              This appears in their notifications now. Email delivery arrives in a
              later phase.
            </p>
          </div>
        )}

        <footer className="flex justify-end gap-2 border-t border-line px-4 py-2.5">
          <Button size="sm" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            size="sm"
            variant="primary"
            disabled={send.isPending || !subject.trim() || !body.trim()}
            onClick={() => {
              setError(null)
              send.mutate()
            }}
          >
            {send.isPending ? 'Sending…' : 'Send reminder'}
          </Button>
        </footer>
      </div>
    </div>
  )
}
