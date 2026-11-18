"""Shared helpers for tests of chat with MCP tools (SMA-42, SMA-43).

The fixtures that use them (tool_fakes, tool_chat) are in conftest.py.
"""

import json

from app.services.llm.base import ToolCall
from app.services.llm.registry import ModelRegistry

REGISTRY = ModelRegistry.model_validate(
    {
        "version": 1,
        "providers": {"p": {"base_url": "https://p.test/v1", "api_key_env": "P_KEY"}},
        "models": [
            {
                "id": "tools-model",
                "provider": "p",
                "display_name": "With tools",
                "priority": 1,
                "supports_tools": True,
                "default_for": ["chat"],
            },
            {
                "id": "plain-model",
                "provider": "p",
                "display_name": "No tools",
                "priority": 2,
                "supports_tools": False,
            },
        ],
    }
)
QUESTION = "Add a task to finish thermodynamics notes by Sunday, then list my pending tasks"


def call(name: str, arguments: dict, call_id: str = "") -> ToolCall:
    return ToolCall(id=call_id or f"call_{name}", name=name, arguments=json.dumps(arguments))
