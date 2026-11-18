"""The write-action policy (guide 7.2): what the AI may do on its own. SMA-43.

Only the student's OWN message can authorise a write. Text in notes, documents or tool
results never can: the model may be fooled by "ignore previous instructions...", but this
code only looks at the tool's tag and at what the student typed.

    read                       -> run
    create, the student asked  -> run (shown with an Undo button)
    create, not asked for      -> hold (a confirmation card)
    change                     -> hold (a confirmation card), always
"""

import re
from typing import Literal

Kind = Literal["read", "create", "change"]
Decision = Literal["run", "hold"]

# Words that show the student asked for something to be DONE, not just answered.
# Whole words only ("address" doesn't match "add"). A miss is safe: the write becomes a card.
ACTION_WORDS = re.compile(
    r"\b(add|create|make|save|remind|schedule|plan|put|note down|set up|new task)\b",
    re.IGNORECASE,
)


def asks_to_act(message: str) -> bool:
    """Does the student's own message ask for something to be created?"""
    return ACTION_WORDS.search(message) is not None


def decide(kind: Kind, user_asked_to_act: bool) -> Decision:
    if kind == "read":
        return "run"
    if kind == "create" and user_asked_to_act:
        return "run"
    return "hold"  # changes, and any write the student didn't ask for
