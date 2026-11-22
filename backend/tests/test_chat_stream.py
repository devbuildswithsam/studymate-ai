"""Streaming chat answers over Server-Sent Events, and the Stop button. SMA-62.

The same POST /api/conversations/{id}/messages streams when the browser asks for
`Accept: text/event-stream`, and answers with one JSON object otherwise (as before).
Events: `token` (a piece of text), `tool` (a tool the AI used), `done` (the saved answer,
same fields as the JSON reply) or `error`. Written test-first; the AI is a FakeProvider.
"""

import json

import pytest
from sqlalchemy import select

from app.models import LLMCall, Message
from app.services.chat_streams import CUT_OFF_NOTE, STOPPED_NOTE
from app.services.llm.exceptions import ProviderUnavailableError
from app.services.llm.fake import FakeProvider
from app.services.study import NOT_FOUND_TEXT
from tests.pdf_maker import make_pdf
from tests.test_conversations_api import use_fakes
from tests.test_study_chat import PAGES
from tests.tool_helpers import call

SSE = {"Accept": "text/event-stream"}


@pytest.fixture
def physics(client) -> dict:
    """A ready two-page PDF for the study-chat tests (same pages as test_study_chat)."""
    response = client.post(
        "/api/documents", files={"file": ("Physics.pdf", make_pdf(PAGES), "application/pdf")}
    )
    document = json.loads(response.text.splitlines()[-1])["document"]
    assert document["status"] == "ready"
    return document


def events(response) -> list[tuple[str, dict]]:
    """Parse a Server-Sent Events body: blocks of 'event: ...' and 'data: ...' lines."""
    parsed = []
    for block in response.text.split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in fields:
            parsed.append((fields["event"], json.loads(fields["data"])))
    return parsed


def streamed_text(parsed) -> str:
    return "".join(data["text"] for kind, data in parsed if kind == "token")


def new_chat(client, **body) -> str:
    return client.post("/api/conversations", json=body).json()["id"]


def ask(client, chat_id: str, message: str = "What is entropy?"):
    return client.post(
        f"/api/conversations/{chat_id}/messages", json={"message": message}, headers=SSE
    )


def saved_answer(db_session) -> Message:
    db_session.expire_all()
    return db_session.scalars(select(Message).where(Message.role == "assistant")).one()


# --- A streamed answer ------------------------------------------------------------------------


def test_an_answer_arrives_in_pieces_then_done(client, db_session):
    use_fakes(
        {"main": FakeProvider(replies=["Entropy measures disorder."]), "backup": FakeProvider()}
    )
    chat_id = new_chat(client)

    response = ask(client, chat_id)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    parsed = events(response)
    assert [kind for kind, _ in parsed] == ["token", "token", "token", "done"]
    assert streamed_text(parsed) == "Entropy measures disorder."
    done = parsed[-1][1]
    assert done["reply"] == "Entropy measures disorder."
    assert done["stopped"] is False
    # Saved exactly as before: the question, the answer, the call log.
    assert saved_answer(db_session).id == done["message_id"]
    assert saved_answer(db_session).content == "Entropy measures disorder."
    calls = db_session.scalars(select(LLMCall)).all()
    assert [(c.status, c.tokens_out) for c in calls] == [("ok", 3)]


def test_without_the_header_the_answer_is_one_json_object_as_before(client):
    use_fakes({"main": FakeProvider(replies=["Plain answer."]), "backup": FakeProvider()})

    response = client.post(
        f"/api/conversations/{new_chat(client)}/messages", json={"message": "hi"}
    )

    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["reply"] == "Plain answer."


def test_a_bad_request_is_still_a_normal_error(client):
    response = client.post(
        "/api/conversations/00000000-0000-0000-0000-000000000000/messages",
        json={"message": "hi"},
        headers=SSE,
    )

    assert response.status_code == 404  # checked before streaming starts


# --- Fallback and failures --------------------------------------------------------------------


def test_a_failure_before_the_first_piece_still_falls_back(client):
    broken = FakeProvider(error=ProviderUnavailableError("down", "fake"))
    use_fakes({"main": broken, "backup": FakeProvider(replies=["From the backup."])})

    parsed = events(ask(client, new_chat(client)))

    assert streamed_text(parsed) == "From the backup."
    assert parsed[-1] == ("done", parsed[-1][1]) and parsed[-1][1]["fallback_used"] is True


def test_a_failure_mid_answer_keeps_the_part_that_arrived(client, db_session):
    flaky = FakeProvider(replies=["one two three four"], fail_after_pieces=2)
    use_fakes({"main": flaky, "backup": FakeProvider(replies=["never used"])})

    parsed = events(ask(client, new_chat(client)))

    assert streamed_text(parsed) == "one two "
    kind, data = parsed[-1]
    assert kind == "error"
    assert "cut off" in data["error"]["message"]
    saved = saved_answer(db_session)
    assert saved.content == "one two" + CUT_OFF_NOTE  # kept, and marked
    assert data["message_id"] == saved.id
    assert [c.status for c in db_session.scalars(select(LLMCall))] == ["error"]


def test_when_every_model_fails_nothing_is_saved_but_the_calls_are_logged(client, db_session):
    broken = FakeProvider(error=ProviderUnavailableError("down", "fake"))
    use_fakes({"main": broken, "backup": broken})

    parsed = events(ask(client, new_chat(client)))

    kind, data = parsed[-1]
    assert kind == "error" and data["error"]["code"] == "service_unavailable"
    assert data["message_id"] is None
    assert db_session.scalars(select(Message)).all() == []  # no half turn
    assert len(db_session.scalars(select(LLMCall)).all()) == 2


# --- Stop ----------------------------------------------------------------------------------------


def test_stop_keeps_and_saves_what_arrived(client, db_session):
    chat_id = new_chat(client)

    def press_stop(piece_number: int):
        if piece_number == 2:  # after two pieces arrived, the student presses Stop
            assert client.post(f"/api/conversations/{chat_id}/stop").status_code == 202

    use_fakes(
        {
            "main": FakeProvider(replies=["one two three four"], before_piece=press_stop),
            "backup": FakeProvider(),
        }
    )

    parsed = events(ask(client, chat_id))

    assert streamed_text(parsed) == "one two "
    kind, done = parsed[-1]
    assert kind == "done" and done["stopped"] is True
    assert done["reply"] == "one two" + STOPPED_NOTE
    assert saved_answer(db_session).content == "one two" + STOPPED_NOTE
    assert [c.status for c in db_session.scalars(select(LLMCall))] == ["ok"]


def test_stop_with_no_answer_running_is_404(client):
    assert client.post(f"/api/conversations/{new_chat(client)}/stop").status_code == 404


def test_a_finished_answer_can_no_longer_be_stopped(client):
    # Its Stop switch is removed when it ends: a late click finds nothing running.
    use_fakes({"main": FakeProvider(replies=["Done."]), "backup": FakeProvider()})
    chat_id = new_chat(client)
    ask(client, chat_id)

    assert client.post(f"/api/conversations/{chat_id}/stop").status_code == 404


# --- Tool chats and study chats --------------------------------------------------------------


def test_a_tool_chat_streams_its_tools_then_the_answer(tool_chat, tool_fakes, client):
    tool_fakes["tools-model"].replies = [[call("list_tasks", {})], "You have no tasks."]
    chat_id = client.post("/api/conversations", json={}).json()["id"]

    parsed = events(ask(client, chat_id, "list my tasks"))

    kinds = [kind for kind, _ in parsed]
    assert kinds[0] == "tool" and kinds[-1] == "done"
    assert parsed[0][1]["name"] == "list_tasks"
    assert streamed_text(parsed) == "You have no tasks."
    assert parsed[-1][1]["mode"] == "tool"


def test_a_study_answer_streams_then_its_citations_are_checked(client, physics):
    # The model invents source [7]: it streams as written, then the check replaces it.
    use_fakes(
        {"main": FakeProvider(replies=["It always increases [7]."]), "backup": FakeProvider()}
    )
    chat_id = new_chat(client, mode="study", document_ids=[physics["id"]])

    parsed = events(ask(client, chat_id))

    assert streamed_text(parsed) == "It always increases [7]."
    done = parsed[-1][1]
    assert done["reply"] == NOT_FOUND_TEXT and done["citations"] == []


def test_a_cited_study_answer_streams_and_keeps_its_citation(client, physics):
    use_fakes(
        {"main": FakeProvider(replies=["Entropy always increases [1]."]), "backup": FakeProvider()}
    )
    chat_id = new_chat(client, mode="study", document_ids=[physics["id"]])

    done = events(ask(client, chat_id))[-1][1]

    assert done["reply"] == "Entropy always increases [1]."
    assert [c["n"] for c in done["citations"]] == [1]


@pytest.mark.parametrize("stop_at", [1])
def test_a_stopped_study_answer_is_kept_not_turned_into_not_found(client, physics, stop_at):
    chat_id = new_chat(client, mode="study", document_ids=[physics["id"]])

    def press_stop(piece_number: int):
        if piece_number == stop_at:
            client.post(f"/api/conversations/{chat_id}/stop")

    use_fakes(
        {
            "main": FakeProvider(
                replies=["Entropy always increases [1]."], before_piece=press_stop
            ),
            "backup": FakeProvider(),
        }
    )

    done = events(ask(client, chat_id))[-1][1]

    assert done["stopped"] is True
    assert done["reply"] == "Entropy" + STOPPED_NOTE  # cut before its citation, still kept


# --- SMA-69: paths coverage showed were untested --------------------------------------------


def test_a_bug_while_streaming_ends_with_an_error_event_that_names_the_request(client):
    """A crash (not an AI failure) must still end the stream cleanly, with an id to report."""
    use_fakes({"main": FakeProvider(error=ZeroDivisionError("a bug")), "backup": FakeProvider()})

    response = ask(client, new_chat(client))

    kind, data = events(response)[-1]
    assert kind == "error"
    assert data["error"]["code"] == "internal_error"
    assert "a bug" not in data["error"]["message"]  # internals stay in the logs
    assert data["error"]["request_id"] == response.headers["x-request-id"]


def test_a_study_answer_cut_off_midway_keeps_the_part_that_arrived(client, physics, db_session):
    flaky = FakeProvider(replies=["Entropy always increases [1]."], fail_after_pieces=2)
    use_fakes({"main": flaky, "backup": FakeProvider(replies=["never used"])})
    chat_id = new_chat(client, mode="study", document_ids=[physics["id"]])

    kind, data = events(ask(client, chat_id))[-1]

    assert kind == "error" and "cut off" in data["error"]["message"]
    saved = saved_answer(db_session)
    assert saved.content == "Entropy always" + CUT_OFF_NOTE
    assert saved.mode == "grounded" and data["message_id"] == saved.id


def test_switching_models_in_a_study_chat_is_remembered(client, physics):
    use_fakes({"main": FakeProvider(), "backup": FakeProvider(replies=["Entropy rises [1]."])})
    chat_id = new_chat(client, mode="study", document_ids=[physics["id"]])

    reply = client.post(
        f"/api/conversations/{chat_id}/messages",
        json={"message": "What is entropy?", "model": "backup"},
    ).json()

    assert reply["model"] == "fake-model"  # the fake answered as the backup model
    assert client.get(f"/api/conversations/{chat_id}").json()["model"] == "backup"
