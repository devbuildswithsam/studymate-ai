"""The chat's agent loop: the model asks for MCP tools, we run them, results go back. SMA-42.

The AI is always a FakeProvider (CLAUDE.md). The tools are the app's real MCP server, in
memory, acting for a real user on the temporary test database (SMA-41's trusted context).
"""

import json

import pytest

from app.db.session import _session_factory
from app.mcp_server.context import ToolContext
from app.models import Task, User
from app.services.agent import MAX_TOOL_CALLS, run_agent_for_user
from app.services.llm.base import ChatOptions, ToolCall
from app.services.llm.exceptions import AllModelsFailedError, ProviderTimeoutError
from app.services.llm.fake import FakeProvider
from app.services.llm.fallback import FallbackManager
from app.services.llm.registry import ModelRegistry
from app.services.tool_policy import asks_to_act

REGISTRY = ModelRegistry.model_validate(
    {
        "version": 1,
        "providers": {"p": {"base_url": "https://p.test/v1", "api_key_env": "P_KEY"}},
        "models": [
            {
                "id": "main",
                "provider": "p",
                "display_name": "Main",
                "priority": 1,
                "supports_tools": True,
            },
            {
                "id": "backup",
                "provider": "p",
                "display_name": "Backup",
                "priority": 2,
                "supports_tools": True,
            },
        ],
    }
)
QUESTION = "Add a task to finish thermodynamics notes by Sunday, then list my pending tasks"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def user(db_session) -> User:
    user = User(email="student@example.com")
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def tools_session(db_url, user) -> ToolContext:
    """The tool context the backend sets: act for `user` on the test database."""
    return ToolContext(user.id, _session_factory(db_url))


def call(name: str, arguments, call_id: str = "") -> ToolCall:
    text = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return ToolCall(id=call_id or f"call_{name}", name=name, arguments=text)


def manager_for(main: FakeProvider, backup: FakeProvider | None = None) -> FallbackManager:
    fakes = {"main": main, "backup": backup or FakeProvider(replies=["backup answer"])}
    return FallbackManager(REGISTRY, lambda m: fakes[m.id])


def start(question: str = QUESTION) -> list[dict]:
    return [
        {"role": "system", "content": "You are StudyMate."},
        {"role": "user", "content": question},
    ]


async def run(context, manager, messages=None):
    messages = messages or start()
    # SMA-43: like the chat route, only the student's own (last) message can ask to act.
    asked = asks_to_act(messages[-1]["content"])
    return await run_agent_for_user(
        context, manager, messages, "main", True, ChatOptions(), user_asked_to_act=asked
    )


# --- Done when: "Add a task ... by Sunday, then list my pending tasks" --------------


@pytest.mark.anyio
async def test_add_a_task_then_list_pending_tasks(tools_session, db_session, user):
    main = FakeProvider(
        replies=[
            [
                call(
                    "create_task",
                    {"title": "Finish thermodynamics notes", "due_date": "2026-11-22"},
                )
            ],
            [call("list_tasks", {"status": "todo"})],
            "Added it. Pending: Finish thermodynamics notes (due Sunday).",
        ]
    )

    run_ = await run(tools_session, manager_for(main))

    assert run_.response.text.startswith("Added it.")
    assert [s.name for s in run_.steps] == ["create_task", "list_tasks"]
    assert not any(s.is_error for s in run_.steps)
    task = db_session.query(Task).one()
    assert (task.title, task.user_id, task.created_by) == (
        "Finish thermodynamics notes",
        user.id,
        "ai",
    )


@pytest.mark.anyio
async def test_the_model_gets_the_tools_and_each_result_with_its_call_id(tools_session):
    main = FakeProvider(replies=[[call("list_tasks", {}, call_id="c1")], "No tasks."])

    await run(tools_session, manager_for(main))

    offered = {t["function"]["name"] for t in main.options[0].tools}
    assert offered == {
        "create_task",
        "list_tasks",
        "update_task",
        "complete_task",
        "save_note",
        "search_notes",
    }
    second_turn = main.calls[1]
    assert second_turn[-2]["role"] == "assistant"
    assert second_turn[-2]["tool_calls"][0]["id"] == "c1"
    assert second_turn[-1] == {"role": "tool", "tool_call_id": "c1", "content": '{"result": []}'}


@pytest.mark.anyio
async def test_provider_extras_like_geminis_thought_signature_are_sent_back(tools_session):
    extra = {"extra_content": {"google": {"thought_signature": "abc"}}}
    signed = ToolCall("c1", "list_tasks", "{}", extra=extra)
    main = FakeProvider(replies=[[signed], "No tasks."])

    await run(tools_session, manager_for(main))

    assert main.calls[1][-2]["tool_calls"][0]["extra_content"] == extra["extra_content"]


# --- Mistakes go back to the model as errors ----------------------------------------


@pytest.mark.anyio
async def test_an_invalid_argument_is_reported_back_and_the_model_can_fix_it(
    tools_session, db_session
):
    main = FakeProvider(
        replies=[
            [call("create_task", {"title": "Essay", "priority": "urgent"}, call_id="bad")],
            [call("create_task", {"title": "Essay", "priority": "high"}, call_id="good")],
            "Added Essay.",
        ]
    )

    run_ = await run(tools_session, manager_for(main))

    assert [s.is_error for s in run_.steps] == [True, False]
    assert "priority" in main.calls[1][-1]["content"]
    assert db_session.query(Task).count() == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    "bad_call, expected",
    [
        (call("create_task", {"title": "x", "user_id": "someone-else"}), "user_id"),
        (call("create_task", "{not json"), "not valid JSON"),
        (call("delete_everything", {}), "delete_everything"),
    ],
    ids=["injected user_id", "broken JSON", "unknown tool"],
)
async def test_rejected_calls_become_error_results_not_crashes(
    tools_session, db_session, bad_call, expected
):
    main = FakeProvider(replies=[[bad_call], "Sorry, that didn't work."])

    run_ = await run(tools_session, manager_for(main))

    assert run_.steps[0].is_error
    assert expected in main.calls[1][-1]["content"]
    assert run_.response.text == "Sorry, that didn't work."
    assert db_session.query(Task).count() == 0


# --- Stop conditions -------------------------------------------------------------------


@pytest.mark.anyio
async def test_at_most_5_tool_calls_per_message(tools_session):
    looping = FakeProvider(replies=[[call("list_tasks", {})]])  # never answers

    run_ = await run(tools_session, manager_for(looping))

    assert len(run_.steps) == MAX_TOOL_CALLS == 5
    assert run_.stopped_early is True
    assert "5 tool calls" in run_.response.text


@pytest.mark.anyio
async def test_the_limit_counts_calls_inside_one_turn(tools_session):
    burst = FakeProvider(replies=[[call("list_tasks", {}, call_id=f"c{n}") for n in range(8)]])

    run_ = await run(tools_session, manager_for(burst))

    assert len(run_.steps) == 5
    assert run_.stopped_early is True


@pytest.mark.anyio
async def test_a_plain_answer_uses_no_tools(tools_session):
    main = FakeProvider(replies=["Osmosis is water moving through a membrane."])

    run_ = await run(tools_session, manager_for(main))

    assert run_.steps == []
    assert run_.response.text.startswith("Osmosis")
    assert len(main.calls) == 1


# --- Models and logging ------------------------------------------------------------------


class FailsOnce(FakeProvider):
    """Times out on its first call only."""

    def chat(self, messages, options=None):
        if not self.calls:
            self.calls.append(list(messages))
            raise ProviderTimeoutError("slow", "p")
        return super().chat(messages, options)


@pytest.mark.anyio
async def test_after_the_first_turn_the_loop_stays_on_the_model_that_answered(tools_session):
    # Provider extras (Gemini's thought signatures) only make sense to that provider.
    main = FailsOnce(replies=["main answer"])
    backup = FakeProvider(replies=[[call("list_tasks", {})], "backup's final answer"])

    run_ = await run(tools_session, manager_for(main, backup))

    assert run_.response.text == "backup's final answer"
    assert len(main.calls) == 1  # only the failed first try, never again
    assert run_.fallback_used is True


@pytest.mark.anyio
async def test_only_models_that_can_call_tools_are_used(tools_session):
    registry = REGISTRY.model_copy(deep=True)
    registry.models[1].supports_tools = False  # backup can't call tools
    main = FakeProvider(error=ProviderTimeoutError("slow", "p"))
    no_tools = FakeProvider(replies=["I would have answered without tools"])
    manager = FallbackManager(registry, lambda m: {"main": main, "backup": no_tools}[m.id])

    with pytest.raises(AllModelsFailedError):
        await run(tools_session, manager)

    assert no_tools.calls == []  # never offered tools it can't use


@pytest.mark.anyio
async def test_every_model_call_of_every_turn_is_reported(tools_session):
    main = FakeProvider(replies=[[call("list_tasks", {})], [call("list_tasks", {})], "Done."])

    run_ = await run(tools_session, manager_for(main))

    assert [a.status for a in run_.attempts] == ["ok", "ok", "ok"]  # three turns
    assert run_.tokens_in > 0 and run_.tokens_out > 0


@pytest.mark.anyio
async def test_tool_steps_record_what_was_called_and_how_it_went(tools_session):
    main = FakeProvider(replies=[[call("create_task", {"title": "Read ch. 2"})], "Done."])

    run_ = await run(tools_session, manager_for(main))

    step = run_.steps[0]
    assert (step.name, json.loads(step.arguments)) == ("create_task", {"title": "Read ch. 2"})
    assert json.loads(step.result)["title"] == "Read ch. 2"
    assert step.duration_ms >= 0


@pytest.mark.anyio
async def test_if_the_answering_model_fails_mid_loop_it_does_not_switch_provider(tools_session):
    # Turn 1 is answered by backup (main timed out). If backup then fails, the loop stops:
    # sending backup's history (with its provider extras) to another provider could break.
    main = FailsOnce(replies=["main would answer now"])

    class FailsSecondTime(FakeProvider):
        def chat(self, messages, options=None):
            if self.calls:
                self.calls.append(list(messages))
                raise ProviderTimeoutError("slow", "p")
            return super().chat(messages, options)

    backup = FailsSecondTime(replies=[[call("list_tasks", {})]])

    with pytest.raises(AllModelsFailedError):
        await run(tools_session, manager_for(main, backup))

    assert len(main.calls) == 1  # main was not asked again mid-loop


# --- Write-action policy (SMA-43) ----------------------------------------------------------


@pytest.fixture
def a_task(db_session, user) -> Task:
    task = Task(user_id=user.id, title="Revise ch.3")
    db_session.add(task)
    db_session.commit()
    return task


@pytest.mark.anyio
async def test_a_change_is_held_even_when_the_student_asks_for_it(
    tools_session, db_session, a_task
):
    main = FakeProvider(replies=[[call("complete_task", {"task_id": a_task.id})], "Confirm it?"])

    run_ = await run(tools_session, manager_for(main), start("Please complete my Revise ch.3 task"))

    step = run_.steps[0]
    assert (step.held, step.is_error) == (True, False)
    db_session.refresh(a_task)
    assert a_task.status == "todo"  # nothing changed: it waits for the Confirm click
    told = main.calls[1][-1]["content"]  # the model is told it is NOT done, and why
    assert told.startswith("Not done yet") and "needs the student's confirmation" in told


@pytest.mark.anyio
async def test_a_create_the_student_did_not_ask_for_is_held(tools_session, db_session):
    main = FakeProvider(replies=[[call("create_task", {"title": "Read about entropy"})], "Ok."])

    run_ = await run(tools_session, manager_for(main), start("What is entropy?"))

    assert run_.steps[0].held is True
    assert db_session.query(Task).count() == 0


@pytest.mark.anyio
async def test_a_create_the_student_asked_for_runs(tools_session, db_session):
    main = FakeProvider(replies=[[call("create_task", {"title": "Essay"})], "Added."])

    run_ = await run(tools_session, manager_for(main), start("Add a task: essay"))

    assert run_.steps[0].held is False
    assert db_session.query(Task).count() == 1


@pytest.mark.anyio
async def test_reads_always_run(tools_session):
    main = FakeProvider(replies=[[call("list_tasks", {})], "Nothing."])

    run_ = await run(tools_session, manager_for(main), start("What is entropy?"))

    assert (run_.steps[0].held, run_.steps[0].result) == (False, '{"result": []}')


@pytest.mark.anyio
async def test_a_held_call_with_an_unknown_argument_is_an_error_not_a_card(tools_session, a_task):
    bad = call("complete_task", {"task_id": a_task.id, "user_id": "someone-else"})
    main = FakeProvider(replies=[[bad], "Sorry."])

    run_ = await run(tools_session, manager_for(main), start("complete my task"))

    assert (run_.steps[0].held, run_.steps[0].is_error) == (False, True)
    assert "user_id" in run_.steps[0].result
