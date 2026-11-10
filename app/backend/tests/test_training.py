"""Training orchestration only: temporary exports, mocked Ollama, and tiny CPU workers."""
import hashlib
import json
import sys
import threading
from pathlib import Path

import httpx
import pytest

from amelia_academy import datasets, db, gpu, projects, qa, runs, training, workshop
from amelia_academy.llm import OllamaClient
from test_qa import Stub, conn, generate, pair, project, upload  # noqa: F401 - fixtures

ORIGINAL_UNLOAD = gpu.unload_ollama


@pytest.fixture(autouse=True)
def no_live_ollama(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("This test must not contact Ollama")
    monkeypatch.setattr(gpu, "unload_ollama", unexpected)
    assert gpu.status()["owner"] is None
    yield
    assert gpu.status() == {"owner": None, "generation_calls": 0, "generation_waiting": False}


@pytest.fixture
def exported(conn, tmp_path, project):
    examples = [
        ("How do bees help flowers reproduce?", "Bees carry pollen between flowers.",
         "Bees move pollen between flowers, helping plants reproduce and grow seeds."),
        ("Why does iron develop a reddish coating outside?", "Iron reacts with oxygen and moisture to form rust.",
         "Iron reacts with oxygen and moisture to form a reddish coating called rust."),
        ("What keeps our planet circling its star?", "Gravity holds Earth in orbit around the Sun.",
         "Gravity holds Earth in orbit around the Sun while Earth moves through space."),
    ]
    for i, (question, answer, text) in enumerate(examples):
        source = upload(conn, tmp_path, project, name=f"{i}.txt", content=text + " This observation describes a basic process found in the natural world and can be checked independently.")
        generate(conn, Stub(pairs=[pair(question=question, answer=answer, quote=text)]), source)
    for sample in qa.list_samples(conn, project["id"]):
        qa.decide(conn, sample["id"], "approve")
    return datasets.export_dataset(conn, tmp_path / "datasets", "train", project["id"], outputs=["finetune"])


def saved_run(conn, project, status="training", run_id="trn-test"):
    config = {"dataset_id": "dataset-test", "model": training.CATALOG[0]["id"]}
    conn.execute("INSERT INTO train_runs(id,project_id,dataset_id,model,config,status,created_at) VALUES (?,?,?,?,?,?,?)",
                 (run_id, project["id"], config["dataset_id"], config["model"], json.dumps(config), status, db.now()))
    conn.commit()
    return run_id, config


def test_training_version_migration_numbers_runs_per_project(conn, project):
    other = projects.create(conn, display_name="Other", language="en", slug="other")
    for run_id, owner, created in (("old-a", project, "2026-01-01"), ("old-b", project, "2026-01-02"), ("other-a", other, "2026-01-01")):
        saved_run(conn, owner, "finished", run_id)
        conn.execute("UPDATE train_runs SET created_at=?,version=NULL WHERE id=?", (created, run_id))
    db._migrate(conn)
    assert [r[0] for r in conn.execute("SELECT version FROM train_runs WHERE project_id=? ORDER BY created_at", (project["id"],))] == [1, 2]
    assert conn.execute("SELECT version FROM train_runs WHERE id='other-a'").fetchone()[0] == 1


def test_version_name_and_in_use_are_project_scoped(conn, project):
    first, _ = saved_run(conn, project, "finished", "trn-v1")
    second, _ = saved_run(conn, project, "finished", "trn-v2")
    conn.execute("UPDATE train_runs SET version=1 WHERE id=?", (first,))
    conn.execute("UPDATE train_runs SET version=2 WHERE id=?", (second,)); conn.commit()
    assert training.update_version(conn, project["id"], first, name="  More examples  ")["label"] == "More examples"
    training.update_version(conn, project["id"], first, in_use=True)
    training.update_version(conn, project["id"], second, in_use=True)
    assert conn.execute("SELECT id FROM train_runs WHERE project_id=? AND in_use=1", (project["id"],)).fetchone()[0] == second


def test_version_delete_undo_expiry_and_in_use_fallback(conn, project, tmp_path):
    first, config = saved_run(conn, project, "finished", "trn-delete-1")
    second, _ = saved_run(conn, project, "finished", "trn-delete-2")
    conn.execute("UPDATE train_runs SET version=1,in_use=1 WHERE id=?", (first,))
    conn.execute("UPDATE train_runs SET version=2 WHERE id=?", (second,)); conn.commit()
    folder = tmp_path / "runs" / first
    folder.mkdir(parents=True); (folder / "marker").write_text("keep until expiry")
    pending = training.delete_version(conn, tmp_path, project["id"], first)
    assert first not in [r["id"] for r in training.list_runs(conn, project["id"])]
    training.undo_delete(conn, project["id"], first)
    assert (folder / "marker").is_file()
    pending = training.delete_version(conn, tmp_path, project["id"], first)
    conn.execute("UPDATE train_runs SET deleting_at='2000-01-01T00:00:00+00:00' WHERE id=?", (first,)); conn.commit()
    training.cleanup_deletions(conn, tmp_path)
    assert not (folder / "marker").exists()
    assert conn.execute("SELECT in_use FROM train_runs WHERE id=?", (second,)).fetchone()[0] == 1


def test_cannot_delete_training_version(conn, project, tmp_path):
    run_id, _ = saved_run(conn, project, "training")
    with pytest.raises(workshop.Conflict, match="Stop training"):
        training.delete_version(conn, tmp_path, project["id"], run_id)


def test_version_summary_reports_data_size_and_comparison_score(conn, project, tmp_path):
    run_id, config = saved_run(conn, project, "finished")
    folder = tmp_path / "runs" / run_id / "data"
    folder.mkdir(parents=True)
    (folder / "training-manifest.json").write_text(json.dumps({"statistics": {"total_samples": 5, "direct": 3}, "entries": [{"answer_model": "Qwen/Qwen3-4B"}]}))
    (folder / "samples.jsonl").write_text("x" * 5)
    conn.execute("UPDATE train_runs SET version=1 WHERE id=?", (run_id,))
    conn.execute("INSERT INTO train_comparisons(id,run_id,question,set_name,left_answer,right_answer,base_on_left,choice,created_at) VALUES ('cmp-v','?', 'q','held_out','a','b',1,'right',?)".replace("'?'", "?"), (run_id, db.now()))
    conn.commit()
    item = training.list_runs(conn, project["id"], tmp_path)[0]
    assert (item["samples"], item["pairs"], item["answer_model"], item["size_bytes"]) == (5, 3, "Qwen3-4B", 5 + len((folder / "training-manifest.json").read_bytes()))
    assert (item["better"], item["worse"], item["total"]) == (1, 0, 1)


def test_train_changes_counts_new_and_edited_approved_pairs(conn, project, exported, tmp_path):
    run_id, config = saved_run(conn, project, "finished")
    source, _ = training._dataset(conn, tmp_path, project["id"], exported["id"])
    data = tmp_path / "runs" / run_id / "data"
    data.mkdir(parents=True)
    (data / "samples.jsonl").write_bytes((source / "samples.jsonl").read_bytes())
    config.update(data=str(data))
    conn.execute("UPDATE train_runs SET version=4,in_use=1,config=? WHERE id=?", (json.dumps(config), run_id)); conn.commit()
    assert training.changes(conn, project["id"]) == {"since_version": 4, "pairs_changed": 0}
    sample_id = conn.execute("SELECT id FROM qa_samples WHERE project_id=? AND status='approved' LIMIT 1", (project["id"],)).fetchone()[0]
    conn.execute("UPDATE qa_samples SET revision=revision+1 WHERE id=?", (sample_id,)); conn.commit()
    assert training.changes(conn, project["id"]) == {"since_version": 4, "pairs_changed": 1}


def frozen_config(root, run_id):
    folder = root / "runs" / run_id
    data = folder / "data"
    data.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for name in ("train.jsonl", "valid.jsonl"):
        payload = json.dumps({"messages": [{"role": "user", "content": "Hello"},
                                           {"role": "assistant", "content": "Hi"}]}) + "\n"
        (data / name).write_text(payload)
        hashes[name] = hashlib.sha256((data / name).read_bytes()).hexdigest()
    return {"dataset_id": "dataset-test", "model": training.CATALOG[0]["id"],
            "data": str(data), "output": str(folder / "adapters"), "rendered_sha256": hashes}


@pytest.fixture
def worker(tmp_path, monkeypatch):
    """Run a real, bounded child, preserving supervise's pipe and process-group handling."""
    monkeypatch.setattr(training, "PYTHON", Path(sys.executable))
    monkeypatch.setattr(training, "KILL_SECONDS", 0.5)

    def install(source):
        script = tmp_path / "fake_worker.py"
        script.write_text("import json, pathlib, sys, time\n" + source)
        monkeypatch.setattr(training, "command", lambda path, mode: [sys.executable, "-u", str(script), str(path), mode])
    return install


def test_reservation_blocks_local_generation_until_its_owner_releases(monkeypatch):
    entered, called = threading.Event(), threading.Event()
    errors = []
    client = OllamaClient(model="fake")

    def post(*args):
        called.set()
        return {"message": {"content": "ready"}}

    monkeypatch.setattr(client, "_post", post)
    original_check = runs.check

    def check():
        if threading.current_thread() is thread:
            entered.set()
        original_check()

    monkeypatch.setattr(runs, "check", check)

    def generate_local():
        try:
            assert client._chat("hello", 0) == "ready"
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=generate_local, daemon=True)
    gpu.reserve("trainer")
    try:
        with pytest.raises(runs.Busy):
            gpu.reserve("comparison")
        thread.start()
        assert entered.wait(2), "generation never reached the GPU gate"
        gpu.release("another-owner")
        assert not called.is_set()
        assert gpu.status()["generation_waiting"]
    finally:
        gpu.release("trainer")
        thread.join(3)
    assert not thread.is_alive()
    assert not errors
    assert called.is_set()


@pytest.mark.parametrize("failure", [RuntimeError("unload failed"), runs.Stopped()])
def test_exclusive_releases_reservation_when_unloading_fails_or_stops(monkeypatch, failure):
    def unload(url):
        raise failure
    monkeypatch.setattr(gpu, "unload_ollama", unload)
    gpu.reserve("trainer")
    with pytest.raises(type(failure)):
        with gpu.exclusive("trainer", "http://unused"):
            pytest.fail("worker started despite failed preparation")
    assert gpu.status()["owner"] is None
    with gpu.generation():
        assert gpu.status()["generation_calls"] == 1


def test_generation_exception_does_not_leave_a_reader():
    with pytest.raises(RuntimeError, match="generation failed"):
        with gpu.generation():
            raise RuntimeError("generation failed")
    assert gpu.status()["generation_calls"] == 0


def test_unload_sends_keep_alive_zero_for_each_model_and_confirms_empty(monkeypatch):
    monkeypatch.setattr(gpu, "unload_ollama", ORIGINAL_UNLOAD)
    requests = []
    polls = iter([{"models": [{"name": "small"}, {"model": "large"}]},
                  {"models": [{"name": "large"}]}, {"models": []}])

    def handle(request):
        requests.append((request.method, request.url.path, json.loads(request.content) if request.content else None))
        return httpx.Response(200, json=next(polls) if request.method == "GET" else {})

    real_client = httpx.Client
    monkeypatch.setattr(gpu.httpx, "Client", lambda **kw: real_client(**kw, transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(gpu.time, "sleep", lambda _: None)
    assert gpu.unload_ollama("http://ollama.invalid/") == ["small", "large"]
    assert requests == [("GET", "/api/ps", None),
                        ("POST", "/api/generate", {"model": "small", "keep_alive": 0, "stream": False}),
                        ("POST", "/api/generate", {"model": "large", "keep_alive": 0, "stream": False}),
                        ("GET", "/api/ps", None), ("GET", "/api/ps", None)]


def test_unload_refuses_to_start_if_models_remain(monkeypatch):
    real_client = httpx.Client
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"models": [{"name": "busy"}]}))
    monkeypatch.setattr(gpu.httpx, "Client", lambda **kw: real_client(**kw, transport=transport))
    with pytest.raises(RuntimeError, match="did not release"):
        ORIGINAL_UNLOAD("http://ollama.invalid", timeout=0)


def test_model_catalog_is_an_explicit_at_most_four_b_allowlist(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "empty-cache"))
    assert training.models()
    for item in training.models():
        assert 0 < item["parameters_b"] <= 4
        assert item["cached"] is False
        assert "base_path" not in item
        assert training.model_info(item["id"])["revision"] == item["revision"]
    for model in ("mlx-community/Qwen3-8B-4bit", "untrusted/custom-1B", "../../model"):
        with pytest.raises(ValueError, match="supported model.*4B"):
            training.model_info(model)


@pytest.mark.parametrize("filename", ["samples.jsonl", "train.jsonl", "valid.jsonl"])
def test_exported_files_with_tampered_hashes_are_rejected(conn, tmp_path, project, exported, filename):
    folder, manifest = training._dataset(conn, tmp_path, project["id"], exported["id"])
    assert manifest["schema_version"] == "2.0"
    path = folder / filename
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="changed after export"):
        training._dataset(conn, tmp_path, project["id"], exported["id"])


def test_another_projects_dataset_cannot_be_used(conn, tmp_path, exported):
    other = projects.create(conn, display_name="Other", language="en", slug="other")
    with pytest.raises(workshop.NotFound):
        training._dataset(conn, tmp_path, other["id"], exported["id"])


def test_supervise_persists_progress_checkpoint_and_returns_result(conn, tmp_path, project, worker):
    run_id, config = saved_run(conn, project)
    worker("""folder = pathlib.Path(sys.argv[1]).parent
adapter = folder / 'adapters/best/adapters.safetensors'
adapter.parent.mkdir(parents=True)
adapter.write_bytes(b'fake adapter')
for kind, payload in [('progress', {'iteration': 1, 'train_loss': 1.2}),
                      ('checkpoint', {'iteration': 2, 'val_loss': 0.8}),
                      ('result', {'best_val_loss': 0.8, 'best_iteration': 2})]:
    print(json.dumps({'type': kind, 'payload': payload}), flush=True)
""")
    assert training.supervise(conn, run_id, tmp_path, config) == {"best_val_loss": 0.8, "best_iteration": 2}
    row = training.get(conn, project["id"], run_id)
    assert (row["best_val_loss"], row["best_iteration"]) == (0.8, 2)
    events = training.events(conn, project["id"], run_id)
    assert [e["type"] for e in events] == ["progress", "checkpoint", "result"]
    assert [e["seq"] for e in events] == [1, 2, 3]
    assert training.events(conn, project["id"], run_id, after=2) == events[2:]
    assert run_id not in training._processes


@pytest.mark.parametrize("source,reason", [
    ("print(json.dumps({'type': 'progress', 'payload': {'iteration': 1}}))", "stopped before it finished"),
    ("print(json.dumps({'type': 'result', 'payload': {}}))", "validated adapter"),
    ("print(json.dumps({'type': 'result', 'payload': {}}))\nsys.exit(3)", "stopped before it finished"),
    *[(f"print(json.dumps({{'type': 'checkpoint', 'payload': {{'iteration': 1, 'val_loss': float('{loss}')}}}}))", "invalid number")
      for loss in ("nan", "inf", "-inf")],
])
def test_supervise_rejects_incomplete_or_invalid_workers(conn, tmp_path, project, worker, source, reason):
    run_id, config = saved_run(conn, project)
    worker(source)
    with pytest.raises(ValueError, match=reason):
        training.supervise(conn, run_id, tmp_path, config)
    assert run_id not in training._processes
    assert training.get(conn, project["id"], run_id)["best_val_loss"] is None


@pytest.mark.parametrize("ignore_sigterm", [False, True])
def test_stop_terminates_the_child_persists_stopped_and_releases_gpu(conn, tmp_path, project, worker, monkeypatch, ignore_sigterm):
    setup = "import signal\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\n" if ignore_sigterm else ""
    worker(setup + "print(json.dumps({'type': 'accepted', 'payload': {}}), flush=True)\ntime.sleep(8)")
    folder = tmp_path / "runs/trn-stop"
    folder.mkdir(parents=True)
    child_ready = threading.Event()
    children = []
    real_event = training.event

    def event(c, run_id, kind, payload):
        real_event(c, run_id, kind, payload)
        if kind == "accepted":
            children.append(training._processes[run_id])
            child_ready.set()

    monkeypatch.setattr(training, "event", event)
    monkeypatch.setattr(gpu, "unload_ollama", lambda url: [])
    connection = lambda: db.connect(tmp_path / "t.sqlite3")
    config = frozen_config(tmp_path, "trn-stop")
    training._start(conn, tmp_path, project["id"], "trn-stop", config, "http://unused", connection)
    entry = runs.find("training", "trn-stop")
    try:
        assert child_ready.wait(3), "worker never emitted accepted"
        assert gpu.status()["owner"].startswith("trn-stop:")
        training.stop(conn, project["id"], "trn-stop")
        entry["thread"].join(3)
        assert not entry["thread"].is_alive(), "cancellation did not promptly stop training"
        assert children[0].poll() is not None
        assert training.get(conn, project["id"], "trn-stop")["status"] == "stopped"
        assert training.events(conn, project["id"], "trn-stop")[-1]["type"] == "cancelled"
        assert gpu.status()["owner"] is None
        assert "trn-stop" not in training._processes
    finally:
        runs.stop("training", "trn-stop")
        entry["thread"].join(10)


def test_failed_training_is_persisted_and_releases_gpu(conn, tmp_path, project, worker, monkeypatch):
    worker("sys.exit(2)")
    (tmp_path / "runs/trn-fail").mkdir(parents=True)
    monkeypatch.setattr(gpu, "unload_ollama", lambda url: [])
    config = frozen_config(tmp_path, "trn-fail")
    training._start(conn, tmp_path, project["id"], "trn-fail", config, "http://unused",
                    lambda: db.connect(tmp_path / "t.sqlite3"))
    entry = runs.find("training", "trn-fail")
    entry["thread"].join(3)
    assert not entry["thread"].is_alive()
    row = training.get(conn, project["id"], "trn-fail")
    assert row["status"] == "failed" and "stopped before it finished" in row["error"]
    assert row["finished_at"]
    assert gpu.status()["owner"] is None


@pytest.mark.parametrize("operation", ["get", "events", "stop", "continue", "download", "comparison", "choose", "compare"])
def test_cross_project_run_access_is_rejected(conn, tmp_path, project, operation):
    run_id, _ = saved_run(conn, project)
    other = projects.create(conn, display_name="Other", language="en", slug="other")
    args = (conn, other["id"], run_id)
    calls = {
        "get": lambda: training.get(*args), "events": lambda: training.events(*args),
        "stop": lambda: training.stop(*args), "comparison": lambda: training.comparison(*args),
        "choose": lambda: training.choose(*args, "cmp-test", "left"),
        "continue": lambda: training.continue_run(conn, tmp_path, other["id"], run_id, "unused", None),
        "download": lambda: training.download(conn, tmp_path, other["id"], run_id),
        "compare": lambda: training.start_compare(conn, tmp_path, other["id"], run_id, {}, "unused", None),
    }
    with pytest.raises(workshop.NotFound):
        calls[operation]()
    assert training.list_runs(conn, other["id"]) == []
    assert training.get(conn, project["id"], run_id)["status"] == "training"


def test_recover_marks_only_orphaned_active_runs_failed_and_keeps_checkpoints(conn, tmp_path, project):
    for status in ("preparing", "training", "finished", "stopped", "failed"):
        saved_run(conn, project, status, "trn-" + status)
    conn.execute("UPDATE train_runs SET best_val_loss=0.7,best_iteration=4")
    conn.commit()
    checkpoint = tmp_path / "runs/trn-training/adapters/adapters.safetensors"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b'checkpoint')
    reopened = db.connect(tmp_path / "t.sqlite3")
    try:
        training.recover(reopened)
        training.recover(reopened)  # recovery is safe on repeated app startup
        for status in ("preparing", "training", "finished", "stopped", "failed"):
            row = training.get(reopened, project["id"], "trn-" + status)
            assert row["status"] == ("failed" if status in ("preparing", "training") else status)
            assert (row["best_val_loss"], row["best_iteration"]) == (0.7, 4)
            if status in ("preparing", "training"):
                assert row["error"] == "Stopped when the app closed" and row["finished_at"]
        assert checkpoint.read_bytes() == b'checkpoint'
    finally:
        reopened.close()


@pytest.mark.parametrize("base_on_left", [0, 1])
def test_blind_comparison_choice_can_be_undone_without_revealing_models(conn, project, base_on_left):
    run_id, _ = saved_run(conn, project, "finished")
    conn.execute("INSERT INTO train_comparisons(id,run_id,question,set_name,left_answer,right_answer,base_on_left,created_at) VALUES (?,?,?,?,?,?,?,?)",
                 ("cmp-test", run_id, "Which answer?", "held_out", "First", "Second", base_on_left, db.now()))
    conn.commit()
    before = training.comparison(conn, project["id"], run_id)
    assert before["revealed"] is False and before["base_side"] == {}
    assert before["items"][0] == {"id": "cmp-test", "question": "Which answer?", "set_name": "new",
                                  "left": "First", "right": "Second", "choice": None, "expected": ""}
    for choice in ("left", "right", "same", "both_wrong"):
        chosen = training.choose(conn, project["id"], run_id, "cmp-test", choice)
        assert chosen["items"][0]["choice"] == choice
        assert chosen["revealed"] is True
        assert chosen["base_side"] == {"cmp-test": "left" if base_on_left else "right"}
        assert training.choose(conn, project["id"], run_id, "cmp-test", None) == before
    with pytest.raises(ValueError, match="Unknown comparison choice"):
        training.choose(conn, project["id"], run_id, "cmp-test", "trained")
    with pytest.raises(workshop.NotFound):
        training.choose(conn, project["id"], run_id, "missing", "left")


def test_comparison_reveals_group_score_and_maps_legacy_names_and_choices(conn, project):
    run_id, _ = saved_run(conn, project, "finished")
    rows = [
        ("cmp-study", "studied", 1, "fact", "trained fact", "right"),
        ("cmp-new", "held_out", 0, "trained miss", "correct", "left"),
        ("cmp-general", "general", 1, "same", "same", "same"),
        ("cmp-own", "manual", 0, "wrong", "also wrong", "both_wrong"),
    ]
    for item_id, group, base_left, left, right, choice in rows:
        conn.execute("INSERT INTO train_comparisons(id,run_id,question,set_name,left_answer,right_answer,base_on_left,choice,created_at,expected) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (item_id, run_id, item_id, group, left, right, base_left, choice, db.now(), "expected answer"))
    conn.commit()
    result = training.comparison(conn, project["id"], run_id)
    assert result["revealed"] is True
    assert {row["set_name"] for row in result["items"]} == {"studied", "new", "general", "yours"}
    assert result["sets"]["studied"]["better"] == 1
    assert result["sets"]["new"]["better"] == 1
    assert result["sets"]["general"]["same"] == 1
    assert result["sets"]["yours"]["both_wrong"] == 1
    assert result["items"][0]["expected"] == "expected answer"


@pytest.mark.parametrize("kind", ["training", "comparison", "recall"])
def test_connection_failure_releases_gpu(conn, tmp_path, project, kind):
    run_id = "trn-connect-fail"
    config = frozen_config(tmp_path, run_id)

    def unavailable():
        raise RuntimeError("database unavailable")

    if kind == "training":
        training._start(conn, tmp_path, project["id"], run_id, config, "unused", unavailable)
    else:
        saved_run(conn, project, "finished", run_id)
        if kind == "recall":
            training.draft_recall(conn, tmp_path, project["id"], run_id, "unused", unavailable)
        else:
            training.start_compare(conn, tmp_path, project["id"], run_id,
                                   {"question": "Hello?"}, "unused", unavailable)
    entry = runs.find("training" if kind == "training" else "comparison", run_id)
    try:
        entry["thread"].join(2)
        assert not entry["thread"].is_alive()
        assert entry["status"] == "failed" and entry["error"] == "database unavailable"
        assert gpu.status()["owner"] is None
    finally:
        owner = gpu.status()["owner"]
        if owner is not None:
            gpu.release(owner)  # keep subsequent tests isolated if this regresses


@pytest.mark.parametrize("kind", ["training", "comparison"])
def test_launch_rejection_releases_gpu(conn, tmp_path, project, monkeypatch, kind):
    run_id = "trn-rejected"
    config = frozen_config(tmp_path, run_id)

    def busy(*args, **kwargs):
        raise runs.Busy("already running")

    monkeypatch.setattr(runs, "launch", busy)
    with pytest.raises(runs.Busy, match="already running"):
        if kind == "training":
            training._start(conn, tmp_path, project["id"], run_id, config, "unused", None)
        else:
            saved_run(conn, project, "finished", run_id)
            training.start_compare(conn, tmp_path, project["id"], run_id,
                                   {"question": "Hello?"}, "unused", None)
    assert gpu.status()["owner"] is None
    if kind == "training":
        assert training.get(conn, project["id"], run_id)["status"] == "failed"


def test_resume_persists_previous_best_and_frozen_config(conn, tmp_path, project, worker, monkeypatch):
    run_id, _ = saved_run(conn, project, "stopped")
    config = frozen_config(tmp_path, run_id)
    folder = tmp_path / "runs" / run_id
    checkpoint = folder / "adapters/adapters.safetensors"
    checkpoint.parent.mkdir()
    checkpoint.write_bytes(b"previous checkpoint")
    conn.execute("UPDATE train_runs SET config=?,best_val_loss=0.7,best_iteration=4 WHERE id=?",
                 (json.dumps(config), run_id))
    conn.commit()
    training.event(conn, run_id, "checkpoint", {"val_loss": 0.7, "iteration": 4})
    training.event(conn, run_id, "progress", {"iteration": 10, "train_loss": 1.2})
    worker("""config = json.loads(pathlib.Path(sys.argv[1]).read_text())
assert config['start_iteration'] == 10, 'it goes on from the last saved step'
assert config['previous_best_val_loss'] == 0.7 and config['previous_best_iteration'] == 4
assert config['optimizer_restarted'] is True
assert pathlib.Path(config['resume_adapter_file']).read_bytes() == b'previous checkpoint'
adapter = pathlib.Path(config['output']) / 'best/adapters.safetensors'
adapter.parent.mkdir(parents=True)
adapter.write_bytes(b'best checkpoint')
print(json.dumps({'type': 'result', 'payload': {'best_val_loss': 0.7, 'best_iteration': 4}}))
""")
    monkeypatch.setattr(gpu, "unload_ollama", lambda url: [])
    training.continue_run(conn, tmp_path, project["id"], run_id, "unused",
                          lambda: db.connect(tmp_path / "t.sqlite3"))
    entry = runs.find("training", run_id)
    entry["thread"].join(3)
    assert not entry["thread"].is_alive()
    row = training.get(conn, project["id"], run_id)
    assert row["status"] == "finished", row["error"]
    assert row["config"]["previous_best_val_loss"] == 0.7
    assert row["config"]["resume_adapter_file"] == str(checkpoint)
    assert json.loads((folder / "run.json").read_text()) == row["config"]
    assert training.events(conn, project["id"], run_id)[0]["type"] == "checkpoint"
    assert gpu.status()["owner"] is None


def test_resume_rejects_tampered_frozen_data_before_reserving(conn, tmp_path, project):
    run_id, _ = saved_run(conn, project, "stopped")
    config = frozen_config(tmp_path, run_id)
    checkpoint = tmp_path / "runs" / run_id / "adapters/adapters.safetensors"
    checkpoint.parent.mkdir()
    checkpoint.write_bytes(b"checkpoint")
    conn.execute("UPDATE train_runs SET config=? WHERE id=?", (json.dumps(config), run_id))
    conn.commit()
    (Path(config["data"]) / "valid.jsonl").write_text("tampered")
    with pytest.raises(ValueError, match="frozen training data changed"):
        training.continue_run(conn, tmp_path, project["id"], run_id, "unused", None)
    assert gpu.status()["owner"] is None
    assert training.get(conn, project["id"], run_id)["status"] == "stopped"


def test_generation_waiting_behind_training_can_be_stopped(monkeypatch, project):
    parked = threading.Event()
    original = runs.set_waiting

    def waiting(value):
        original(value)
        if value:
            parked.set()

    monkeypatch.setattr(runs, "set_waiting", waiting)

    def work():
        with gpu.generation():
            pytest.fail("generation should stay blocked behind training")

    gpu.reserve("trainer")
    entry = runs.launch(project["id"], "reading", "parked", "Reading", {}, work)
    try:
        assert parked.wait(2)
        assert runs.public(entry)["waiting"] is True
        assert runs.stop("reading", "parked")
        entry["thread"].join(2)
        assert not entry["thread"].is_alive()
        assert entry["status"] == "stopped"
        assert entry["waiting"] is False
        assert gpu.status()["owner"] == "trainer"
        assert gpu.status()["generation_calls"] == 0
    finally:
        gpu.release("trainer")
        runs.stop("reading", "parked")
        entry["thread"].join(2)


def test_the_download_carries_no_path_of_this_machine(conn, tmp_path, project):
    import io, zipfile
    run_id, _ = saved_run(conn, project, "finished")
    config = {**frozen_config(tmp_path, run_id), "base_path": "/Users/someone/.cache/hf/model", "base_revision": "abc",
              "canonical_sha256": "d" * 64, "iters": 40, "identity": "You are Metrics."}
    conn.execute("UPDATE train_runs SET config=?, best_val_loss=0.5 WHERE id=?", (json.dumps(config), run_id)); conn.commit()
    best = tmp_path / "runs" / run_id / "adapters/best"; best.mkdir(parents=True)
    (best / "adapters.safetensors").write_bytes(b"weights")
    (best / "adapter_config.json").write_text(json.dumps({"model": "/Users/someone/.cache/hf/model", "data": "/Users/someone/data",
                                                           "num_layers": 16, "lora_parameters": {"rank": 8}}))
    archive = zipfile.ZipFile(io.BytesIO(training.download(conn, tmp_path, project["id"], run_id)))
    for name in archive.namelist():
        assert "/Users/" not in archive.read(name).decode(errors="ignore"), name
    adapter = json.loads(archive.read("adapter/adapter_config.json"))
    assert adapter["model"] == training.CATALOG[0]["id"] and adapter["num_layers"] == 16
    assert json.loads(archive.read("run.yaml"))["identity"] == "You are Metrics.", "the identity travels with the adapter"


def test_held_out_questions_take_turns_between_kinds(tmp_path):
    def line(q, kind=None):
        user = {"role": "user", "content": q}
        return json.dumps({"messages": [user, {"role": "assistant", "content": "a"}]}), \
            json.dumps({"kind": kind, "messages": [{"role": "user", "content": [{"type": "text", "text": q}]}]})
    rows = [line(f"refusal {i}", "unanswered") for i in range(8)] + [line(f"known {i}", "file") for i in range(2)]
    (tmp_path / "test.jsonl").write_text("".join(r[0] + "\n" for r in rows))
    (tmp_path / "samples.jsonl").write_text("".join(r[1] + "\n" for r in rows))
    picked = training.held_out(tmp_path, most=4)
    assert picked == ["known 0", "refusal 0", "known 1", "refusal 1"]
    assert training.held_out(tmp_path / "missing") == []


def test_training_without_dataset_exports_direct_finetune_implicitly(conn, project, tmp_path, monkeypatch):
    from amelia_academy import datasets
    monkeypatch.setattr(training.platform, 'system', lambda: 'Darwin')
    monkeypatch.setattr(training.platform, 'machine', lambda: 'arm64')
    monkeypatch.setattr(training, 'PYTHON', Path('/fake/python'))
    monkeypatch.setattr(Path, 'exists', lambda self: True)
    monkeypatch.setattr(training, 'model_info', lambda model: {'id': model, 'base_path': '/cached', 'revision': 'rev', 'cached': True, 'num_layers': 36})
    monkeypatch.setattr(training.projects, 'get', lambda *_: {'language': 'en'})
    calls = {}
    def export(conn_arg, out, name, project_id, theme_ids=None, outputs=None, **kwargs):
        calls.update(name=name, outputs=outputs, profile=kwargs.get('profile'))
        return {'id': 'auto-dataset'}
    monkeypatch.setattr(datasets, 'export_dataset', export)
    folder = tmp_path / 'dataset'
    manifest = {'files': {'train.jsonl': {'lines': 20, 'sha256': 'a'}, 'valid.jsonl': {'sha256': 'b'}},
                'statistics': {}, 'canonical_sha256': 'c'}
    monkeypatch.setattr(training, '_dataset', lambda *_: (folder, manifest))
    body = {'dataset_id': None, 'model': 'mlx-community/Qwen3-4B-4bit'}
    config = training._configuration(conn, tmp_path, project['id'], body)
    assert config['dataset_id'] == body['dataset_id'] == 'auto-dataset'
    assert calls == {'name': 'Training dataset', 'outputs': ['finetune'], 'profile': 'direct'}
