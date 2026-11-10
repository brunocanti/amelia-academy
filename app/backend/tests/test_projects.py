"""Projects as the scope boundary (spec 001). The LLM is a scripted stub: these tests cover scoping, not model quality."""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from amelia_academy import api, db, projects, workshop
from amelia_academy.datasets import canonical_id


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DATA_DIR", tmp_path)
    monkeypatch.setattr(api, "DB_PATH", tmp_path / "academy.sqlite3")
    monkeypatch.setattr(api, "_conn", None)
    return TestClient(api.app)


class Writer:
    """Stands in for the sample model: one fixed, valid dialogue per call."""

    model = "stub-model"

    def __init__(self, user, reply):
        self.item = {"user_message": user, "response_text": reply}

    def complete_json(self, prompt, schema, temperature=0.9):
        return {"items": [self.item]}


def make_project(client, name, objective="behavior", **extra):
    r = client.post("/projects", json={"display_name": name, "objective": objective, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def test_about_scope_draft_includes_summary_for_every_source(client, monkeypatch):
    project = make_project(client, "Tardigrades", objective="knowledge")
    texts = [
        ("SAHS-CAHS", "Tardigrade intrinsically disordered proteins protect cells during desiccation."),
        ("UV-C DNA repair", "Tardigrades repair DNA damage caused by UV-C radiation."),
        ("Cell stiffness", "Tardigrade cell stiffness changes under dehydration."),
        ("Yeast", "Yeast expresses tardigrade proteins and gains stress tolerance."),
    ]
    c = api.conn()
    from amelia_academy import sources
    for title, text in texts:
        sources.ingest(c, api.DATA_DIR / "sources", project_id=project["id"], name=title + ".txt", content=text, purpose="research", license_basis="test")
    captured = {}
    class Stub:
        def complete_json(self, prompt, schema, temperature=0.1):
            captured["prompt"] = prompt
            return {"about": "Tardigrade adaptations protect cells from environmental stress."}
    monkeypatch.setattr(api, "client_for", lambda _model: Stub())
    response = client.post(f"/projects/{project['id']}/about-scope/draft", json={"model": "stub"})
    assert response.status_code == 200, response.text
    assert response.json()["about_scope"]
    for title, text in texts:
        assert f"File: {title}" in captured["prompt"]
        assert text in captured["prompt"]
    assert "common to all files" in captured["prompt"]


def make_pattern(client, project, title="Quiet company"):
    r = client.post(f"/projects/{project['id']}/patterns", json={
        "title": title, "intent": "stay with the person", "tone": "calm",
        "guidelines": "acknowledge one detail", "description": "someone shares a hard day"})
    assert r.status_code == 200, r.text
    return r.json()


def approved_sample(client, project, user, reply):
    """A pattern with one approved sample, written by the stub through the real workshop code."""
    pattern = make_pattern(client, project)
    c = api.conn()
    workshop.set_pattern_status(c, pattern["id"], "approved")
    batch = workshop.generate_batch(c, Writer(user, reply), pattern["id"], count=1)
    sample = batch["proposed"][0]
    r = client.post(f"/projects/{project['id']}/samples/{sample['id']}/approve")
    assert r.status_code == 200, r.text
    return pattern, sample


# --- creating and editing projects ---

def test_project_defaults_to_english_and_slugs_the_name(client):
    p = make_project(client, "Signal Compression Notes", objective="knowledge")
    assert p["language"] == "en"
    assert p["slug"] == "signal-compression-notes"
    assert p["status"] == "active"


def test_invalid_projects_are_rejected(client):
    assert client.post("/projects", json={"display_name": "x", "objective": "persona"}).status_code == 422
    assert client.post("/projects", json={"display_name": " ", "objective": "behavior"}).status_code == 422
    assert client.post("/projects", json={"display_name": "ok", "objective": "behavior", "language": "english"}).status_code == 422
    assert client.post("/projects", json={"display_name": "ok", "objective": "behavior", "slug": "Bad Slug"}).status_code == 422


def test_duplicate_slug_conflicts(client):
    make_project(client, "Atlas")
    assert client.post("/projects", json={"display_name": "Atlas again", "objective": "behavior", "slug": "atlas"}).status_code == 409


def test_objective_cannot_be_changed_after_creation(client):
    p = make_project(client, "Atlas")
    r = client.patch(f"/projects/{p['id']}", json={"objective": "knowledge"})
    assert r.status_code == 422
    assert client.get(f"/projects/{p['id']}").json()["objective"] == "behavior"


def test_name_description_and_language_can_be_edited(client):
    p = make_project(client, "Atlas")
    r = client.patch(f"/projects/{p['id']}", json={"display_name": "Atlas Support", "language": "pt-BR", "description": "d"})
    assert r.json()["display_name"] == "Atlas Support" and r.json()["language"] == "pt-BR"


def test_prepare_and_train_preferences_share_project_patch(client):
    p = make_project(client, "Prepared")
    default = p["train_model"]
    assert p["prepare_count"] == "normal"
    updated = client.patch(f"/projects/{p['id']}", json={"train_model": default, "prepare_count": "few"})
    assert updated.status_code == 200 and updated.json()["prepare_count"] == "few"
    preserved = client.patch(f"/projects/{p['id']}", json={"description": "keep choices"}).json()
    assert preserved["train_model"] == default and preserved["prepare_count"] == "few"
    assert client.patch(f"/projects/{p['id']}", json={"prepare_count": "lots"}).status_code == 422
    assert client.patch(f"/projects/{p['id']}", json={"train_model": "unknown"}).status_code == 422


# --- isolation between projects ---

def test_two_projects_run_the_same_flow_without_persona_fields(client):
    a, b = make_project(client, "Voice project"), make_project(client, "Product expert", objective="knowledge")
    make_pattern(client, a, "Only in A")
    make_pattern(client, b, "Only in B")
    assert [p["title"] for p in client.get(f"/projects/{a['id']}/patterns").json()] == ["Only in A"]
    assert [p["title"] for p in client.get(f"/projects/{b['id']}/patterns").json()] == ["Only in B"]


def test_cross_project_access_answers_not_found(client):
    a, b = make_project(client, "Project A"), make_project(client, "Project B")
    pattern, sample = approved_sample(client, a, "I have been feeling stuck with my project since last week.",
                                      "That sounds heavy. Do you want to tell me what part feels stuck?")
    src = client.post(f"/projects/{a['id']}/sources", json={
        "name": "n.txt", "content": "Presence without demands means the assistant stays with the person.",
        "purpose": "test", "license_basis": "own"}).json()
    paths = [
        ("get", f"/projects/{b['id']}/patterns/{pattern['id']}"),
        ("post", f"/projects/{b['id']}/patterns/{pattern['id']}/status"),
        ("post", f"/projects/{b['id']}/samples/{sample['id']}/reject"),
        ("get", f"/projects/{b['id']}/sources/{src['id']}"),
    ]
    for method, path in paths:
        r = getattr(client, method)(path, **({"json": {"status": "approved"}} if path.endswith("/status") else {}))
        assert r.status_code == 404, (method, path, r.status_code)
    # and nothing changed in A
    assert client.get(f"/projects/{a['id']}/patterns/{pattern['id']}").json()["status"] == "approved"


def test_unknown_project_is_not_found(client):
    assert client.get("/projects/prj_nope/patterns").status_code == 404
    assert client.post("/projects/prj_nope/datasets", json={"name": "x"}).status_code == 404


def test_sources_are_listed_per_project_and_identical_files_do_not_cross(client):
    a, b = make_project(client, "Project A"), make_project(client, "Project B")
    body = {"name": "same.txt", "content": "The very same file uploaded twice, by two projects.",
            "purpose": "test", "license_basis": "own"}
    sa = client.post(f"/projects/{a['id']}/sources", json=body).json()
    sb = client.post(f"/projects/{b['id']}/sources", json=body).json()
    assert sa["id"] != sb["id"]
    assert [s["id"] for s in client.get(f"/projects/{a['id']}/sources").json()] == [sa["id"]]
    assert [s["id"] for s in client.get(f"/projects/{b['id']}/sources").json()] == [sb["id"]]


def test_binary_upload_lands_in_its_project(client):
    a, b = make_project(client, "Project A"), make_project(client, "Project B")
    r = client.post(f"/projects/{a['id']}/sources/upload",
                    files={"file": ("n.txt", b"A short note about presence without demands.", "text/plain")},
                    data={"purpose": "test", "license_basis": "own"})
    assert r.status_code == 200, r.text
    assert len(client.get(f"/projects/{a['id']}/sources").json()) == 1
    assert client.get(f"/projects/{b['id']}/sources").json() == []


def test_dataset_export_carries_only_its_own_projects_samples(client):
    a, b = make_project(client, "Project A"), make_project(client, "Project B")
    _, sample_a = approved_sample(client, a, "I have been feeling stuck with my project since last week.",
                                  "That sounds heavy. Do you want to tell me what part feels stuck?")
    _, sample_b = approved_sample(client, b, "My landlord raised the rent and I am worried about next month.",
                                  "A rent increase is a lot to carry. Which part worries you most right now?")
    ra = client.post(f"/projects/{a['id']}/datasets", json={"name": "a"})
    assert ra.status_code == 200, ra.text
    assert ra.json()["sample_count"] == 1
    ids = [json.loads(line)["sample_id"] for line in open(ra.json()["path"], encoding="utf-8")]
    assert ids == [canonical_id(sample_a["id"])]
    rb = client.post(f"/projects/{b['id']}/datasets", json={"name": "b"})
    assert [json.loads(line)["sample_id"] for line in open(rb.json()["path"], encoding="utf-8")] == [canonical_id(sample_b["id"])]


def test_export_with_nothing_approved_in_this_project_fails_even_if_others_have_samples(client):
    a, b = make_project(client, "Project A"), make_project(client, "Project B")
    approved_sample(client, a, "I have been feeling stuck with my project since last week.",
                    "That sounds heavy. Do you want to tell me what part feels stuck?")
    assert client.post(f"/projects/{b['id']}/datasets", json={"name": "b"}).status_code == 422


# --- archived projects and objectives ---

def test_archived_project_stays_readable_and_rejects_new_work(client):
    p = make_project(client, "Old project")
    pattern = make_pattern(client, p)
    client.patch(f"/projects/{p['id']}", json={"status": "archived"})
    assert client.get(f"/projects/{p['id']}/patterns/{pattern['id']}").status_code == 200
    assert client.get(f"/projects/{p['id']}/sources").status_code == 200
    assert client.post(f"/projects/{p['id']}/patterns", json={
        "title": "t", "intent": "i", "tone": "t", "guidelines": "g", "description": "d"}).status_code == 409
    assert client.post(f"/projects/{p['id']}/sources", json={
        "name": "n.txt", "content": "text", "purpose": "p", "license_basis": "l"}).status_code == 409
    client.patch(f"/projects/{p['id']}", json={"status": "active"})
    assert make_pattern(client, p, "Back again")["title"] == "Back again"


def test_behavior_samples_work_on_a_project_created_as_knowledge(client, monkeypatch):
    p = make_project(client, "Product expert", objective="knowledge")
    pattern = make_pattern(client, p)
    workshop.set_pattern_status(api.conn(), pattern["id"], "approved")

    class Stub:
        model = "stub"

        def complete_json(self, prompt, schema, temperature=0.9):
            return {"items": [{"user_message": "I finally repainted the old bench in my garden this weekend.",
                               "response_text": "A repainted bench changes the whole garden. What colour did you pick?"}]}

    monkeypatch.setattr(api, "OllamaClient", lambda **kw: Stub())
    r = client.post(f"/projects/{p['id']}/patterns/{pattern['id']}/batches", json={"count": 1})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "done" and "1 of 1 written" in r.json()["message"]


def test_identity_is_saved_per_project_and_reaches_generation(client, monkeypatch):
    a, b = make_project(client, "Voice project"), make_project(client, "Product expert")
    assert a["identity"] == ""
    assert client.patch(f"/projects/{a['id']}", json={"identity": "  My name is Lia.  "}).json()["identity"] == "My name is Lia."
    assert client.get(f"/projects/{b['id']}").json()["identity"] == ""
    assert client.patch(f"/projects/{a['id']}", json={"identity": "x" * 2001}).status_code == 422

    sent = []

    class Stub:
        model = "stub"

        def complete_json(self, prompt, schema, temperature=0.9):
            sent.append(prompt)
            return {"items": [{"user_message": "I finally repainted the old bench in my garden this weekend.",
                               "response_text": "A repainted bench changes the whole garden. What colour did you pick?"}]}

    monkeypatch.setattr(api, "OllamaClient", lambda **kw: Stub())
    for project, expected in ((a, True), (b, False)):
        pattern = make_pattern(client, project)
        workshop.set_pattern_status(api.conn(), pattern["id"], "approved")
        client.post(f"/projects/{project['id']}/patterns/{pattern['id']}/batches", json={"count": 1})
        assert ("My name is Lia." in sent[-1]) is expected


def test_a_card_about_identity_writes_nothing_until_the_project_says_who_the_model_is(client, monkeypatch):
    project = make_project(client, "Voice project")
    card = client.post(f"/projects/{project['id']}/patterns", json={
        "title": "Who I am", "intent": "i", "tone": "t", "guidelines": "g", "description": "d", "about_identity": True}).json()
    workshop.set_pattern_status(api.conn(), card["id"], "approved")

    class Stub:
        model = "stub"

        def complete_json(self, prompt, schema, temperature=0.9):
            return {"items": []}

    monkeypatch.setattr(api, "OllamaClient", lambda **kw: Stub())
    url = f"/projects/{project['id']}/patterns/{card['id']}/batches"
    refused = client.post(url, json={"count": 1})
    assert refused.status_code == 409
    assert api.conn().execute("SELECT COUNT(*) FROM batches WHERE pattern_id = ?", (card["id"],)).fetchone()[0] == 0

    client.patch(f"/projects/{project['id']}", json={"identity": "My name is Lia."})
    assert client.post(url, json={"count": 1}).status_code == 200


# --- databases created before projects existed ---

def test_legacy_rows_are_adopted_by_a_project(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    conn = db.connect(path)
    conn.execute("INSERT INTO patterns (id, project, title, intent, tone, guidelines, description, status, created_at)"
                 " VALUES ('pat_old','amelia','t','i','t','g','d','approved','x')")
    conn.execute("INSERT INTO sources (id, project, name, mime, sha256, size, purpose, license_basis, status, created_at)"
                 " VALUES ('src_old','amelia','n.md','text/markdown','abc',1,'p','l','available','x')")
    conn.execute("INSERT INTO datasets (id, name, path, sample_count, manifest_hash, created_at)"
                 " VALUES ('ds_old','d','/x',1,'h','x')")
    conn.commit()
    conn.close()

    conn = db.connect(path)  # reopening runs the migration
    project = projects.list_projects(conn)
    assert [p["slug"] for p in project] == ["amelia"]
    assert project[0]["objective"] == "behavior"
    pid = project[0]["id"]
    for table in ("patterns", "sources", "datasets"):
        assert conn.execute(f"SELECT project_id FROM {table}").fetchone()[0] == pid
    assert [p["id"] for p in workshop.list_patterns(conn, pid)] == ["pat_old"]


def test_migration_is_idempotent(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    conn = db.connect(path)
    conn.execute("INSERT INTO patterns (id, project, title, intent, tone, guidelines, description, status, created_at)"
                 " VALUES ('pat_old','amelia','t','i','t','g','d','approved','x')")
    conn.commit()
    for _ in range(3):
        conn = db.connect(path)
    assert len(projects.list_projects(conn)) == 1
