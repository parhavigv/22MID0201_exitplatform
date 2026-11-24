-- ============================================================================
-- Migration 0008 — Automated document verification
--
-- When an employee uploads a file, the platform asks the model whether it is
-- actually the kind of document that was requested. Someone attaching their
-- asset return form where a resignation letter was asked for should find out
-- immediately, not a week later when their manager opens it.
--
-- The verdict is advisory and never blocks the upload (CLAUDE.md rule 2 — the
-- model drafts, a human decides). It is stored so the reviewing manager sees
-- the same warning the employee saw.
--
-- Shape of `verification`:
--   {
--     "belongs":       bool,      -- does it match the requested type
--     "detected_type": str,       -- what it looks like instead
--     "reason":        str,       -- one sentence, shown to both parties
--     "confidence":    "high" | "medium" | "low",
--     "checked_at":    timestamptz,
--     "model":         str
--   }
--
-- Null means not checked — the file could not be read, the model was
-- unavailable, or the row predates this migration. Null is never presented as
-- a pass; the UI says "not checked" so nobody mistakes silence for approval.
-- ============================================================================

alter table documents
  add column if not exists verification jsonb null;

comment on column documents.verification is
  'Advisory model verdict on whether the file matches its doc_type_code.
   Null = not checked (unreadable file, model unavailable, or pre-0008 row).
   Never blocks upload; the reviewing human decides.';

-- The manager inbox wants "show me what was flagged" without scanning every
-- document on every case.
create index if not exists documents_flagged_idx
  on documents (case_id)
  where verification is not null and (verification ->> 'belongs') = 'false';
