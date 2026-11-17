# MCP lab (Stage 3a)

A tiny MCP server, **separate from the app**, to learn the protocol itself. SMA-36.
Uses the MCP Python SDK **2.3.0** (pinned in `pyproject.toml`). In 2.x, `FastMCP` is
called `MCPServer` (`from mcp.server.mcpserver import MCPServer`), so 1.x tutorials won't run.

## The three MCP primitives
| Primitive | Who uses it | Here |
|---|---|---|
| **Tool** | the AI calls it to *do* something | `add_task`, `list_tasks`, `complete_task` |
| **Resource** | the AI (or app) *reads* it, like a file | `tasks://summary` |
| **Prompt** | the *user* picks a ready-made instruction | `plan_my_day` |

A tool's Python type hints and `Field(...)` descriptions become its **JSON Schema**: that
is all the AI knows about the tool's inputs. Tasks are stored in `lab.db` (throwaway,
git-ignored).

## Setup (once)
From the repo root, in Command Prompt:

```bat
cd mcp_lab
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

## Tests
They talk to the server through the real MCP protocol, in-process (`mcp.Client(server.mcp)`).

```bat
cd mcp_lab
.venv\Scripts\python -m pytest
```

The app's `pytest` (repo root or `backend\`) doesn't run these.

## Explore it in MCP Inspector
The Inspector is a web page that acts as an MCP client. Node 22 is needed (already installed).

```bat
cd mcp_lab
npx @modelcontextprotocol/inspector@2.15.0 .venv\Scripts\python.exe server.py
```

It opens the Inspector in your browser (the URL includes a session token). Then:
1. **Connect** (transport: STDIO, the command is already filled in).
2. **Tools** → *List Tools* → `add_task` → fill in a title (and a date like `2026-11-22`) → *Run Tool*.
   Try `list_tasks`, `complete_task` with the id, and `complete_task` with id `99` (an error the AI can read).
3. **Resources** → *List Resources* → `tasks://summary`.
4. **Prompts** → *List Prompts* → `plan_my_day` → `hours_available` = 2 → *Get Prompt*.

Stop it with **Ctrl+C** in the terminal.

## Run the server on its own
```bat
.venv\Scripts\python server.py
```
It waits silently for JSON-RPC messages on stdin: a client starts it this way. Over stdio,
stdout is the protocol channel, so the server never uses `print()`; its logs go to stderr.
