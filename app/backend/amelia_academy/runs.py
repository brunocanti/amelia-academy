"""Work a person starts and can leave. It goes on in its own thread, whatever screen they are on, until it ends or they stop it.

Imports nothing from this package, because the model client itself asks here whether to stop.
"""

import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable


class Stopped(BaseException):
    """A person asked to stop. Not an Exception on purpose: the `except Exception` that keeps one failed figure
    or one failed step from ending a run must not swallow this."""


class Busy(RuntimeError):
    """The same work is already running."""


_lock = threading.Lock()
_runs: dict[str, dict] = {}
_threads: list[threading.Thread] = []
_lanes: dict[str, threading.Lock] = {}
_here = threading.local()

# Never leaves this module's callers through `public`.
_PRIVATE = {"again", "note", "raised", "thread"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def key(kind: str, subject: str) -> str:
    return f"{kind}:{subject}"


def launch(project_id: str, kind: str, subject: str, title: str, where: dict, work: Callable[[], object],
           *, note: Callable[[object], str] | None = None, again: Callable[[], dict] | None = None) -> dict:
    """Start `work` in its own thread. `note` words what came out; `again` starts it once more after a stop."""
    entry = {"key": key(kind, subject), "project_id": project_id, "kind": kind, "subject": subject, "title": title, "where": where,
             "status": "running", "stopping": False, "waiting": False, "done": 0, "total": 0, "error": "", "message": "",
             "started_at": _now(), "finished_at": None, "note": note, "again": again, "raised": None}
    with _lock:
        current = _runs.get(entry["key"])
        if current and current["status"] == "running":
            raise Busy(f"{title}: already running")
        _runs[entry["key"]] = entry
        thread = threading.Thread(target=_go, args=(entry, work), name=entry["key"], daemon=True)
        entry["thread"] = thread
        _threads[:] = [t for t in _threads if t.is_alive()] + [thread]
    thread.start()
    return entry


def _go(entry: dict, work: Callable[[], object]) -> None:
    _here.entry = entry
    status, error, message, raised = "done", "", "", None
    try:
        result = work()
        message = entry["note"](result) if entry["note"] else ""
    except Stopped:
        status = "stopped"
    except Exception as exc:  # it reaches the person through the list of runs
        status, error, raised = "failed", str(exc), exc
    with _lock:
        entry.update(status=status, error=error, message=message, raised=raised, stopping=False, finished_at=_now())


def settle(entry: dict, seconds: float) -> None:
    """A refusal comes before any model call. Waiting this long lets it answer the click that caused it."""
    entry["thread"].join(seconds)


def forget(entry: dict) -> None:
    with _lock:
        if _runs.get(entry["key"]) is entry:
            del _runs[entry["key"]]


def check() -> None:
    """Called between steps and between pieces of a model's reply. Outside a run it does nothing."""
    entry = getattr(_here, "entry", None)
    if entry is not None and entry["stopping"]:
        raise Stopped


@contextmanager
def in_turn(lane: str):
    """Runs of one lane go one after the other, and one still waiting can be stopped."""
    with _lock:
        turn = _lanes.setdefault(lane, threading.Lock())
    entry = getattr(_here, "entry", None)
    if entry is not None:
        entry["waiting"] = True
    while not turn.acquire(timeout=0.2):
        check()
    try:
        if entry is not None:
            entry["waiting"] = False
        check()
        yield
    finally:
        turn.release()


def progress(done: int, total: int) -> None:
    entry = getattr(_here, "entry", None)
    if entry is not None:
        entry["done"], entry["total"] = done, total


def say(text: str) -> None:
    """Words what a running step is doing now; the finishing note replaces it."""
    entry = getattr(_here, "entry", None)
    if entry is not None:
        entry["message"] = text


def stop(kind: str, subject: str) -> bool:
    with _lock:
        entry = _runs.get(key(kind, subject))
        if not entry or entry["status"] != "running":
            return False
        entry["stopping"] = True
        return True


def find(kind: str, subject: str) -> dict | None:
    with _lock:
        return _runs.get(key(kind, subject))


def is_running(kind: str, subject: str) -> bool:
    entry = find(kind, subject)
    return bool(entry and entry["status"] == "running")


def in_project(project_id: str) -> list[dict]:
    with _lock:
        return [e for e in _runs.values() if e["project_id"] == project_id]


def public(entry: dict) -> dict:
    return {**{k: v for k, v in entry.items() if k not in _PRIVATE},
            "can_continue": bool(entry.get("again")) and entry["status"] in ("stopped", "failed")}


def wait(seconds: float = 10.0) -> None:
    """For tests: every run started so far has ended."""
    for thread in list(_threads):
        thread.join(seconds)


def set_waiting(value: bool) -> None:
    """A shared resource can explain why a task has not started yet."""
    entry = getattr(_here, "entry", None)
    if entry is not None:
        entry['waiting'] = value
