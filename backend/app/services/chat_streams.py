"""Streaming chat answers to the browser (Server-Sent Events) and the Stop button. SMA-62.

Server-Sent Events: one HTTP response that stays open and sends small text events,
    event: token
    data: {"text": "Entropy "}

    (a blank line ends each event). The browser reads them as they arrive.

The answer is made in a worker thread (the AI calls block); it puts events on a queue, and
the response reads the queue and sends them. Stop: POST .../stop flips this answer's
switch; the provider checks it between pieces, the answer ends, and what arrived is saved.
A closed tab flips the same switch.

The switches live in this process's memory: fine for one server process (v1.1). Several
processes would need a shared store (e.g. Redis), noted for deployment (Stage 6).
"""

import json
import queue
import threading
from collections.abc import AsyncIterator, Callable

import anyio
import anyio.lowlevel
from anyio.lowlevel import EventLoopToken
from starlette.requests import Request

# Added to a saved answer that didn't finish, so it's clear when the chat is reopened.
STOPPED_NOTE = "\n\n*(Stopped)*"
CUT_OFF_NOTE = "\n\n*(The answer was cut off. You can ask again.)*"

Emit = Callable[[str, dict], None]  # emit("token", {"text": "..."}) from the worker thread

_running: dict[tuple[str, str], threading.Event] = {}  # (user_id, conversation_id) -> switch
_lock = threading.Lock()


def start(user_id: str, conversation_id: str) -> threading.Event:
    """A new Stop switch for this conversation's answer (one answer at a time)."""
    switch = threading.Event()
    with _lock:
        _running[(user_id, conversation_id)] = switch
    return switch


def stop(user_id: str, conversation_id: str) -> bool:
    """Flip the switch of the answer being written; False if none is (or it isn't yours)."""
    with _lock:
        switch = _running.get((user_id, conversation_id))
    if switch is None:
        return False
    switch.set()
    return True


def finish(user_id: str, conversation_id: str, switch: threading.Event) -> None:
    with _lock:
        if _running.get((user_id, conversation_id)) is switch:  # not a newer answer's switch
            del _running[(user_id, conversation_id)]


def sse(kind: str, data: dict) -> str:
    """One Server-Sent Event: its type, its JSON data, and the blank line that ends it."""
    return f"event: {kind}\ndata: {json.dumps(data)}\n\n"


async def event_stream(
    request: Request, work: Callable[[Emit, EventLoopToken], None], switch: threading.Event
) -> AsyncIterator[str]:
    """Run `work` in a worker thread and send what it emits, as it emits it.

    `work` must always end by emitting "done" or "error" (and save before that). It gets
    this event loop's token: the tool chat runs its async agent loop here, from the thread.
    """
    events: queue.Queue = queue.Queue()
    token = anyio.lowlevel.current_token()

    def worker() -> None:
        try:
            work(lambda kind, data: events.put((kind, data)), token)
        finally:
            events.put(None)  # the end, even if `work` crashed

    threading.Thread(target=worker, daemon=True).start()
    try:
        while True:
            try:
                item = events.get_nowait()
            except queue.Empty:
                if await request.is_disconnected():
                    break  # the tab was closed: finally below stops the answer
                await anyio.sleep(0.02)  # check again soon (20 ms: unnoticeable)
                continue
            if item is None:
                break
            yield sse(*item)
    finally:
        # Normally the answer has already finished. If the browser went away mid-answer,
        # this works like Stop: the worker ends the answer and saves what arrived.
        switch.set()
