"""Documents: upload, list, open, delete (guide 7.3, wireframe 6.3). SMA-44.

POST   /api/documents        upload one PDF / TXT / MD file (multipart, field "file")
GET    /api/documents        my documents, newest first
GET    /api/documents/{id}   one of my documents
DELETE /api/documents/{id}   delete it (its chunks and chat links too)
POST   /api/documents/{id}/retry   re-run embedding after a failure (SMA-46)

The upload is checked (app/services/uploads.py) and recorded as "processing". The file
itself is not kept: SMA-45/47 turn it into text chunks within this same request.
The user comes only from get_current_user_id. Another user's document answers 404.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id
from app.db.session import get_db
from app.models import Document
from app.repositories import documents as repo
from app.services.llm.embeddings import EmbeddingProvider, get_embedder
from app.services.llm.exceptions import LLMConfigError
from app.services.rag.embed import EmbeddingFailed, embed_document, failure_message
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


@router.post("", response_model=DocumentOut, status_code=201)
def upload_document(file: UploadFile, user_id: CurrentUserId, db: Db) -> Document:
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
    return document


@router.get("", response_model=list[DocumentOut])
def list_documents(user_id: CurrentUserId, db: Db) -> list[DocumentOut]:
    documents = repo.list_documents(db, user_id)
    with_chunks = repo.ids_with_chunks(db, [d.id for d in documents])
    return [document_out(d, d.id in with_chunks) for d in documents]


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: str, user_id: CurrentUserId, db: Db) -> DocumentOut:
    document = my_document(db, user_id, document_id)
    return document_out(document, bool(repo.ids_with_chunks(db, [document.id])))


@router.post("/{document_id}/retry", response_model=DocumentOut)
def retry_document(
    document_id: str,
    user_id: CurrentUserId,
    db: Db,
    embedder: Annotated[Callable[[], EmbeddingProvider], Depends(get_embedder)],
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
        document.status = "ready"
        db.commit()
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
