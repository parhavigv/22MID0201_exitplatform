import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CheckSquare, Square, AlertCircle } from 'lucide-react'
import { useSession } from '@/auth/AuthProvider'
import { Button } from '@/components/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/format'

const ITEMS = [
  'I have returned all confidential information — physical or digital — in my possession, or have deleted it.',
  'I understand my post-employment confidentiality obligations and they remain in effect after my last working day.',
  'I have not taken, and will not take, any confidential information to my next employer or any other third party.',
  'I have disclosed to the company any potential conflicts of interest between my next employer and the company.',
]

interface NDAFormProps {
  caseId: string
  employeeId: string
  onSubmitted: () => void
}

export function NDAForm({ caseId, employeeId, onSubmitted }: NDAFormProps) {
  const { employee } = useSession()
  const qc = useQueryClient()
  const [checked, setChecked] = useState<boolean[]>(ITEMS.map(() => false))
  const [nameInput, setNameInput] = useState('')
  const [error, setError] = useState<string | null>(null)

  const submit = useMutation({
    mutationFn: () =>
      api.submitInlineDocument(caseId, 'NDA_ACKNOWLEDGEMENT', {
        acknowledgements: checked,
        full_name: nameInput.trim(),
        submitted_at: new Date().toISOString(),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['my-exit', employeeId] })
      onSubmitted()
    },
    onError: () => setError('Could not save. Please try again.'),
  })

  const allChecked = checked.every(Boolean)
  const nameMatches =
    nameInput.trim().toLowerCase() === employee.full_name.toLowerCase()

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    if (!allChecked) {
      setError('Tick all four statements before submitting.')
      return
    }
    if (!nameMatches) {
      setError(`Type your full name exactly as it appears on record: "${employee.full_name}"`)
      return
    }
    submit.mutate()
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div className="space-y-3">
        {ITEMS.map((text, i) => (
          <label
            key={i}
            className={cn(
              'flex cursor-pointer items-start gap-3 border p-3 transition-colors',
              checked[i] ? 'border-moss/50 bg-moss-soft' : 'border-line bg-surface',
            )}
          >
            <span className="mt-0.5 shrink-0">
              {checked[i] ? (
                <CheckSquare className="size-4 text-moss" />
              ) : (
                <Square className="size-4 text-muted" />
              )}
            </span>
            <input
              type="checkbox"
              className="sr-only"
              checked={checked[i]}
              onChange={(e) => {
                const next = [...checked]
                next[i] = e.target.checked
                setChecked(next)
              }}
            />
            <span className="text-[13px] leading-relaxed text-ink">{text}</span>
          </label>
        ))}
      </div>

      <div className="space-y-1.5">
        <label className="block text-[13px] font-medium text-ink-soft">
          Type your full name to confirm
        </label>
        <input
          value={nameInput}
          onChange={(e) => setNameInput(e.target.value)}
          placeholder={employee.full_name}
          className="w-full border border-line bg-paper px-3 py-2 text-ink placeholder:text-muted"
          autoComplete="off"
        />
        <p className="text-[12px] text-muted">
          Must match exactly: <strong>{employee.full_name}</strong>
        </p>
      </div>

      {error && (
        <div className="flex items-start gap-2 border border-rust/30 bg-rust-soft p-3">
          <AlertCircle className="mt-0.5 size-4 shrink-0 text-rust" />
          <p className="text-[13px] text-ink-soft">{error}</p>
        </div>
      )}

      <div className="flex justify-end">
        <Button
          type="submit"
          variant="primary"
          disabled={submit.isPending}
        >
          {submit.isPending ? 'Submitting…' : 'Submit for manager review'}
        </Button>
      </div>
    </form>
  )
}
