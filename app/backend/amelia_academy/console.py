"""What the model is doing, for the console at the foot of the page.

Every model call passes through a client's `_chat`, so this sees all of them. It lives in memory: it holds
recent work since the server started, and the dataset never depends on it.
"""

import threading
import time
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone

from . import agents

MAX_LINES = 400
MAX_SENT = 150  # lines sent to a page that has seen none yet
MAX_TEXT = 8000  # of each prompt and reply kept for reading
MAX_LIVE = 3000  # of the reply being written, sent at each poll
PREVIEW = 200

_agent = ContextVar("console_agent", default="")
_lock = threading.Lock()
_lines: deque = deque(maxlen=MAX_LINES)
_running: dict[int, dict] = {}
_tally: dict[str, dict] = {}
_seq = 0


def _next() -> int:
    global _seq
    _seq += 1
    return _seq


def _count(agent: str) -> dict:
    return _tally.setdefault(agent, {"calls": 0, "problems": 0, "prompt_tokens": 0, "output_tokens": 0,
                                     "seconds": 0.0, "kept": 0, "turned_down": 0})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def acting(agent: str):
    """Model calls inside this block are the named agent's. A name outside the group is a bug, so it raises."""
    if agent not in agents.BY_NAME:
        raise KeyError(f"no agent named {agent}")
    token = _agent.set(agent)
    try:
        yield
    finally:
        _agent.reset(token)


def begin(model: str, prompt: str) -> int:
    with _lock:
        call = _next()
        _running[call] = {"agent": _agent.get(), "model": model, "prompt": prompt, "started": time.monotonic(), "text": "", "pieces": 0}
    return call


def progress(call: int, piece: str) -> None:
    """A piece of the reply as the model writes it. Ollama sends about one token per piece."""
    with _lock:
        running = _running[call]
        running["text"] = (running["text"] + piece)[-MAX_TEXT:]
        running["pieces"] += 1


def end(call: int, reply: str = "", error: str = "", prompt_tokens: int = 0, output_tokens: int = 0, stopped: bool = False) -> None:
    with _lock:
        started = _running.pop(call)
        seconds = round(time.monotonic() - started["started"], 1)
        count = _count(started["agent"])
        count["calls"] += 1
        count["problems"] += 1 if error else 0
        count["prompt_tokens"] += prompt_tokens
        count["output_tokens"] += output_tokens
        count["seconds"] = round(count["seconds"] + seconds, 1)
        # Numbered now, not at begin: a page that polled during the call is already past the number begin took.
        _lines.append({"seq": _next(), "at": _now(), "kind": "call", "agent": started["agent"], "model": started["model"],
                       "seconds": seconds, "prompt_tokens": prompt_tokens, "output_tokens": output_tokens, "error": error,
                       "text": "Stopped by you." if stopped else reply[:PREVIEW], "prompt": started["prompt"][:MAX_TEXT],
                       "reply": started["text"] if stopped else reply[:MAX_TEXT]})


def problem(text: str) -> None:
    """Something went wrong after the call returned, such as a reply that broke the agreed shape."""
    with _lock:
        agent = _agent.get()
        _count(agent)["problems"] += 1
        _lines.append({"seq": _next(), "at": _now(), "kind": "problem", "agent": agent, "error": text})


def outcome(agent: str, where: str, kept: int, reasons: list[str]) -> None:
    """What the checks did with what an agent wrote: this is where a model that errs a lot shows."""
    with _lock:
        count = _count(agent)
        count["kept"] += kept
        count["turned_down"] += len(reasons)
        _lines.append({"seq": _next(), "at": _now(), "kind": "outcome", "agent": agent, "where": where,
                       "kept": kept, "turned_down": len(reasons), "reasons": reasons[:20]})


def snapshot(after: int = 0) -> dict:
    with _lock:
        now = time.monotonic()
        fresh = [{k: v for k, v in line.items() if k not in ("prompt", "reply")} for line in _lines if line["seq"] > after]
        return {
            "last_seq": _seq,
            "lines": fresh[-MAX_SENT:],
            "running": [{"agent": r["agent"], "model": r["model"], "seconds": round(now - r["started"], 1),
                         "text": r["text"][-MAX_LIVE:], "tokens": r["pieces"]} for r in _running.values()],
            "agents": [{**agent, **_count_view(agent["name"])} for agent in agents.AGENTS],
            "unnamed": _count_view(""),
        }


def _count_view(name: str) -> dict:
    return dict(_tally.get(name) or {"calls": 0, "problems": 0, "prompt_tokens": 0, "output_tokens": 0,
                                     "seconds": 0.0, "kept": 0, "turned_down": 0})


def line(seq: int) -> dict | None:
    """One line whole, with its prompt and reply. Old lines fall off the end."""
    with _lock:
        return next((dict(item) for item in _lines if item["seq"] == seq), None)


def clear() -> None:
    global _seq
    with _lock:
        _lines.clear()
        _running.clear()
        _tally.clear()
        _seq = 0
