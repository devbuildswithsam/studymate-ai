"""POST /api/chat: general chat with the AI. SMA-23.

The route never talks to Gemini or Groq directly: it asks the FallbackManager (SMA-22),
which picks the model, falls back if needed and labels the answer.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, StringConstraints

from app.api.deps import get_current_user_id
from app.services.chat_history import ConversationStore, get_conversation_store
from app.services.llm.base import ChatOptions
from app.services.llm.exceptions import AllModelsFailedError, LLMConfigError
from app.services.llm.fallback import FallbackManager, get_fallback_manager
from app.services.llm.registry import ModelRegistry, get_registry

router = APIRouter(prefix="/api", tags=["chat"])

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


class ChatRequest(BaseModel):
    # Checked by FastAPI before our code runs: too long or empty -> 422.
    message: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_MESSAGE_CHARS)
    ]
    conversation_id: str | None = None  # None = start a new conversation
    model: str | None = None  # a model id from models.yaml; None = the chat default
    provider: str | None = None  # optional cross-check: must match the model's provider


class ChatReply(BaseModel):
    conversation_id: str
    reply: str
    provider: str  # who actually answered (may differ from the request after a fallback)
    model: str
    mode: Literal["general"] = "general"  # later: "grounded" (documents), "tool" (MCP)
    fallback_used: bool
    fallback_reason: str | None
    tokens_in: int
    tokens_out: int


@router.post("/chat", response_model=ChatReply)
def chat(
    request: ChatRequest,
    manager: Annotated[FallbackManager, Depends(get_fallback_manager)],
    store: Annotated[ConversationStore, Depends(get_conversation_store)],
    registry: Annotated[ModelRegistry, Depends(get_registry)],
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> ChatReply:
    model_id = choose_model(request, registry)

    # The store keeps the whole conversation; only the recent part is sent to the model.
    history = []
    if request.conversation_id:
        try:
            history = store.messages(user_id, request.conversation_id)[-MAX_HISTORY_MESSAGES:]
        except KeyError:
            # Same answer for "doesn't exist" and "someone else's": reveals nothing.
            raise HTTPException(404, "Conversation not found") from None
    question = {"role": "user", "content": request.message}

    # The model has no memory of its own: every call sends the conversation so far.
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *history, question]
    try:
        result = manager.chat(messages, ChatOptions(max_tokens=MAX_OUTPUT_TOKENS), model_id)
    except AllModelsFailedError as e:
        raise HTTPException(503, f"The AI is unavailable right now ({e})") from e
    except LLMConfigError as e:  # e.g. the chosen model is disabled
        raise HTTPException(400, str(e)) from e
    answer = result.response

    # Save the turn only once the AI has answered, so a failed call leaves no half-turn
    # (and a new conversation is only created when it has something in it).
    conversation_id = request.conversation_id or store.create(user_id)
    store.append(user_id, conversation_id, question, {"role": "assistant", "content": answer.text})
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


def choose_model(request: ChatRequest, registry: ModelRegistry) -> str | None:
    """The model id to try first. 400 if it's unknown or doesn't match `provider`."""
    model_id = request.model or registry.default_model("chat")
    if model_id is None:
        return None  # no chat default: the manager uses the first enabled model
    try:
        model = registry.get(model_id)
    except KeyError:
        raise HTTPException(400, f"Unknown model {model_id!r}: see GET /api/models") from None
    if request.provider and request.provider != model.provider:
        raise HTTPException(
            400,
            f"Model {model_id!r} belongs to provider {model.provider!r}, not {request.provider!r}",
        )
    return model_id
