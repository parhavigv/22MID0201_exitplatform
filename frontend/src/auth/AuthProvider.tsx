import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { api, USE_MOCKS } from '@/lib/api'
import { supabase } from '@/lib/supabase'
import type { AppRole, Session } from '@/lib/types'

interface AuthState {
  session: Session | null
  loading: boolean
  signIn: (email: string, password: string) => Promise<void>
  signInAs: (employeeId: string) => Promise<void>
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false

    api
      .currentSession()
      .then((s) => {
        if (!cancelled) setSession(s)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    if (USE_MOCKS) {
      return () => {
        cancelled = true
      }
    }

    // Supabase refreshes tokens in the background and can sign the user out
    // from another tab. Without this listener the UI keeps showing a dashboard
    // whose requests have started failing.
    const { data: subscription } = supabase.auth.onAuthStateChange((event) => {
      if (event === 'SIGNED_OUT') {
        setSession(null)
      }
    })

    return () => {
      cancelled = true
      subscription.subscription.unsubscribe()
    }
  }, [])

  const signIn = useCallback(async (email: string, password: string) => {
    setSession(await api.signIn(email, password))
  }, [])

  const signInAs = useCallback(async (employeeId: string) => {
    setSession(await api.signInAs(employeeId))
  }, [])

  const signOut = useCallback(async () => {
    await api.signOut()
    setSession(null)
  }, [])

  const value = useMemo(
    () => ({ session, loading, signIn, signInAs, signOut }),
    [session, loading, signIn, signInAs, signOut],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}

/** The signed-in employee. Only call inside a RequireRole subtree. */
export function useSession(): Session {
  const { session } = useAuth()
  if (!session) throw new Error('useSession called outside an authenticated route')
  return session
}

/**
 * Where each role lands. Manager and HR go to their inbox rather than a list —
 * the first question either of them has is "what needs me?", not "show me
 * everything".
 */
export const HOME_FOR: Record<AppRole, string> = {
  employee: '/my-exit',
  manager: '/needs-you',
  hr: '/needs-you',
  it: '/clearance',
  finance: '/clearance',
}
