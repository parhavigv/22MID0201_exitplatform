import { useState, type FormEvent } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { HOME_FOR, useAuth } from '@/auth/AuthProvider'
import { Button } from '@/components/ui'
import { USE_MOCKS } from '@/lib/api'
import { mockDb } from '@/lib/mock'
import { cn } from '@/lib/format'

export function SignIn() {
  const { session, loading } = useAuth()

  if (loading) {
    return (
      <div className="grid min-h-dvh place-items-center bg-paper">
        <p className="text-muted">Loading…</p>
      </div>
    )
  }

  if (session) return <Navigate to={HOME_FOR[session.role]} replace />

  return (
    <div className="grid min-h-dvh place-items-center bg-paper px-5 py-12">
      <div className="w-full max-w-md">
        <h1 className="font-serif text-[30px] leading-tight text-ink">Exit Process</h1>
        <p className="mt-1.5 max-w-[48ch] text-ink-soft">
          Everything you need to finish before your last working day, in one place.
        </p>

        {USE_MOCKS ? <RolePicker /> : <PasswordForm />}
      </div>
    </div>
  )
}

function PasswordForm() {
  const { signIn } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await signIn(email.trim(), password)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not sign you in.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="mt-8 border border-line bg-surface p-5">
      <label className="block">
        <span className="text-[13px] text-ink-soft">Work email</span>
        <input
          type="email"
          required
          autoComplete="username"
          autoFocus
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className={inputClass}
        />
      </label>

      <label className="mt-4 block">
        <span className="text-[13px] text-ink-soft">Password</span>
        <input
          type="password"
          required
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className={inputClass}
        />
      </label>

      {error && (
        <p
          role="alert"
          className="mt-4 border-l-2 border-rust bg-rust-soft px-3 py-2 text-[13px] text-ink"
        >
          {error}
        </p>
      )}

      <Button
        type="submit"
        variant="primary"
        disabled={busy}
        className="mt-5 w-full"
      >
        {busy ? 'Signing in…' : 'Sign in'}
      </Button>

      <p className="mt-4 text-[13px] text-muted">
        Accounts are created by HR. If you can't sign in, contact your HR contact
        rather than registering.
      </p>
    </form>
  )
}

const inputClass = cn(
  'mt-1 w-full border border-line bg-paper px-3 py-2 text-ink',
  'focus:border-indigo focus:outline-none',
)

/** Mocks only. Lets all three dashboards be reviewed without a backend. */
function RolePicker() {
  const { signInAs } = useAuth()
  const [busy, setBusy] = useState<string | null>(null)

  const groups = [
    { heading: 'Leaving', role: 'employee' as const },
    { heading: 'Managing', role: 'manager' as const },
    { heading: 'HR', role: 'hr' as const },
  ]

  return (
    <>
      <div className="mt-8 border border-line bg-surface">
        <p className="border-b border-line px-4 py-2.5 text-[13px] font-semibold text-ink-soft">
          Choose who to sign in as
        </p>

        {groups.map((group) => (
          <div key={group.role} className="border-b border-line last:border-b-0">
            <p className="px-4 pt-3 pb-1 text-[12px] text-muted">{group.heading}</p>
            {mockDb.employees
              .filter((p) => p.app_role === group.role)
              .map((person) => (
                <button
                  key={person.id}
                  disabled={busy !== null}
                  onClick={async () => {
                    setBusy(person.id)
                    try {
                      await signInAs(person.id)
                    } finally {
                      setBusy(null)
                    }
                  }}
                  className="flex w-full items-baseline justify-between gap-3 px-4 py-2 text-left hover:bg-sunken disabled:opacity-50"
                >
                  <span className="text-ink">{person.full_name}</span>
                  <span className="text-[13px] text-muted">
                    {busy === person.id ? 'Signing in…' : person.designation}
                  </span>
                </button>
              ))}
          </div>
        ))}
      </div>

      <p className="mt-4 text-[13px] text-muted">
        Mock data. Set VITE_USE_MOCKS=false for real sign-in.
      </p>
    </>
  )
}

export function NotFound() {
  const { session } = useAuth()
  return (
    <div className="grid min-h-dvh place-items-center bg-paper px-5">
      <div className="text-center">
        <h1 className="font-serif text-[26px] text-ink">That page doesn't exist</h1>
        <p className="mt-1.5 text-ink-soft">The link may be out of date.</p>
        <div className="mt-5">
          <Link to={session ? HOME_FOR[session.role] : '/sign-in'}>
            <Button variant="primary">Go to your dashboard</Button>
          </Link>
        </div>
      </div>
    </div>
  )
}
