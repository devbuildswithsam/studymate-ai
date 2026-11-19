"""The in-app MCP server's tools (guide 7.2). SMA-41, written test-first.

The user ALWAYS comes from the backend (a request-scoped ContextVar), never from the
tool's arguments: a tool called with a user_id argument is rejected.
"""

from contextlib import contextmanager

import pytest
from mcp import Client
from mcp.shared.exceptions import MCPError

from app.db.session import _session_factory
from app.mcp_server.context import ToolContext, acting_as
from app.mcp_server.server import mcp_server
from app.models import Note, Task, User

STAGE_3_TOOLS = {
    "create_task",
    "list_tasks",
    "update_task",
    "complete_task",
    "save_note",
    "search_notes",
}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def users(db_session) -> tuple[User, User]:
    alice, bob = User(email="alice@example.com"), User(email="bob@example.com")
    db_session.add_all([alice, bob])
    db_session.commit()
    return alice, bob


@pytest.fixture
def as_user(db_url):
    """as_user(user): run tools as that user, the way the backend will set it."""

    @contextmanager
    def run_as(user: User, embedder=None):  # embedder: for search_documents (SMA-48)
        context = ToolContext(
            user_id=user.id,
            session_factory=_session_factory(db_url),
            make_embedder=(lambda: embedder) if embedder else None,
        )
        with acting_as(context):
            yield

    return run_as


async def call(client, tool: str, **arguments):
    result = await client.call_tool(tool, arguments)
    assert not result.is_error, result.content[0].text
    return result.structured_content


# --- What the AI is offered ------------------------------------------------------------


@pytest.mark.anyio
async def test_the_tools_and_nothing_that_deletes():
    async with Client(mcp_server) as client:
        tools = (await client.list_tools()).tools

    assert {t.name for t in tools} == STAGE_3_TOOLS | {"search_documents"}  # + SMA-48
    assert not any("delete" in t.name or "remove" in t.name for t in tools)


@pytest.mark.anyio
async def test_no_tool_has_a_user_id_argument():
    async with Client(mcp_server) as client:
        tools = (await client.list_tools()).tools

    for tool in tools:
        assert "user_id" not in tool.input_schema.get("properties", {}), tool.name


@pytest.mark.anyio
async def test_read_only_tools_are_marked_as_such():
    async with Client(mcp_server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}

    for name in ("list_tasks", "search_notes", "search_documents"):
        assert tools[name].annotations.read_only_hint is True, name
    for name in ("create_task", "update_task", "complete_task", "save_note"):
        assert tools[name].annotations.read_only_hint is False, name
        assert tools[name].annotations.destructive_hint is False, name


# --- Tasks ---------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_task_makes_an_ai_task_for_the_current_user(users, as_user, db_session):
    alice, _ = users
    with as_user(alice):
        async with Client(mcp_server) as client:
            task = await call(
                client, "create_task", title="Revise thermodynamics", due_date="2026-11-20"
            )

    assert (task["title"], task["due_date"], task["status"]) == (
        "Revise thermodynamics",
        "2026-11-20",
        "todo",
    )
    saved = db_session.get(Task, task["id"])
    assert (saved.user_id, saved.created_by) == (alice.id, "ai")  # the AI marker


@pytest.mark.anyio
async def test_list_tasks_shows_only_my_tasks_with_filters(users, as_user):
    alice, bob = users
    with as_user(bob):
        async with Client(mcp_server) as client:
            await call(client, "create_task", title="Bob's task")
    with as_user(alice):
        async with Client(mcp_server) as client:
            await call(client, "create_task", title="Soon", due_date="2026-11-19")
            await call(client, "create_task", title="Later", due_date="2026-12-30")
            everything = await call(client, "list_tasks")
            due_soon = await call(client, "list_tasks", due_before="2026-11-25")
            done = await call(client, "list_tasks", status="done")

    assert [t["title"] for t in everything["result"]] == ["Soon", "Later"]
    assert [t["title"] for t in due_soon["result"]] == ["Soon"]
    assert done["result"] == []


@pytest.mark.anyio
async def test_list_tasks_returns_at_most_50(users, as_user):
    alice, _ = users
    with as_user(alice):
        async with Client(mcp_server) as client:
            for n in range(55):
                await call(client, "create_task", title=f"Task {n}")
            listed = await call(client, "list_tasks")

    assert len(listed["result"]) == 50


@pytest.mark.anyio
async def test_update_and_complete_a_task(users, as_user, db_session):
    alice, _ = users
    with as_user(alice):
        async with Client(mcp_server) as client:
            task = await call(client, "create_task", title="Draft")
            updated = await call(
                client, "update_task", task_id=task["id"], title="Final", priority="high"
            )
            completed = await call(client, "complete_task", task_id=task["id"])

    assert (updated["title"], updated["priority"]) == ("Final", "high")
    assert completed["status"] == "done"
    assert db_session.get(Task, task["id"]).completed_at is not None


@pytest.mark.anyio
@pytest.mark.parametrize("tool", ["update_task", "complete_task"])
async def test_another_users_task_is_not_found(users, as_user, tool):
    alice, bob = users
    with as_user(alice):
        async with Client(mcp_server) as client:
            alices = await call(client, "create_task", title="Alice's task")
    with as_user(bob):
        async with Client(mcp_server) as client:
            arguments = {"task_id": alices["id"]}
            if tool == "update_task":
                arguments["title"] = "Bob was here"
            result = await client.call_tool(tool, arguments)

    assert result.is_error
    assert "No task" in result.content[0].text  # same answer as a task that doesn't exist


# --- Notes ---------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_save_and_search_notes(users, as_user, db_session):
    alice, bob = users
    with as_user(alice):
        async with Client(mcp_server) as client:
            note = await call(
                client,
                "save_note",
                title="Newton's 2nd law",
                content="F = m * a",
                tags=["physics"],
            )
            found = await call(client, "search_notes", query="newton")
    with as_user(bob):
        async with Client(mcp_server) as client:
            bobs_search = await call(client, "search_notes", query="newton")

    assert db_session.get(Note, note["id"]).user_id == alice.id
    assert [n["title"] for n in found["result"]] == ["Newton's 2nd law"]
    assert bobs_search["result"] == []


@pytest.mark.anyio
async def test_search_results_are_capped_and_short(users, as_user):
    alice, _ = users
    with as_user(alice):
        async with Client(mcp_server) as client:
            for n in range(12):
                await call(client, "save_note", title=f"Physics {n}", content="x" * 5000)
            found = await call(client, "search_notes", query="physics")
            three = await call(client, "search_notes", query="physics", limit=3)
            too_many = await client.call_tool("search_notes", {"query": "physics", "limit": 50})

    assert len(found["result"]) == 10  # the default and the maximum
    assert len(three["result"]) == 3
    assert too_many.is_error
    assert all(len(n["snippet"]) <= 300 for n in found["result"])  # not 5000 characters


# --- Limits on what the AI can send ---------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize(
    "tool, arguments",
    [
        ("create_task", {"title": "x" * 201}),
        ("create_task", {"title": "   "}),
        ("create_task", {"title": "ok", "priority": "urgent"}),
        ("save_note", {"title": "ok", "content": "x" * 10_001}),
        ("save_note", {"title": "ok", "content": "", "tags": ["t"] * 11}),
        ("search_notes", {"query": "x" * 201}),
    ],
)
async def test_oversized_or_invalid_arguments_are_rejected(users, as_user, tool, arguments):
    alice, _ = users
    with as_user(alice):
        async with Client(mcp_server) as client:
            result = await client.call_tool(tool, arguments)

    assert result.is_error


# --- Identity: only from the backend ----------------------------------------------------


@pytest.mark.anyio
async def test_an_injected_user_id_argument_is_rejected(users, as_user, db_session):
    alice, bob = users
    with as_user(alice):
        async with Client(mcp_server) as client:
            with pytest.raises(MCPError, match="user_id") as caught:
                await client.call_tool("create_task", {"title": "x", "user_id": bob.id})

    assert caught.value.error.code == -32602  # JSON-RPC "invalid params"
    assert db_session.query(Task).count() == 0  # the tool never ran


@pytest.mark.anyio
async def test_any_unknown_argument_is_rejected(users, as_user):
    alice, _ = users
    with as_user(alice):
        async with Client(mcp_server) as client:
            with pytest.raises(MCPError, match="owner"):
                await client.call_tool("list_tasks", {"owner": "everyone"})


@pytest.mark.anyio
async def test_without_a_signed_in_user_the_tools_refuse(db_session):
    # Fail closed: no context set by the backend -> no tool runs.
    async with Client(mcp_server) as client:
        result = await client.call_tool("create_task", {"title": "orphan"})

    assert result.is_error
    assert "No signed-in user" in result.content[0].text
    assert db_session.query(Task).count() == 0


# --- search_documents (SMA-48) ------------------------------------------------------------------


@pytest.fixture
def documents(users, db_session):
    """Alice's physics notes and Bob's (better matching) secret, both embedded and ready."""
    from tests.test_rag_retrieve import PHYSICS, KeywordEmbedder, add_document

    alice, bob = users
    embedder = KeywordEmbedder()
    add_document(db_session, bob, "Bob's secrets.pdf", [(1, "entropy entropy entropy")], embedder)
    physics = add_document(db_session, alice, "Physics.pdf", PHYSICS, embedder)
    return embedder, physics


@pytest.mark.anyio
async def test_search_documents_finds_my_best_passages_with_name_and_page(
    users, as_user, documents
):
    alice, _ = users
    embedder, physics = documents

    with as_user(alice, embedder):
        async with Client(mcp_server) as client:
            hits = (await call(client, "search_documents", query="What is entropy?"))["result"]

    assert (hits[0]["filename"], hits[0]["page"], hits[0]["document_id"]) == (
        "Physics.pdf",
        2,
        physics.id,
    )
    assert hits[0]["text"].startswith("Entropy always increases")
    assert len(hits) == 5
    assert all(h["filename"] != "Bob's secrets.pdf" for h in hits)  # never another user's


@pytest.mark.anyio
async def test_search_documents_can_be_limited_to_some_documents_and_fewer_results(
    users, as_user, documents
):
    alice, _ = users
    embedder, physics = documents

    with as_user(alice, embedder):
        async with Client(mcp_server) as client:
            hits = (
                await call(
                    client, "search_documents", query="heat", document_ids=[physics.id], top_k=2
                )
            )["result"]

    assert len(hits) == 2


@pytest.mark.anyio
@pytest.mark.parametrize(
    "arguments",
    [
        {"query": "heat", "top_k": 9},
        {"query": "heat", "top_k": 0},
        {"query": ""},
        {"query": "x" * 501},
    ],
    ids=["top_k over 8", "top_k 0", "empty query", "query too long"],
)
async def test_search_documents_arguments_are_capped(users, as_user, documents, arguments):
    alice, _ = users
    embedder, _ = documents

    with as_user(alice, embedder):
        async with Client(mcp_server) as client:
            result = await client.call_tool("search_documents", arguments)

    assert result.is_error


@pytest.mark.anyio
async def test_a_busy_embedding_service_is_a_clear_tool_error(users, as_user, documents):
    from app.services.llm.exceptions import RateLimitedError
    from app.services.llm.fake import FakeEmbeddingProvider

    alice, _ = users
    busy = FakeEmbeddingProvider(fail_on_call=1, error=RateLimitedError("quota", "fake"))
    busy.model, busy.dimensions = "keyword-model", 6  # same vectors as the stored chunks

    with as_user(alice, busy):
        async with Client(mcp_server) as client:
            result = await client.call_tool("search_documents", {"query": "entropy"})

    assert result.is_error
    assert "busy" in result.content[0].text


@pytest.mark.anyio
async def test_without_an_embedder_search_is_unavailable_not_a_crash(users, as_user, documents):
    alice, _ = users

    with as_user(alice):  # e.g. a context that only runs write tools
        async with Client(mcp_server) as client:
            result = await client.call_tool("search_documents", {"query": "entropy"})

    assert result.is_error
    assert "search isn't available" in result.content[0].text
