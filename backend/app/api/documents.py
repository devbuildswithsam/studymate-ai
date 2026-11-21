"""Documents: upload, list, open, delete (guide 7.3, wireframe 6.3). SMA-44.

POST   /api/documents        upload one PDF / TXT / MD file (multipart, field "file") and
                             ingest it, streaming progress events (SMA-47)
GET    /api/documents        my documents, newest first
GET    /api/documents/{id}   one of my documents
DELETE /api/documents/{id}   delete it (its chunks and chat links too)
POST   /api/documents/{id}/retry   re-run embedding after a failure (SMA-46)
POST   /api/documents/{id}/summary regenerate the summary and key points (SMA-50)

The upload is checked (app/services/uploads.py), recorded as "processing", then ingested
in the same request (app/services/rag/ingest.py). The file itself is never kept: only its
text chunks and their vectors.
The user comes only from get_current_user_id. Another user's document answers 404.
"""

import json
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id
from app.config import Settings, get_settings
from app.db.session import _session_factory, get_db
from app.models import Document
from app.repositories import documents as repo
from app.services.llm.embeddings import EmbeddingProvider, get_embedder
from app.services.llm.exceptions import LLMConfigError
from app.services.llm.fallback import FallbackManager, get_fallback_manager
from app.services.rag.embed import EmbeddingFailed, embed_document, failure_message
from app.services.rag.ingest import ingest
from app.services.rate_limits import rate_limit
from app.services.summary import Style, SummaryFailed, summarize_document
from app.services.uploads import MAX_UPLOAD_BYTES, UploadRejected, check_upload

router = APIRouter(prefix="/api/documents", tags=["documents"])

CurrentUserId = Annotated[str, Depends(get_current_user_id)]
Db = Annotated[Session, Depends(get_db)]


class DocumentOut(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    filename: str
    mime_type: str
    size_bytes: int
    page_count: int | None
    status: str  # processing / ready / failed
    error: str | None
    summary: str | None
    key_points: list[Any] | None
    created_at: datetime
    # SMA-46: failed, but its chunks exist, so POST .../retry can finish it. Without
    # chunks (it failed earlier) the file is gone: it has to be uploaded again.
    can_retry: bool = False


def document_out(document: Document, has_chunks: bool) -> DocumentOut:
    out = DocumentOut.model_validate(document)
    out.can_retry = document.status == "failed" and has_chunks
    return out


@router.post(
    "",
    status_code=201,
    response_class=StreamingResponse,
    dependencies=[Depends(rate_limit("upload"))],  # SMA-67
)
def upload_document(
    file: UploadFile,
    user_id: CurrentUserId,
    db: Db,
    settings: Annotated[Settings, Depends(get_settings)],
    embedder: Annotated[Callable[[], EmbeddingProvider], Depends(get_embedder)],
    manager: Annotated[FallbackManager, Depends(get_fallback_manager)],
) -> StreamingResponse:
    """Upload + ingest in one request (guide 7.4). Checks first (413/415/422 as normal
    errors), then the answer is a STREAM: one JSON event per line (NDJSON), e.g.
    {"stage": "extracting", "done": 12, "total": 30} ... {"stage": "ready", "document": {...}}.
    """
    # Read one byte MORE than allowed: if we get it, the file is too big. Reading only
    # up to the limit would silently cut the file instead.
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    try:
        checked = check_upload(file.filename or "", data)
    except UploadRejected as e:
        raise HTTPException(e.status, e.message) from e
    document = repo.create_document(
        db,
        user_id,
        filename=checked.filename,
        mime_type=checked.mime_type,  # from the content, never file.content_type
        size_bytes=checked.size_bytes,
    )
    db.commit()
    stream = ingest_stream(document.id, data, settings.database_url, embedder, manager)
    return StreamingResponse(stream, status_code=201, media_type="application/x-ndjson")


def ingest_stream(
    document_id: str,
    data: bytes,
    database_url: str,
    embedder: Callable[[], EmbeddingProvider],
    manager: FallbackManager,
) -> Iterator[str]:
    """Run the pipeline and turn each event into a line of JSON.

    It runs AFTER the route has returned, while the response is being sent, so it opens its
    own database session instead of borrowing the request's.
    """
    with _session_factory(database_url)() as db:
        document = db.get(Document, document_id)
        steps = ingest(
            db, document, data, embedder, lambda db_, doc: summarize_document(db_, doc, manager)
        )
        try:
            for event in steps:
                if event["stage"] in ("ready", "failed"):  # the end: send the document too
                    has_chunks = bool(repo.ids_with_chunks(db, [document.id]))
                    out = document_out(document, has_chunks).model_dump(mode="json")
                    event = {**event, "document": out}
                yield json.dumps(event) + "\n"
        finally:
            steps.close()  # if the browser left early: ingest marks the document failed


@router.get("", response_model=list[DocumentOut])
def list_documents(user_id: CurrentUserId, db: Db) -> list[DocumentOut]:
    documents = repo.list_documents(db, user_id)
    with_chunks = repo.ids_with_chunks(db, [d.id for d in documents])
    return [document_out(d, d.id in with_chunks) for d in documents]


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: str, user_id: CurrentUserId, db: Db) -> DocumentOut:
    document = my_document(db, user_id, document_id)
    return document_out(document, bool(repo.ids_with_chunks(db, [document.id])))


@router.post(
    "/{document_id}/retry",
    response_model=DocumentOut,
    dependencies=[Depends(rate_limit("upload"))],  # embeds again (SMA-67)
)
def retry_document(
    document_id: str,
    user_id: CurrentUserId,
    db: Db,
    embedder: Annotated[Callable[[], EmbeddingProvider], Depends(get_embedder)],
    manager: Annotated[FallbackManager, Depends(get_fallback_manager)],
) -> DocumentOut:
    document = my_document(db, user_id, document_id)
    if document.status != "failed":
        raise HTTPException(
            409, f"Only a failed document can be retried (this one is {document.status})."
        )
    if not repo.ids_with_chunks(db, [document.id]):
        raise HTTPException(409, "Nothing to retry: the file wasn't kept, so upload it again.")
    document.status, document.error = "processing", None
    db.commit()
    try:
        embed_document(db, document, embedder())  # continues where it stopped
    except LLMConfigError as e:  # e.g. no API key: building the provider failed
        document.status, document.error = "failed", failure_message(e)
        db.commit()
    except EmbeddingFailed:
        pass  # embed_document already marked it failed, with the reason
    else:
        try:  # SMA-50: the summary, as at the end of an upload
            summarize_document(db, document, manager)
        except SummaryFailed:
            db.rollback()
        document.status = "ready"
        db.commit()
    return document_out(document, has_chunks=True)


class SummaryRequest(BaseModel):
    style: Style = "short"  # "short" or "detailed" (wireframe 6.4)


@router.post(
    "/{document_id}/summary",
    response_model=DocumentOut,
    dependencies=[Depends(rate_limit("generate"))],  # an AI call (SMA-67)
)
def regenerate_summary(
    document_id: str,
    body: SummaryRequest,
    user_id: CurrentUserId,
    db: Db,
    manager: Annotated[FallbackManager, Depends(get_fallback_manager)],
) -> DocumentOut:
    """Write the summary again, in the chosen style (SMA-50). Only on request: viewing a
    document reads the saved summary and never calls the AI."""
    document = my_document(db, user_id, document_id)
    if document.status != "ready":
        raise HTTPException(
            409, f"Only a ready document can be summarised (this one is {document.status})."
        )
    try:
        summarize_document(db, document, manager, body.style)
    except SummaryFailed as e:
        raise HTTPException(503, str(e)) from e  # the old summary is kept
    return document_out(document, has_chunks=True)


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: str, user_id: CurrentUserId, db: Db) -> Response:
    if not repo.delete_document(db, user_id, document_id):
        raise HTTPException(404, "Document not found")
    db.commit()
    return Response(status_code=204)


def my_document(db: Session, user_id: str, document_id: str) -> Document:
    """The user's document, or 404 (also when it's someone else's: reveals nothing)."""
    document = repo.get_document(db, user_id, document_id)
    if document is None:
        raise HTTPException(404, "Document not found")
    return document
