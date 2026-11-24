"""Phase 5 — RAG pipeline: chunking, embedding, and ingestion into Supabase.

Embedding model: text-embedding-3-small routed through the Portkey gateway
(same credentials as the LLM — PORTKEY_BASE_URL + PORTKEY_API_KEY in .env).
Model slug: EMBEDDING_MODEL in config (default @azure-openai-eus2/text-embedding-3-small).
Output dimensions: 1024 (specified via the `dimensions` parameter so it matches
the `vector(1024)` column — text-embedding-3-small supports Matryoshka truncation).

Chunking strategy:
- Heading-aware: each markdown heading starts a new chunk.
- Soft cap at ~800 tokens (≈ 3200 characters); splits at paragraph boundaries.
- 100-token (≈ 400-character) overlap between consecutive chunks from the same
  section, so a concept that straddles a boundary is retrievable from either side.

Ingestion is idempotent by (title, version): if a doc with the same title and
version is re-ingested, its old chunks are deleted and replaced with fresh ones.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings
from app.deps import service_db

logger = logging.getLogger("app.services.rag")

# Approximate character-to-token ratio for English prose.
# 1 token ≈ 4 chars (OpenAI rule of thumb) — used for soft-cap estimation only.
_CHARS_PER_TOKEN = 4
_CHUNK_SOFT_CAP = 800 * _CHARS_PER_TOKEN   # ~3 200 chars
_OVERLAP = 100 * _CHARS_PER_TOKEN          # ~400 chars


# ---------------------------------------------------------------------------
# Embedding client (OpenAI SDK → Portkey gateway)
# ---------------------------------------------------------------------------

def _embeddings_url() -> str:
    settings = get_settings()
    if not settings.portkey_base_url or not settings.portkey_api_key:
        raise RuntimeError(
            "PORTKEY_BASE_URL and PORTKEY_API_KEY must be set in backend/.env "
            "to use the embedding pipeline."
        )
    base = settings.portkey_base_url.rstrip("/").removesuffix("/v1")
    return f"{base}/v1/embeddings"


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of strings and return one float vector per input.

    Posts straight to the gateway's OpenAI-compatible /v1/embeddings route with
    httpx rather than going through the `openai` SDK — the request is a single
    flat JSON body, so the SDK would be a dependency bought for nothing.

    `dimensions` (Matryoshka truncation) is only supported by the
    text-embedding-3-* family. Older models reject it, so a rejection naming
    that field is retried once without it, mirroring how llm.py degrades
    against this same gateway. The caller checks the width it gets back.
    """
    if not texts:
        return []

    settings = get_settings()
    url = _embeddings_url()
    headers = {
        "x-portkey-api-key": settings.portkey_api_key,
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {"model": settings.embedding_model, "input": texts}
    if settings.embedding_dimensions:
        payload["dimensions"] = settings.embedding_dimensions

    def _post(body: dict[str, Any]) -> httpx.Response:
        return httpx.post(url, headers=headers, json=body, timeout=120.0)

    response = _post(payload)

    if response.status_code == 400 and "dimensions" in response.text.lower():
        logger.warning(
            "embedding model %s rejected `dimensions` — retrying at its native width",
            settings.embedding_model,
        )
        payload.pop("dimensions", None)
        response = _post(payload)

    if response.status_code >= 400:
        raise RuntimeError(
            f"Embedding request failed ({response.status_code}) for model "
            f"{settings.embedding_model!r}: {response.text[:400]}"
        )

    data = response.json().get("data")
    if not data:
        raise RuntimeError(f"Embedding response had no data: {response.text[:400]}")

    return [item["embedding"] for item in sorted(data, key=lambda d: d.get("index", 0))]


# ---------------------------------------------------------------------------
# Chunker
# ---------------------------------------------------------------------------

@dataclass
class Chunk:
    heading: str
    content: str
    chunk_index: int


def chunk_document(text: str) -> list[Chunk]:
    """Heading-aware chunker.

    Splits on markdown headings (# / ## / ###). Within each section, further
    splits at paragraph boundaries if the section exceeds the soft cap, with
    overlap carried forward.
    """
    # Split on headings — keep the heading with the text that follows it.
    sections = re.split(r"(?m)^(#{1,3}\s.+)$", text)

    # re.split with a capture group gives: [pre, heading, body, heading, body, ...]
    # Zip them into (heading, body) pairs.
    raw_pairs: list[tuple[str, str]] = []
    if sections[0].strip():
        raw_pairs.append(("", sections[0]))  # content before the first heading

    it = iter(sections[1:])
    for heading, body in zip(it, it):
        raw_pairs.append((heading.strip(), body.strip()))

    chunks: list[Chunk] = []
    idx = 0
    prev_tail = ""  # overlap from the previous chunk

    for heading, body in raw_pairs:
        # Prepend overlap from previous chunk
        text_to_chunk = (prev_tail + "\n\n" + body).strip() if prev_tail else body
        paragraphs = [p.strip() for p in re.split(r"\n{2,}", text_to_chunk) if p.strip()]

        current: list[str] = []
        current_len = 0

        for para in paragraphs:
            para_len = len(para)
            if current_len + para_len > _CHUNK_SOFT_CAP and current:
                content = "\n\n".join(current)
                chunks.append(Chunk(heading=heading, content=content, chunk_index=idx))
                idx += 1
                # Overlap: keep last ~_OVERLAP chars of current chunk
                overlap_text = content[-_OVERLAP:]
                current = [overlap_text, para] if overlap_text else [para]
                current_len = len(overlap_text) + para_len
            else:
                current.append(para)
                current_len += para_len

        if current:
            content = "\n\n".join(current)
            chunks.append(Chunk(heading=heading, content=content, chunk_index=idx))
            prev_tail = content[-_OVERLAP:]
            idx += 1

    return chunks


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

def ingest_policy_doc(
    *,
    title: str,
    version: str,
    content: str,
    uploaded_by: str,
) -> dict[str, Any]:
    """Chunk → embed → upsert into Supabase.

    Idempotent: if a doc with the same title + version already exists, its
    chunks are deleted and replaced. A new title+version creates a new doc row.

    Returns a summary dict: {doc_id, chunks_ingested, tokens_approx}.
    """
    db = service_db()

    # Check for an existing doc with the same title + version
    existing = (
        db.table("policy_docs")
        .select("id")
        .eq("title", title)
        .eq("version", version)
        .limit(1)
        .execute()
    )

    if existing.data:
        doc_id = existing.data[0]["id"]
        # Delete old chunks so we start fresh
        db.table("policy_chunks").delete().eq("policy_doc_id", doc_id).execute()
        logger.info("ingest: replacing chunks for existing doc %s (%s)", title, version)
    else:
        # storage_path is UNIQUE. Nothing is uploaded to Storage in this build,
        # so it gets a synthetic per-document path — a shared placeholder would
        # let only the first document ever insert.
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        doc_row = (
            db.table("policy_docs")
            .insert(
                {
                    "title": title,
                    "version": version,
                    "storage_path": f"local/policies/{slug}-v{version}.md",
                    "effective_from": "2025-01-01",
                    "uploaded_by": uploaded_by,
                }
            )
            .execute()
        )
        doc_id = doc_row.data[0]["id"]
        logger.info("ingest: created new policy_doc %s id=%s", title, doc_id)

    # Chunk the document
    chunks = chunk_document(content)
    if not chunks:
        logger.warning("ingest: no chunks produced for %s", title)
        return {"doc_id": doc_id, "chunks_ingested": 0, "tokens_approx": 0}

    # Embed all chunks in one batch
    texts = [
        f"{c.heading}\n\n{c.content}" if c.heading else c.content
        for c in chunks
    ]
    embeddings = embed_texts(texts)

    # Upsert chunks
    rows = []
    for chunk, embedding, text in zip(chunks, embeddings, texts):
        rows.append(
            {
                "id": str(uuid.uuid4()),
                "policy_doc_id": doc_id,
                "chunk_index": chunk.chunk_index,
                "heading": chunk.heading or None,
                "content": chunk.content,
                "embedding": embedding,
                "tokens_approx": len(text) // _CHARS_PER_TOKEN,
            }
        )

    # Insert in batches of 50 to stay within PostgREST body limits
    for i in range(0, len(rows), 50):
        db.table("policy_chunks").insert(rows[i : i + 50]).execute()

    total_tokens = sum(r["tokens_approx"] for r in rows)
    logger.info(
        "ingest: %d chunks, ~%d tokens ingested for %s v%s",
        len(rows), total_tokens, title, version,
    )
    return {
        "doc_id": doc_id,
        "chunks_ingested": len(rows),
        "tokens_approx": total_tokens,
    }
