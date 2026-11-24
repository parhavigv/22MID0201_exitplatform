-- ============================================================================
-- Migration 0009 — Publish the tables dashboards are built on to Realtime
--
-- `components/NotificationBell.tsx` has subscribed to postgres_changes on
-- `notifications` since Phase 8, and `lib/useLiveSync.ts` now subscribes to the
-- workflow tables. Neither was ever receiving anything: the
-- `supabase_realtime` publication was empty, so Postgres emitted no change
-- events at all. The bell looked like it worked because the list refetches on
-- page load.
--
-- Adding a table here is what makes a change to it reach an open browser. The
-- client uses the event only as a signal to refetch through its normal
-- RLS-bound query, so the event carries no data a user could not already read.
--
-- Only tables a dashboard actually renders are published. `audit_log`,
-- `policy_chunks` and the checkpoint tables are deliberately absent: nothing
-- watches them, and publishing a high-churn table costs replication work for
-- no benefit.
-- ============================================================================

do $$
declare
  t text;
  live_tables constant text[] := array[
    'notifications',   -- the bell
    'documents',       -- upload, review, verification verdict
    'case_tasks',      -- mark done, and the document-driven status sync
    'exit_cases',      -- stage advances, case completion
    'approvals',       -- stage sign-off
    'kt_records',      -- successor nomination, overall KT status
    'kt_items',        -- topic added, coverage changed
    'agent_actions'    -- the AI approval queue
  ];
begin
  foreach t in array live_tables loop
    if not exists (
      select 1 from pg_publication_tables
      where pubname = 'supabase_realtime'
        and schemaname = 'public'
        and tablename = t
    ) then
      execute format('alter publication supabase_realtime add table public.%I', t);
      raise notice 'realtime: published %', t;
    end if;
  end loop;
end $$;
