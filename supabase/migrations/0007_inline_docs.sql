-- ============================================================================
-- Migration 0007 — Inline (in-platform) document editing
--
-- Extends the documents table so employees can fill in forms inside the
-- platform instead of uploading a file. The manager then reads the content
-- inline and approves or rejects it — no file download needed.
--
-- Affected doc types that use inline forms:
--   NDA_ACKNOWLEDGEMENT  — employee fills 4 acknowledgement checkboxes
--   KT_DOCUMENT          — pulled from kt_records, not a separate form
-- ============================================================================

-- Add in-platform content support to documents
alter table documents
  add column if not exists is_inline   boolean  not null default false,
  add column if not exists content     jsonb    null;

-- Index so manager inbox can filter for inline docs waiting review
create index if not exists documents_inline_pending_idx
  on documents (case_id, is_inline, status)
  where is_inline = true and status = 'pending';

comment on column documents.is_inline is
  'true = content was filled in the platform; storage_path is empty. false = file was uploaded.';

comment on column documents.content is
  'For inline docs: structured form data. Shape depends on doc_type_code.
   NDA_ACKNOWLEDGEMENT: {acknowledgements: bool[], full_name: str, submitted_at: str}';
