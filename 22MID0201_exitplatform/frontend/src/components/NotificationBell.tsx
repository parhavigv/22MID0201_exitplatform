import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bell } from 'lucide-react'
import { cn, relativeTime } from '@/lib/format'
import { api } from '@/lib/api'
import { supabase } from '@/lib/supabase'
import { useSession } from '@/auth/AuthProvider'

const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === 'true'

export function NotificationBell() {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const { employee } = useSession()

  const { data } = useQuery({
    queryKey: ['notifications'],
    queryFn: () => api.listNotifications(),
    refetchInterval: USE_MOCKS ? 60_000 : false, // Realtime handles live updates when not mocked
  })

  const markRead = useMutation({
    mutationFn: (id: string) => api.markNotificationRead(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notifications'] }),
  })

  // Supabase Realtime — push new notifications without polling.
  // Only enabled when not in mock mode (Realtime needs a real Supabase project).
  useEffect(() => {
    if (USE_MOCKS) return

    const channel = supabase
      .channel(`notifications:${employee.id}`)
      .on(
        'postgres_changes',
        {
          event: 'INSERT',
          schema: 'public',
          table: 'notifications',
          filter: `recipient_id=eq.${employee.id}`,
        },
        () => {
          // A new notification arrived — refetch the list
          qc.invalidateQueries({ queryKey: ['notifications'] })
        },
      )
      .subscribe()

    return () => {
      supabase.removeChannel(channel)
    }
  }, [employee.id, qc])

  // Close dropdown on outside click or Escape
  useEffect(() => {
    if (!open) return
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onClick)
    window.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onClick)
      window.removeEventListener('keydown', onKey)
    }
  }, [open])

  const items = data ?? []
  const unread = items.filter((n) => !n.read_at).length

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        aria-label={unread > 0 ? `Notifications, ${unread} unread` : 'Notifications'}
        aria-expanded={open}
        className="relative flex size-8 items-center justify-center rounded-sm text-ink-soft hover:bg-sunken hover:text-ink"
      >
        <Bell className="size-4" strokeWidth={1.75} />
        {unread > 0 && (
          <span className="absolute top-1 right-1 size-1.5 rounded-full bg-rust" />
        )}
      </button>

      {open && (
        <div className="absolute right-0 z-40 mt-1 max-h-[70dvh] w-80 overflow-y-auto border border-line bg-surface shadow-lg">
          <p className="border-b border-line px-3 py-2 text-[13px] font-semibold text-ink-soft">
            Notifications
          </p>

          {items.length === 0 ? (
            <p className="px-3 py-8 text-center text-[13px] text-muted">
              Nothing yet. Reminders about your tasks arrive here.
            </p>
          ) : (
            items.map((n) => (
              <button
                key={n.id}
                onClick={() => !n.read_at && markRead.mutate(n.id)}
                className={cn(
                  'block w-full border-b border-line px-3 py-2.5 text-left last:border-b-0 hover:bg-sunken',
                  !n.read_at && 'bg-indigo-soft/40',
                )}
              >
                <p className="flex items-baseline gap-2 text-[13px] text-ink">
                  {!n.read_at && (
                    <span className="size-1.5 shrink-0 rounded-full bg-indigo" />
                  )}
                  <span className="min-w-0 flex-1">{n.title}</span>
                </p>
                <p className="mt-1 line-clamp-3 text-[12px] whitespace-pre-line text-muted">
                  {n.body}
                </p>
                <p className="mt-1 text-[12px] text-muted">
                  {relativeTime(n.created_at)}
                </p>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  )
}
