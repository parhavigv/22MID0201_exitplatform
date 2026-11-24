-- Phase 3, increment 2: multi-agent supervisor additions.
--
-- One additive column on agent_runs — no new table, no new RLS policy needed.
-- The existing agent_runs_select policy already covers it. Chosen over a
-- dedicated agent_steps table because nothing in this increment needs to query
-- steps across runs by worker name; revisit if that need arises.

alter table agent_runs
  add column if not exists worker_history jsonb not null default '[]'::jsonb;

comment on column agent_runs.worker_history is
  'Ordered list of worker runs in this agent turn — {worker, status, tokens}. '
  'Written by graph.py finalize node. Promoted to a dedicated table if cross-run '
  'queries by worker name become necessary.';

-- summary column on agent_actions for the approval-queue UI
-- (already in 0001_init.sql; adding here if missing for completeness)
alter table agent_actions
  add column if not exists approved_payload jsonb,
  add column if not exists decision_note text,
  add column if not exists executed_at timestamptz,
  add column if not exists failure_reason text;
