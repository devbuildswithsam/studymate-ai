"""Chat messages that use MCP tools (the agent loop in the chat). SMA-42, test-first.

The AI is a FakeProvider; the tools are the app's real MCP server acting for the
request's user on the temporary database.
"""

from datetime import date

from sqlalchemy import select

from app.api.deps import get_current_user_id
from app.main import app
from app.models import LLMCall, Message, Task, User
from app.services.llm.exceptions import ProviderUnavailableError
from app.services.llm.fake import FakeProvider
from tests.tool_helpers import QUESTION, call

# --- Done when ---------------------------------------------------------------------


def test_add_a_task_by_sunday_then_list_pending_tasks(tool_chat, tool_fakes, client):
    tool_fakes["tools-model"].replies = [
        [call("create_task", {"title": "Finish thermodynamics notes", "due_date": "2026-11-22"})],
        [call("list_tasks", {"status": "todo"})],
        "Added it. Your pending task: Finish thermodynamics notes (due Sunday 22 Nov).",
    ]

    conversation_id, response = tool_chat(QUESTION)

    assert response.status_code == 200, response.text
    reply = response.json()
    assert reply["mode"] == "tool"
    assert reply["reply"].startswith("Added it.")
    assert [(t["name"], t["is_error"]) for t in reply["tool_calls"]] == [
        ("create_task", False),
        ("list_tasks", False),
    ]
    assert reply["tool_calls"][0]["arguments"]["due_date"] == "2026-11-22"
    board = client.get("/api/tasks").json()
    assert [(t["title"], t["created_by"]) for t in board] == [("Finish thermodynamics notes", "ai")]


def test_the_tool_calls_are_saved_with_the_answer(tool_chat, tool_fakes, client):
    tool_fakes["tools-model"].replies = [[call("list_tasks", {})], "You have no tasks."]

    conversation_id, _ = tool_chat("list my tasks")

    saved = client.get(f"/api/conversations/{conversation_id}").json()["messages"][-1]
    assert saved["mode"] == "tool"
    assert [t["name"] for t in saved["tool_calls"]] == ["list_tasks"]
    assert saved["tool_calls"][0]["result"] == '{"result": []}'
    assert saved["tool_calls"][0]["duration_ms"] >= 0


def test_every_model_call_of_every_turn_is_logged(tool_chat, tool_fakes, db_session):
    tool_fakes["tools-model"].replies = [[call("list_tasks", {})], "Done."]

    tool_chat("list my tasks")

    calls = db_session.scalars(select(LLMCall)).all()
    assert [(c.model, c.status, c.mode) for c in calls] == [
        ("tools-model", "ok", "tool"),
        ("tools-model", "ok", "tool"),
    ]


def test_the_ai_is_told_todays_date_when_tools_are_offered(tool_chat, tool_fakes):
    tool_chat("add a task for tomorrow")

    system = tool_fakes["tools-model"].calls[0][0]["content"]
    assert date.today().isoformat() in system


# --- When tools are not used ----------------------------------------------------------


def test_a_plain_answer_is_a_general_message(tool_chat, tool_fakes):
    _, response = tool_chat("What is osmosis?")

    reply = response.json()
    assert (reply["mode"], reply["tool_calls"]) == ("general", [])
    assert tool_fakes["tools-model"].options[0].tools  # tools were offered, just not used


def test_a_model_without_tool_support_gets_no_tools(tool_chat, tool_fakes):
    _, response = tool_chat("What is osmosis?", model="plain-model")

    assert response.json()["reply"] == "answer without tools"
    assert tool_fakes["plain-model"].options[0].tools is None


# --- Safety and failures ----------------------------------------------------------------


def test_tools_act_for_the_user_making_the_request(tool_chat, tool_fakes, client, db_session):
    bob = User(email="bob@example.com")
    db_session.add(bob)
    db_session.commit()
    tool_fakes["tools-model"].replies = [[call("create_task", {"title": "Bob's task"})], "Done."]

    app.dependency_overrides[get_current_user_id] = lambda: bob.id
    tool_chat("add a task")

    task = db_session.scalars(select(Task)).one()
    assert task.user_id == bob.id  # from the request, never from the model


def test_an_injected_user_id_is_refused_and_nothing_is_written(tool_chat, tool_fakes, db_session):
    tool_fakes["tools-model"].replies = [
        [call("create_task", {"title": "x", "user_id": "someone-else"})],
        "I couldn't do that.",
    ]

    _, response = tool_chat("add a task for someone else")

    assert response.json()["tool_calls"][0]["is_error"] is True
    assert db_session.scalars(select(Task)).all() == []


def test_all_models_failing_mid_loop_returns_503_and_logs_every_call(
    tool_chat, tool_fakes, db_session
):
    class FailsAfterFirstTurn(FakeProvider):
        def chat(self, messages, options=None):
            if len(self.calls) >= 1:
                self.calls.append(list(messages))
                raise ProviderUnavailableError("503", "p")
            return super().chat(messages, options)

    tool_fakes["tools-model"] = FailsAfterFirstTurn(replies=[[call("list_tasks", {})]])

    _, response = tool_chat("list my tasks")

    assert response.status_code == 503
    statuses = [c.status for c in db_session.scalars(select(LLMCall)).all()]
    assert statuses == ["ok", "error"]  # the first turn and the failed second turn
    assert db_session.scalars(select(Message)).all() == []  # no half-saved turn


def test_the_tool_call_limit_ends_with_a_clear_message(tool_chat, tool_fakes):
    tool_fakes["tools-model"].replies = [[call("list_tasks", {})]]  # never answers

    _, response = tool_chat("list my tasks forever")

    reply = response.json()
    assert len(reply["tool_calls"]) == 5
    assert "5 tool calls" in reply["reply"]


# --- Searching documents from the chat (SMA-48) -------------------------------------------------


def test_the_ai_can_search_my_documents_from_the_chat(tool_chat, tool_fakes, client):
    notes = b"Entropy always increases in an isolated system, so heat flows from hot to cold."
    client.post("/api/documents", files={"file": ("Physics.md", notes, "text/markdown")})
    tool_fakes["tools-model"].replies = [
        [call("search_documents", {"query": "entropy"})],
        "Entropy always increases (Physics.md).",
    ]

    _, response = tool_chat("What do my notes say about entropy?")

    step = response.json()["tool_calls"][0]
    assert (step["name"], step["is_error"]) == ("search_documents", False)
    assert "Physics.md" in step["result"]  # the document was found, for this user
