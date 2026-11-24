-- Put the clearance detail tables on the wire.
--
-- 0009 added Realtime for the tables that existed then. The three clearance
-- tables arrived later in 0012 and nobody added them, so IT marking a laptop
-- returned, or Finance confirming a settlement line, pushed nothing: the
-- employee's "Company items" panel and the IT and Finance queues all sat stale
-- until someone reloaded the page.
--
-- Nothing here changes who can read what. Realtime respects RLS, so a
-- subscriber is still only delivered rows their policies already allow.

do $$
declare
  t text;
begin
  foreach t in array array['case_assets', 'case_access', 'case_settlement'] loop
    if not exists (
      select 1 from pg_publication_tables
      where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = t
    ) then
      execute format('alter publication supabase_realtime add table public.%I', t);
      raise notice 'added % to supabase_realtime', t;
    end if;
  end loop;
end $$;

-- Realtime sends the primary key on a delete and nothing else unless the
-- table replicates its full row. These are tracked inventories where the
-- interesting change is a status moving to 'returned' or 'confirmed', so the
-- old row is what tells a subscriber what actually changed.
alter table public.case_assets     replica identity full;
alter table public.case_access     replica identity full;
alter table public.case_settlement replica identity full;
