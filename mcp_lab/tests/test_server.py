"""The MCP lab server, tested through the real MCP protocol (in-process). SMA-36.

mcp.Client(server) connects to the server in memory: the same JSON-RPC messages as over
stdio (initialize, tools/list, tools/call, resources/read, prompts/get), no subprocess.
"""

import json
from datetime import date

import pytest
import server
from mcp import Client


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def lab_db(tmp_path, monkeypatch):
    """Every test gets its own empty lab.db, and a fixed 'today' (Wed 18 Nov 2026)."""
    monkeypatch.setattr(server, "DB_PATH", tmp_path / "lab.db")
    monkeypatch.setattr(server, "today", lambda: date(2026, 11, 18))


async def call(client, tool: str, **arguments):
    result = await client.call_tool(tool, arguments)
    assert not result.is_error, result.content[0].text
    return result.structured_content


# --- Tools: discovered with a JSON Schema --------------------------------------------


@pytest.mark.anyio
async def test_the_server_offers_three_tools():
    async with Client(server.mcp) as client:
        tools = (await client.list_tools()).tools

    assert sorted(t.name for t in tools) == ["add_task", "complete_task", "list_tasks"]
    assert all(t.description for t in tools)  # the AI reads these to choose a tool


@pytest.mark.anyio
async def test_add_task_inputs_are_described_by_a_json_schema():
    async with Client(server.mcp) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}

    schema = tools["add_task"].input_schema
    assert schema["required"] == ["title"]  # the only argument without a default
    assert schema["properties"]["title"]["maxLength"] == 200
    assert schema["properties"]["priority"]["enum"] == ["low", "medium", "high"]
    assert "YYYY-MM-DD" in schema["properties"]["due_date"]["description"]


# --- Tools: calling them ------------------------------------------------------------


@pytest.mark.anyio
async def test_add_list_and_complete_a_task():
    async with Client(server.mcp) as client:
        added = await call(client, "add_task", title="Revise thermodynamics", due_date="2026-11-22")
        pending = await call(client, "list_tasks")
        completed = await call(client, "complete_task", task_id=added["id"])
        pending_after = await call(client, "list_tasks")
        done = await call(client, "list_tasks", status="done")

    assert added == {
        "id": 1,
        "title": "Revise thermodynamics",
        "due_date": "2026-11-22",
        "priority": "medium",
        "done": False,
    }
    assert [t["title"] for t in pending["result"]] == ["Revise thermodynamics"]
    assert completed["done"] is True
    assert pending_after["result"] == []
    assert [t["id"] for t in done["result"]] == [added["id"]]


@pytest.mark.anyio
async def test_tasks_are_saved_in_lab_db():
    async with Client(server.mcp) as client:
        await call(client, "add_task", title="Read chapter 3")
    async with Client(server.mcp) as fresh_client:  # a new session, same file
        pending = await call(fresh_client, "list_tasks")

    assert [t["title"] for t in pending["result"]] == ["Read chapter 3"]


@pytest.mark.anyio
async def test_pending_tasks_are_listed_by_due_date_then_priority():
    async with Client(server.mcp) as client:
        await call(client, "add_task", title="No date")
        await call(client, "add_task", title="Later", due_date="2026-11-30")
        await call(client, "add_task", title="Soon, low", due_date="2026-11-20", priority="low")
        await call(client, "add_task", title="Soon, high", due_date="2026-11-20", priority="high")
        pending = await call(client, "list_tasks")

    assert [t["title"] for t in pending["result"]] == [
        "Soon, high",
        "Soon, low",
        "Later",
        "No date",
    ]


# --- Errors the AI can read and fix --------------------------------------------------


@pytest.mark.anyio
async def test_completing_an_unknown_task_explains_why():
    async with Client(server.mcp) as client:
        result = await client.call_tool("complete_task", {"task_id": 99})

    assert result.is_error
    assert "No task with id 99" in result.content[0].text  # a ToolError: the AI sees it


@pytest.mark.anyio
@pytest.mark.parametrize(
    "arguments, problem",
    [
        ({"title": ""}, "title"),
        ({"title": "x" * 201}, "title"),
        ({"title": "ok", "priority": "urgent"}, "priority"),
        ({"title": "ok", "due_date": "next friday"}, "due_date"),
    ],
)
async def test_invalid_arguments_are_rejected_before_the_tool_runs(arguments, problem):
    async with Client(server.mcp) as client:
        result = await client.call_tool("add_task", arguments)
        pending = await call(client, "list_tasks")

    assert result.is_error
    assert problem in result.content[0].text
    assert pending["result"] == []  # nothing was saved


# --- Resource ------------------------------------------------------------------------


@pytest.mark.anyio
async def test_the_summary_resource_counts_tasks():
    async with Client(server.mcp) as client:
        await call(client, "add_task", title="Overdue essay", due_date="2026-11-15")
        await call(client, "add_task", title="Today's quiz", due_date="2026-11-18")
        later = await call(client, "add_task", title="Lab report", due_date="2026-11-25")
        await call(client, "complete_task", task_id=later["id"])
        listed = (await client.list_resources()).resources
        result = await client.read_resource("tasks://summary")

    assert [str(r.uri) for r in listed] == ["tasks://summary"]
    text = result.contents[0].text
    assert "2 pending (1 overdue, 1 due today), 1 done" in text
    assert "Overdue essay (due 2026-11-15, OVERDUE)" in text


# --- Prompt --------------------------------------------------------------------------


@pytest.mark.anyio
async def test_plan_my_day_prompt_includes_my_pending_tasks_and_hours():
    async with Client(server.mcp) as client:
        await call(client, "add_task", title="Revise thermodynamics", due_date="2026-11-19")
        prompts = (await client.list_prompts()).prompts
        result = await client.get_prompt("plan_my_day", {"hours_available": "2"})

    assert [p.name for p in prompts] == ["plan_my_day"]
    assert [a.name for a in prompts[0].arguments] == ["hours_available"]
    text = result.messages[0].content.text
    assert result.messages[0].role == "user"
    assert "2 hours" in text
    assert "Revise thermodynamics" in text


@pytest.mark.anyio
async def test_structured_results_are_also_sent_as_text():
    # Older clients only read `content`, so the same data is there as JSON text too.
    async with Client(server.mcp) as client:
        result = await client.call_tool("add_task", {"title": "Flashcards"})

    assert json.loads(result.content[0].text)["title"] == "Flashcards"
