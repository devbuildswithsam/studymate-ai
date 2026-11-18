"""The write-action policy (guide 7.2): which tool calls run and which wait for you. SMA-43.

The rule is code, not a prompt: the model can be talked into anything, the code can't.
"""

import pytest

from app.mcp_server.server import TOOL_KINDS, mcp_server
from app.services.tool_policy import asks_to_act, decide


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_every_tool_is_tagged_read_create_or_change():
    names = {t.name for t in await mcp_server.list_tools()}

    assert set(TOOL_KINDS) == names  # a new tool without a tag fails here
    assert set(TOOL_KINDS.values()) <= {"read", "create", "change"}


def test_the_tags():
    assert TOOL_KINDS == {
        "list_tasks": "read",
        "search_notes": "read",
        "create_task": "create",
        "save_note": "create",
        "update_task": "change",
        "complete_task": "change",
    }


@pytest.mark.parametrize(
    "kind, user_asked, expected",
    [
        ("read", False, "run"),  # reading runs automatically
        ("read", True, "run"),
        ("create", True, "run"),  # a create you asked for runs (with Undo)
        ("create", False, "hold"),  # a create you didn't ask for waits for you
        ("change", True, "hold"),  # a change always waits for you
        ("change", False, "hold"),
    ],
)
def test_decide(kind, user_asked, expected):
    assert decide(kind, user_asked) == expected


@pytest.mark.parametrize(
    "message",
    [
        "Add a task to finish thermodynamics notes by Sunday",
        "please create a task for my essay",
        "Save this as a note",
        "remind me to revise chapter 3 on Friday",
        "Make a note: entropy always increases",
        "Schedule revision for Monday",
        "ADD TASK: read ch. 2",
    ],
)
def test_messages_that_ask_for_an_action(message):
    assert asks_to_act(message) is True


@pytest.mark.parametrize(
    "message",
    [
        "What do my notes say about thermodynamics?",
        "list my pending tasks",
        "Explain the second law",
        "What is an address in memory?",  # "add" inside a word doesn't count
        "What is the input of a compiler?",  # nor "put" at the end of one
        "Summarise my notes",
    ],
)
def test_messages_that_do_not(message):
    assert asks_to_act(message) is False
