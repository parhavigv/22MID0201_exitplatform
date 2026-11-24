import { NavLink, Outlet } from 'react-router-dom'
import {
  BarChart2,
  Bot,
  CalendarClock,
  CheckCircle,
  ClipboardList,
  FileText,
  Gauge,
  Inbox,
  LayoutList,
  LogOut,
  MessageSquare,
  Scale,
  ShieldCheck,
  Users,
  Wallet,
  Workflow,
} from 'lucide-react'
import { useAuth } from '@/auth/AuthProvider'
import { AgentChat } from '@/components/AgentChat'
import { NotificationBell } from '@/components/NotificationBell'
import { cn } from '@/lib/format'
import { useLiveSync } from '@/lib/useLiveSync'
import type { AppRole } from '@/lib/types'

interface NavItem {
  to: string
  label: string
  icon: typeof Inbox
}

const NAV: Record<AppRole, NavItem[]> = {
  // "Assistant activity" is for the people reviewing AI output that affects
  // someone else — HR, the manager, IT, Finance. An employee has one or two
  // runs about their own tasks and nothing to audit, so for them the page is
  // an empty screen in the way of finishing their exit. The route still works
  // if they are sent a link; it just is not in their sidebar.
  employee: [
    { to: '/my-exit', label: 'My exit', icon: CalendarClock },
    { to: '/my-tasks', label: 'Tasks', icon: ClipboardList },
    { to: '/my-documents', label: 'Documents', icon: FileText },
    { to: '/my-kt', label: 'Knowledge transfer', icon: LayoutList },
    { to: '/my-interview', label: 'Exit interview', icon: MessageSquare },
  ],
  manager: [
    { to: '/needs-you', label: 'Needs you', icon: Inbox },
    { to: '/team', label: 'Team exits', icon: Users },
    { to: '/approvals', label: 'AI approvals', icon: CheckCircle },
    { to: '/agent-trace', label: 'Assistant activity', icon: Workflow },
  ],
  // IT and Finance have one screen each: the queue of people they must clear.
  // They own a stage, not a person, so none of the case-management views apply.
  it: [
    { to: '/clearance', label: 'IT clearance', icon: ShieldCheck },
    { to: '/agent-trace', label: 'Assistant activity', icon: Workflow },
  ],
  finance: [
    { to: '/clearance', label: 'Settlements', icon: Wallet },
    { to: '/agent-trace', label: 'Assistant activity', icon: Workflow },
  ],
  hr: [
    { to: '/needs-you', label: 'Needs you', icon: Inbox },
    { to: '/progress', label: 'Progress', icon: Gauge },
    { to: '/cases', label: 'All cases', icon: Users },
    { to: '/sla', label: 'Overdue', icon: Scale },
    { to: '/approvals', label: 'AI approvals', icon: Bot },
    { to: '/agent-trace', label: 'Assistant activity', icon: Workflow },
    { to: '/analytics', label: 'Analytics', icon: BarChart2 },
    { to: '/policies', label: 'Policy docs', icon: FileText },
  ],
}

export function AppShell() {
  const { session, signOut } = useAuth()

  // One subscription for the whole app: a change anyone makes refreshes the
  // screens that depend on it, on every open dashboard. Must run before the
  // early return below, or it would be conditional.
  useLiveSync()

  if (!session) return null

  const items = NAV[session.role]

  return (
    <div className="min-h-dvh bg-paper">
      <div className="mx-auto flex max-w-[1400px] flex-col md:flex-row">
        <Sidebar items={items} />

        <main className="min-w-0 flex-1 px-5 py-6 md:px-8 md:py-10">
          <Outlet />
        </main>
      </div>

      {/* Exit Copilot chat — floating, available on every page */}
      <AgentChat />

      {/* Sign out: fixed to bottom-left, not in nav, not in the flex layout. */}
      <button
        onClick={signOut}
        className="fixed left-4 bottom-4 inline-flex items-center gap-1.5 border border-line bg-surface px-2.5 py-1.5 text-[12px] text-muted hover:text-ink"
        style={{ marginBottom: 'env(safe-area-inset-bottom, 0px)' }}
      >
        <LogOut className="size-3.5" />
        Sign out
      </button>
    </div>
  )
}

function Sidebar({ items }: { items: NavItem[] }) {
  const { session } = useAuth()
  if (!session) return null

  return (
    <nav className="shrink-0 border-b border-line bg-surface md:min-h-dvh md:w-56 md:border-r md:border-b-0">
      <div className="border-b border-line px-4 py-4 md:py-5">
        <div className="flex items-start justify-between gap-2">
          <p className="font-serif text-[17px] leading-none text-ink">Exit Process</p>
          <NotificationBell />
        </div>
        <p className="mt-2 truncate text-[13px] text-ink-soft">{session.employee.full_name}</p>
        <p className="truncate text-[12px] text-muted">
          {session.employee.designation}
        </p>
      </div>

      <ul className="flex gap-1 overflow-x-auto p-2 md:block md:space-y-0.5 md:overflow-visible">
        {items.map(({ to, label, icon: Icon }) => (
          <li key={to} className="shrink-0">
            <NavLink
              to={to}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-2.5 rounded-sm px-2.5 py-2 text-[13px] whitespace-nowrap transition-colors',
                  isActive
                    ? 'bg-indigo-soft font-medium text-indigo'
                    : 'text-ink-soft hover:bg-sunken hover:text-ink',
                )
              }
            >
              <Icon className="size-4 shrink-0" strokeWidth={1.75} />
              {label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  )
}
