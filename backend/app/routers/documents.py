"""
Document upload and review.

Files live in the private `case-documents` storage bucket; this table holds the
metadata and the review decision. Downloads are never direct — the client asks
for a short-lived signed URL, which is only issued after RLS has confirmed the
caller can see the case.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.deps import Actor, service_db
from app.services.audit import write_audit
from app.services.doc_check import verify_document
from app.services.documents import is_outbound, sync_task_for_document
from app.services.letters import GENERATABLE, generate

log = logging.getLogger("app.routers.documents")
router = APIRouter(tags=["documents"])

BUCKET = "case-documents"
MAX_BYTES = 10 * 1024 * 1024
ALLOWED_MIME = {"application/pdf", "image/png", "image/jpeg"}
SIGNED_URL_TTL_SECONDS = 120


class ReviewBody(BaseModel):
    status: Literal["approved", "rejected"]
    note: str | None = None


class InlineDocBody(BaseModel):
    doc_type_code: str
    content: dict


@router.post("/cases/{case_id}/documents/inline", status_code=status.HTTP_201_CREATED)
async def submit_inline_document(
    case_id: str,
    body: InlineDocBody,
    actor: Actor,
) -> dict[str, object]:
    """Save a form-filled document (NDA acknowledgement, etc.) without a file upload.

    The `content` dict is stored in the `documents.content` column so the
    reviewing manager can read it inline — no file to download.
    """
    visible = actor.db.table("exit_cases").select("id").eq("id", case_id).execute()
    if not visible.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found.")

    # mime_type and size_bytes are NOT NULL on documents — the table was built
    # for uploads, and migration 0007 added inline forms without relaxing them.
    # An inline submission has both for real: it is a JSON payload of a known
    # length, so describe it accurately rather than inserting placeholders.
    payload = json.dumps(body.content, separators=(",", ":"))

    # storage_path is UNIQUE. Inline documents have no file, and an empty
    # string here meant the *second* inline document anywhere in the system
    # collided with the first — the NDA form worked once, then failed for
    # everyone else. A synthetic path keeps the column unique and still says
    # plainly that there is nothing in the bucket to fetch.
    storage_path = f"inline/{case_id}/{body.doc_type_code}/{uuid4()}"

    inserted = (
        actor.db.table("documents")
        .insert(
            {
                "case_id": case_id,
                "doc_type_code": body.doc_type_code,
                "file_name": f"{body.doc_type_code}_inline",
                "storage_path": storage_path,
                "mime_type": "application/json",
                "size_bytes": len(payload.encode("utf-8")),
                "is_inline": True,
                "content": body.content,
                "uploaded_by": actor.employee_id,
                "status": "pending",
            }
        )
        .execute()
    )

    if not inserted.data:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You cannot submit a document to this case."
        )

    document = inserted.data[0]
    write_audit(
        action="documents.submitted_inline",
        entity_table="documents",
        entity_id=document["id"],
        actor=actor,
        case_id=case_id,
        after={"doc_type_code": body.doc_type_code, "is_inline": True},
    )
    sync_task_for_document(
        actor,
        case_id=case_id,
        doc_type_code=body.doc_type_code,
        document_state="submitted",
    )
    return document


@router.post("/cases/{case_id}/documents", status_code=status.HTTP_201_CREATED)
async def upload_document(
    case_id: str,
    actor: Actor,
    file: UploadFile = File(...),
    doc_type_code: str = Form(...),
) -> dict[str, object]:
    # Prove the caller can see the case before touching storage. A user who
    # cannot read the case gets nothing back from this query.
    visible = actor.db.table("exit_cases").select("id").eq("id", case_id).execute()
    if not visible.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found.")

    # Which direction is this document travelling? An outbound one — a
    # relieving letter, a no-dues certificate — is issued by the company and
    # has no reviewer, so only the role that owns it may upload one. Without
    # this an employee could upload their own relieving letter and it would
    # auto-approve itself.
    issuing_role = is_outbound(doc_type_code)
    if issuing_role and actor.role not in (issuing_role, "hr"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Only {issuing_role.upper()} can issue this document.",
        )

    content = await file.read()
    if len(content) > MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "That file is larger than 10 MB. Compress it or split it up.",
        )
    if file.content_type not in ALLOWED_MIME:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Upload a PDF, PNG, or JPEG.",
        )

    # Ask the model whether this is the document that was requested, before the
    # row is written so the verdict lands with it. Advisory: a negative answer
    # warns the employee and flags it for their reviewer, it does not refuse the
    # upload. Returns None — and the upload simply proceeds unchecked — if the
    # model is unavailable or the file cannot be read.
    doc_type = (
        actor.db.table("document_types")
        .select("name, description")
        .eq("code", doc_type_code)
        .execute()
    )
    verification = None
    if doc_type.data:
        verification = verify_document(
            content=content,
            mime_type=file.content_type,
            expected_name=doc_type.data[0]["name"],
            expected_description=doc_type.data[0].get("description"),
        )

    # Generated name, not the user's. Stops path traversal and collisions.
    suffix = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg"}[
        file.content_type
    ]
    path = f"{case_id}/{doc_type_code}/{uuid4()}.{suffix}"

    # Storage writes use the service role: the bucket is private with no
    # user-facing policies, so access is gated here rather than by bucket rules.
    service_db().storage.from_(BUCKET).upload(
        path, content, {"content-type": file.content_type}
    )

    inserted = (
        actor.db.table("documents")
        .insert(
            {
                "case_id": case_id,
                "doc_type_code": doc_type_code,
                "file_name": file.filename or f"document.{suffix}",
                "storage_path": path,
                "mime_type": file.content_type,
                "size_bytes": len(content),
                "uploaded_by": actor.employee_id,
                # Issuing is the completion. An outbound document lands
                # approved and signed by the issuer, because there is no second
                # person who could approve it.
                "status": "approved" if issuing_role else "pending",
                "reviewed_by": actor.employee_id if issuing_role else None,
                "reviewed_at": _now() if issuing_role else None,
                "verification": verification,
            }
        )
        .execute()
    )

    if not inserted.data:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You cannot upload to this case."
        )

    document = inserted.data[0]
    write_audit(
        action="documents.issued" if issuing_role else "documents.uploaded",
        entity_table="documents",
        entity_id=document["id"],
        actor=actor,
        case_id=case_id,
        after={"doc_type_code": doc_type_code, "file_name": document["file_name"]},
    )
    sync_task_for_document(
        actor,
        case_id=case_id,
        doc_type_code=doc_type_code,
        document_state="approved" if issuing_role else "submitted",
    )
    if issuing_role:
        _notify_issued(case_id=case_id, doc_type_code=doc_type_code)
    return document


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class GenerateBody(BaseModel):
    doc_type_code: str


@router.post("/cases/{case_id}/documents/generate", status_code=status.HTTP_201_CREATED)
async def generate_document(
    case_id: str, body: GenerateBody, actor: Actor
) -> dict[str, object]:
    """Write the letter from the exit record and issue it.

    The upload path assumes HR already has a PDF. Often they do not, and the
    employee then receives nothing at all — there was no way to produce a
    relieving letter from inside the platform. Every fact one states is
    already here, so the platform writes it and the issuer reviews it.

    Same permission rule and same end state as an upload: only the owning role
    may issue, the document lands approved, the task closes, the employee is
    notified. The only difference is where the bytes came from.
    """
    issuing_role = is_outbound(body.doc_type_code)
    if not issuing_role:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Only documents the company issues can be generated.",
        )
    if actor.role not in (issuing_role, "hr"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Only {issuing_role.upper()} can issue this document.",
        )
    if body.doc_type_code not in GENERATABLE:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "There is no template for that document — upload a file instead.",
        )

    found = (
        actor.db.table("exit_cases")
        .select(
            "*, employee:employees!exit_cases_employee_id_fkey"
            "(id, full_name, emp_code, department, designation, date_of_joining)"
        )
        .eq("id", case_id)
        .execute()
    )
    if not found.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found.")

    case = found.data[0]
    employee = case.pop("employee")
    settlement = (
        actor.db.table("case_settlement")
        .select("kind, label, amount, status")
        .eq("case_id", case_id)
        .order("sort_order")
        .execute()
    ).data

    content = generate(
        body.doc_type_code,
        employee=employee,
        case=case,
        settlement=settlement,
        issued_by=actor.full_name,
    )
    slug = body.doc_type_code.lower().replace("_", "-")
    return _store_issued(
        actor,
        case_id=case_id,
        doc_type_code=body.doc_type_code,
        content=content,
        file_name=f"{slug}.pdf",
        mime_type="application/pdf",
    )


def _store_issued(
    actor,
    *,
    case_id: str,
    doc_type_code: str,
    content: bytes,
    file_name: str,
    mime_type: str,
) -> dict[str, object]:
    """Put an issued document in storage and on the record.

    Shared by the upload and generate paths so the two cannot drift: an
    issued document must always land approved, close its task and notify the
    employee, however its bytes were produced.
    """
    path = f"{case_id}/{doc_type_code}/{uuid4()}.pdf"
    service_db().storage.from_(BUCKET).upload(path, content, {"content-type": mime_type})

    inserted = (
        actor.db.table("documents")
        .insert(
            {
                "case_id": case_id,
                "doc_type_code": doc_type_code,
                "file_name": file_name,
                "storage_path": path,
                "mime_type": mime_type,
                "size_bytes": len(content),
                "uploaded_by": actor.employee_id,
                "status": "approved",
                "reviewed_by": actor.employee_id,
                "reviewed_at": _now(),
            }
        )
        .execute()
    )
    if not inserted.data:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You cannot issue documents on this case."
        )

    document = inserted.data[0]
    write_audit(
        action="documents.issued",
        entity_table="documents",
        entity_id=document["id"],
        actor=actor,
        case_id=case_id,
        after={
            "doc_type_code": doc_type_code,
            "file_name": file_name,
            "generated": True,
        },
    )
    sync_task_for_document(
        actor, case_id=case_id, doc_type_code=doc_type_code, document_state="approved"
    )
    _notify_issued(case_id=case_id, doc_type_code=doc_type_code)
    return document


def _notify_issued(*, case_id: str, doc_type_code: str) -> None:
    """Tell the employee their document is ready.

    A letter that appears silently in a list is not "sent". The bell is how the
    employee finds out, so an issue that does not notify has not really
    happened from their side.

    Best-effort: the document is already issued and the task already closed by
    the time this runs, so a failure here must not undo either.
    """
    db = service_db()
    try:
        case = (
            db.table("exit_cases")
            .select("employee_id")
            .eq("id", case_id)
            .single()
            .execute()
        )
        doc_type = (
            db.table("document_types")
            .select("name")
            .eq("code", doc_type_code)
            .single()
            .execute()
        )
        name = doc_type.data["name"]
        db.table("notifications").insert(
            {
                "recipient_id": case.data["employee_id"],
                "case_id": case_id,
                "title": f"{name} issued",
                "body": f"Your {name.lower()} is ready. Open Documents to download it.",
            }
        ).execute()
    except Exception:  # noqa: BLE001
        log.exception("could not notify employee that %s was issued", doc_type_code)


@router.post("/documents/{document_id}/review", status_code=status.HTTP_204_NO_CONTENT)
async def review_document(document_id: str, body: ReviewBody, actor: Actor) -> None:
    existing = actor.db.table("documents").select("*").eq("id", document_id).execute()
    if not existing.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found.")

    before = existing.data[0]

    # You cannot approve your own upload. RLS cannot express this — a manager
    # uploading to their report's case passes every policy — so it lives here.
    if before["uploaded_by"] == actor.employee_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "You cannot review a document you uploaded yourself.",
        )

    # An issued document has no review step — the issuing role is the authority
    # on it. Letting a second person "reject" HR's own relieving letter would
    # reopen a task that was legitimately closed.
    if is_outbound(before["doc_type_code"]):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This document was issued, not submitted. There is nothing to review.",
        )

    if body.status == "rejected" and not (body.note or "").strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Say what needs to change — the employee sees this note.",
        )

    result = (
        actor.db.table("documents")
        .update(
            {
                "status": body.status,
                "reviewed_by": actor.employee_id,
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
                "review_note": body.note,
            }
        )
        .eq("id", document_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You cannot review documents on this case."
        )

    write_audit(
        action=f"documents.{body.status}",
        entity_table="documents",
        entity_id=document_id,
        actor=actor,
        case_id=before["case_id"],
        before={"status": before["status"]},
        after={"status": body.status, "note": body.note},
    )

    # The decision the employee is actually waiting on: approving completes
    # their task, rejecting hands it back.
    sync_task_for_document(
        actor,
        case_id=before["case_id"],
        doc_type_code=before["doc_type_code"],
        document_state="approved" if body.status == "approved" else "rejected",
    )


@router.get("/documents/{document_id}/url")
async def signed_url(document_id: str, actor: Actor) -> dict[str, str]:
    """A short-lived download link, issued only after RLS confirms visibility."""
    found = (
        actor.db.table("documents")
        .select("storage_path, is_inline")
        .eq("id", document_id)
        .execute()
    )
    if not found.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found.")

    document = found.data[0]
    if document["is_inline"]:
        # Its `storage_path` is a synthetic id, not an object in the bucket —
        # signing it would hand back a URL that 404s. Inline content is read
        # from `documents.content`, which the case and document views already do.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This document was filled in on the platform — read it in the case, "
            "there is no file to download.",
        )

    signed = service_db().storage.from_(BUCKET).create_signed_url(
        document["storage_path"], SIGNED_URL_TTL_SECONDS
    )
    return {"url": signed["signedURL"]}
