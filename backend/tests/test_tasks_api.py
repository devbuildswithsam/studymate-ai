"""Tasks API: the board's data (wireframe 6.6). SMA-40, written test-first.

Isolation between users is tested in test_isolation.py (the guard there makes sure).
"""

from datetime import UTC, datetime

import pytest

from app.models import Task


def create(client, **body):
    response = client.post("/api/tasks", json={"title": "Revise ch. 3", **body})
    assert response.status_code == 201, response.text
    return response.json()


def edit(client, task_id, **changes):
    response = client.patch(f"/api/tasks/{task_id}", json=changes)
    assert response.status_code == 200, response.text
    return response.json()


# --- Create ----------------------------------------------------------------------------


def test_a_new_task_starts_in_to_do_with_medium_priority(client):
    task = create(client, title="Revise thermodynamics")

    assert task["title"] == "Revise thermodynamics"
    assert (task["status"], task["priority"], task["created_by"]) == ("todo", "medium", "user")
    assert task["due_date"] is None and task["description"] is None
    assert task["completed_at"] is None
    assert task["id"] and task["created_at"]


def test_a_task_with_every_field(client):
    task = create(
        client,
        title="DBMS notes",
        description="Normal forms, chapter 4",
        due_date="2026-11-20",
        priority="high",
        status="doing",
    )

    assert (task["description"], task["due_date"]) == ("Normal forms, chapter 4", "2026-11-20")
    assert (task["priority"], task["status"]) == ("high", "doing")


def test_the_ai_marker_cannot_be_set_through_the_api(client):
    # created_by="ai" only ever comes from the MCP tools (SMA-41), never from a request.
    task = create(client, title="Fake AI task", created_by="ai")

    assert task["created_by"] == "user"
    assert edit(client, task["id"], created_by="ai")["created_by"] == "user"


@pytest.mark.parametrize(
    "body",
    [
        {"title": "   "},
        {"title": "x" * 201},
        {"title": "ok", "priority": "urgent"},
        {"title": "ok", "status": "blocked"},
        {"title": "ok", "due_date": "next friday"},
        {"title": "ok", "description": "x" * 2001},
    ],
)
def test_invalid_tasks_are_rejected(client, body):
    assert client.post("/api/tasks", json=body).status_code == 422


def test_a_title_is_trimmed(client):
    assert create(client, title="  Read ch. 2  ")["title"] == "Read ch. 2"


# --- List ------------------------------------------------------------------------------


def test_tasks_are_listed_soonest_due_first_then_by_priority(client):
    create(client, title="No date")
    create(client, title="Later", due_date="2026-11-30")
    create(client, title="Soon, low", due_date="2026-11-20", priority="low")
    create(client, title="Soon, high", due_date="2026-11-20", priority="high")

    titles = [t["title"] for t in client.get("/api/tasks").json()]

    assert titles == ["Soon, high", "Soon, low", "Later", "No date"]


def test_tasks_can_be_filtered_by_status(client):
    create(client, title="A")
    doing = create(client, title="B", status="doing")

    listed = client.get("/api/tasks", params={"status": "doing"}).json()

    assert [t["id"] for t in listed] == [doing["id"]]
    assert client.get("/api/tasks", params={"status": "nope"}).status_code == 422


# --- Edit and move between columns -----------------------------------------------------


def test_edit_a_task(client):
    task = create(client, title="Old", due_date="2026-11-20")

    edited = edit(client, task["id"], title="New", priority="low", description="details")

    assert (edited["title"], edited["priority"], edited["description"]) == ("New", "low", "details")
    assert edited["due_date"] == "2026-11-20"  # not sent, so not changed


def test_sending_null_clears_the_due_date_but_leaving_it_out_keeps_it(client):
    task = create(client, due_date="2026-11-20")

    assert edit(client, task["id"], title="Still dated")["due_date"] == "2026-11-20"
    assert edit(client, task["id"], due_date=None)["due_date"] is None


def test_a_title_cannot_be_cleared(client):
    task = create(client)

    assert client.patch(f"/api/tasks/{task['id']}", json={"title": None}).status_code == 422
    assert client.patch(f"/api/tasks/{task['id']}", json={"title": " "}).status_code == 422


def test_moving_to_done_records_when_and_moving_back_clears_it(client):
    task = create(client)

    done = edit(client, task["id"], status="done")
    reopened = edit(client, task["id"], status="doing")

    assert done["completed_at"] is not None
    assert reopened["completed_at"] is None


def test_editing_a_done_task_keeps_its_completion_time(client, db_session):
    task = create(client)
    edit(client, task["id"], status="done")
    db_session.get(Task, task["id"]).completed_at = datetime(2026, 11, 1, tzinfo=UTC)
    db_session.commit()

    edited = edit(client, task["id"], title="Renamed", status="done")

    assert edited["completed_at"].startswith("2026-11-01")


# --- Delete -----------------------------------------------------------------------------


def test_delete_a_task(client):
    task = create(client)

    assert client.delete(f"/api/tasks/{task['id']}").status_code == 204
    assert client.get("/api/tasks").json() == []
    assert client.patch(f"/api/tasks/{task['id']}", json={"title": "x"}).status_code == 404
