-- ---------------------------------------------------------------------------
-- Migration 0005: Policy RAG
-- Adds heading/tokens columns, HNSW vector index, and a similarity-search
-- SQL function callable via Supabase .rpc().  Idempotent — safe to re-run.
-- ---------------------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS vector;

-- 1. Extra columns on policy_chunks -----------------------------------------
ALTER TABLE policy_chunks ADD COLUMN IF NOT EXISTS heading       text;
ALTER TABLE policy_chunks ADD COLUMN IF NOT EXISTS tokens_approx int;

-- 2. HNSW cosine-similarity index -------------------------------------------
-- Used automatically when queries ORDER BY embedding <=> with vector_cosine_ops.
CREATE INDEX IF NOT EXISTS policy_chunks_embedding_idx
    ON policy_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- 3. RLS on policy_docs / policy_chunks -------------------------------------
ALTER TABLE policy_docs   ENABLE ROW LEVEL SECURITY;
ALTER TABLE policy_chunks ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='policy_docs' AND policyname='policy_docs_select') THEN
        CREATE POLICY policy_docs_select   ON policy_docs FOR SELECT USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='policy_docs' AND policyname='policy_docs_insert') THEN
        CREATE POLICY policy_docs_insert   ON policy_docs FOR INSERT WITH CHECK (
            (SELECT app_role FROM employees WHERE auth_user_id = auth.uid()) = 'hr'
        );
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='policy_docs' AND policyname='policy_docs_update') THEN
        CREATE POLICY policy_docs_update   ON policy_docs FOR UPDATE USING (
            (SELECT app_role FROM employees WHERE auth_user_id = auth.uid()) = 'hr'
        );
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='policy_chunks' AND policyname='policy_chunks_select') THEN
        CREATE POLICY policy_chunks_select ON policy_chunks FOR SELECT USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='policy_chunks' AND policyname='policy_chunks_insert') THEN
        -- Written by ingest script (service role) — allow any caller so the
        -- policy doesn't block the script running as service_db().
        CREATE POLICY policy_chunks_insert ON policy_chunks FOR INSERT WITH CHECK (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='policy_chunks' AND policyname='policy_chunks_delete') THEN
        CREATE POLICY policy_chunks_delete ON policy_chunks FOR DELETE USING (
            (SELECT app_role FROM employees WHERE auth_user_id = auth.uid()) = 'hr'
        );
    END IF;
END $$;

-- 4. Similarity-search RPC ---------------------------------------------------
-- Called via ctx.actor.db.rpc("search_policy_chunks", {...}).
-- SECURITY INVOKER (default) → runs under the caller's JWT → RLS applies.
CREATE OR REPLACE FUNCTION search_policy_chunks(
    query_embedding vector(1024),
    match_count      int DEFAULT 5,
    min_similarity   float DEFAULT 0.3
)
RETURNS TABLE (
    id             uuid,
    policy_doc_id  uuid,
    chunk_index    int,
    heading        text,
    content        text,
    similarity     float,
    title          text,
    version        text
)
LANGUAGE sql STABLE
AS $$
    SELECT
        pc.id,
        pc.policy_doc_id,
        pc.chunk_index,
        pc.heading,
        pc.content,
        (1 - (pc.embedding <=> query_embedding))::float AS similarity,
        pd.title,
        pd.version
    FROM  policy_chunks pc
    JOIN  policy_docs   pd ON pd.id = pc.policy_doc_id
    WHERE pc.embedding IS NOT NULL
      AND (1 - (pc.embedding <=> query_embedding)) >= min_similarity
    ORDER BY pc.embedding <=> query_embedding
    LIMIT match_count;
$$;
