"""Conversations and chat, saved in the database. SMA-30 (replaces SMA-23's POST /api/chat).

GET/POST   /api/conversations            list mine / start one
GET        /api/conversations/{id}       one conversation with its messages
PATCH      /api/conversations/{id}       rename
DELETE     /api/conversations/{id}       delete (its messages too)
POST       /api/conversations/{id}/messages   ask the AI; question + answer are saved
POST       /api/conversations/{id}/title      AI title from the first message (SMA-31)

The user comes only from get_current_user_id, never from the request. Each request is one
transaction: the repositories never commit, these routes commit once at the end.
"""

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Annotated, Any, Literal

import anyio
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, StringConstraints
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id
from app.config import Settings, get_settings
from app.db.session import _session_factory, get_db
from app.mcp_server.context import ToolContext
from app.models import Conversation
from app.repositories import conversations as repo
from app.services.agent import ToolStep, run_agent_for_user
from app.services.llm.base import ChatOptions, ChatResponse, Message
from app.services.llm.exceptions import AllModelsFailedError, LLMConfigError
from app.services.llm.fallback import Attempt, FallbackManager, get_fallback_manager
from app.services.llm.registry import ModelConfig, ModelRegistry, get_registry
from app.services.titles import generate_title

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
MODE = "general"  # later: "grounded" (documents, Stage 4)
# Added when the model can use the MCP tools (SMA-42). It needs today's date to work out
# "by Sunday" or "tomorrow" (SMA-39 lesson).
TOOLS_PROMPT = (
    " You can manage the student's study tasks and notes with tools. Today is {today} "
    "({weekday}). Use a tool only when the student asks for something it does."
)

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


class ToolCallOut(BaseModel):
    """One tool the AI used for an answer (SMA-42): "Used tool: create_task -> ..."."""

    name: str
    arguments: dict[str, Any] | str  # a string only if the AI sent broken JSON
    result: str  # what the tool sent back to the AI (shortened)
    is_error: bool
    duration_ms: int


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
    tool_calls: list[ToolCallOut] | None = None  # SMA-42
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
    message_id: str  # the saved answer: lets the page "Save as note" (SMA-32)
    reply: str
    provider: str  # who actually answered (may differ from the request after a fallback)
    model: str
    mode: Literal["general", "tool"] = MODE  # "tool": the AI used MCP tools (SMA-42)
    tool_calls: list[ToolCallOut] = []
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
    settings: Annotated[Settings, Depends(get_settings)],
) -> ChatReply:
    conversation = my_conversation(db, user_id, conversation_id)
    model_id = choose_model(request, conversation, registry)
    # SMA-42: a model that can call tools gets the app's MCP tools (only those models).
    uses_tools = model_id is not None and registry.get(model_id).supports("tools")

    # The model has no memory of its own: every call sends the recent conversation.
    history = [
        {"role": m.role, "content": m.content}
        for m in repo.recent_messages(db, user_id, conversation_id, MAX_HISTORY_MESSAGES)
    ]
    system = SYSTEM_PROMPT + (tools_prompt(date.today()) if uses_tools else "")
    messages = [{"role": "system", "content": system}, *history]
    messages.append({"role": "user", "content": request.message})
    options = ChatOptions(max_tokens=MAX_OUTPUT_TOKENS)
    try:
        if uses_tools:
            # The tools act for THIS request's user, set by us, never chosen by the AI.
            context = ToolContext(user_id, _session_factory(settings.database_url))
            outcome = ask_with_tools(context, manager, messages, model_id, request, options)
        else:
            outcome = ask(manager, messages, model_id, request, options)
    except AllModelsFailedError as e:
        # Keep the record of the failed calls, but save no half-turn (no question alone).
        repo.log_llm_calls(db, user_id, conversation_id, e.attempts, call_mode(uses_tools))
        db.commit()
        raise HTTPException(503, f"The AI is unavailable right now ({e})") from e
    except LLMConfigError as e:  # e.g. the chosen model is disabled
        raise HTTPException(400, str(e)) from e
    answer = outcome.response
    tool_calls = [tool_call_out(step) for step in outcome.steps]
    mode = "tool" if tool_calls else MODE

    # One transaction: the question, the answer and the call log are saved together, or
    # (if anything fails before commit) not at all.
    if request.model:  # the user switched models: remember it for this conversation
        conversation.provider, conversation.model = registry.get(model_id).provider, model_id
    repo.add_message(db, conversation, role="user", content=request.message)
    saved_answer = repo.add_message(
        db,
        conversation,
        role="assistant",
        content=answer.text,
        provider=answer.provider,
        model=answer.model,
        mode=mode,
        fallback_used=outcome.fallback_used,
        tokens_in=outcome.tokens_in,
        tokens_out=outcome.tokens_out,
        tool_calls=[t.model_dump() for t in tool_calls] or None,
    )
    repo.log_llm_calls(db, user_id, conversation_id, outcome.attempts, call_mode(uses_tools))
    db.commit()

    return ChatReply(
        conversation_id=conversation_id,
        message_id=saved_answer.id,
        reply=answer.text,
        provider=answer.provider,
        model=answer.model,
        mode=mode,
        tool_calls=tool_calls,
        fallback_used=outcome.fallback_used,
        fallback_reason=outcome.fallback_reason,
        tokens_in=outcome.tokens_in,
        tokens_out=outcome.tokens_out,
    )


# --- Asking the model (with or without tools) ----------------------------------------


@dataclass
class Outcome:
    """What one chat message produced, whichever way the model was asked."""

    response: ChatResponse
    fallback_used: bool
    fallback_reason: str | None
    attempts: list[Attempt]  # every model call (several turns with tools)
    tokens_in: int
    tokens_out: int
    steps: list[ToolStep] = field(default_factory=list)


def ask(manager, messages: list[Message], model_id, request: SendMessage, options) -> Outcome:
    result = manager.chat(messages, options, model_id, allow_fallback=request.allow_fallback)
    answer = result.response
    return Outcome(
        answer,
        result.fallback_used,
        result.fallback_reason,
        result.attempts,
        answer.tokens_in,
        answer.tokens_out,
    )


def ask_with_tools(
    context: ToolContext, manager, messages: list[Message], model_id, request, options
) -> Outcome:
    """The agent loop (SMA-42). This route runs in a worker thread: from_thread.run runs
    the async loop on the app's event loop and waits for it."""
    run = anyio.from_thread.run(
        run_agent_for_user, context, manager, messages, model_id, request.allow_fallback, options
    )
    return Outcome(
        run.response,
        run.fallback_used,
        run.fallback_reason,
        run.attempts,
        run.tokens_in,
        run.tokens_out,
        run.steps,
    )


def tools_prompt(today: date) -> str:
    return TOOLS_PROMPT.format(today=today.isoformat(), weekday=today.strftime("%A"))


def call_mode(uses_tools: bool) -> str:
    """llm_calls.mode: separates tool turns from plain chat in the usage numbers."""
    return "tool" if uses_tools else MODE


def tool_call_out(step: ToolStep) -> ToolCallOut:
    try:
        arguments = json.loads(step.arguments or "{}")
    except json.JSONDecodeError:
        arguments = step.arguments  # broken JSON from the AI: keep it as text
    return ToolCallOut(
        name=step.name,
        arguments=arguments,
        result=step.result[:1000],  # tool results can be long: keep the saved copy short
        is_error=step.is_error,
        duration_ms=step.duration_ms,
    )


@router.post("/{conversation_id}/title", response_model=ConversationOut)
def create_title(
    conversation_id: str,
    user_id: CurrentUserId,
    db: Db,
    registry: Registry,
    manager: Annotated[FallbackManager, Depends(get_fallback_manager)],
) -> Conversation:
    """Name the conversation after its first message. A separate call, so the first
    answer isn't slowed down: the page asks for it once the answer has arrived."""
    conversation = my_conversation(db, user_id, conversation_id)
    if conversation.title:
        return conversation  # already named (maybe renamed by the user): keep it
    first = repo.first_user_message(db, user_id, conversation_id)
    if first is None:
        raise HTTPException(409, "Send a message before asking for a title")

    model_id = conversation.model or registry.default_model("chat")
    result = generate_title(manager, first.content, model_id)
    conversation.title = result.title
    repo.log_llm_calls(db, user_id, conversation_id, result.attempts, "title")
    db.commit()
    return conversation


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
