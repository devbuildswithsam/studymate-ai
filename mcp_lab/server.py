"""MCP lab server (Stage 3a, SMA-36): the three MCP primitives, separate from the app.

- Tools     (the AI *does* something):  add_task, list_tasks, complete_task
- Resource  (the AI *reads* something): tasks://summary
- Prompt    (a ready-made instruction the USER picks): plan_my_day

Run over stdio (the client starts this file and talks to it through stdin/stdout):
    .venv\\Scripts\\python server.py

Over stdio, stdout IS the protocol channel: never print() here, or the JSON-RPC messages
get corrupted. Logs go to stderr.

Uses mcp 2.x, where FastMCP is called MCPServer.
"""

import os
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

# A throwaway SQLite file next to this script (git-ignored). Tests point it elsewhere.
DB_PATH = Path(os.environ.get("MCP_LAB_DB", Path(__file__).with_name("lab.db")))

Priority = Literal["low", "medium", "high"]

mcp = MCPServer(
    "StudyMate MCP lab",
    instructions="A study task list. Use the tools to add, list and complete tasks.",
)


def today() -> date:
    """Today's date (a function, so tests can fix it)."""
    return date.today()


class Task(BaseModel):
    """One task, as the tools return it. Also becomes the tools' output JSON Schema."""

    id: int
    title: str
    due_date: date | None
    priority: Priority
    done: bool


# --- Storage -------------------------------------------------------------------------


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            title    TEXT    NOT NULL,
            due_date TEXT,
            priority TEXT    NOT NULL CHECK (priority IN ('low', 'medium', 'high')),
            done     INTEGER NOT NULL DEFAULT 0
        )
        """)
    return connection


def to_task(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"],
        title=row["title"],
        due_date=row["due_date"],
        priority=row["priority"],
        done=bool(row["done"]),
    )


# Pending first by due date (no date last), then high > medium > low.
ORDER = """
    ORDER BY due_date IS NULL, due_date,
             CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, id
"""


def fetch_tasks(done: bool | None) -> list[Task]:
    """done=None: every task. Values always go in as ? parameters, never into the SQL text."""
    with closing(connect()) as connection:
        if done is None:
            rows = connection.execute(f"SELECT * FROM tasks {ORDER}").fetchall()
        else:
            rows = connection.execute(
                f"SELECT * FROM tasks WHERE done = ? {ORDER}", (int(done),)
            ).fetchall()
    return [to_task(row) for row in rows]


# --- Tools ---------------------------------------------------------------------------
# The type hints and Field(...) descriptions become each tool's JSON Schema, which is
# all the AI knows about a tool. The docstring becomes its description.


@mcp.tool()
def add_task(
    title: Annotated[
        str, Field(min_length=1, max_length=200, description="What to do, e.g. 'Revise ch. 3'")
    ],
    due_date: Annotated[date | None, Field(description="Due date as YYYY-MM-DD, if any")] = None,
    priority: Annotated[Priority, Field(description="How important it is")] = "medium",
) -> Task:
    """Add a study task to the list. Returns the new task with its id."""
    with closing(connect()) as connection, connection:  # second "connection": commit
        cursor = connection.execute(
            "INSERT INTO tasks (title, due_date, priority) VALUES (?, ?, ?)",
            (title, due_date.isoformat() if due_date else None, priority),
        )
        row = connection.execute("SELECT * FROM tasks WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return to_task(row)


@mcp.tool()
def list_tasks(
    status: Annotated[
        Literal["pending", "done", "all"], Field(description="Which tasks to list")
    ] = "pending",
) -> list[Task]:
    """List tasks: pending ones by due date and priority, or done ones, or all."""
    return fetch_tasks(done={"pending": False, "done": True, "all": None}[status])


@mcp.tool()
def complete_task(
    task_id: Annotated[int, Field(description="The task's id, from add_task or list_tasks")],
) -> Task:
    """Mark a task as done. Returns the updated task."""
    with closing(connect()) as connection, connection:
        connection.execute("UPDATE tasks SET done = 1 WHERE id = ?", (task_id,))
        row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        # ToolError: an expected failure. Its message reaches the AI, which can then
        # call list_tasks to find the right id. Other exceptions only say "Error".
        raise ToolError(f"No task with id {task_id}. Call list_tasks to see the ids.")
    return to_task(row)


# --- Resource ------------------------------------------------------------------------


def describe(task: Task, on: date) -> str:
    if task.due_date is None:
        return f"- {task.title} (no due date, {task.priority})"
    when = "OVERDUE" if task.due_date < on else "TODAY" if task.due_date == on else task.priority
    return f"- {task.title} (due {task.due_date.isoformat()}, {when})"


@mcp.resource("tasks://summary", mime_type="text/plain")
def tasks_summary() -> str:
    """A short overview of the task list: counts, then every pending task."""
    on = today()
    pending = fetch_tasks(done=False)
    done_count = len(fetch_tasks(done=True))
    overdue = sum(1 for t in pending if t.due_date and t.due_date < on)
    due_today = sum(1 for t in pending if t.due_date == on)
    lines = [
        f"{len(pending)} pending ({overdue} overdue, {due_today} due today), {done_count} done",
        "",
        *[describe(t, on) for t in pending],
    ]
    return "\n".join(lines)


# --- Prompt --------------------------------------------------------------------------


@mcp.prompt()
def plan_my_day(hours_available: int = 3) -> str:
    """Ask the AI for a study plan for today, based on my pending tasks."""
    on = today()
    pending = fetch_tasks(done=False)
    task_lines = "\n".join(describe(t, on) for t in pending) or "- (no pending tasks)"
    return (
        f"Today is {on.isoformat()}. I have {hours_available} hours to study.\n"
        f"My pending tasks:\n{task_lines}\n\n"
        "Make a realistic plan for today: overdue and today's tasks first, then high "
        "priority. Give each block a time and say which tasks wait for another day."
    )


if __name__ == "__main__":
    mcp.run()  # stdio by default
