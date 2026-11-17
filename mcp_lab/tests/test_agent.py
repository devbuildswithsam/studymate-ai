"""The agent loop: an AI picks MCP tools, we run them, results go back. SMA-39.

The AI is always a FakeLLM with a script (CLAUDE.md: tests never call real APIs). The MCP
side is the real lab server, in memory (mcp.Client), on a temporary lab.db.
"""

import json
from datetime import date

import agent
import httpx2
import openai
import pytest
import server
from mcp import Client

TODAY = date(2026, 11, 17)  # a Tuesday


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def lab_db(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DB_PATH", tmp_path / "lab.db")
    monkeypatch.setattr(server, "today", lambda: TODAY)


class FakeLLM:
    """Answers with scripted turns, and records what it was sent each time."""

    def __init__(self, *turns: agent.AssistantTurn):
        self.turns = list(turns)
        self.received: list[list[dict]] = []  # the messages of each call
        self.tools: list[list[dict]] = []

    def complete(self, messages, tools):
        self.received.append(json.loads(json.dumps(messages)))  # a snapshot
        self.tools.append(tools)
        return self.turns.pop(0) if len(self.turns) > 1 else self.turns[0]


def call(name: str, arguments: dict | str, call_id: str = "") -> agent.ToolCall:
    text = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return agent.ToolCall(id=call_id or f"call_{name}", name=name, arguments=text)


def tools_turn(*calls: agent.ToolCall) -> agent.AssistantTurn:
    return agent.AssistantTurn(text=None, tool_calls=list(calls))


def final(text: str) -> agent.AssistantTurn:
    return agent.AssistantTurn(text=text, tool_calls=[])


async def run(llm: FakeLLM, question: str, **kwargs) -> agent.AgentResult:
    async with Client(server.mcp) as session:
        return await agent.run_agent(session, llm, question, today=TODAY, **kwargs)


async def pending_titles() -> list[str]:
    async with Client(server.mcp) as session:
        result = await session.call_tool("list_tasks", {})
    return [t["title"] for t in result.structured_content["result"]]


# --- The MCP tool list, in the format the AI APIs expect ------------------------------


@pytest.mark.anyio
async def test_mcp_tools_are_offered_to_the_ai_as_functions():
    async with Client(server.mcp) as session:
        mcp_tools = (await session.list_tools()).tools

    functions = agent.to_openai_tools(mcp_tools)

    by_name = {f["function"]["name"]: f for f in functions}
    assert set(by_name) == {"add_task", "list_tasks", "complete_task"}
    add = by_name["add_task"]
    assert add["type"] == "function"
    assert add["function"]["description"].startswith("Add a study task")
    assert add["function"]["parameters"] == next(
        t.input_schema for t in mcp_tools if t.name == "add_task"
    )  # the MCP JSON Schema, unchanged


# --- Done when: "add a task for tomorrow and list my tasks" -------------------------


@pytest.mark.anyio
async def test_add_a_task_for_tomorrow_and_list_my_tasks():
    llm = FakeLLM(
        tools_turn(call("add_task", {"title": "Revise thermodynamics", "due_date": "2026-11-18"})),
        tools_turn(call("list_tasks", {})),
        final("Added it. You have 1 pending task: Revise thermodynamics (due tomorrow)."),
    )

    result = await run(llm, "add a task for tomorrow and list my tasks")

    assert result.answer.startswith("Added it.")
    assert result.stopped_early is False
    assert [s.tool for s in result.steps] == ["add_task", "list_tasks"]
    assert not any(s.is_error for s in result.steps)
    assert await pending_titles() == ["Revise thermodynamics"]


@pytest.mark.anyio
async def test_the_ai_knows_today_so_it_can_work_out_tomorrow():
    llm = FakeLLM(final("ok"))

    await run(llm, "add a task for tomorrow")

    system = llm.received[0][0]
    assert system["role"] == "system"
    assert "2026-11-17" in system["content"] and "Tuesday" in system["content"]


@pytest.mark.anyio
async def test_each_result_goes_back_with_the_id_of_its_call():
    llm = FakeLLM(
        tools_turn(call("add_task", {"title": "Read ch. 3"}, call_id="call_A")),
        final("Done."),
    )

    await run(llm, "add read ch. 3")

    second = llm.received[1]  # what the AI saw on its second turn
    assistant, tool_result = second[-2], second[-1]
    assert assistant["role"] == "assistant"
    assert assistant["tool_calls"][0]["id"] == "call_A"
    assert assistant["tool_calls"][0]["function"]["name"] == "add_task"
    assert tool_result["role"] == "tool"
    assert tool_result["tool_call_id"] == "call_A"
    assert json.loads(tool_result["content"])["title"] == "Read ch. 3"


@pytest.mark.anyio
async def test_several_tool_calls_in_one_turn_run_in_order():
    # Gemini asks for both tools at once (seen in the SMA-39 probe).
    llm = FakeLLM(
        tools_turn(
            call("add_task", {"title": "Lab report"}, call_id="c1"),
            call("list_tasks", {}, call_id="c2"),
        ),
        final("Done."),
    )

    result = await run(llm, "add lab report and list")

    assert [s.tool for s in result.steps] == ["add_task", "list_tasks"]
    listed = json.loads(llm.received[1][-1]["content"])  # list_tasks ran after add_task
    assert [t["title"] for t in listed["result"]] == ["Lab report"]


@pytest.mark.anyio
async def test_every_lab_tool_works_through_the_agent():
    llm = FakeLLM(
        tools_turn(call("add_task", {"title": "Flashcards", "priority": "high"})),
        tools_turn(call("complete_task", {"task_id": 1})),
        tools_turn(call("list_tasks", {"status": "done"})),
        final("Flashcards is done."),
    )

    result = await run(llm, "add flashcards, complete it, show done tasks")

    assert [s.tool for s in result.steps] == ["add_task", "complete_task", "list_tasks"]
    assert not any(s.is_error for s in result.steps)
    assert await pending_titles() == []


# --- Mistakes the AI makes are sent back to it, not crashes --------------------------


@pytest.mark.anyio
async def test_an_invalid_argument_is_rejected_and_the_ai_can_correct_it():
    llm = FakeLLM(
        tools_turn(call("add_task", {"title": "Essay", "priority": "urgent"}, call_id="bad")),
        tools_turn(call("add_task", {"title": "Essay", "priority": "high"}, call_id="good")),
        final("Added Essay with high priority."),
    )

    result = await run(llm, "add an urgent essay task")

    assert [s.is_error for s in result.steps] == [True, False]
    error_sent_back = llm.received[1][-1]
    assert error_sent_back["tool_call_id"] == "bad"
    assert "priority" in error_sent_back["content"]  # the AI can see what was wrong
    assert await pending_titles() == ["Essay"]  # only the corrected call saved anything


@pytest.mark.anyio
@pytest.mark.parametrize(
    "bad_call, expected",
    [
        (call("add_task", "{not json"), "not valid JSON"),
        (call("add_task", '["a", "list"]'), "JSON object"),
        (call("delete_everything", {}), "delete_everything"),
    ],
    ids=["broken JSON", "not an object", "unknown tool"],
)
async def test_broken_tool_calls_become_error_results(bad_call, expected):
    llm = FakeLLM(tools_turn(bad_call), final("Sorry, that didn't work."))

    result = await run(llm, "do something")

    assert result.steps[0].is_error
    assert expected in llm.received[1][-1]["content"]
    assert result.answer == "Sorry, that didn't work."


# --- Stop conditions -----------------------------------------------------------------


@pytest.mark.anyio
async def test_the_loop_stops_after_5_tool_calls():
    looping = FakeLLM(tools_turn(call("list_tasks", {})))  # never gives a final answer

    result = await run(looping, "list my tasks forever")

    assert len(result.steps) == agent.MAX_TOOL_CALLS == 5
    assert result.stopped_early is True
    assert "5 tool calls" in result.answer


@pytest.mark.anyio
async def test_the_limit_also_counts_calls_inside_one_turn():
    burst = FakeLLM(tools_turn(*[call("list_tasks", {}, call_id=f"c{n}") for n in range(8)]))

    result = await run(burst, "list a lot")

    assert len(result.steps) == 5
    assert result.stopped_early is True


@pytest.mark.anyio
async def test_a_final_answer_without_tools_stops_at_once():
    llm = FakeLLM(final("Hi! I can manage your study tasks."))

    result = await run(llm, "hello")

    assert result.steps == []
    assert result.answer == "Hi! I can manage your study tasks."
    assert len(llm.received) == 1


# --- The real AI: chosen from models.yaml, called through the OpenAI-compatible API --


REGISTRY_YAML = """
version: 1
providers:
  gemini: {base_url: "https://g.test/v1/", api_key_env: GEMINI_API_KEY}
  groq: {base_url: "https://q.test/v1/", api_key_env: GROQ_API_KEY}
models:
  - {id: main-model, provider: gemini, display_name: Main, priority: 1,
     supports_tools: true, supports_json: true, default_for: [chat], enabled: true}
  - {id: backup-model, provider: groq, display_name: Backup, priority: 2,
     supports_tools: true, supports_json: true, default_for: [], enabled: true}
  - {id: no-tools-model, provider: groq, display_name: No tools, priority: 3,
     supports_tools: false, supports_json: true, default_for: [], enabled: true}
  - {id: off-model, provider: groq, display_name: Off, priority: 4,
     supports_tools: true, supports_json: true, default_for: [], enabled: false}
"""


@pytest.fixture
def registry_files(tmp_path):
    registry = tmp_path / "models.yaml"
    registry.write_text(REGISTRY_YAML, encoding="utf-8")
    env = tmp_path / ".env"
    env.write_text("GEMINI_API_KEY=fake-gemini-key\nGROQ_API_KEY=fake-groq-key\n", encoding="utf-8")
    return registry, env


def test_the_chat_default_model_is_used_unless_another_is_chosen(registry_files):
    registry, env = registry_files

    default = agent.llm_from_registry(registry_path=registry, env_path=env)
    backup = agent.llm_from_registry("backup-model", registry_path=registry, env_path=env)

    assert (default.model, str(default.client.base_url)) == ("main-model", "https://g.test/v1/")
    assert (backup.model, str(backup.client.base_url)) == ("backup-model", "https://q.test/v1/")


@pytest.mark.parametrize(
    "model_id, problem",
    [
        ("gpt-99", "Unknown model"),
        ("no-tools-model", "can't call tools"),
        ("off-model", "disabled"),
    ],
)
def test_unusable_models_are_refused_clearly(registry_files, model_id, problem):
    registry, env = registry_files

    with pytest.raises(ValueError, match=problem):
        agent.llm_from_registry(model_id, registry_path=registry, env_path=env)


def test_a_missing_key_is_named_but_never_shown(registry_files, monkeypatch):
    registry, _ = registry_files
    empty_env = registry.with_name("empty.env")
    empty_env.write_text("", encoding="utf-8")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(ValueError, match="GEMINI_API_KEY is not set"):
        agent.llm_from_registry(registry_path=registry, env_path=empty_env)


def test_the_real_llm_sends_the_tools_and_reads_tool_calls(registry_files):
    sent = {}

    def fake_api(request: httpx2.Request) -> httpx2.Response:
        sent.update(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 0,
                "model": "main-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "list_tasks", "arguments": "{}"},
                                }
                            ],
                        },
                    }
                ],
            },
        )

    client = openai.OpenAI(
        base_url="https://g.test/v1/",
        api_key="fake",
        http_client=httpx2.Client(transport=httpx2.MockTransport(fake_api)),
    )
    llm = agent.OpenAICompatibleLLM(client, "main-model")
    tools = [{"type": "function", "function": {"name": "list_tasks", "parameters": {}}}]

    turn = llm.complete([{"role": "user", "content": "list"}], tools)

    assert sent["model"] == "main-model"
    assert sent["tools"] == tools
    assert turn.tool_calls == [agent.ToolCall(id="call_1", name="list_tasks", arguments="{}")]


@pytest.mark.anyio
async def test_an_empty_list_reaches_the_ai_as_an_empty_list_not_as_nothing():
    # The text content of an empty list has no parts at all: "" would be ambiguous.
    llm = FakeLLM(tools_turn(call("list_tasks", {})), final("You have no tasks."))

    result = await run(llm, "list my tasks")

    assert json.loads(llm.received[1][-1]["content"]) == {"result": []}
    assert result.steps[0].result == '{"result": []}'


def test_the_agent_runs_from_the_terminal(tmp_path, monkeypatch, capsys):
    import client

    fake = FakeLLM(
        tools_turn(call("add_task", {"title": "Revise thermodynamics", "due_date": "2026-11-18"})),
        tools_turn(call("list_tasks", {})),
        final("Added. You have 1 pending task."),
    )
    chosen = []
    monkeypatch.setattr(
        client.agent, "llm_from_registry", lambda model_id=None: chosen.append(model_id) or fake
    )

    client.main(
        ["--db", str(tmp_path / "lab.db"), "--agent", "add a task for tomorrow", "--model", "m2"]
    )

    out = capsys.readouterr().out
    assert chosen == ["m2"]
    assert "Tool call 1: add_task" in out
    assert "Tool call 2: list_tasks" in out
    assert "Answer: Added. You have 1 pending task." in out


# --- Found in the real terminal run (SMA-39) ------------------------------------------

GEMINI_EXTRA = {"google": {"thought_signature": "EpQDCpEDAWkUfRM75tP3"}}


def test_extra_provider_data_on_a_tool_call_is_kept():
    # Gemini's thinking models put a "thought_signature" in extra_content on each call.
    def fake_api(request: httpx2.Request) -> httpx2.Response:
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "list_tasks", "arguments": "{}"},
                    "extra_content": GEMINI_EXTRA,
                }
            ],
        }
        return httpx2.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 0,
                "model": "m",
                "choices": [{"index": 0, "finish_reason": "tool_calls", "message": message}],
            },
        )

    client = openai.OpenAI(
        base_url="https://g.test/v1/",
        api_key="fake",
        http_client=httpx2.Client(transport=httpx2.MockTransport(fake_api)),
    )

    turn = agent.OpenAICompatibleLLM(client, "m").complete([], [])

    assert turn.tool_calls[0].extra == {"extra_content": GEMINI_EXTRA}


@pytest.mark.anyio
async def test_extra_provider_data_is_sent_back_unchanged_with_the_call():
    # Gemini answers 400 "Function call is missing a thought_signature" otherwise.
    gemini_call = agent.ToolCall(
        id="c1", name="list_tasks", arguments="{}", extra={"extra_content": GEMINI_EXTRA}
    )
    llm = FakeLLM(tools_turn(gemini_call), final("No tasks."))

    await run(llm, "list my tasks")

    sent_back = llm.received[1][-2]["tool_calls"][0]
    assert sent_back["extra_content"] == GEMINI_EXTRA
    assert sent_back["id"] == "c1"


def test_answers_with_characters_the_console_cannot_show_do_not_crash(monkeypatch):
    # Windows' console (cp1252) can't print e.g. a narrow no-break space (U+202F).
    import io

    import client

    console = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr("sys.stdout", console)
    client.make_stdout_safe()

    client.print_agent_result(agent.AgentResult("Due on 18\u202fNov."))
    console.flush()

    assert b"Answer: Due on 18?Nov." in console.buffer.getvalue()
