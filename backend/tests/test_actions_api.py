"""Pending actions: confirmation cards, Confirm / Cancel, and Undo (guide 7.2). SMA-43.

The AI is a FakeProvider; the tools are the app's real MCP server on the test database.
"""

import pytest
from sqlalchemy import select

from app.models import Note, Task, User
from tests.tool_helpers import call


@pytest.fixture
def a_task(client, db_session) -> Task:
    user = db_session.scalars(select(User)).one()
    task = Task(user_id=user.id, title="Revise ch.3")
    db_session.add(task)
    db_session.commit()
    return task


def send(tool_chat, tool_fakes, message: str, *tool_calls):
    tool_fakes["tools-model"].replies = [list(tool_calls), "Done (or waiting for you)."]
    conversation_id, response = tool_chat(message)
    assert response.status_code == 200, response.text
    return conversation_id, response.json()


def status_of(db_session, task: Task) -> str:
    db_session.expire_all()
    return db_session.get(Task, task.id).status


# --- A change becomes a confirmation card ------------------------------------------


def test_a_change_becomes_a_pending_action_and_nothing_changes(
    tool_chat, tool_fakes, a_task, db_session
):
    _, reply = send(
        tool_chat, tool_fakes, "complete Revise ch.3", call("complete_task", {"task_id": a_task.id})
    )

    [action] = reply["actions"]
    assert (action["tool"], action["kind"], action["status"]) == (
        "complete_task",
        "change",
        "pending",
    )
    assert action["summary"] == "Mark 'Revise ch.3' as done"
    assert reply["tool_calls"][0]["held"] is True
    assert status_of(db_session, a_task) == "todo"


def test_the_card_is_saved_with_the_answer(tool_chat, tool_fakes, a_task, client):
    conversation_id, reply = send(
        tool_chat, tool_fakes, "complete it", call("complete_task", {"task_id": a_task.id})
    )

    saved = client.get(f"/api/conversations/{conversation_id}").json()["messages"][-1]
    assert [a["id"] for a in saved["actions"]] == [reply["actions"][0]["id"]]


def test_confirm_runs_the_tool_once(tool_chat, tool_fakes, a_task, client, db_session):
    _, reply = send(
        tool_chat, tool_fakes, "complete it", call("complete_task", {"task_id": a_task.id})
    )
    action_id = reply["actions"][0]["id"]

    confirmed = client.post(f"/api/actions/{action_id}/confirm")

    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "done"
    assert status_of(db_session, a_task) == "done"
    assert client.post(f"/api/actions/{action_id}/confirm").status_code == 409  # only once


def test_cancel_leaves_everything_as_it_was(tool_chat, tool_fakes, a_task, client, db_session):
    _, reply = send(
        tool_chat, tool_fakes, "complete it", call("complete_task", {"task_id": a_task.id})
    )
    action_id = reply["actions"][0]["id"]

    cancelled = client.post(f"/api/actions/{action_id}/cancel")

    assert cancelled.json()["status"] == "cancelled"
    assert status_of(db_session, a_task) == "todo"
    assert client.post(f"/api/actions/{action_id}/confirm").status_code == 409


def test_a_confirmed_action_that_fails_says_why(tool_chat, tool_fakes, a_task, client, db_session):
    _, reply = send(
        tool_chat, tool_fakes, "complete it", call("complete_task", {"task_id": a_task.id})
    )
    client.delete(f"/api/tasks/{a_task.id}")  # the task is gone before you click Confirm

    confirmed = client.post(f"/api/actions/{reply['actions'][0]['id']}/confirm").json()

    assert confirmed["status"] == "failed"
    assert "No task with id" in confirmed["error"]


def test_the_summary_of_an_update(tool_chat, tool_fakes, a_task):
    _, reply = send(
        tool_chat,
        tool_fakes,
        "move it to Friday",
        call("update_task", {"task_id": a_task.id, "due_date": "2026-11-20", "status": "doing"}),
    )

    assert (
        reply["actions"][0]["summary"]
        == "Change 'Revise ch.3': due_date → 2026-11-20, status → doing"
    )


# --- Creates: run with Undo when asked, held when not ------------------------------------


def test_a_requested_create_runs_and_can_be_undone(tool_chat, tool_fakes, client, db_session):
    _, reply = send(
        tool_chat, tool_fakes, "Add a task: essay", call("create_task", {"title": "Essay"})
    )

    [action] = reply["actions"]
    assert (action["kind"], action["status"], action["summary"]) == (
        "create",
        "done",
        "Add task 'Essay'",
    )
    assert [t["title"] for t in client.get("/api/tasks").json()] == ["Essay"]

    undone = client.post(f"/api/actions/{action['id']}/undo")

    assert undone.json()["status"] == "undone"
    assert client.get("/api/tasks").json() == []
    assert client.post(f"/api/actions/{action['id']}/undo").status_code == 409  # only once


def test_undo_a_saved_note(tool_chat, tool_fakes, client, db_session):
    _, reply = send(
        tool_chat,
        tool_fakes,
        "save a note on entropy",
        call("save_note", {"title": "Entropy", "content": "S"}),
    )

    client.post(f"/api/actions/{reply['actions'][0]['id']}/undo")

    assert db_session.scalars(select(Note)).all() == []


def test_a_create_you_did_not_ask_for_waits_and_confirm_makes_it(tool_chat, tool_fakes, client):
    _, reply = send(
        tool_chat, tool_fakes, "What is entropy?", call("create_task", {"title": "Read on entropy"})
    )
    action = reply["actions"][0]
    assert action["status"] == "pending"
    assert client.get("/api/tasks").json() == []

    client.post(f"/api/actions/{action['id']}/confirm")

    [task] = client.get("/api/tasks").json()
    assert (task["title"], task["created_by"]) == ("Read on entropy", "ai")
    assert client.post(f"/api/actions/{action['id']}/undo").json()["status"] == "undone"


def test_a_change_cannot_be_undone(tool_chat, tool_fakes, a_task, client):
    _, reply = send(
        tool_chat, tool_fakes, "complete it", call("complete_task", {"task_id": a_task.id})
    )
    action_id = reply["actions"][0]["id"]
    client.post(f"/api/actions/{action_id}/confirm")

    assert client.post(f"/api/actions/{action_id}/undo").status_code == 409


def test_reads_and_errors_make_no_actions(tool_chat, tool_fakes):
    _, reply = send(
        tool_chat,
        tool_fakes,
        "list my tasks",
        call("list_tasks", {}),
        call("create_task", {"title": "x", "user_id": "someone-else"}),
    )

    assert reply["actions"] == []


def test_an_unknown_action_is_404(client):
    assert (
        client.post("/api/actions/00000000-0000-0000-0000-000000000000/confirm").status_code == 404
    )
