"""Phase 5 — Policy document endpoints.

GET  /policies           — list all policy docs (HR + managers)
POST /policies           — upload and ingest a new policy doc (HR only)
GET  /policies/{id}      — fetch one doc's metadata + chunk count
DELETE /policies/{id}    — delete a policy doc and all its chunks (HR only)

Upload accepts plain text (.txt) or markdown (.md) — the same formats
ingest_policies.py uses from backend/data/policies/. PDF support is a
Phase 9 addition (requires a PDF-to-text extraction step before chunking).

Ingestion is synchronous in this build (runs in the request). A large doc
with many chunks can take 5–15 seconds while the embedding API is called.
The frontend shows a spinner; Phase 9 can move this to a background task.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, UploadFile, status
from fastapi import File, Form

from app.deps import Actor, service_db
from app.services.audit import write_audit

log = logging.getLogger("app.routers.policy")

router = APIRouter(tags=["policy"])

_ALLOWED_CONTENT_TYPES = {
    "text/plain",
    "text/markdown",
    "text/x-markdown",
    "application/octet-stream",  # browsers sometimes send .md with this
}
_MAX_SIZE_BYTES = 2 * 1024 * 1024  # 2 MB — well above any realistic policy doc


@router.get("/policies")
async def list_policies(actor: Actor) -> list[dict]:
    """List all ingested policy documents."""
    if actor.role == "employee":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "HR and managers only.")

    result = (
        actor.db.table("policy_docs")
        .select("id, title, version, effective_from, uploaded_by, created_at")
        .order("created_at", desc=True)
        .execute()
    )
    return result.data


@router.get("/policies/{policy_id}")
async def get_policy(policy_id: str, actor: Actor) -> dict:
    """Fetch one policy doc's metadata plus chunk count."""
    if actor.role == "employee":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "HR and managers only.")

    doc = (
        actor.db.table("policy_docs")
        .select("*")
        .eq("id", policy_id)
        .limit(1)
        .execute()
    )
    if not doc.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Policy doc not found.")

    chunk_count = (
        service_db()
        .table("policy_chunks")
        .select("id", count="exact")
        .eq("policy_doc_id", policy_id)
        .execute()
    )

    return {**doc.data[0], "chunk_count": chunk_count.count or 0}


@router.post("/policies", status_code=status.HTTP_201_CREATED)
async def upload_policy(
    actor: Actor,
    file: UploadFile = File(...),
    title: str = Form(...),
    version: str = Form(...),
    effective_from: str = Form("2025-01-01"),
) -> dict:
    """Upload, chunk, embed, and ingest a policy document.

    HR only. Accepts .txt or .md files up to 2 MB.
    Ingestion is idempotent on (title, version) — re-uploading replaces chunks.
    """
    if actor.role != "hr":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "HR only.")

    if not title.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Title is required.")
    if not version.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Version is required.")

    raw = await file.read()
    if len(raw) > _MAX_SIZE_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File too large. Maximum is {_MAX_SIZE_BYTES // 1024} KB.",
        )

    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "File must be UTF-8 encoded text or markdown.",
        )

    if not content.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "File is empty.")

    try:
        from app.services.rag import ingest_policy_doc  # lazy — avoids openai import on startup

        result = ingest_policy_doc(
            title=title.strip(),
            version=version.strip(),
            content=content,
            uploaded_by=actor.employee_id,
        )
    except RuntimeError as exc:
        # Gateway/embedding not configured
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except Exception as exc:
        log.exception("policy upload failed: %s", exc)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Ingestion failed.") from exc

    write_audit(
        action="policy_docs.uploaded",
        entity_table="policy_docs",
        entity_id=result["doc_id"],
        actor=actor,
        after={
            "title": title,
            "version": version,
            "chunks": result["chunks_ingested"],
        },
    )

    return result


@router.delete("/policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_policy(policy_id: str, actor: Actor) -> None:
    """Delete a policy doc and all its chunks. HR only."""
    if actor.role != "hr":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "HR only.")

    doc = (
        actor.db.table("policy_docs")
        .select("id, title, version")
        .eq("id", policy_id)
        .limit(1)
        .execute()
    )
    if not doc.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Policy doc not found.")

    db = service_db()
    db.table("policy_chunks").delete().eq("policy_doc_id", policy_id).execute()
    db.table("policy_docs").delete().eq("id", policy_id).execute()

    write_audit(
        action="policy_docs.deleted",
        entity_table="policy_docs",
        entity_id=policy_id,
        actor=actor,
        before={"title": doc.data[0]["title"], "version": doc.data[0]["version"]},
    )
