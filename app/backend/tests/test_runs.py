"""A run goes on without the page, can be stopped, and can go on from where it stopped."""

import json
import threading

import httpx
import pytest
from fastapi.testclient import TestClient

from amelia_academy import api, challenge, console, kinds, runs
from amelia_academy.llm import OllamaClient
from test_challenge import Judge, add, contradicting
from test_challenge import conn as conn  # noqa: F401 - fixture
from test_challenge import project as project  # noqa: F401 - fixture
from test_qa import TEXT, Stub, pair

# Sections long enough to each be one window, so a stop falls between them.
SECTION = "Structural similarity compares luminance, contrast and structure between two images instead of raw pixels alone. " * 40
LONG = TEXT + "\n\n" + "\n\n".join(f"{i} {SECTION}" for i in range(4))


class StopsAt(Stub):
    """Stops the way a person does: asks for the stop, and the next piece of the reply ends the run."""

    def __init__(self, at, kind="reading", **kw):
        super().__init__(**kw)
        self.at, self.kind, self.subject, self.sections = at, kind, None, 0

    def complete_json(self, prompt, schema, temperature=0.9):
        if "themes" in schema["properties"]:
            return super().complete_json(prompt, schema, temperature)
        self.sections += 1
        if self.at and self.sections == self.at:
            assert runs.stop(self.kind, self.subject)
            runs.check()
        return super().complete_json(prompt, schema, temperature)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DATA_DIR", tmp_path)
    monkeypatch.setattr(api, "DB_PATH", tmp_path / "academy.sqlite3")
    monkeypatch.setattr(api, "_conn", None)
    return TestClient(api.app)


def started(client, stub, monkeypatch, **options):
    monkeypatch.setattr(api, "OllamaClient", lambda **kw: stub)
    p = client.post("/projects", json={"display_name": "Metrics", "max_themes": 4}).json()
    base = f"/projects/{p['id']}"
    source = client.post(f"{base}/sources/upload", files={"file": ("a.txt", LONG.encode(), "text/plain")}).json()
    stub.subject = source["id"]
    answer = client.post(f"{base}/sources/{source['id']}/generate", json={"model": "m", **options})
    assert answer.status_code == 200, answer.text
    return base, source["id"]


def extraction(client, base, source_id):
    return client.get(f"{base}/sources/{source_id}/extraction").json()


def test_the_click_is_answered_while_the_work_goes_on(client, monkeypatch):
    monkeypatch.setattr(api, "REFUSAL_WAIT", 0)
    gate = threading.Event()

    class Waits(Stub):
        def complete_json(self, prompt, schema, temperature=0.9):
            gate.wait(10)
            return super().complete_json(prompt, schema, temperature)

    base, source_id = started(client, Waits(pairs=[pair()]), monkeypatch)
    try:
        assert extraction(client, base, source_id)["status"] == "running"
        listed = client.get(f"{base}/runs").json()
        assert [(r["kind"], r["status"]) for r in listed] == [("reading", "running")]
        assert client.post(f"{base}/sources/{source_id}/generate", json={"model": "m"}).status_code == 409
    finally:
        gate.set()
        runs.wait()
    assert extraction(client, base, source_id)["status"] == "succeeded"
    assert client.get(f"{base}/runs").json()[0]["status"] == "done"


def test_a_stopped_reading_goes_on_from_the_same_section_without_doubling(client, monkeypatch):
    stub = StopsAt(2, pairs=[pair()])
    base, source_id = started(client, stub, monkeypatch)
    stopped = extraction(client, base, source_id)
    assert stopped["status"] == "stopped" and stopped["passages_read"] == 1 and stopped["can_continue"]
    total = stopped["passages_total"]
    assert total > 2
    listed = client.get(f"{base}/runs").json()[0]
    assert (listed["status"], listed["done"], listed["total"], listed["can_continue"]) == ("stopped", 1, total, True)
    kept = len(client.get(f"{base}/samples").json())
    assert kept == 1

    stub.at = None
    before = stub.sections
    assert client.post(f"{base}/runs/reading/{source_id}/continue").status_code == 200
    done = extraction(client, base, source_id)
    assert done["status"] == "succeeded" and done["passages_read"] == total
    assert stub.sections - before == total - 1, "the section the stop cut goes again; the one already read does not"
    assert len(client.get(f"{base}/samples").json()) == kept
    assert client.post(f"{base}/runs/reading/{source_id}/continue").status_code == 422


def test_a_stop_while_writing_the_other_kinds_shows_and_goes_on(client, monkeypatch):
    stub = StopsAt(None, pairs=[pair()])
    stage, armed = kinds._stage, []

    def stops_inside(*args, **kw):
        if not armed:
            armed.append(True)
            stub.at = stub.sections + 1
        return stage(*args, **kw)

    monkeypatch.setattr(kinds, "_stage", stops_inside)
    base, source_id = started(client, stub, monkeypatch, unanswered_pct=20)
    total = extraction(client, base, source_id)["passages_total"]
    stopped = extraction(client, base, source_id)
    assert stopped["status"] == "stopped" and stopped["passages_read"] == total
    assert stopped["reading"]["kinds"]["stopped"] and not stopped["reading"]["kinds"]["running"]
    assert not stopped["reading"]["kinds"]["unanswered"]["discarded"], "a stop is not the model writing too little"

    stub.at = None
    assert client.post(f"{base}/runs/reading/{source_id}/continue").status_code == 200
    done = extraction(client, base, source_id)
    assert done["status"] == "succeeded" and "stopped" not in done["reading"]["kinds"]


def test_what_the_app_closed_on_can_still_go_on(client, monkeypatch):
    stub = StopsAt(2, pairs=[pair()])
    base, source_id = started(client, stub, monkeypatch)
    api.conn().execute("UPDATE extractions SET status = 'running'")
    api.conn().commit()
    runs._runs.clear()
    monkeypatch.setattr(api, "_conn", None)  # as a new process opens the database

    listed = client.get(f"{base}/runs").json()
    assert [(r["kind"], r["status"], r["can_continue"], r["done"]) for r in listed] == [("reading", "stopped", True, 1)]
    assert "closed" in listed[0]["message"]
    stub.at = None
    assert client.post(f"{base}/runs/reading/{source_id}/continue").status_code == 200
    assert extraction(client, base, source_id)["status"] == "succeeded"


def test_another_project_cannot_stop_or_continue_a_run(client, monkeypatch):
    monkeypatch.setattr(api, "REFUSAL_WAIT", 0)
    gate = threading.Event()

    class Waits(Stub):
        def complete_json(self, prompt, schema, temperature=0.9):
            gate.wait(10)
            return super().complete_json(prompt, schema, temperature)

    base, source_id = started(client, Waits(pairs=[pair()]), monkeypatch)
    other = client.post("/projects", json={"display_name": "Other"}).json()["id"]
    try:
        assert client.post(f"/projects/{other}/runs/reading/{source_id}/stop").status_code == 404
        assert client.post(f"/projects/{other}/runs/reading/{source_id}/continue").status_code == 404
        assert client.get(f"/projects/{other}/runs").json() == []
    finally:
        gate.set()
        runs.wait()
    assert extraction(client, base, source_id)["status"] == "succeeded"


def test_what_cannot_start_still_answers_the_click(client, monkeypatch):
    monkeypatch.setattr(api, "OllamaClient", lambda **kw: Stub())
    p = client.post("/projects", json={"display_name": "Metrics"}).json()
    assert client.post(f"/projects/{p['id']}/refusals", json={"model": "m", "count": 1}).status_code == 422
    assert client.get(f"/projects/{p['id']}/runs").json() == []


def test_a_failure_reaches_the_list_and_keeps_what_was_read(client, monkeypatch):
    stub = Stub(pairs=[pair()], fail_at=3)  # themes, one section, then the model goes away
    base, source_id = started(client, stub, monkeypatch)
    failed = extraction(client, base, source_id)
    assert failed["status"] == "failed" and failed["passages_read"] == 1 and failed["can_continue"]
    listed = client.get(f"{base}/runs").json()[0]
    assert listed["status"] == "failed" and "model went away" in listed["error"] and listed["can_continue"]


def test_a_stopped_challenge_keeps_its_count_and_pays_only_for_the_rest(conn, project, monkeypatch):  # noqa: F811
    monkeypatch.setattr(challenge, "MIN_CLOSENESS", 0.0)
    contradicting(conn, project)
    add(conn, project, question="Does a PSNR above 40 dB hide the difference?", answer="Most viewers do not see the difference.")

    class Stops(Judge):
        def complete_json(self, prompt, schema, temperature=0.9):
            if self.calls == self.stop_after:
                raise runs.Stopped
            return super().complete_json(prompt, schema, temperature)

    llm = Stops(pair="complement")
    llm.stop_after = 1
    cid = challenge.start(conn, project["id"], llm.model)
    with pytest.raises(runs.Stopped):
        challenge.run(conn, llm, cid)
    stopped = challenge.latest(conn, project["id"])
    assert stopped["status"] == "stopped" and stopped["done"] == 1 and stopped["total"] > 1

    llm.stop_after = None
    assert challenge.resume(conn, project["id"])["id"] == cid
    done = challenge.run(conn, llm, cid)
    assert done["status"] == "succeeded" and done["done"] == done["total"] == stopped["total"]
    assert llm.calls == stopped["total"]
    with pytest.raises(ValueError):
        challenge.resume(conn, project["id"])


def test_stopping_mid_reply_leaves_nothing_writing_in_the_console(monkeypatch):
    class Reply:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def iter_lines(self):
            yield json.dumps({"message": {"content": "first "}})
            assert runs.stop("t", "mid")
            yield json.dumps({"message": {"content": "second"}})

    monkeypatch.setattr(httpx, "stream", lambda *a, **kw: Reply())
    entry = runs.launch("p", "t", "mid", "A test", {}, lambda: OllamaClient(model="m", base_url="http://x").complete("hi"))
    runs.wait()
    assert entry["status"] == "stopped" and not entry["error"]
    assert not console._running
    last = console._lines[-1]
    assert last["text"] == "Stopped by you." and last["reply"] == "first " and not last["error"]


def test_the_same_work_cannot_run_twice_and_a_stop_after_the_end_does_nothing():
    gate = threading.Event()
    runs.launch("p", "t", "s", "A test", {}, lambda: gate.wait(10))
    with pytest.raises(runs.Busy):
        runs.launch("p", "t", "s", "A test", {}, lambda: None)
    gate.set()
    runs.wait()
    assert not runs.stop("t", "s")
    runs.check()  # outside a run it does nothing



def test_files_dropped_together_are_read_in_parallel_and_one_can_be_stopped(client, monkeypatch):
    monkeypatch.setattr(api, "REFUSAL_WAIT", 0)
    gate, now, most = threading.Event(), [], []

    class Slow(Stub):
        def complete_json(self, prompt, schema, temperature=0.9):
            now.append(1)
            most.append(len(now))
            gate.wait(10)
            now.pop()
            return super().complete_json(prompt, schema, temperature)

    monkeypatch.setattr(api, "OllamaClient", lambda **kw: Slow(pairs=[pair()]))
    p = client.post("/projects", json={"display_name": "Metrics", "max_themes": 4}).json()
    base = f"/projects/{p['id']}"
    ids = [client.post(f"{base}/sources/upload", files={"file": (f"{n}.txt", f"{n} {LONG}".encode(), "text/plain")}).json()["id"] for n in "abc"]
    for source_id in ids:
        assert client.post(f"{base}/sources/{source_id}/generate", json={"model": "m"}).status_code == 200
    try:
        for _ in range(100):
            active = [r for r in client.get(f"{base}/runs").json() if r["status"] == "running"]
            if len(active) == 3 and len(most) == 3:
                break
            threading.Event().wait(0.05)
        assert len(active) == 3 and max(most) == 3
        out = active[0]["subject"]
        assert client.post(f"{base}/runs/reading/{out}/stop").status_code == 200
        gate.set()
        for _ in range(100):
            if extraction(client, base, out)["status"] == "stopped":
                break
            threading.Event().wait(0.05)
        final = extraction(client, base, out)
        assert final["status"] == "stopped", {"status": final["status"], "error": final.get("error"), "run": client.get(f"{base}/runs").json()}
    finally:
        gate.set()
        runs.wait()
    assert max(most) == 3
    assert sorted(extraction(client, base, s)["status"] for s in ids) == ["stopped", "succeeded", "succeeded"]
