import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { supabase } from '@/lib/supabase'
import { USE_MOCKS } from '@/lib/api'

/**
 * Keep every open dashboard in step with the database.
 *
 * Before this, a change only reached the screen that caused it. A manager
 * approving a document saw their own queue update, but the employee sitting on
 * their dashboard saw a stale "waiting for review" until they happened to
 * reload — and IT had no idea a clearance had been signed off.
 *
 * Supabase Realtime already pushed new notifications to the bell. This applies
 * the same idea to the tables the dashboards are actually built on, and turns
 * each change into a cache invalidation rather than a hand-rolled state update:
 * TanStack Query refetches whatever is currently mounted and nothing else, so
 * one subscription keeps the employee, manager, HR, IT and Finance views
 * honest without any of them knowing about the others.
 *
 * Mounted once in `AppShell`, so it covers every signed-in screen.
 *
 * Note this listens per table, not per row. A change to someone else's case
 * still triggers a refetch here — wasteful in a large tenant, irrelevant at
 * pilot size, and RLS means the refetch returns only rows this user may see.
 * If that ever matters, narrow it with a `filter` the way the bell does.
 */

/** Which cached queries go stale when a given table changes. */
const AFFECTED_BY: Record<string, string[][]> = {
  // `clearance-queue` backs the IT and Finance screens. It was missing from
  // every entry below, so those two dashboards were the only ones that never
  // updated on their own — an employee could hand back a laptop and IT would
  // sit looking at a stale list until they reloaded.
  documents: [
    ['my-exit'],
    ['case-detail'],
    ['inbox'],
    ['cases'],
    ['progress'],
    ['clearance-queue'],
    ['compliance-actions'],
  ],
  case_tasks: [
    ['my-exit'],
    ['case-detail'],
    ['inbox'],
    ['cases'],
    ['progress'],
    ['clearance-queue'],
  ],
  exit_cases: [
    ['my-exit'],
    ['case-detail'],
    ['inbox'],
    ['cases'],
    ['progress'],
    ['clearance-queue'],
  ],
  approvals: [
    ['case-detail'],
    ['inbox'],
    ['recent-approvals'],
    ['progress'],
    ['clearance-queue'],
  ],
  kt_records: [['kt'], ['case-detail'], ['my-exit']],
  kt_items: [['kt'], ['case-detail']],
  agent_actions: [['agent-actions'], ['approvals'], ['compliance-actions']],
  // IT marking a laptop returned, or Finance confirming a settlement line,
  // has to reach the employee too — those lists are now on their own screen.
  case_assets: [['clearance-queue'], ['my-exit'], ['case-detail']],
  case_access: [['clearance-queue'], ['case-detail']],
  case_settlement: [['clearance-queue'], ['my-exit'], ['case-detail']],
}

export function useLiveSync(): void {
  const qc = useQueryClient()

  useEffect(() => {
    if (USE_MOCKS) return

    const channel = supabase.channel('live-sync')

    for (const [table, keys] of Object.entries(AFFECTED_BY)) {
      channel.on(
        'postgres_changes',
        { event: '*', schema: 'public', table },
        () => {
          // Partial match: ['my-exit'] invalidates ['my-exit', <employeeId>].
          for (const key of keys) {
            qc.invalidateQueries({ queryKey: key })
          }
        },
      )
    }

    channel.subscribe()
    return () => {
      supabase.removeChannel(channel)
    }
  }, [qc])
}
