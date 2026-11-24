import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Send } from 'lucide-react'
import { useSession } from '@/auth/AuthProvider'
import { Button, Empty, Loading, PageHeader, Row } from '@/components/ui'
import { api } from '@/lib/api'
import { cn, relativeTime, type Tone } from '@/lib/format'
import type { KtCoverageStatus, KtItem } from '@/lib/types'

const COVERAGE: { value: KtCoverageStatus; label: string }[] = [
  { value: 'not_started', label: 'Not started' },
  { value: 'in_progress', label: 'In progress' },
  { value: 'documented', label: 'Documented' },
]

const TONE_FOR: Record<KtCoverageStatus, Tone> = {
  not_started: 'neutral',
  in_progress: 'amber',
  documented: 'moss',
  verified: 'moss',
  gap: 'rust',
}

/**
 * The handover record. In Phase 6 the agent reads this and names what's
 * missing — which is only useful if the employee can express things loosely
 * here, so topics are free text rather than a fixed taxonomy.
 */
export function MyKt() {
  const { employee } = useSession()
  const qc = useQueryClient()

  const { data: exit } = useQuery({
    queryKey: ['my-exit', employee.id],
    queryFn: () => api.myExit(employee.id),
  })

  const caseId = exit?.case.id

  const { data: kt, isLoading } = useQuery({
    queryKey: ['kt', caseId],
    queryFn: () => api.getKt(caseId!),
    enabled: !!caseId,
  })

  const saveItem = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Partial<KtItem> }) =>
      api.saveKtItem(caseId!, id, patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['kt', caseId] }),
  })

  const addItem = useMutation({
    mutationFn: ({ topic, detail }: { topic: string; detail: string }) =>
      api.addKtItem(caseId!, topic, detail),
    // Clear the form only once the row is really saved. Clearing on submit
    // meant a failed request threw away what had just been typed, with nothing
    // on screen to say it had failed.
    onSuccess: () => {
      setTopic('')
      setDetail('')
      setJustAdded(true)
      qc.invalidateQueries({ queryKey: ['kt', caseId] })
    },
  })

  const submitKt = useMutation({
    mutationFn: () => {
      const topics = kt?.items.map((i) => ({
        topic: i.topic,
        detail: i.detail,
        status: i.coverage_status,
        gap_note: i.gap_note,
      })) ?? []
      return api.submitInlineDocument(caseId!, 'KT_DOCUMENT', {
        topics,
        submitted_at: new Date().toISOString(),
        items_count: topics.length,
        documented_count: topics.filter((t) => t.status === 'documented').length,
      })
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['my-exit', employee.id] }),
  })

  const { data: docs } = useQuery({
    queryKey: ['my-exit', employee.id],
    queryFn: () => api.myExit(employee.id),
  })
  const ktDocSubmitted = docs?.documents.some(
    (d) => d.doc_type_code === 'KT_DOCUMENT' && d.status !== 'rejected',
  )

  const [topic, setTopic] = useState('')
  const [detail, setDetail] = useState('')
  const [justAdded, setJustAdded] = useState(false)

  if (isLoading || !exit) return <Loading />

  if (!kt) {
    return (
      <div>
        <PageHeader title="Knowledge transfer" />
        <Empty
          title="Your manager hasn't opened knowledge transfer yet."
          hint="It starts once they've acknowledged your resignation and named a successor."
        />
      </div>
    )
  }

  const gaps = kt.items.filter((i) => i.coverage_status === 'gap')

  return (
    <div>
      <PageHeader
        title="Knowledge transfer"
        lede="What you own, and where it's written down. Your manager reviews this before IT clearance can start."
      />

      {gaps.length > 0 && (
        <div className="mb-5 border border-rust/40 bg-rust-soft px-4 py-3">
          <p className="text-ink">
            {gaps.length === 1 ? 'One topic has' : `${gaps.length} topics have`} an
            unresolved gap
          </p>
          <p className="mt-0.5 text-[13px] text-ink-soft">
            Your manager flagged these as not covered well enough to hand over.
          </p>
        </div>
      )}

      <div className="border border-line bg-surface">
        {kt.items.map((item) => (
          <Row key={item.id} tone={TONE_FOR[item.coverage_status]}>
            <div className="min-w-0 flex-1">
              <p className="text-ink">{item.topic}</p>
              {item.detail && (
                <p className="mt-0.5 max-w-[70ch] text-[13px] text-muted">{item.detail}</p>
              )}
              {item.gap_note && (
                <p className="mt-1.5 border-l-2 border-rust pl-2 text-[13px] text-ink-soft">
                  {item.gap_note}
                </p>
              )}
            </div>

            <div className="shrink-0 self-center">
              {item.coverage_status === 'verified' ? (
                <span className="text-[13px] text-moss">Verified by your manager</span>
              ) : (
                <select
                  value={item.coverage_status === 'gap' ? 'in_progress' : item.coverage_status}
                  onChange={(e) =>
                    saveItem.mutate({
                      id: item.id,
                      patch: { coverage_status: e.target.value as KtCoverageStatus },
                    })
                  }
                  className="border border-line bg-paper px-2 py-1 text-[13px] text-ink"
                  aria-label={`Status for ${item.topic}`}
                >
                  {COVERAGE.map((c) => (
                    <option key={c.value} value={c.value}>
                      {c.label}
                    </option>
                  ))}
                </select>
              )}
            </div>
          </Row>
        ))}

        {kt.items.length === 0 && (
          <Empty
            title="Nothing recorded yet."
            hint="Start with the systems and processes only you know how to run."
          />
        )}
      </div>

      <form
        className="mt-5 border border-line bg-surface p-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (!topic.trim() || addItem.isPending) return
          setJustAdded(false)
          addItem.mutate({ topic: topic.trim(), detail: detail.trim() })
        }}
      >
        <h2 className="text-[13px] font-semibold text-ink-soft">Add a topic</h2>
        <div className="mt-3 space-y-2">
          <input
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="What you own — a system, a process, a relationship"
            className={cn(
              'w-full border border-line bg-paper px-3 py-2 text-ink',
              'placeholder:text-muted',
            )}
            aria-label="Topic"
          />
          <textarea
            value={detail}
            onChange={(e) => setDetail(e.target.value)}
            rows={3}
            placeholder="Where the runbook lives, who else knows it, anything that would bite whoever takes over"
            className="w-full resize-y border border-line bg-paper px-3 py-2 text-[13px] text-ink placeholder:text-muted"
            aria-label="Detail"
          />
        </div>
        <div className="mt-3 flex items-center justify-end gap-3">
          {addItem.isError && (
            <span className="text-[13px] text-rust">
              {addItem.error instanceof Error
                ? addItem.error.message
                : 'Could not save that topic.'}{' '}
              Your text is still here — try again.
            </span>
          )}
          {justAdded && !addItem.isPending && !addItem.isError && (
            <span className="text-[13px] text-moss">Topic saved.</span>
          )}
          <Button type="submit" variant="primary" size="sm" disabled={addItem.isPending}>
            <Plus className="size-3.5" />
            {addItem.isPending ? 'Saving…' : 'Add topic'}
          </Button>
        </div>
      </form>

      {/* Submit the whole KT record for manager review */}
      <div className="mt-5 border border-line bg-surface p-4">
        {ktDocSubmitted ? (
          <div className="flex items-center gap-3">
            <div className="size-2 rounded-full bg-amber" />
            <div>
              <p className="text-[13px] font-medium text-ink">
                KT document submitted for manager review
              </p>
              {docs?.documents
                .filter((d) => d.doc_type_code === 'KT_DOCUMENT' && d.status !== 'rejected')
                .slice(0, 1)
                .map((d) => (
                  <p key={d.id} className="mt-0.5 text-[13px] text-muted">
                    {d.status === 'approved'
                      ? `Approved ${relativeTime(d.reviewed_at ?? d.created_at)}`
                      : `Submitted ${relativeTime(d.created_at)} · waiting for review`}
                  </p>
                ))}
            </div>
          </div>
        ) : (
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-[13px] font-semibold text-ink">
                Ready for manager review?
              </p>
              <p className="mt-0.5 text-[13px] text-muted">
                Mark all topics as documented, then submit. Your manager will verify
                each one and sign off before IT clearance starts.
              </p>
            </div>
            <Button
              variant="primary"
              size="sm"
              disabled={submitKt.isPending || kt.items.length === 0}
              onClick={() => submitKt.mutate()}
              className="shrink-0"
            >
              <Send className="size-3.5" />
              {submitKt.isPending ? 'Submitting…' : 'Submit for review'}
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
