"""Summaries through the API: written at upload, cached, regenerated on request. SMA-50.

Done when: every ready document shows a summary and key points without re-calling the LLM
on each view.
"""

import json

import pytest
from sqlalchemy import select

from app.main import app
from app.models import LLMCall
from app.services.llm.fake import FakeProvider
from app.services.llm.fallback import FallbackManager, get_fallback_manager
from app.services.llm.registry import ModelRegistry, get_registry

REGISTRY = ModelRegistry.model_validate(
    {
        "version": 1,
        "providers": {"p": {"base_url": "https://p.test/v1", "api_key_env": "P_KEY"}},
        "models": [
            {"id": "m", "provider": "p", "display_name": "M", "priority": 1, "supports_json": True}
        ],
    }
)
NOTES = b"Entropy always increases in an isolated system, so heat flows from hot to cold."


def summary_json(text: str, points: list[str]) -> str:
    return json.dumps({"summary": text, "key_points": points})


@pytest.fixture
def ai(client) -> FakeProvider:
    fake = FakeProvider(replies=[summary_json("About entropy.", ["Entropy increases."])])
    manager = FallbackManager(REGISTRY, lambda m: fake)
    app.dependency_overrides[get_registry] = lambda: REGISTRY
    app.dependency_overrides[get_fallback_manager] = lambda: manager
    return fake


def upload(client, data=NOTES, name="notes.md") -> dict:
    response = client.post("/api/documents", files={"file": (name, data, "text/markdown")})
    events = [json.loads(line) for line in response.text.splitlines()]
    return events


def test_tests_never_reach_the_real_chat_api(client):
    # conftest gives every test client a fake AI, like the fake embedder (SMA-47).
    manager = app.dependency_overrides[get_fallback_manager]()

    assert isinstance(manager.provider_factory(manager.registry.enabled_models()[0]), FakeProvider)


# --- Done when: every ready document shows its summary, without calling the LLM again -------------


def test_an_upload_writes_the_summary_and_key_points(client, ai):
    events = upload(client)

    assert [e["stage"] for e in events][-2:] == ["summarizing", "ready"]
    document = events[-1]["document"]
    assert (document["summary"], document["key_points"]) == (
        "About entropy.",
        ["Entropy increases."],
    )


def test_viewing_a_document_never_calls_the_llm_again(client, ai):
    document_id = upload(client)[-1]["document"]["id"]
    calls_after_upload = len(ai.calls)

    for _ in range(3):
        shown = client.get(f"/api/documents/{document_id}").json()
        assert shown["summary"] == "About entropy."
    client.get("/api/documents")

    assert len(ai.calls) == calls_after_upload == 1  # cached in the database


def test_the_summary_call_is_logged(client, ai, db_session):
    upload(client)

    assert [c.mode for c in db_session.scalars(select(LLMCall))] == ["summary"]


def test_a_failed_summary_leaves_a_ready_document_without_one(client, ai):
    ai.replies = ["Not JSON at all."]

    document = upload(client)[-1]["document"]

    assert (document["status"], document["summary"], document["key_points"]) == (
        "ready",
        None,
        None,
    )


# --- Regenerate on request ------------------------------------------------------------------------


def test_regenerate_writes_a_new_summary_in_the_chosen_style(client, ai):
    document_id = upload(client)[-1]["document"]["id"]
    ai.replies = [summary_json("A longer summary.", ["One.", "Two.", "Three."])]

    response = client.post(f"/api/documents/{document_id}/summary", json={"style": "detailed"})

    assert response.status_code == 200, response.text
    assert response.json()["summary"] == "A longer summary."
    assert "paragraphs" in ai.calls[-1][0]["content"]  # the detailed style was asked for
    assert client.get(f"/api/documents/{document_id}").json()["key_points"] == [
        "One.",
        "Two.",
        "Three.",
    ]


def test_regenerate_defaults_to_short(client, ai):
    document_id = upload(client)[-1]["document"]["id"]
    ai.replies = [summary_json("Short.", ["One."])]

    client.post(f"/api/documents/{document_id}/summary", json={})

    assert "3 or 4 sentences" in ai.calls[-1][0]["content"]


def test_a_failed_regenerate_keeps_the_old_summary_and_says_why(client, ai):
    document_id = upload(client)[-1]["document"]["id"]
    ai.replies = ["Not JSON."]

    response = client.post(f"/api/documents/{document_id}/summary", json={"style": "short"})

    assert response.status_code == 503
    assert "unexpected answer" in response.json()["error"]["message"]
    assert client.get(f"/api/documents/{document_id}").json()["summary"] == "About entropy."


def test_only_a_ready_document_can_be_summarised(client, ai):
    failed = upload(client, data=b"x" * 5, name="tiny.md")[-1]["document"]  # "No text found"

    response = client.post(f"/api/documents/{failed['id']}/summary", json={"style": "short"})

    assert response.status_code == 409


def test_an_unknown_style_is_refused(client, ai):
    document_id = upload(client)[-1]["document"]["id"]

    response = client.post(f"/api/documents/{document_id}/summary", json={"style": "poem"})

    assert response.status_code == 422
