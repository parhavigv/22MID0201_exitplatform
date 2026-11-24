import { useMutation, useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'

/**
 * Who inherits this person's work.
 *
 * The manager's call, not the leaver's — enforced server-side too. Choosing a
 * successor is what makes the KT gaps meaningful: "not documented" only matters
 * once someone has to pick it up.
 */
export function SuccessorPicker({
  caseId,
  subjectId,
  department,
  successorId,
  onChange,
}: {
  caseId: string
  subjectId: string
  department: string
  successorId: string | null
  onChange: () => void
}) {
  const { data: employees } = useQuery({
    queryKey: ['employees'],
    queryFn: () => api.listEmployees(),
  })

  const nominate = useMutation({
    mutationFn: (id: string) => api.patchKtRecord(caseId, { successor_id: id }),
    onSuccess: onChange,
  })

  const candidates = (employees ?? [])
    .filter((e) => e.id !== subjectId && e.is_active)
    // Same department first — the likely successor is nearly always a colleague.
    .sort((a, b) => {
      const aSame = a.department === department ? 0 : 1
      const bSame = b.department === department ? 0 : 1
      return aSame - bSame || a.full_name.localeCompare(b.full_name)
    })

  return (
    <div className="flex flex-wrap items-center gap-2 px-4 py-3">
      <label className="text-[13px] text-ink-soft" htmlFor="successor">
        Work transfers to
      </label>
      <select
        id="successor"
        value={successorId ?? ''}
        disabled={nominate.isPending}
        onChange={(e) => e.target.value && nominate.mutate(e.target.value)}
        className="min-w-52 border border-line bg-paper px-2.5 py-1.5 text-[13px] text-ink"
      >
        <option value="">Nobody nominated yet</option>
        {candidates.map((e) => (
          <option key={e.id} value={e.id}>
            {e.full_name} — {e.designation}
            {e.department !== department ? ` (${e.department})` : ''}
          </option>
        ))}
      </select>

      {nominate.isPending && <span className="text-[13px] text-muted">Saving…</span>}

      {!successorId && !nominate.isPending && (
        <span className="text-[13px] text-amber">
          Nominate someone before knowledge transfer can be signed off
        </span>
      )}
    </div>
  )
}
