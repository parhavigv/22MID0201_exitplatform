import type { ReactNode } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { HOME_FOR, useAuth } from './AuthProvider'
import type { AppRole } from '@/lib/types'

/**
 * Route guard. This is convenience, not security — RLS is the real boundary.
 * A user who forges their way to a route still sees nothing, because the API
 * returns nothing.
 *
 * Works as a layout route (renders an Outlet) or as a wrapper around a single
 * element, which is how the role-specific pages inside the shell use it.
 */
export function RequireRole({
  allow,
  children,
}: {
  allow: AppRole[]
  children?: ReactNode
}) {
  const { session, loading } = useAuth()
  const location = useLocation()

  if (loading) {
    return (
      <div className="grid min-h-dvh place-items-center bg-paper">
        <p className="text-muted">Loading…</p>
      </div>
    )
  }

  if (!session) {
    return <Navigate to="/sign-in" replace state={{ from: location.pathname }} />
  }

  if (!allow.includes(session.role)) {
    return <Navigate to={HOME_FOR[session.role]} replace />
  }

  return <>{children ?? <Outlet />}</>
}
