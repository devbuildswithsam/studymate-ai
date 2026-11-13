"""SMA-17: check each enabled model for chat, tool calling and JSON output.

Run from backend/ with the venv active:
    python -m scripts.check_models
    python -m scripts.check_models --only gemini-3.8-flash
"""

import argparse
import json
import time

from openai import APIConnectionError, APIStatusError

from app.services.llm.registry import client_for, enabled_models, load_registry

# The same kind of tool the MCP server will expose in Stage 3.
TASK_TOOL = {
    "type": "function",
    "function": {
        "name": "create_task",
        "description": "Create a study task for the user.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short task title"},
                "due_date": {"type": "string", "description": "Due date as YYYY-MM-DD"},
            },
            "required": ["title"],
        },
    },
}


def check_chat(client, model):
    r = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Reply with exactly the word OK."}],
        max_tokens=200,
    )
    text = (r.choices[0].message.content or "").strip()
    return bool(text), text[:60]


def check_tools(client, model):
    """Does the model call our tool, by name, with valid JSON arguments?"""
    r = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "Today is 2026-11-13. Use the tools when the user asks to create a task.",
            },
            {"role": "user", "content": "Add a task to revise physics chapter 3 by 2026-11-20."},
        ],
        tools=[TASK_TOOL],
        tool_choice="auto",
        max_tokens=1024,
    )
    calls = r.choices[0].message.tool_calls or []
    if not calls:
        return False, "answered in text, no tool call"
    call = calls[0]
    args = json.loads(call.function.arguments)  # must be valid JSON
    ok = call.function.name == "create_task" and "title" in args
    return ok, f"{call.function.name}({args})"


def check_json(client, model):
    """Can the model return valid JSON in the shape a quiz needs?"""
    r = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "Reply only with a JSON object."},
            {
                "role": "user",
                "content": "One multiple-choice question about photosynthesis as JSON with keys "
                '"question" (string), "options" (list of 4 strings), "answer_index" (0-3).',
            },
        ],
        response_format={"type": "json_object"},
        max_tokens=1024,
    )
    data = json.loads(r.choices[0].message.content or "")
    ok = (
        isinstance(data.get("options"), list)
        and len(data["options"]) == 4
        and data.get("answer_index") in range(4)
    )
    return ok, str(data.get("question", ""))[:60]


def run(check, client, model):
    start = time.perf_counter()
    try:
        ok, detail = check(client, model)
    except APIStatusError as e:
        ok, detail = False, f"HTTP {e.status_code}: {str(e.body)[:120]}"
    except APIConnectionError:
        ok, detail = False, "connection error"
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as e:
        ok, detail = False, f"bad output ({type(e).__name__})"
    return ok, detail, time.perf_counter() - start


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="check a single model id")
    args = parser.parse_args()

    registry = load_registry()
    for m in enabled_models(registry):
        if args.only and m["id"] != args.only:
            continue
        print(f"\n{m['id']}  ({m['provider']})")
        try:
            client = client_for(registry, m["provider"])
        except RuntimeError as e:
            print(f"  skipped: {e}")
            continue
        results = {}
        for name, check in (("chat", check_chat), ("tools", check_tools), ("json", check_json)):
            ok, detail, secs = run(check, client, m["id"])
            results[name] = ok
            print(f"  {name:<6}{'PASS' if ok else 'FAIL'}  {secs:5.1f}s  {detail}")
        print(
            f"  -> supports_tools: {str(results['tools']).lower()}, supports_json: {str(results['json']).lower()}"
        )


if __name__ == "__main__":
    main()
