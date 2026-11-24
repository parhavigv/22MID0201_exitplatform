import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSession } from '@/auth/AuthProvider'
import { Button, Empty, Loading, PageHeader } from '@/components/ui'
import { api } from '@/lib/api'
import { INTERVIEW_QUESTIONS } from '@/lib/mock'
import { cn, longDate } from '@/lib/format'

const SCALE = [1, 2, 3, 4, 5]
const SCALE_ENDS = ['Poor', 'Excellent']

/**
 * Candid feedback, so the confidentiality promise has to be on the page and
 * has to be true: RLS hides `exit_interviews` from managers entirely. They see
 * only the derived summary, and only after HR releases it.
 */
export function ExitInterview() {
  const { employee } = useSession()
  const qc = useQueryClient()

  const { data: exit } = useQuery({
    queryKey: ['my-exit', employee.id],
    queryFn: () => api.myExit(employee.id),
  })
  const caseId = exit?.case.id

  const { data: interview, isLoading } = useQuery({
    queryKey: ['interview', caseId],
    queryFn: () => api.getInterview(caseId!),
    enabled: !!caseId,
  })

  const [answers, setAnswers] = useState<Record<string, string | number>>({})

  useEffect(() => {
    if (interview) setAnswers(interview.responses)
  }, [interview])

  const save = useMutation({
    mutationFn: (submit: boolean) => api.saveInterview(caseId!, answers, submit),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['interview', caseId] }),
  })

  if (isLoading || !exit) return <Loading />
  if (!interview) return <Empty title="No exit interview is open for you." />

  if (interview.submitted_at) {
    return (
      <div>
        <PageHeader title="Exit interview" />
        <div className="border border-line bg-surface px-4 py-8 text-center">
          <p className="text-ink">Submitted on {longDate(interview.submitted_at)}</p>
          <p className="mx-auto mt-1 max-w-[52ch] text-[13px] text-muted">
            Thank you. HR reads every response. Your manager sees only a summary,
            never what you wrote here.
          </p>
        </div>
      </div>
    )
  }

  const answered = INTERVIEW_QUESTIONS.filter((q) => {
    const v = answers[q.key]
    return v !== undefined && String(v).trim() !== ''
  }).length

  const complete = answered === INTERVIEW_QUESTIONS.length

  return (
    <div>
      <PageHeader
        title="Exit interview"
        lede="Your answers go to HR only. Your manager will never see what you write here — they receive a summary after you've left."
      />

      <div className="space-y-4">
        {INTERVIEW_QUESTIONS.map((q) => (
          <fieldset key={q.key} className="border border-line bg-surface px-4 py-3">
            <legend className="sr-only">{q.prompt}</legend>
            <p className="text-ink">{q.prompt}</p>
            {q.help && <p className="mt-0.5 text-[13px] text-muted">{q.help}</p>}

            {q.kind === 'scale' ? (
              <div className="mt-3 flex items-center gap-2">
                <span className="w-16 shrink-0 text-[13px] text-muted">{SCALE_ENDS[0]}</span>
                <div className="flex gap-1.5">
                  {SCALE.map((n) => {
                    const selected = answers[q.key] === n
                    return (
                      <button
                        key={n}
                        type="button"
                        aria-pressed={selected}
                        aria-label={`${q.prompt} — ${n} of 5`}
                        onClick={() => setAnswers((a) => ({ ...a, [q.key]: n }))}
                        className={cn(
                          'tnum size-9 border text-[13px] transition-colors',
                          selected
                            ? 'border-indigo bg-indigo text-white'
                            : 'border-line-strong bg-paper text-ink-soft hover:bg-sunken',
                        )}
                      >
                        {n}
                      </button>
                    )
                  })}
                </div>
                <span className="w-16 shrink-0 text-[13px] text-muted">{SCALE_ENDS[1]}</span>
              </div>
            ) : (
              <textarea
                value={String(answers[q.key] ?? '')}
                onChange={(e) => setAnswers((a) => ({ ...a, [q.key]: e.target.value }))}
                rows={4}
                className="mt-3 w-full resize-y border border-line bg-paper px-3 py-2 text-[13px] leading-relaxed text-ink"
                aria-label={q.prompt}
              />
            )}
          </fieldset>
        ))}
      </div>

      <div className="mt-5 flex flex-wrap items-center justify-end gap-3">
        <span className="mr-auto text-[13px] text-muted">
          {answered} of {INTERVIEW_QUESTIONS.length} answered
        </span>
        <Button onClick={() => save.mutate(false)} disabled={save.isPending}>
          Save draft
        </Button>
        <Button
          variant="primary"
          onClick={() => save.mutate(true)}
          disabled={save.isPending || !complete}
          title={complete ? undefined : 'Answer every question before submitting'}
        >
          {save.isPending ? 'Saving' : 'Submit'}
        </Button>
      </div>

      {!complete && (
        <p className="mt-2 text-right text-[13px] text-muted">
          You can save a draft and come back. Submitting is final.
        </p>
      )}
    </div>
  )
}
