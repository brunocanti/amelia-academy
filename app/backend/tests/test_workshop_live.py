"""End-to-end against the real local model. No fake LLM.

Skips only when Ollama is not reachable, and says so. A skip is not a pass.
"""

import os

import httpx
import pytest

from amelia_academy import datasets, db, projects, qa, workshop
from amelia_academy.llm import OllamaClient

MODEL = os.environ.get("AMELIA_ACADEMY_MODEL", "qwen3:14b")
OLLAMA = os.environ.get("AMELIA_ACADEMY_OLLAMA_URL", "http://localhost:11434")


def _ollama_has_model() -> bool:
    try:
        r = httpx.get(f"{OLLAMA}/api/tags", timeout=3)
        return any(m["name"] == MODEL or m["name"] == f"{MODEL}:latest" for m in r.json()["models"])
    except httpx.HTTPError:
        return False


requires_model = pytest.mark.skipif(
    not _ollama_has_model(), reason=f"Ollama with model {MODEL} not reachable; live test NOT run"
)


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.sqlite3")
    projects.create(c, display_name="Test project", objective="behavior", language="en", slug="test")
    return c


def _project_id(conn):
    return conn.execute("SELECT id FROM projects WHERE slug = 'test'").fetchone()[0]


def _approved_pattern(conn):
    p = workshop.create_pattern(
        conn,
        project_id=_project_id(conn),
        title="Presence without possession",
        intent="The person wants company without being asked to depend on the assistant.",
        tone="warm, direct, Brazilian Portuguese-friendly calm",
        guidelines="Acknowledge the situation in one sentence; ask one open question; no claims of feelings.",
        description="Someone shares a mild difficulty and wants to be heard, not managed.",
    )
    return workshop.set_pattern_status(conn, p["id"], "approved")


def test_unapproved_pattern_cannot_generate(conn):
    p = workshop.create_pattern(conn, project_id=_project_id(conn), title="t", intent="i", tone="t", guidelines="g", description="d")
    llm = OllamaClient(model=MODEL, base_url=OLLAMA)
    with pytest.raises(workshop.PatternNotApproved):
        workshop.generate_batch(conn, llm, p["id"], count=3)


@requires_model
def test_live_batch_is_proposed_and_failures_are_visible(conn, tmp_path):
    pattern = _approved_pattern(conn)
    llm = OllamaClient(model=MODEL, base_url=OLLAMA)
    batch = workshop.generate_batch(conn, llm, pattern["id"], count=5, variation_type="positive")

    assert batch["model"] == MODEL
    assert batch["denominator"]["requested"] == 5
    assert batch["status"] in ("reviewable", "failed")
    if batch["status"] == "failed":
        pytest.fail(f"live batch failed visibly: {batch['error']} rejected={batch['rejected_lines']}")
    assert batch["denominator"]["proposed"] >= 1
    for s in batch["proposed"]:
        assert s["status"] == "proposed"
        assert s["question"] and s["answer"]

    # Human decides one; export contains only approved samples.
    first = batch["proposed"][0]
    qa.decide(conn, first["id"], "approve")
    ds = datasets.export_dataset(conn, tmp_path / "out", "test", _project_id(conn))
    assert ds["sample_count"] == 1
    assert os.path.exists(ds["path"])

