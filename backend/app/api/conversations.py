"""Conversations and chat, saved in the database. SMA-30 (replaces SMA-23's POST /api/chat).

GET/POST   /api/conversations            list mine / start one
GET        /api/conversations/{id}       one conversation with its messages
PATCH      /api/conversations/{id}       rename
DELETE     /api/conversations/{id}       delete (its messages too)
POST       /api/conversations/{id}/messages   ask the AI; question + answer are saved

The user comes only from get_current_user_id, never from the request. Each request is one
transaction: the repositories never commit, these routes commit once at the end.
"""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, StringConstraints
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id
from app.db.session import get_db
from app.models import Conversation
from app.repositories import conversations as repo
from app.services.llm.base import ChatOptions
from app.services.llm.exceptions import AllModelsFailedError, LLMConfigError
from app.services.llm.fallback import FallbackManager, get_fallback_manager
from app.services.llm.registry import ModelConfig, ModelRegistry, get_registry

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

SYSTEM_PROMPT = (
    "You are StudyMate, a friendly study assistant for college students. "
    "Explain clearly and concisely, and say so when you are not sure."
)

# Send only the last N messages (= 5 question/answer pairs). Every message sent costs
# tokens, time and free-tier quota, and the model's context window has a hard limit.
MAX_HISTORY_MESSAGES = 10

# Limits (guide: "max message length, max tokens per answer"): protect the free quota
# and keep answers readable.
MAX_MESSAGE_CHARS = 4000
MAX_OUTPUT_TOKENS = 1024
MODE = "general"  # later: "grounded" (documents, Stage 4), "tool" (MCP, Stage 3)

# Shared shapes for the dependencies every route uses.
CurrentUserId = Annotated[str, Depends(get_current_user_id)]
Db = Annotated[Session, Depends(get_db)]
Registry = Annotated[ModelRegistry, Depends(get_registry)]


# --- Request and response shapes ---------------------------------------------------


class ConversationCreate(BaseModel):
    model: str | None = None  # a model id from models.yaml; None = the chat default


class ConversationRename(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class ConversationOut(BaseModel):
    # from_attributes: build it straight from a SQLAlchemy Conversation object.
    model_config = {"from_attributes": True}

    id: str
    title: str | None
    provider: str | None
    model: str | None
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    role: str
    content: str
    provider: str | None  # the answer's details (empty on the user's own messages)
    model: str | None
    mode: str | None
    fallback_used: bool
    tokens_in: int | None
    tokens_out: int | None
    created_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class SendMessage(BaseModel):
    # Checked by FastAPI before our code runs: too long or empty -> 422.
    message: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_MESSAGE_CHARS)
    ]
    model: str | None = None  # switch this conversation to another model
    provider: str | None = None  # optional cross-check: must match the model's provider
    allow_fallback: bool = True  # False: only the chosen model may answer (SMA-26)


class ChatReply(BaseModel):
    conversation_id: str
    reply: str
    provider: str  # who actually answered (may differ from the request after a fallback)
    model: str
    mode: Literal["general"] = MODE
    fallback_used: bool
    fallback_reason: str | None
    tokens_in: int
    tokens_out: int


# --- Conversations CRUD ------------------------------------------------------------


@router.get("", response_model=list[ConversationOut])
def list_conversations(user_id: CurrentUserId, db: Db) -> list[Conversation]:
    return repo.list_conversations(db, user_id)


@router.post("", response_model=ConversationOut, status_code=201)
def create_conversation(
    body: ConversationCreate, user_id: CurrentUserId, db: Db, registry: Registry
) -> Conversation:
    model = find_model(registry, body.model) if body.model else None
    conversation = repo.create_conversation(
        db,
        user_id,
        provider=model.provider if model else None,
        model=model.id if model else None,
    )
    db.commit()
    return conversation


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: str, user_id: CurrentUserId, db: Db) -> Conversation:
    return my_conversation(db, user_id, conversation_id, with_messages=True)


@router.patch("/{conversation_id}", response_model=ConversationOut)
def rename_conversation(
    conversation_id: str, body: ConversationRename, user_id: CurrentUserId, db: Db
) -> Conversation:
    conversation = repo.rename_conversation(db, user_id, conversation_id, body.title)
    if conversation is None:
        raise HTTPException(404, "Conversation not found")
    db.commit()
    return conversation


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str, user_id: CurrentUserId, db: Db) -> Response:
    if not repo.delete_conversation(db, user_id, conversation_id):
        raise HTTPException(404, "Conversation not found")
    db.commit()
    return Response(status_code=204)


# --- Chat --------------------------------------------------------------------------


@router.post("/{conversation_id}/messages", response_model=ChatReply)
def send_message(
    conversation_id: str,
    request: SendMessage,
    user_id: CurrentUserId,
    db: Db,
    registry: Registry,
    manager: Annotated[FallbackManager, Depends(get_fallback_manager)],
) -> ChatReply:
    conversation = my_conversation(db, user_id, conversation_id)
    model_id = choose_model(request, conversation, registry)

    # The model has no memory of its own: every call sends the recent conversation.
    history = [
        {"role": m.role, "content": m.content}
        for m in repo.recent_messages(db, user_id, conversation_id, MAX_HISTORY_MESSAGES)
    ]
    question = {"role": "user", "content": request.message}
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *history, question]
    try:
        result = manager.chat(
            messages,
            ChatOptions(max_tokens=MAX_OUTPUT_TOKENS),
            model_id,
            allow_fallback=request.allow_fallback,
        )
    except AllModelsFailedError as e:
        # Keep the record of the failed calls, but save no half-turn (no question alone).
        repo.log_llm_calls(db, user_id, conversation_id, e.attempts, MODE)
        db.commit()
        raise HTTPException(503, f"The AI is unavailable right now ({e})") from e
    except LLMConfigError as e:  # e.g. the chosen model is disabled
        raise HTTPException(400, str(e)) from e
    answer = result.response

    # One transaction: the question, the answer and the call log are saved together, or
    # (if anything fails before commit) not at all.
    if request.model:  # the user switched models: remember it for this conversation
        conversation.provider, conversation.model = registry.get(model_id).provider, model_id
    repo.add_message(db, conversation, role="user", content=request.message)
    repo.add_message(
        db,
        conversation,
        role="assistant",
        content=answer.text,
        provider=answer.provider,
        model=answer.model,
        mode=MODE,
        fallback_used=result.fallback_used,
        tokens_in=answer.tokens_in,
        tokens_out=answer.tokens_out,
    )
    repo.log_llm_calls(db, user_id, conversation_id, result.attempts, MODE)
    db.commit()

    return ChatReply(
        conversation_id=conversation_id,
        reply=answer.text,
        provider=answer.provider,
        model=answer.model,
        fallback_used=result.fallback_used,
        fallback_reason=result.fallback_reason,
        tokens_in=answer.tokens_in,
        tokens_out=answer.tokens_out,
    )


# --- Helpers -----------------------------------------------------------------------


def my_conversation(
    db: Session, user_id: str, conversation_id: str, *, with_messages: bool = False
) -> Conversation:
    """The user's conversation, or 404 (also when it's someone else's: reveals nothing)."""
    conversation = repo.get_conversation(db, user_id, conversation_id, with_messages=with_messages)
    if conversation is None:
        raise HTTPException(404, "Conversation not found")
    return conversation


def find_model(registry: ModelRegistry, model_id: str) -> ModelConfig:
    try:
        return registry.get(model_id)
    except KeyError:
        raise HTTPException(400, f"Unknown model {model_id!r}: see GET /api/models") from None


def choose_model(
    request: SendMessage, conversation: Conversation, registry: ModelRegistry
) -> str | None:
    """The model to try first: the request's, else the conversation's, else the default.

    400 if it's unknown or doesn't match `provider`.
    """
    model_id = request.model or conversation.model or registry.default_model("chat")
    if model_id is None:
        return None  # no chat default: the manager uses the first enabled model
    model = find_model(registry, model_id)
    if request.provider and request.provider != model.provider:
        raise HTTPException(
            400,
            f"Model {model_id!r} belongs to provider {model.provider!r}, not {request.provider!r}",
        )
    return model_id
