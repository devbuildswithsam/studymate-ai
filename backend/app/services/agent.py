"""The chat's agent loop (guide 7.2 "The agent loop"). SMA-42, from the SMA-39 lab.

The model never runs anything itself: it *asks* for a tool call. We run it through the
app's MCP server (an in-memory MCP session acting for the signed-in user, SMA-41), send
the result back, and repeat until the model answers without asking for a tool, or after
MAX_TOOL_CALLS calls.

SMA-43: before running a write, the write-action policy (tool_policy.py) decides. A held
call is NOT run: it becomes a confirmation card, and the model is told it is waiting.
"""

import functools
import json
import time
from dataclasses import dataclass, field
from typing import Any

import anyio
from mcp import Client
from mcp.shared.exceptions import MCPError

from app.mcp_server.context import ToolContext, acting_as
from app.mcp_server.server import TOOL_KINDS, mcp_server
from app.services.llm.base import ChatOptions, ChatResponse, Message, ToolCall
from app.services.llm.exceptions import AllModelsFailedError
from app.services.llm.fallback import Attempt, ChatResult, FallbackManager
from app.services.tool_policy import decide

MAX_TOOL_CALLS = 5  # per user message (guide 7.2): never let a model loop forever

# What the model is told about a held call. It must not retry or claim it's done.
HELD_RESULT = (
    "Not done yet: this needs the student's confirmation. The app shows it to them as a "
    "card with Confirm and Cancel buttons. Tell them to confirm it there; don't call it again."
)


@dataclass
class ToolStep:
    """One tool call, as saved in messages.tool_calls and shown under the answer."""

    name: str
    arguments: str  # JSON text, as the model wrote it
    result: str  # what the model was sent back
    is_error: bool
    duration_ms: int
    held: bool = False  # SMA-43: not run, waiting for the student's Confirm click


@dataclass
class AgentRun:
    response: ChatResponse  # the final answer
    fallback_used: bool
    fallback_reason: str | None
    steps: list[ToolStep] = field(default_factory=list)
    attempts: list[Attempt] = field(default_factory=list)  # every model call, every turn
    tokens_in: int = 0  # summed over every turn
    tokens_out: int = 0
    stopped_early: bool = False


def to_openai_tools(mcp_tools) -> list[dict[str, Any]]:
    """MCP tools -> the chat API's "functions" format. The JSON Schema is unchanged."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description or "",
                "parameters": t.input_schema,
            },
        }
        for t in mcp_tools
    ]


async def run_agent(
    manager: FallbackManager,
    session,  # an MCP client session on the app's server, acting for the user
    messages: list[Message],
    model_id: str | None,
    allow_fallback: bool,
    options: ChatOptions,
    max_tool_calls: int = MAX_TOOL_CALLS,
    user_asked_to_act: bool = False,  # SMA-43: from the student's own message only
) -> AgentRun:
    mcp_tools = (await session.list_tools()).tools
    schemas = {t.name: t.input_schema for t in mcp_tools}
    tools = to_openai_tools(mcp_tools)
    options = ChatOptions(**{**options.__dict__, "tools": tools})
    messages = list(messages)  # we append to it: never change the caller's list
    steps: list[ToolStep] = []
    attempts: list[Attempt] = []
    tokens_in = tokens_out = 0
    first: ChatResult | None = None

    while True:
        try:
            result = await anyio.to_thread.run_sync(
                functools.partial(
                    manager.chat,
                    messages,
                    options,
                    model_id,
                    needs=("tools",),  # never fall back to a model that can't call tools
                    allow_fallback=allow_fallback,
                )
            )
        except AllModelsFailedError as e:
            e.attempts = attempts + e.attempts  # so every call of every turn gets logged
            raise
        attempts += result.attempts
        tokens_in += result.response.tokens_in
        tokens_out += result.response.tokens_out
        if first is None:
            first = result
            # Stay on the model that answered: provider extras (Gemini's thought
            # signatures) in the history only make sense to that provider.
            model_id = next(a.model for a in reversed(result.attempts) if a.status == "ok")
            allow_fallback = False

        run = AgentRun(
            result.response,
            first.fallback_used,
            first.fallback_reason,
            steps,
            attempts,
            tokens_in,
            tokens_out,
        )
        if not result.response.tool_calls:
            return run  # stop condition 1: a final answer

        messages.append(
            {
                "role": "assistant",
                "content": result.response.text or None,
                "tool_calls": [c.as_message_part() for c in result.response.tool_calls],
            }
        )
        for tool_call in result.response.tool_calls:
            if len(steps) >= max_tool_calls:  # stop condition 2: the limit
                run.response = ChatResponse(
                    text=f"I stopped after {max_tool_calls} tool calls without finishing. "
                    "Please try a smaller request.",
                    tokens_in=0,
                    tokens_out=0,
                    model=result.response.model,
                    provider=result.response.provider,
                    latency_ms=0,
                )
                run.stopped_early = True
                return run
            step = await run_tool(session, tool_call, schemas, user_asked_to_act)
            steps.append(step)
            messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": step.result})


async def run_tool(
    session, tool_call: ToolCall, schemas: dict[str, dict], user_asked_to_act: bool
) -> ToolStep:
    """Run one call through MCP, if the policy allows it. Mistakes become error text for
    the model, never crashes."""
    started = time.perf_counter()

    def step(result: str, is_error: bool) -> ToolStep:
        duration_ms = round((time.perf_counter() - started) * 1000)
        return ToolStep(tool_call.name, tool_call.arguments, result, is_error, duration_ms)

    try:
        arguments = json.loads(tool_call.arguments or "{}")
    except json.JSONDecodeError:
        return step(f"Error: the arguments were not valid JSON: {tool_call.arguments!r}", True)
    if not isinstance(arguments, dict):
        return step('Error: the arguments must be a JSON object, like {"title": "..."}', True)
    if tool_call.name in TOOL_KINDS:
        # Checked BEFORE holding: a card must never carry an argument like user_id.
        unknown = sorted(set(arguments) - set(schemas[tool_call.name].get("properties", {})))
        if unknown:
            return step(f"Error: unknown argument(s) for {tool_call.name}: {unknown}", True)
        if decide(TOOL_KINDS[tool_call.name], user_asked_to_act) == "hold":
            held = step(HELD_RESULT, False)
            held.held = True
            return held
    try:
        result = await session.call_tool(tool_call.name, arguments)
    except MCPError as e:  # e.g. an injected user_id (RejectUnknownArguments, SMA-41)
        return step(f"Error: {e.error.message}", True)
    if result.structured_content is not None and not result.is_error:
        # Structured JSON is always clear: an empty list's text content has no parts.
        return step(json.dumps(result.structured_content), False)
    text = "\n".join(part.text for part in result.content if getattr(part, "text", None))
    return step(text, bool(result.is_error))


async def run_agent_for_user(
    context: ToolContext,
    manager: FallbackManager,
    messages: list[Message],
    model_id: str | None,
    allow_fallback: bool,
    options: ChatOptions,
    user_asked_to_act: bool = False,
) -> AgentRun:
    """Run the loop with the app's own MCP tools, acting for this user (SMA-41 context).

    The tools are reached through an in-memory MCP session: the same server as /mcp, no
    HTTP. Errors are raised AFTER the session has closed: raised inside it, they would come
    out wrapped in an ExceptionGroup (checked in SMA-42) and the route couldn't catch them.
    """
    failure: Exception | None = None
    with acting_as(context):  # set and reset in this one function (same context)
        async with Client(mcp_server) as session:
            try:
                return await run_agent(
                    manager,
                    session,
                    messages,
                    model_id,
                    allow_fallback,
                    options,
                    user_asked_to_act=user_asked_to_act,
                )
            except Exception as e:
                failure = e
    raise failure
