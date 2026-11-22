"""Conversations and chat, saved in the database. SMA-30 (replaces SMA-23's POST /api/chat).

GET/POST   /api/conversations            list mine / start one
GET        /api/conversations/{id}       one conversation with its messages
PATCH      /api/conversations/{id}       rename
DELETE     /api/conversations/{id}       delete (its messages too)
POST       /api/conversations/{id}/messages   ask the AI; question + answer are saved.
           With `Accept: text/event-stream` the answer streams (SMA-62): events token /
           tool / done / error, as Server-Sent Events. Otherwise one JSON object.
POST       /api/conversations/{id}/stop       Stop the answer being written (SMA-62)
POST       /api/conversations/{id}/title      AI title from the first message (SMA-31)

The user comes only from get_current_user_id, never from the request. Each request is one
transaction: the repositories never commit, these routes commit once at the end.
"""

import functools
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Annotated, Any, Literal

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy.orm import Session

from app.api.actions import ActionOut
from app.api.deps import get_current_user_id
from app.config import Settings, get_settings
from app.db.session import _session_factory, get_db
from app.errors import CODES_BY_STATUS, error_body
from app.mcp_server.context import ToolContext
from app.models import Conversation
from app.repositories import conversations as repo
from app.services import chat_streams
from app.services.actions import record_actions
from app.services.agent import ToolStep, run_agent_for_user
from app.services.answer_cache import AnswerCache, cache_key, get_answer_cache
from app.services.chat_streams import CUT_OFF_NOTE, STOPPED_NOTE
from app.services.llm.base import ChatOptions, ChatResponse, Message, TextStream
from app.services.llm.embeddings import EmbeddingProvider, get_embedder
from app.services.llm.exceptions import (
    AllModelsFailedError,
    AnswerInterruptedError,
    LLMConfigError,
)
from app.services.llm.fallback import Attempt, FallbackManager, get_fallback_manager
from app.services.llm.registry import ModelConfig, ModelRegistry, get_registry
from app.services.rate_limits import rate_limit
from app.services.study import StudyError, answer_from_documents
from app.services.titles import generate_title
from app.services.tool_policy import asks_to_act

router = APIRouter(prefix="/api/conversations", tags=["conversations"])
logger = logging.getLogger(__name__)

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
    "({weekday}). Use a tool only when the student asks for something it does. "
    "Changes to existing tasks, and anything the student didn't ask for, wait for their "
    "confirmation in the app (SMA-43): never say those are done."
)

# Shared shapes for the dependencies every route uses.
CurrentUserId = Annotated[str, Depends(get_current_user_id)]
Db = Annotated[Session, Depends(get_db)]
Registry = Annotated[ModelRegistry, Depends(get_registry)]


# --- Request and response shapes ---------------------------------------------------


class ConversationCreate(BaseModel):
    model: str | None = None  # a model id from models.yaml; None = the chat default
    # SMA-49: "study" = answers come from these documents, with citations.
    mode: Literal["general", "study"] = "general"
    document_ids: Annotated[list[str], Field(max_length=20)] = []


class DocumentsChange(BaseModel):
    document_ids: Annotated[list[str], Field(max_length=20)]


class DocumentRef(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    filename: str


class CitationOut(BaseModel):
    """One source an answer cites (SMA-49): "[1] Physics.pdf, p.12" and the chunk itself."""

    n: int  # the number used in the answer: [1]
    chunk_id: str
    document_id: str
    filename: str
    page: int | None  # None for TXT / MD
    text: str


class ConversationRename(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class ConversationOut(BaseModel):
    # from_attributes: build it straight from a SQLAlchemy Conversation object.
    model_config = {"from_attributes": True}

    id: str
    title: str | None
    provider: str | None
    model: str | None
    mode: str = "general"  # SMA-49: "study" chats open on the Study page
    created_at: datetime
    updated_at: datetime


class StudyConversationOut(ConversationOut):
    documents: list[DocumentRef] = []  # SMA-49: what a study chat may search


class ToolCallOut(BaseModel):
    """One tool the AI used for an answer (SMA-42): "Used tool: create_task -> ..."."""

    name: str
    arguments: dict[str, Any] | str  # a string only if the AI sent broken JSON
    result: str  # what the tool sent back to the AI (shortened)
    is_error: bool
    duration_ms: int
    held: bool = False  # SMA-43: not run, waiting for the student's confirmation


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
    actions: list[ActionOut] = []  # SMA-43: confirmation cards and Undo buttons
    citations: list[CitationOut] | None = None  # SMA-49: a study answer's sources
    created_at: datetime


class ConversationDetail(StudyConversationOut):
    messages: list[MessageOut]


class SendMessage(BaseModel):
    # Checked by FastAPI before our code runs: too long or empty -> 422.
    message: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_MESSAGE_CHARS)
    ]
    model: str | None = None  # switch this conversation to another model
    provider: str | None = None  # optional cross-check: must match the model's provider
    allow_fallback: bool = True  # False: only the chosen model may answer (SMA-26)
    # SMA-49, study chats: "Answer from general knowledge" (no documents, labelled General).
    general: bool = False


class ChatReply(BaseModel):
    conversation_id: str
    message_id: str  # the saved answer: lets the page "Save as note" (SMA-32)
    reply: str
    provider: str  # who actually answered (may differ from the request after a fallback)
    model: str
    # "tool": the AI used MCP tools (SMA-42); "grounded": from the documents (SMA-49)
    mode: Literal["general", "tool", "grounded"] = MODE
    tool_calls: list[ToolCallOut] = []
    citations: list[CitationOut] = []  # SMA-49: empty on a grounded answer = not found
    actions: list[ActionOut] = []  # SMA-43: cards to confirm, creates to undo
    fallback_used: bool
    fallback_reason: str | None
    tokens_in: int
    tokens_out: int
    stopped: bool = False  # SMA-62: the student pressed Stop; `reply` is what arrived
    cached: bool = False  # SMA-67: the same study question was answered before: no AI call


# --- Conversations CRUD ------------------------------------------------------------


@router.get("", response_model=list[ConversationOut])
def list_conversations(user_id: CurrentUserId, db: Db) -> list[Conversation]:
    return repo.list_conversations(db, user_id)


@router.post("", response_model=StudyConversationOut, status_code=201)
def create_conversation(
    body: ConversationCreate, user_id: CurrentUserId, db: Db, registry: Registry
) -> Conversation:
    model = find_model(registry, body.model) if body.model else None
    conversation = repo.create_conversation(
        db,
        user_id,
        provider=model.provider if model else None,
        model=model.id if model else None,
        mode=body.mode,
        documents=my_documents(db, user_id, body.document_ids),
    )
    db.commit()
    return conversation


@router.put("/{conversation_id}/documents", response_model=StudyConversationOut)
def set_documents(
    conversation_id: str, body: DocumentsChange, user_id: CurrentUserId, db: Db
) -> Conversation:
    """Choose which documents a study chat may search (SMA-49)."""
    conversation = repo.with_documents(db, user_id, conversation_id)
    if conversation is None:
        raise HTTPException(404, "Conversation not found")
    if conversation.mode != "study":
        raise HTTPException(400, "Only a study chat has documents.")
    conversation.documents = my_documents(db, user_id, body.document_ids)
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


@dataclass
class Turn:
    """Everything one chat message needs, whichever way it is answered (SMA-62)."""

    user_id: str
    request: SendMessage
    model_id: str | None
    registry: ModelRegistry
    manager: FallbackManager
    settings: Settings
    embedder: Callable[[], EmbeddingProvider]
    stream: TextStream | None = None  # None: answer in one piece (JSON)
    on_tool: Callable[[ToolStep], None] | None = None
    token: Any = None  # the event loop's token, when called from a stream's own thread
    cache: AnswerCache | None = None  # SMA-67: answers to identical study questions


class AnswerCutOff(Exception):
    """A streamed answer failed halfway: what arrived was saved (as message_id)."""

    def __init__(self, message: str, message_id: str):
        super().__init__(message)
        self.message_id = message_id


@router.post(
    "/{conversation_id}/messages",
    response_model=ChatReply,
    # SMA-67: checked before anything else, so a 429 is never a broken stream.
    dependencies=[Depends(rate_limit("chat"))],
)
def send_message(
    conversation_id: str,
    request: SendMessage,
    http_request: Request,
    user_id: CurrentUserId,
    db: Db,
    registry: Registry,
    manager: Annotated[FallbackManager, Depends(get_fallback_manager)],
    settings: Annotated[Settings, Depends(get_settings)],
    embedder: Annotated[Callable[[], EmbeddingProvider], Depends(get_embedder)],
    cache: Annotated[AnswerCache, Depends(get_answer_cache)],
) -> ChatReply | StreamingResponse:
    # Checked first, so a wrong id or model is a normal 404/400, never a broken stream.
    conversation = my_conversation(db, user_id, conversation_id)
    model_id = choose_model(request, conversation, registry)
    turn = Turn(user_id, request, model_id, registry, manager, settings, embedder, cache=cache)
    if "text/event-stream" in http_request.headers.get("accept", ""):
        return stream_reply(http_request, conversation_id, turn)  # SMA-62
    return chat_turn(db, conversation, turn)


@router.post("/{conversation_id}/stop", status_code=202)
def stop_answer(conversation_id: str, user_id: CurrentUserId, db: Db) -> Response:
    """The Stop button (SMA-62): end the answer being written; what arrived is kept."""
    my_conversation(db, user_id, conversation_id)  # someone else's chat: 404
    if not chat_streams.stop(user_id, conversation_id):
        raise HTTPException(404, "No answer is being written in this chat.")
    return Response(status_code=202)


def stream_reply(http_request: Request, conversation_id: str, turn: Turn) -> StreamingResponse:
    """Answer as Server-Sent Events: token pieces, tool steps, then done (or error)."""
    switch = chat_streams.start(turn.user_id, conversation_id)

    def work(emit: chat_streams.Emit, token) -> None:  # runs in its own thread
        turn.stream = TextStream(
            on_text=lambda piece: emit("token", {"text": piece}), should_stop=switch.is_set
        )
        turn.on_tool = lambda step: emit("tool", tool_call_out(step).model_dump())
        turn.token = token
        try:
            # Its own session: the request's closes when the route returns, before this.
            with _session_factory(turn.settings.database_url)() as db:
                conversation = my_conversation(db, turn.user_id, conversation_id)
                reply = chat_turn(db, conversation, turn)
            emit("done", reply.model_dump(mode="json"))
        except AnswerCutOff as e:
            emit("error", error_event(503, str(e), e.message_id))
        except HTTPException as e:  # e.g. every model failed (503), a study problem (400)
            emit("error", error_event(e.status_code, str(e.detail)))
        except Exception:
            logger.exception("Streaming an answer failed")
            emit("error", error_event(500, "Something went wrong on our side."))
        finally:
            chat_streams.finish(turn.user_id, conversation_id, switch)

    return StreamingResponse(
        chat_streams.event_stream(http_request, work, switch),
        media_type="text/event-stream",
        # Don't let a proxy hold the events back to send them all at once.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def error_event(status: int, message: str, message_id: str | None = None) -> dict:
    """An error in the API's usual shape, plus the saved partial answer's id (if any)."""
    code = CODES_BY_STATUS.get(status, "error")
    return {"error": error_body(code, message), "message_id": message_id}


def finished_text(text: str, stopped: bool) -> str:
    """The answer as saved: a stopped one says so (shown again when the chat is reopened)."""
    return (text.rstrip() + STOPPED_NOTE).strip() if stopped else text


def chat_turn(db: Session, conversation: Conversation, turn: Turn) -> ChatReply:
    """Ask the AI and save the question and answer (one JSON reply, or streamed)."""
    request, model_id, registry = turn.request, turn.model_id, turn.registry
    user_id, conversation_id = turn.user_id, conversation.id
    if conversation.mode == "study" and not request.general:
        return study_answer(db, conversation, turn)
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
            context = ToolContext(
                user_id,
                _session_factory(turn.settings.database_url),
                make_embedder=turn.embedder,  # SMA-48: search_documents embeds the question
            )
            outcome = ask_with_tools(context, messages, turn, options)
        else:
            outcome = ask(messages, turn, options)
    except AllModelsFailedError as e:
        # Keep the record of the failed calls, but save no half-turn (no question alone).
        repo.log_llm_calls(db, user_id, conversation_id, e.attempts, call_mode(uses_tools))
        db.commit()
        raise HTTPException(503, f"The AI is unavailable right now ({e})") from e
    except AnswerInterruptedError as e:  # SMA-62: failed halfway through a streamed answer
        raise save_cut_off(db, conversation, turn, e, MODE, call_mode(uses_tools)) from e
    except LLMConfigError as e:  # e.g. the chosen model is disabled
        raise HTTPException(400, str(e)) from e
    answer = outcome.response
    tool_calls = [tool_call_out(step) for step in outcome.steps]
    mode = "tool" if tool_calls else MODE
    text = finished_text(answer.text, answer.stopped)  # SMA-62: "(Stopped)" if stopped

    # One transaction: the question, the answer and the call log are saved together, or
    # (if anything fails before commit) not at all.
    if request.model:  # the user switched models: remember it for this conversation
        conversation.provider, conversation.model = registry.get(model_id).provider, model_id
    repo.add_message(db, conversation, role="user", content=request.message)
    saved_answer = repo.add_message(
        db,
        conversation,
        role="assistant",
        content=text,
        provider=answer.provider,
        model=answer.model,
        mode=mode,
        fallback_used=outcome.fallback_used,
        tokens_in=outcome.tokens_in,
        tokens_out=outcome.tokens_out,
        tool_calls=[t.model_dump() for t in tool_calls] or None,
    )
    # SMA-43: held writes become confirmation cards; creates that ran can be undone.
    actions = record_actions(db, user_id, saved_answer, outcome.steps)
    repo.log_llm_calls(db, user_id, conversation_id, outcome.attempts, call_mode(uses_tools))
    db.commit()

    return ChatReply(
        conversation_id=conversation_id,
        message_id=saved_answer.id,
        reply=text,
        provider=answer.provider,
        model=answer.model,
        mode=mode,
        tool_calls=tool_calls,
        actions=[ActionOut.model_validate(a) for a in actions],
        fallback_used=outcome.fallback_used,
        fallback_reason=outcome.fallback_reason,
        tokens_in=outcome.tokens_in,
        tokens_out=outcome.tokens_out,
        stopped=answer.stopped,
    )


def save_cut_off(
    db: Session,
    conversation: Conversation,
    turn: Turn,
    error: AnswerInterruptedError,
    mode: str,
    log_mode: str,
) -> AnswerCutOff:
    """A streamed answer failed halfway (SMA-62): the student already read part of it, so
    save the question and that part, marked as cut off, plus the call log."""
    failed = error.attempts[-1] if error.attempts else None
    repo.add_message(db, conversation, role="user", content=turn.request.message)
    saved = repo.add_message(
        db,
        conversation,
        role="assistant",
        content=error.partial_text.rstrip() + CUT_OFF_NOTE,
        provider=failed.provider if failed else None,
        model=failed.model if failed else None,
        mode=mode,
        fallback_used=failed.fallback_used if failed else False,
    )
    repo.log_llm_calls(db, turn.user_id, conversation.id, error.attempts, log_mode)
    db.commit()
    return AnswerCutOff(str(error), saved.id)


# --- Study chats: answers from the documents (SMA-49) ---------------------------------


def study_answer(db: Session, conversation: Conversation, turn: Turn) -> ChatReply:
    """A study chat's answer: grounded in its documents, citations checked (study.py).
    Streamed (SMA-62): the text streams as written, then the check runs on the whole
    answer, and the `done` event carries the checked version."""
    user_id, request, model_id = turn.user_id, turn.request, turn.model_id
    history = [
        {"role": m.role, "content": m.content}
        for m in repo.recent_messages(db, user_id, conversation.id, MAX_HISTORY_MESSAGES)
    ]
    document_ids = repo.document_ids_of(db, conversation.id)
    # SMA-67: everything the answer depends on is in the key (see answer_cache.py).
    key = cache_key(
        user_id, document_ids, request.message, history, model_id, request.allow_fallback
    )
    if turn.cache is not None and (cached := turn.cache.get(key)) is not None:
        if turn.stream is not None:
            turn.stream.send(cached["text"])  # a cached answer arrives in one piece
        return save_study_reply(db, conversation, turn, cached, tokens=(0, 0), cached=True)
    try:
        answer = answer_from_documents(
            db,
            user_id,
            document_ids,
            request.message,
            history,
            turn.manager,
            model_id,
            request.allow_fallback,
            turn.embedder,
            stream=turn.stream,
        )
    except StudyError as e:
        raise HTTPException(e.status, e.message) from e
    except AllModelsFailedError as e:
        repo.log_llm_calls(db, user_id, conversation.id, e.attempts, "grounded")
        db.commit()
        raise HTTPException(503, f"The AI is unavailable right now ({e})") from e
    except AnswerInterruptedError as e:  # SMA-62
        raise save_cut_off(db, conversation, turn, e, "grounded", "grounded") from e
    except LLMConfigError as e:
        raise HTTPException(400, str(e)) from e

    stopped = answer.response.stopped
    result = {
        "text": finished_text(answer.text, stopped),
        "citations": answer.citations,  # [] = "Not found in your documents"
        "provider": answer.response.provider,
        "model": answer.response.model,
        "fallback_used": answer.fallback_used,
        "fallback_reason": answer.fallback_reason,
    }
    repo.log_llm_calls(db, user_id, conversation.id, answer.attempts, "grounded")
    if turn.cache is not None and not stopped:  # half an answer is never reused
        turn.cache.put(key, result)
    return save_study_reply(
        db, conversation, turn, result, (answer.tokens_in, answer.tokens_out), stopped=stopped
    )


def save_study_reply(
    db: Session,
    conversation: Conversation,
    turn: Turn,
    result: dict[str, Any],
    tokens: tuple[int, int],
    stopped: bool = False,
    cached: bool = False,
) -> ChatReply:
    """Save the question and its study answer (new or from the cache), and reply."""
    if turn.request.model:  # the user switched models: remember it for this conversation
        conversation.provider = turn.registry.get(turn.model_id).provider
        conversation.model = turn.model_id
    repo.add_message(db, conversation, role="user", content=turn.request.message)
    saved = repo.add_message(
        db,
        conversation,
        role="assistant",
        content=result["text"],
        provider=result["provider"],
        model=result["model"],
        mode="grounded",
        fallback_used=result["fallback_used"],
        tokens_in=tokens[0],
        tokens_out=tokens[1],
        citations=result["citations"],
    )
    db.commit()
    return ChatReply(
        conversation_id=conversation.id,
        message_id=saved.id,
        reply=result["text"],
        provider=result["provider"],
        model=result["model"],
        mode="grounded",
        citations=[CitationOut(**c) for c in result["citations"]],
        fallback_used=result["fallback_used"],
        fallback_reason=result["fallback_reason"],
        tokens_in=tokens[0],
        tokens_out=tokens[1],
        stopped=stopped,
        cached=cached,
    )


def my_documents(db: Session, user_id: str, document_ids: list[str]):
    """The user's own documents, or 404 (also when one is someone else's: reveals nothing)."""
    documents = repo.my_documents(db, user_id, document_ids)
    if documents is None:
        raise HTTPException(404, "Document not found")
    return documents


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


def ask(messages: list[Message], turn: Turn, options) -> Outcome:
    result = turn.manager.chat(
        messages,
        options,
        turn.model_id,
        allow_fallback=turn.request.allow_fallback,
        stream=turn.stream,
    )
    answer = result.response
    return Outcome(
        answer,
        result.fallback_used,
        result.fallback_reason,
        result.attempts,
        answer.tokens_in,
        answer.tokens_out,
    )


def ask_with_tools(context: ToolContext, messages: list[Message], turn: Turn, options) -> Outcome:
    """The agent loop (SMA-42). This runs in a worker thread: from_thread.run runs the
    async loop on the app's event loop and waits for it. A streamed answer's own thread
    passes the loop's token (SMA-62); the route's thread pool doesn't need one."""
    run = anyio.from_thread.run(
        functools.partial(
            run_agent_for_user,
            context,
            turn.manager,
            messages,
            turn.model_id,
            turn.request.allow_fallback,
            options,
            # SMA-43: only the student's OWN message can ask for a write (not notes,
            # documents or tool results: those reach the model, never this check).
            user_asked_to_act=asks_to_act(turn.request.message),
            stream=turn.stream,
            on_tool=turn.on_tool,
        ),
        token=turn.token,
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
        held=step.held,
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
