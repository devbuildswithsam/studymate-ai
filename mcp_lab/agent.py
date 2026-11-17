"""A minimal AI agent loop over MCP (Stage 3a, SMA-39).

The AI never runs anything itself. It only *asks*: "call add_task with these arguments".
We run that call through the MCP session, send the result back, and repeat until the AI
answers without asking for a tool (the final answer) or MAX_TOOL_CALLS calls are used.

The AI is Gemini or Groq through the OpenAI-compatible API. Model ids come only from
backend/app/services/llm/models.yaml, API keys only from backend/.env (never printed).
"""

import json
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Protocol

import anyio
import openai
import yaml
from dotenv import dotenv_values

BACKEND = Path(__file__).resolve().parents[1] / "backend"
MAX_TOOL_CALLS = 5  # a stop condition: never let the AI loop forever
SYSTEM_PROMPT = (
    "You help a student manage their study tasks using the tools provided. "
    "Today is {today} ({weekday}). Use the tools when needed; when you are done, "
    "answer briefly in plain sentences."
)


# --- What the AI sends back -----------------------------------------------------------


@dataclass(frozen=True)
class ToolCall:
    id: str  # every result we send back must carry this id
    name: str
    arguments: str  # JSON text, exactly as the AI wrote it (it may be broken)
    # Provider-specific fields outside the OpenAI format, sent back unchanged. Gemini's
    # thinking models need their "thought_signature" (in extra_content) back, or 400.
    extra: dict[str, Any] | None = None

    def as_message_part(self) -> dict[str, Any]:
        """This call as it goes back into the history (assistant message)."""
        part = {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": self.arguments},
        }
        return {**part, **(self.extra or {})}


STANDARD_TOOL_CALL_FIELDS = {"id", "type", "function", "index"}


@dataclass
class AssistantTurn:
    text: str | None
    tool_calls: list[ToolCall]  # empty = a final answer


class LLM(Protocol):
    """Anything that can answer messages, optionally asking for tools (tests: a fake)."""

    def complete(self, messages: list[dict], tools: list[dict]) -> AssistantTurn: ...


# --- The loop -------------------------------------------------------------------------


@dataclass
class AgentStep:
    tool: str
    arguments: str
    result: str
    is_error: bool


@dataclass
class AgentResult:
    answer: str | None
    steps: list[AgentStep] = field(default_factory=list)
    stopped_early: bool = False  # True when MAX_TOOL_CALLS was reached


def to_openai_tools(mcp_tools) -> list[dict]:
    """MCP tools -> the 'functions' format the chat API expects. The schema is unchanged."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.input_schema,
            },
        }
        for tool in mcp_tools
    ]


async def run_agent(
    session, llm: LLM, question: str, today: date | None = None, max_tool_calls=MAX_TOOL_CALLS
) -> AgentResult:
    """session: an MCP client session (list_tools / call_tool)."""
    today = today or date.today()
    tools = to_openai_tools((await session.list_tools()).tools)
    system = SYSTEM_PROMPT.format(today=today.isoformat(), weekday=today.strftime("%A"))
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": question},
    ]
    steps: list[AgentStep] = []

    while True:
        # The API call blocks for a while: run it in a thread so MCP keeps working.
        turn = await anyio.to_thread.run_sync(llm.complete, messages, tools)
        if not turn.tool_calls:
            return AgentResult(turn.text, steps)  # stop condition 1: a final answer

        # The AI's request goes into the history first, then one result per call.
        messages.append(
            {
                "role": "assistant",
                "content": turn.text,
                "tool_calls": [c.as_message_part() for c in turn.tool_calls],
            }
        )
        for tool_call in turn.tool_calls:
            if len(steps) >= max_tool_calls:  # stop condition 2: the limit
                answer = f"Stopped after {max_tool_calls} tool calls without a final answer."
                return AgentResult(answer, steps, stopped_early=True)
            result, is_error = await run_tool(session, tool_call)
            steps.append(AgentStep(tool_call.name, tool_call.arguments, result, is_error))
            messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result})


async def run_tool(session, tool_call: ToolCall) -> tuple[str, bool]:
    """Run one call through MCP. Mistakes become error text for the AI, never crashes."""
    try:
        arguments = json.loads(tool_call.arguments or "{}")
    except json.JSONDecodeError:
        return f"Error: the arguments were not valid JSON: {tool_call.arguments!r}", True
    if not isinstance(arguments, dict):
        return 'Error: the arguments must be a JSON object, like {"title": "..."}', True
    result = await session.call_tool(tool_call.name, arguments)
    if result.structured_content is not None and not result.is_error:
        # The structured JSON is always clear, e.g. {"result": []} for "no tasks". The
        # text content of an empty list has no parts at all: the AI would get "".
        return json.dumps(result.structured_content), False
    text = "\n".join(part.text for part in result.content if getattr(part, "text", None))
    return text, bool(result.is_error)


# --- The real AI ----------------------------------------------------------------------


class OpenAICompatibleLLM:
    """Gemini or Groq through the OpenAI-compatible chat API, with tools."""

    def __init__(self, client: openai.OpenAI, model: str):
        self.client, self.model = client, model

    def complete(self, messages: list[dict], tools: list[dict]) -> AssistantTurn:
        response = self.client.chat.completions.create(
            model=self.model, messages=messages, tools=tools, max_tokens=1024
        )
        message = response.choices[0].message
        calls = []
        for c in message.tool_calls or []:
            raw = c.model_dump(exclude_none=True)  # includes fields the SDK doesn't know
            extra = {k: v for k, v in raw.items() if k not in STANDARD_TOOL_CALL_FIELDS}
            calls.append(ToolCall(c.id, c.function.name, c.function.arguments, extra=extra or None))
        return AssistantTurn(text=message.content, tool_calls=calls)


def llm_from_registry(
    model_id: str | None = None,
    registry_path: Path = BACKEND / "app" / "services" / "llm" / "models.yaml",
    env_path: Path = BACKEND / ".env",
) -> OpenAICompatibleLLM:
    """The model from models.yaml (default: the chat default), with its key from .env."""
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    models = {m["id"]: m for m in registry["models"]}
    if model_id is None:
        model_id = next(m["id"] for m in models.values() if "chat" in m["default_for"])
    if model_id not in models:
        raise ValueError(f"Unknown model {model_id!r}: see models.yaml")
    model = models[model_id]
    if not model["enabled"]:
        raise ValueError(f"Model {model_id!r} is disabled in models.yaml")
    if model["supports_tools"] is not True:
        raise ValueError(f"Model {model_id!r} can't call tools (models.yaml)")

    provider = registry["providers"][model["provider"]]
    key_name = provider["api_key_env"]
    api_key = dotenv_values(env_path).get(key_name) or os.environ.get(key_name)
    if not api_key:
        raise ValueError(f"{key_name} is not set in backend/.env")
    client = openai.OpenAI(base_url=provider["base_url"], api_key=api_key, timeout=120)
    return OpenAICompatibleLLM(client, model_id)
