"""The shared "ask for JSON, check, repair once" helper (structured.py). SMA-64.

Quizzes and flashcards test their own rules; this checks what the helper alone adds.
"""

from pydantic import BaseModel

from app.services.llm.base import ChatOptions
from app.services.llm.fake import FakeProvider
from app.services.llm.fallback import FallbackManager
from app.services.llm.registry import ModelRegistry
from app.services.structured import ask_for_json, parse_as

# The plain model comes FIRST: a JSON request must still skip it.
REGISTRY = ModelRegistry.model_validate(
    {
        "version": 1,
        "providers": {"p": {"base_url": "https://p.test/v1", "api_key_env": "P_KEY"}},
        "models": [
            {
                "id": "plain",
                "provider": "p",
                "display_name": "Plain",
                "priority": 1,
                "supports_json": False,
            },
            {
                "id": "json",
                "provider": "p",
                "display_name": "JSON",
                "priority": 2,
                "supports_json": True,
            },
        ],
    }
)


class _Answer(BaseModel):
    ok: bool


def test_only_a_model_that_promises_json_is_asked():
    plain = FakeProvider(replies=['{"ok": true}'])
    json_model = FakeProvider(replies=['{"ok": true}'])
    fakes = {"plain": plain, "json": json_model}
    manager = FallbackManager(REGISTRY, lambda model: fakes[model.id])

    answer, attempts = ask_for_json(
        manager,
        [{"role": "user", "content": "hi"}],
        ChatOptions(json_mode=True),
        check=lambda reply: parse_as(_Answer, reply),
        repair_note=lambda problem: problem,
    )

    assert answer.ok is True
    assert plain.calls == []  # never asked: it can't promise JSON
    assert [a.model for a in attempts] == ["json"]
