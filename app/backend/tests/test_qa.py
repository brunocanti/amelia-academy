"""File -> themes -> pairs -> curation -> export. The model is a stub: these tests cover the rules, not its quality."""

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from amelia_academy import api, datasets, db, kinds, okf, projects, qa, sources, workshop
from amelia_academy.llm import LLMError, OutputCapped

TEXT = """Peak signal-to-noise ratio measures how close a compressed image stays to the original picture.

A value above 40 dB usually means the difference is invisible to most viewers looking at the two pictures.

Structural similarity compares luminance, contrast and structure between two images instead of raw pixels alone.
"""
PSNR_QUOTE = "A value above 40 dB usually means the difference is invisible"


class Stub:
    """Answers theme calls and pair calls apart, as the schemas differ."""

    model = "stub-model"

    def __init__(self, themes=None, pairs=None, fail_at=None):
        self.themes = themes if themes is not None else [{"title": "Image metrics", "description": "How pictures are compared."}]
        self.pairs = pairs if pairs is not None else []
        self.fail_at = fail_at
        self.calls = 0
        self.prompts = []

    def complete_json(self, prompt, schema, temperature=0.9):
        self.calls += 1
        self.prompts.append(prompt)
        if self.fail_at is not None and self.calls >= self.fail_at:
            raise LLMError("model went away")
        return {"themes": self.themes} if "themes" in schema["properties"] else {"items": self.pairs}


def pair(question="What PSNR value is usually invisible to viewers?", answer="Above 40 dB most viewers see no difference.",
         quote=PSNR_QUOTE, theme="image-metrics"):
    return {"question": question, "answer": answer, "quote": quote, "theme": theme}


@pytest.fixture
def conn(tmp_path: Path):
    return db.connect(tmp_path / "t.sqlite3")


@pytest.fixture
def project(conn):
    return projects.create(conn, display_name="Metrics", language="en", slug="metrics", max_themes=8)


def upload(conn, tmp_path, project, name="a.txt", content=TEXT):
    return sources.ingest(conn, tmp_path / "sources", project_id=project["id"], name=name, content=content,
                          purpose="qa-dataset", license_basis="own")


def generate(conn, llm, source):
    return qa.run(conn, llm, qa.start(conn, source["id"], llm.model))


# --- themes ---

def test_slots_keep_room_for_later_files():
    assert [qa.new_theme_slots(8, used) for used in (0, 5, 7, 8)] == [5, 2, 1, 0]


def test_theme_merge_and_split_are_undoable_and_validate_model_assignment(conn, tmp_path, project):
    generate(conn, Stub(pairs=[pair(), {**pair(), "question":"How does structural similarity compare pictures?", "answer":"It compares luminance, contrast and structure."}]), upload(conn, tmp_path, project))
    original = qa.list_themes(conn, project['id'])[0]
    second = qa.create_theme(conn, project['id'], "Other metrics")
    merged = qa.merge_theme(conn, original['id'], second['id'])
    assert merged['undo']['theme']['id'] == original['id']
    assert qa.undo_theme_operation(conn, project['id'], merged['undo'])['ok']
    class Splitter:
        model = 'stub'
        def complete_json(self, prompt, schema, temperature=0.1):
            ids = [r['id'] for r in conn.execute('SELECT id FROM qa_samples WHERE theme_id=? ORDER BY id', (original['id'],))]
            return {'themes':[{'title':'Signal quality','description':'Quality.'},{'title':'Image structure','description':'Structure.'}],
                    'groups':[{'pair_id':ids[0],'group':0},{'pair_id':ids[1],'group':1}]}
    proposal = qa.split_theme(conn, original['id'], Splitter())
    assert len(proposal['themes']) == 2
    assert {r['theme_id'] for r in conn.execute('SELECT theme_id FROM qa_samples WHERE project_id=?', (project['id'],))} == {original['id']}
    split = qa.confirm_theme_split(conn, original['id'], proposal)
    assert {r['theme_id'] for r in conn.execute('SELECT theme_id FROM qa_samples WHERE project_id=?', (project['id'],))} == {t['id'] for t in split['themes']}
    qa.undo_theme_operation(conn, project['id'], split['undo'])
    assert {r['theme_id'] for r in conn.execute('SELECT theme_id FROM qa_samples WHERE project_id=?', (project['id'],))} == {original['id']}


def test_similar_theme_names_suggest_a_merge(conn, project):
    first = qa.create_theme(conn, project['id'], 'Image quality metrics')
    qa.create_theme(conn, project['id'], 'Image quality measures')
    listed = qa.list_themes(conn, project['id'])
    found = next(theme for theme in listed if theme['id'] == first['id'])
    assert found['merge_suggestion']


def test_one_file_cannot_take_every_theme(conn, tmp_path, project):
    many = [{"title": f"Theme number {i}", "description": "d"} for i in range(20)]
    generate(conn, Stub(themes=many), upload(conn, tmp_path, project))
    topics = [t for t in qa.list_themes(conn, project["id"]) if t["kind"] == "topic"]
    assert len(topics) == 2  # dynamic three-theme cap reserves one slot for a later file


def test_limit_holds_after_many_files_and_no_model_call_when_full(conn, tmp_path, project):
    for i in range(6):
        stub = Stub(themes=[{"title": f"File {i} theme {n}", "description": "d"} for n in range(9)])
        generate(conn, stub, upload(conn, tmp_path, project, f"{i}.txt", TEXT + f"\nFile number {i} adds this closing line.\n"))
    assert sum(t["kind"] == "topic" for t in qa.list_themes(conn, project["id"])) == 3
    stub = Stub(themes=[{"title": "Never created", "description": "d"}])
    generate(conn, stub, upload(conn, tmp_path, project, "last.txt", TEXT + "\nOne more closing line for this file.\n"))
    assert not any(t["title"] == "Never created" for t in qa.list_themes(conn, project["id"]))
    assert not any("Propose at most" in p for p in stub.prompts)


def test_pair_schema_is_a_closed_list_and_unknown_theme_lands_in_other(conn, tmp_path, project):
    stub = Stub(pairs=[pair(theme="something-invented")])
    generate(conn, stub, upload(conn, tmp_path, project))
    assert qa.pair_schema(["a", "outros"])["properties"]["items"]["items"]["properties"]["theme"]["enum"] == ["a", "outros"]
    assert [s["theme_slug"] for s in qa.list_samples(conn, project["id"])] == [qa.OTHER_SLUG]


def test_stub_call_count_is_one_theme_call_plus_one_per_read_window(conn, tmp_path, project):
    stub = Stub(pairs=[pair()])
    source = upload(conn, tmp_path, project)
    windows = qa.read_plan(source["chunks"])["windows"]
    result = generate(conn, stub, source)
    assert result["status"] == "succeeded", result
    # With no optional kinds requested, validation is local and the legacy kind stage
    # makes no extra model call: theme outline + each passage exactly once.
    assert stub.calls == 1 + len(windows)


def test_a_pair_that_fits_lands_in_its_theme(conn, tmp_path, project):
    generate(conn, Stub(pairs=[pair()]), upload(conn, tmp_path, project))
    sample = qa.list_samples(conn, project["id"])[0]
    assert sample["theme_title"] == "Image metrics" and sample["status"] == "proposed"
    assert sample["source_name"] == "a.txt" and sample["quote"] == PSNR_QUOTE + " to most viewers looking at the two pictures."


def test_creating_past_the_limit_is_refused_and_lowering_below_use_too(conn, project):
    for i in range(3):
        qa.create_theme(conn, project["id"], f"Theme {i}")
    with pytest.raises(workshop.Conflict):
        qa.create_theme(conn, project["id"], "One too many")
    with pytest.raises(projects.ProjectInvalid):
        projects.update(conn, project["id"], max_themes=2)
    assert projects.update(conn, project["id"], max_themes=9)["max_themes"] == 9


def test_rename_keeps_slug_and_merge_moves_pairs_and_frees_the_slot(conn, tmp_path, project):
    generate(conn, Stub(pairs=[pair()]), upload(conn, tmp_path, project))
    theme = next(t for t in qa.list_themes(conn, project["id"]) if t["kind"] == "topic")
    renamed = qa.edit_theme(conn, theme["id"], title="Picture quality")
    assert renamed["slug"] == "image-metrics"
    other = qa.other_theme(conn, project["id"])
    with pytest.raises(workshop.Conflict):
        qa.merge_theme(conn, other["id"], theme["id"])
    qa.merge_theme(conn, theme["id"], other["id"])
    assert [s["theme_slug"] for s in qa.list_samples(conn, project["id"])] == [qa.OTHER_SLUG]
    assert not any(t["kind"] == "topic" for t in qa.list_themes(conn, project["id"]))


# --- what the model writes ---

@pytest.mark.parametrize("bad, reason", [
    (pair(quote="This sentence is nowhere in the file."), "quote not found"),
    (pair(answer="Above 55 dB most viewers see no difference."), "numbers the section does not hold"),
    (pair(answer="According to the text, above 40 dB most viewers see no difference."), "talks about its source"),
    (pair(question="Peak signal-to-noise ratio measures how close a compressed image stays to the original picture"),
     "copied from the source"),
    (pair(answer="One. Two. Three. Four. Five."), "sentences"),
])
def test_a_bad_pair_is_rejected_visibly(conn, tmp_path, project, bad, reason):
    result = generate(conn, Stub(pairs=[bad]), upload(conn, tmp_path, project))
    assert result["status"] == "failed" and reason in result["rejected"][0]["reason"]
    assert qa.list_samples(conn, project["id"]) == []


def test_a_near_duplicate_across_files_is_rejected_even_if_the_first_was_rejected_by_a_person(conn, tmp_path, project):
    generate(conn, Stub(pairs=[pair()]), upload(conn, tmp_path, project))
    sample = qa.list_samples(conn, project["id"])[0]
    qa.decide(conn, sample["id"], "reject")
    second = upload(conn, tmp_path, project, "b.txt", TEXT + "\nSomething else closes this second file nicely.\n")
    result = generate(conn, Stub(pairs=[pair()]), second)
    assert "too close to a question already asked" in result["rejected"][0]["reason"]
    assert len(qa.list_samples(conn, project["id"])) == 1


def test_a_section_with_nothing_to_ask_is_fine_when_another_one_produces(conn, tmp_path, project):
    class OneEmpty(Stub):
        def complete_json(self, prompt, schema, temperature=0.9):
            reply = super().complete_json(prompt, schema, temperature)
            if "items" in reply and self.calls == 2:
                return {"items": []}
            return reply

    text = "\n\n".join(f"Paragraph {i} " + "with some content that fills the page " * 110 for i in range(2))
    text += f"\n\n{PSNR_QUOTE} on any screen.\n"
    stub = OneEmpty(pairs=[pair()])
    result = generate(conn, stub, upload(conn, tmp_path, project, content=text))
    assert result["status"] == "succeeded" and result["kept"] == 1


def test_model_failure_is_visible_and_never_leaves_a_run_going(conn, tmp_path, project):
    source = upload(conn, tmp_path, project)
    result = generate(conn, Stub(fail_at=1), source)
    assert result["status"] == "failed" and "model went away" in result["error"]
    assert sources.extraction_progress(conn, source["id"])["status"] == "failed"


def test_failure_midway_keeps_what_was_written(conn, tmp_path, project):
    text = "\n\n".join(f"{PSNR_QUOTE} in case {i}. " + "Filler words that make the window long enough. " * 95 for i in range(3))
    stub = Stub(pairs=[pair()], fail_at=3)
    result = generate(conn, stub, upload(conn, tmp_path, project, content=text))
    assert result["status"] == "failed" and result["kept"] == 1 and "model went away" in result["error"]


def test_a_file_without_a_real_section_never_reaches_the_model(conn, tmp_path, project):
    source = upload(conn, tmp_path, project, content="Just a title\n")
    with pytest.raises(sources.SourceRejected):
        qa.start(conn, source["id"], "stub-model")


def test_a_file_cannot_generate_twice_at_once_and_restart_clears_it(conn, tmp_path, project):
    source = upload(conn, tmp_path, project)
    qa.start(conn, source["id"], "m")
    with pytest.raises(workshop.Conflict):
        qa.start(conn, source["id"], "m")
    assert qa.stop_interrupted(conn) == 1
    stopped = sources.extraction_progress(conn, source["id"])
    assert stopped["status"] == "stopped" and "closed" in stopped["error"] and stopped["can_continue"]
    qa.start(conn, source["id"], "m")


def test_a_window_never_crosses_a_page():
    chunks = [{"index": i, "text": "x" * 200, "locator": {"page": page}} for i, page in enumerate([1, 1, 2])]
    assert [[c["index"] for c in w] for w in qa.make_windows(chunks)] == [[0, 1], [2]]


# --- curation ---

def test_an_edit_returns_to_proposed_and_is_checked_and_moving_keeps_the_decision(conn, tmp_path, project):
    generate(conn, Stub(pairs=[pair()]), upload(conn, tmp_path, project))
    sample = qa.list_samples(conn, project["id"])[0]
    qa.decide(conn, sample["id"], "approve")
    other = qa.other_theme(conn, project["id"])
    moved = qa.edit(conn, sample["id"], theme_id=other["id"])
    assert moved["status"] == "approved" and moved["revision"] == 1 and moved["theme_id"] == other["id"]
    edited = qa.edit(conn, sample["id"], answer="Above 40 dB nobody notices it.")
    assert edited["status"] == "proposed" and edited["revision"] == 2
    with pytest.raises(ValueError):
        qa.edit(conn, sample["id"], answer="x" * (qa.MAX_ANSWER_CHARS + 1), theme_id=moved["theme_id"])


def test_theme_decision_only_touches_what_is_pending(conn, tmp_path, project):
    pairs = [pair(), pair(question="How does structural similarity compare two images?",
                          answer="It compares luminance, contrast and structure.",
                          quote="compares luminance, contrast and structure")]
    generate(conn, Stub(pairs=pairs), upload(conn, tmp_path, project))
    first, second = qa.list_samples(conn, project["id"])
    qa.decide(conn, first["id"], "reject")
    assert qa.decide_many(conn, project["id"], [first["id"], second["id"]], "approve") == {"changed": [second["id"]]}
    assert qa.get_sample(conn, first["id"])["status"] == "rejected"
    assert qa.get_sample(conn, second["id"])["status"] == "approved"


# --- export ---

def approved_export(conn, tmp_path, project, **kwargs):
    pairs = [pair(), pair(question="How does structural similarity compare two images?",
                          answer="It compares luminance, contrast and structure.",
                          quote="compares luminance, contrast and structure", theme=qa.OTHER_SLUG)]
    generate(conn, Stub(pairs=pairs), upload(conn, tmp_path, project))
    first, second = qa.list_samples(conn, project["id"])
    qa.decide(conn, first["id"], "approve")
    qa.decide(conn, second["id"], "reject")
    return first, datasets.export_dataset(conn, tmp_path / "out", "My Dataset!", project["id"], **kwargs)


def test_export_holds_only_approved_pairs_and_a_valid_wiki(conn, tmp_path, project):
    first, ds = approved_export(conn, tmp_path, project)
    assert ds["sample_count"] == 1 and ds["themes"] == {"Image metrics": 1}
    assert Path(ds["folder"]).name.startswith("my-dataset-")
    record = json.loads(Path(ds["path"]).read_text(encoding="utf-8"))
    assert record["sample_id"] == datasets.canonical_id(first["id"])
    assert record["provenance"]["kind"] == "source"
    assert "okf:/themes/image-metrics.md" in record["provenance"]["evidence_refs"]
    wiki = okf.read_bundle(Path(ds["folder"]) / "wiki")
    assert okf.validate(wiki) == []
    assert first["question"] in wiki["themes/image-metrics.md"] and PSNR_QUOTE in wiki["themes/image-metrics.md"]
    assert "structural similarity" not in "".join(wiki.values())
    assert "themes/image-metrics.md" in wiki["index.md"]


def test_export_by_theme_is_one_dataset_per_subject(conn, tmp_path, project):
    pairs = [pair(), pair(question="How does structural similarity compare two images?",
                          answer="It compares luminance, contrast and structure.",
                          quote="compares luminance, contrast and structure", theme=qa.OTHER_SLUG)]
    generate(conn, Stub(pairs=pairs), upload(conn, tmp_path, project))
    for sample in qa.list_samples(conn, project["id"]):
        qa.decide(conn, sample["id"], "approve")
    theme = qa.other_theme(conn, project["id"])
    ds = datasets.export_dataset(conn, tmp_path / "out", "other", project["id"], theme_ids=[theme["id"]])
    assert ds["sample_count"] == 1 and list(ds["themes"]) == [theme["title"]]


def test_export_with_nothing_approved_fails(conn, tmp_path, project):
    generate(conn, Stub(pairs=[pair()]), upload(conn, tmp_path, project))
    with pytest.raises(ValueError, match="no approved pairs"):
        datasets.export_dataset(conn, tmp_path / "out", "x", project["id"])


def test_pairs_of_one_passage_stay_in_one_split(conn, tmp_path, project):
    items = [{"id": f"s{i}", "scenario_key": f"sc{i}", "source_group": "passage:same"} for i in range(5)]
    assert len(set(datasets.assign_splits(items).values())) == 1


# --- behaviors share the list ---

class Writer:
    model = "stub-model"

    def complete_json(self, prompt, schema, temperature=0.9):
        return {"items": [{"user_message": "I finally repainted the old bench in my garden this weekend.",
                           "response_text": "A repainted bench changes the whole garden. What colour did you pick?"}]}


def test_conversations_of_a_card_are_curated_and_exported_with_the_rest(conn, tmp_path, project):
    pattern = workshop.create_pattern(conn, project_id=project["id"], title="Quiet company", intent="stay with the person",
                                      tone="calm", guidelines="one detail", description="a hard day")
    workshop.set_pattern_status(conn, pattern["id"], "approved")
    batch = workshop.generate_batch(conn, Writer(), pattern["id"], count=1)
    sample = qa.list_samples(conn, project["id"])[0]
    assert batch["status"] == "reviewable" and sample["origin"] == "behavior" and sample["theme_title"] == "Quiet company"
    assert not any(t["kind"] == "topic" for t in qa.list_themes(conn, project["id"]))
    with pytest.raises(ValueError):  # a conversation keeps its own, tighter limits
        qa.edit(conn, sample["id"], answer="One. Two. Three.")
    qa.decide(conn, sample["id"], "approve")
    ds = datasets.export_dataset(conn, tmp_path / "out", "b", project["id"])
    assert ds["sample_count"] == 1
    assert json.loads(Path(ds["path"]).read_text())["provenance"]["kind"] == "manual"
    # A behavior teaches fine-tuning only: no other file of the export holds it.
    folder = Path(ds["folder"])
    assert ds["memory_count"] == 0 and not (folder / "memory.jsonl").exists()
    assert not any("repainted" in p.read_text() for p in (folder / "wiki").rglob("*.md"))


def test_old_behavior_samples_are_adopted_once(tmp_path):
    path = tmp_path / "old.sqlite3"
    conn = db.connect(path)
    pid = projects.create(conn, display_name="Old", language="en", slug="old")["id"]
    conn.execute("INSERT INTO patterns (id, project, project_id, title, intent, tone, guidelines, description, status, created_at)"
                 " VALUES ('pat_1','old',?,'Card','i','t','g','d','approved','x')", (pid,))
    conn.execute("INSERT INTO batches (id, pattern_id, runtime, model, variation_type, requested, status, created_at)"
                 " VALUES ('bat_1','pat_1','ollama','m','positive',1,'reviewable','x')")
    conn.execute("CREATE TABLE samples (id TEXT, batch_id TEXT, pattern_id TEXT, variation_type TEXT, user_message TEXT,"
                 " response_text TEXT, content_hash TEXT, revision INTEGER, status TEXT, created_at TEXT)")
    conn.execute("INSERT INTO samples VALUES ('smp_1','bat_1','pat_1','positive','u','r','h',1,'approved','x')")
    conn.commit()
    conn.close()
    for _ in range(2):
        conn = db.connect(path)
    found = qa.list_samples(conn, pid)
    assert [(s["id"], s["question"], s["status"], s["theme_title"]) for s in found] == [("smp_1", "u", "approved", "Card")]


# --- API ---

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DATA_DIR", tmp_path)
    monkeypatch.setattr(api, "DB_PATH", tmp_path / "academy.sqlite3")
    monkeypatch.setattr(api, "_conn", None)
    return TestClient(api.app)


def test_the_whole_flow_over_http(client, monkeypatch):
    monkeypatch.setattr(api, "OllamaClient", lambda **kw: Stub(pairs=[pair()]))
    p = client.post("/projects", json={"display_name": "Metrics", "max_themes": 4}).json()
    base = f"/projects/{p['id']}"
    assert p["max_themes"] == 4
    source = client.post(f"{base}/sources/upload", files={"file": ("a.txt", TEXT.encode(), "text/plain")}).json()
    run = client.post(f"{base}/sources/{source['id']}/generate", json={"model": "m"})
    assert run.status_code == 200 and run.json()["status"] == "done", run.text
    listed = client.get(f"{base}/sources").json()[0]
    assert listed["pairs"] == 1 and listed["run"]["status"] == "succeeded"
    themes = client.get(f"{base}/themes").json()
    assert [t["slug"] for t in themes] == ["image-metrics", qa.OTHER_SLUG] and themes[0]["proposed"] == 1
    sample = client.get(f"{base}/samples", params={"theme": themes[0]["id"]}).json()[0]
    assert client.post(f"{base}/samples/{sample['id']}/approve").json()["status"] == "approved"
    ds = client.post(f"{base}/datasets", json={"name": "metrics", "theme_ids": [themes[0]["id"]]}).json()
    assert ds["sample_count"] == 1
    download = client.get(f"{base}/datasets/{ds['id']}/download")
    assert download.status_code == 200 and download.headers["content-type"] == "application/zip"
    assert re.search(r"metrics-ds_\w+\.zip", download.headers["content-disposition"])


def test_merge_split_and_undo_routes(client, monkeypatch):
    monkeypatch.setattr(api, "OllamaClient", lambda **kw: Stub(pairs=[pair(), {**pair(), "question":"How does structure compare these pictures?"}]))
    p = client.post("/projects", json={"display_name":"Theme operations"}).json()
    base = f"/projects/{p['id']}"
    source = client.post(f"{base}/sources/upload", files={"file":("a.txt", TEXT.encode(), "text/plain")}).json()
    client.post(f"{base}/sources/{source['id']}/generate", json={"model":"m"})
    theme = next(t for t in client.get(f"{base}/themes").json() if t["kind"] == "topic")
    class Splitter:
        def complete_json(self, prompt, schema, temperature=0.1):
            ids = [r["id"] for r in api.conn().execute("SELECT id FROM qa_samples WHERE theme_id=? ORDER BY id", (theme["id"],))]
            return {"themes":[{"title":"Signal quality","description":"Quality"},{"title":"Image structure","description":"Structure"}],
                    "groups":[{"pair_id":ids[0],"group":0},{"pair_id":ids[1],"group":1}]}
    monkeypatch.setattr(api, "client_for", lambda model: Splitter())
    proposal = client.post(f"{base}/themes/{theme['id']}/split", json={"model":"stub"})
    assert proposal.status_code == 200, proposal.text
    assert len(proposal.json()["themes"]) == 2
    assert len(client.get(f"{base}/themes").json()) == 2  # preview did not change the saved themes
    split = client.post(f"{base}/themes/{theme['id']}/split/confirm", json={"proposal":proposal.json()})
    assert split.status_code == 200, split.text
    undone = client.post(f"{base}/themes/undo", json={"snapshot":split.json()["undo"]})
    assert undone.status_code == 200


def test_another_project_answers_not_found(client, monkeypatch):
    monkeypatch.setattr(api, "OllamaClient", lambda **kw: Stub(pairs=[pair()]))
    a = client.post("/projects", json={"display_name": "Project A"}).json()
    b = client.post("/projects", json={"display_name": "Project B"}).json()
    base_a, base_b = f"/projects/{a['id']}", f"/projects/{b['id']}"
    source = client.post(f"{base_a}/sources/upload", files={"file": ("a.txt", TEXT.encode(), "text/plain")}).json()
    client.post(f"{base_a}/sources/{source['id']}/generate", json={"model": "m"})
    sample = client.get(f"{base_a}/samples").json()[0]
    client.post(f"{base_a}/samples/{sample['id']}/approve")
    ds = client.post(f"{base_a}/datasets", json={"name": "a"}).json()
    other = client.get(f"{base_b}/themes").json()[0]
    assert client.post(f"{base_b}/samples/{sample['id']}/reject").status_code == 404
    assert client.put(f"{base_b}/samples/{sample['id']}", json={"answer": "No."}).status_code == 404
    assert client.post(f"{base_b}/sources/{source['id']}/generate", json={"model": "m"}).status_code == 404
    assert client.post(f"{base_b}/samples/decide", json={"sample_ids": [sample["id"]], "decision": "approve"}).json() == {"changed": []}
    assert client.get(f"{base_b}/datasets/{ds['id']}/download").status_code == 404
    assert client.put(f"{base_a}/samples/{sample['id']}", json={"theme_id": other["id"]}).status_code == 404
    assert client.post(f"{base_a}/themes/{sample['theme_id']}/merge", json={"into": other["id"]}).status_code == 404
    assert client.get(f"{base_a}/samples").json()[0]["status"] == "approved"


# --- reading by section ---

def _chunk(index, text, section=None, role=None, page=None, start=0):
    locator = {"element_char_start": start}
    if section:
        locator["section"] = section
    if role:
        locator["role"] = role
    if page:
        locator["page"] = page
    return {"index": index, "text": text, "locator": locator}


def _plan_indexes(chunks):
    return [[c["index"] for c in w] for w in qa.read_plan(chunks)["windows"]]


def test_a_window_does_not_cross_a_long_enough_section():
    chunks = [_chunk(0, "x" * 1600, "1 Intro", page=1), _chunk(1, "y" * 1600, "2 Method", page=1)]
    assert _plan_indexes(chunks) == [[0], [1]]


def test_a_short_section_joins_the_next_and_pages_do_not_cut():
    chunks = [_chunk(0, "x" * 400, "3 Method", page=1), _chunk(1, "y" * 1200, "3.1 Index", page=1),
              _chunk(2, "z" * 900, "3.1 Index", page=2)]
    plan = qa.read_plan(chunks)
    assert [[c["index"] for c in w] for w in plan["windows"]] == [[0, 1, 2]]
    assert plan["by_section"] is True


def test_a_long_section_breaks_at_a_paragraph():
    chunks = [_chunk(0, "a" * 2000, "S"), _chunk(1, "b" * 700, "S"), _chunk(2, "c" * 700, "S", start=700),
              _chunk(3, "d" * 700, "S", start=1400), _chunk(4, "e" * 1000, "S")]
    # The fourth piece would pass 4500 together with the fifth, and chunks 2-3 continue the paragraph of chunk 1.
    assert _plan_indexes(chunks) == [[0], [1, 2, 3, 4]]


def test_bibliography_and_equivalents_are_left_out_and_counted():
    chunks = [_chunk(0, "x" * 1600, "1 Intro"), _chunk(1, "r" * 900, "References"), _chunk(2, "r" * 900, "References"),
              _chunk(3, "a" * 300, "Agradecimentos"), _chunk(4, "b" * 300, "7. Referências Bibliográficas"),
              _chunk(5, "y" * 1600, "A Appendix")]
    plan = qa.read_plan(chunks)
    assert [[c["index"] for c in w] for w in plan["windows"]] == [[0], [5]]
    counts = {e["reason"]: e["passages"] for e in plan["left_out"]}
    assert counts == {"bibliography": 3, "acknowledgements": 1}


def test_a_section_about_references_is_not_a_bibliography():
    chunks = [_chunk(0, "x" * 1600, "Reference counting in Python")]
    assert _plan_indexes(chunks) == [[0]]


def test_captions_and_margin_text_are_left_out():
    chunks = [_chunk(0, "x" * 1600, "S"), _chunk(1, "Figure 1: a picture.", "S", role="caption"),
              _chunk(2, "arXiv:1 [cs.IR]", "S", role="margin")]
    plan = qa.read_plan(chunks)
    assert _plan_indexes(chunks) == [[0]]
    assert {e["reason"] for e in plan["left_out"]} == {"figure or table caption", "text in the page margin"}


def test_short_text_before_the_first_heading_is_left_out_but_a_real_opening_stays():
    title = [_chunk(0, "A title and its authors " * 3), _chunk(1, "x" * 1600, "1 Intro")]
    assert _plan_indexes(title) == [[1]]
    opening = [_chunk(0, "o" * 1600), _chunk(1, "x" * 1600, "1 Intro")]
    assert _plan_indexes(opening) == [[0], [1]]


def test_a_file_without_headings_keeps_reading_by_page_and_says_so():
    chunks = [_chunk(0, "x" * 800, page=1), _chunk(1, "y" * 800, page=2)]
    plan = qa.read_plan(chunks)
    assert plan["by_section"] is False and _plan_indexes(chunks) == [[0], [1]]


def test_the_run_records_what_was_left_out(conn, tmp_path, project):
    text = "# Intro\n\n" + TEXT + "\n" + ("More about image quality and metrics. " * 45) + "\n\n# References\n\nSmith, 2020. A paper.\n"
    source = upload(conn, tmp_path, project, name="a.md", content=text)
    eid = qa.start(conn, source["id"], "m")
    reading = sources.extraction_summary(conn, eid)["reading"]
    assert reading["by_section"] is True
    assert [e["reason"] for e in reading["left_out"]] == ["bibliography"]
    assert sources.extraction_progress(conn, source["id"])["reading"] == reading


# --- quotes ---

@pytest.mark.parametrize("quote, source, stored", [
    ("the phenomenon of hops", "the phe-\nnomenon of hops", "the phe-\nnomenon of hops"),
    ("the phe- nomenon of hops", "the phe-\nnomenon of hops", "the phe-\nnomenon of hops"),
    ("a multi-hop query", "a multi-\nhop query", "a multi-\nhop query"),
    ("a multihop query", "a multi-hop query", "a multi-hop query"),
    ("the first filter", "the ﬁrst ﬁlter", "the ﬁrst ﬁlter"),
    ("the ﬁrst", "the first one", "the first"),
    ("spread   over\nlines", "spread over lines", "spread over lines"),
    ("range 3 - 4 holds", "range 3 - 4 holds", "range 3 - 4 holds"),
])
def test_a_quote_matches_across_extraction_noise_and_keeps_the_source_text(quote, source, stored):
    assert sources.find_quote(quote, source) == stored


@pytest.mark.parametrize("quote, source", [("", "any text"), ("   ", "any text"), ("something else", "any text")])
def test_a_quote_that_is_not_there_is_not_found(quote, source):
    assert sources.find_quote(quote, source) is None


def test_a_pair_quoting_across_a_line_break_keeps_the_source_text_and_exports(conn, tmp_path, project):
    broken = "Peak signal-to-noise ratio is a com-\nmon measure of how close a compressed image stays to its original picture.\n\n" + TEXT
    generate(conn, Stub(pairs=[pair(question="What does PSNR measure in a compressed image?", answer="How close it stays to the original.",
                                    quote="is a common measure of how close")]),
             upload(conn, tmp_path, project, content=broken))
    sample = qa.list_samples(conn, project["id"])[0]
    assert sample["quote"] == "Peak signal-to-noise ratio is a com-\nmon measure of how close a compressed image stays to its original picture."
    qa.decide(conn, sample["id"], "approve")
    assert datasets.export_dataset(conn, tmp_path / "out", "d", project["id"])["sample_count"] == 1


def test_a_quote_may_run_into_the_next_passage_and_still_exports(conn, tmp_path, project):
    long_paragraph = "Image quality has many sides worth measuring with care. " * 11 + "Sharpness survives heavy compression only when the codec keeps the fine edges intact across every frame of the clip."
    source = upload(conn, tmp_path, project, content=long_paragraph + "\n\n" + TEXT)
    first, second = source["chunks"][0], source["chunks"][1]
    quote = first["text"].strip()[-30:] + " " + second["text"].strip()[:30]
    generate(conn, Stub(pairs=[pair(question="What does sharpness need from a codec?", answer="It needs the fine edges kept.", quote=quote)]), source)
    sample = qa.list_samples(conn, project["id"])[0]
    assert sample["chunk_id"] == first["id"]
    qa.decide(conn, sample["id"], "approve")
    assert datasets.export_dataset(conn, tmp_path / "out", "d", project["id"])["sample_count"] == 1


def test_a_quote_does_not_run_across_passages_that_are_not_neighbors():
    window = [{"index": 0, "text": "alpha beta"}, {"index": 5, "text": "gamma delta"}]
    assert qa.locate_quote("beta gamma", window) == (None, None)


LONG = "\n\n".join(f"Paragraph {i} explains how image metrics compare a compressed picture with its original in some detail." for i in range(60))


def test_a_read_chooses_how_many_pairs_per_section_and_records_it(conn, tmp_path, project):
    many = [pair(question=f"Which fact number {i} about PSNR values is true for viewers?", answer=f"Fact {i} says above 40 dB most viewers see no difference.") for i in range(9)]
    stub = Stub(pairs=many)
    source = upload(conn, tmp_path, project)
    eid = qa.start(conn, source["id"], "m", pairs_per_section=3)
    result = qa.run(conn, stub, eid)
    assert result["status"] == "succeeded"
    assert len(qa.list_samples(conn, project["id"], source_id=source["id"])) == 3
    assert "write up to 3 pairs" in stub.prompts[-1]
    assert sources.extraction_progress(conn, source["id"])["reading"]["options"] == {"amount": "normal", "care": "direct", "mix": None, "pairs_per_section": 3, "section_chars": 4500, "images": False, "unanswered_pct": 0, "false_premise_pct": 0, "neighbour_pct": 0, "false_per_section": 0, "doubts_per_section": 0}


def test_a_read_chooses_the_section_length(conn, tmp_path, project):
    chunks = sources.get_source(conn, upload(conn, tmp_path, project, "long.txt", LONG)["id"])["chunks"]
    assert len(qa.read_plan(chunks, window_chars=2000)["windows"]) > len(qa.read_plan(chunks, window_chars=4500)["windows"])


def test_density_limits_follow_verifiable_facts_and_ignore_reference_sections():
    dense = [{"text": "Mitochondria contain 37 genes. Smith measured 12 cells. Heat causes damage in 2020."}]
    plain = [{"text": ""}]
    refs = [{"text": "Smith, J. (2020). Cell biology. Journal of Things 4, 20-30.", "locator": {"section": "References"}}]
    assert qa.density_limit(dense, "everything") > qa.density_limit(plain, "everything") == 0
    assert qa.read_plan(refs)["windows"] == []


def test_read_preferences_map_old_values_and_total_mix_targets():
    assert qa.read_preferences("quick", "direct")["pairs_per_section"] < qa.read_preferences("everything", "direct")["pairs_per_section"]
    assert (qa.read_preferences("normal", "direct")["false_premise_pct"], qa.read_preferences("normal", "direct")["unanswered_pct"]) == (7, 8)
    assert qa.read_preferences("normal", "balanced")["false_per_section"] > 0
    assert qa.mix_targets(70, 15, 15) == (15, 15)
    assert qa.mix_targets(70, 0, 0) == (0, 0)


def test_the_api_refuses_options_out_of_range(conn, tmp_path, project, monkeypatch):
    monkeypatch.setattr(api, "conn", lambda: conn)
    client = TestClient(api.app)
    source = upload(conn, tmp_path, project)
    url = f"/projects/{project['id']}/sources/{source['id']}/generate"
    assert client.post(url, json={"model": "m", "pairs_per_section": 13}).status_code == 422
    assert client.post(url, json={"model": "m", "section_chars": 1000}).status_code == 422


def test_reading_estimate_counts_fact_windows_without_a_model(conn, tmp_path, project, monkeypatch):
    monkeypatch.setattr(api, "conn", lambda: conn)
    source = upload(conn, tmp_path, project, content=TEXT)
    response = TestClient(api.app).get(f"/projects/{project['id']}/reading-estimate?amount=everything&care=direct")
    assert response.status_code == 200
    assert response.json()["pairs"] > 0
    assert response.json()["minutes"] >= 1
    assert response.json()["windows"] > 0


def test_reading_estimate_uses_model_history_but_keeps_density_pair_count(conn, tmp_path, project, monkeypatch):
    monkeypatch.setattr(api, "conn", lambda: conn)
    source = upload(conn, tmp_path, project, content=TEXT)
    stub = Stub(pairs=[pair()])
    stub.model = "history-model"
    generate(conn, stub, source)
    progress = sources.extraction_progress(conn, source["id"])
    assert progress["duration_seconds"] is not None
    response = TestClient(api.app).get(
        f"/projects/{project['id']}/reading-estimate?amount=normal&care=balanced&model=history-model"
    )
    assert response.status_code == 200
    body = response.json()
    made = conn.execute("SELECT COUNT(*) FROM qa_samples WHERE source_id = ? AND origin != 'refusal'", (source["id"],)).fetchone()[0]
    # One earlier reading of this same file: the estimate gives back what it really made, not the density ceiling.
    assert body["pairs_per_window"] == round(made / body["windows"], 2)
    assert abs(body["pairs"] - made) <= 1
    assert body["seconds_per_window"] >= 0


class Eye:
    model = "vision-stub"

    def __init__(self, fail=False):
        self.calls, self.fail = 0, fail

    def read_figure(self, png):
        self.calls += 1
        if self.fail:
            raise RuntimeError("model went away")
        return {"visible_text": "", "reading": "A curve shows that PSNR above 40 dB looks the same to viewers in every test that was shown here, while lower values show visible blocks and banding."}


def _png():
    import io
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (120, 120), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def picture(conn, tmp_path, project):
    return sources.ingest_bytes(conn, tmp_path / "sources", project_id=project["id"], name="scan.png", data=_png(),
                                purpose="qa-dataset", license_basis="own")


FIGURE_PAIR = {"question": "What does the PSNR curve show about viewers?", "answer": "Above 40 dB viewers see no change.",
               "quote": "PSNR above 40 dB looks the same to viewers", "theme": "image-metrics"}


def test_images_off_a_picture_file_says_how_to_read_it(conn, tmp_path, project):
    with pytest.raises(sources.SourceRejected, match="Read images"):
        qa.start(conn, picture(conn, tmp_path, project)["id"], "m")


def test_images_on_reads_the_figures_first_and_their_pairs_cite_the_reading(conn, tmp_path, project):
    source, eye = picture(conn, tmp_path, project), Eye()
    eid = qa.start(conn, source["id"], "m", images=True)
    result = qa.run(conn, Stub(pairs=[FIGURE_PAIR]), eid, out_dir=tmp_path / "sources", vision=eye)
    assert result["status"] == "succeeded"
    assert eye.calls == 1
    progress = sources.extraction_progress(conn, source["id"])
    assert progress["reading"]["figures"] == {"read": 1, "total": 1, "failed": 0, "skipped": 0}
    assert progress["kept"] == 1
    assert sources.get_source(conn, source["id"])["status"] == "available"


def test_images_off_leaves_a_reading_out_and_says_so(conn, tmp_path, project):
    source = sources.ingest_bytes(conn, tmp_path / "sources", project_id=project["id"], name="doc.md",
                                  data=TEXT.encode(), purpose="qa-dataset", license_basis="own")
    chunks = sources.get_source(conn, source["id"])["chunks"]
    chunks = chunks + [{"index": 99, "text": "A curve falls as the rate grows and this is the reading.", "kind": "figure_reading", "locator": {}}]
    plan = qa.read_plan(chunks, images=False)
    assert all(c["index"] != 99 for w in plan["windows"] for c in w)
    assert {"reason": "image reading, with images off", "passages": 1, "chars": len(chunks[-1]["text"])} in plan["left_out"]


def test_reading_figures_skips_what_was_read_and_retries_what_failed(conn, tmp_path, project):
    source, out = picture(conn, tmp_path, project), tmp_path / "sources"
    failed = sources.read_figures(conn, out, source["id"], Eye(fail=True))
    listed = next(s for s in sources.list_sources(conn, source["project_id"]) if s["id"] == source["id"])
    assert "model went away" in listed["assets"][0]["ocr_error"]
    assert failed["failed"] == 1 and "model went away" in failed["error"]
    assert sources.list_sources(conn, project["id"])[0]["assets"][0]["ocr_status"] == "failed"
    assert sources.read_figures(conn, out, source["id"], Eye())["failed"] == 0
    assert sources.get_source(conn, source["id"])["assets"][0]["ocr_error"] == ""
    listed = sources.list_sources(conn, project["id"])[0]
    assert listed["totals"]["figures_read"] == 1
    cited = [c["id"] for c in sources.get_source(conn, source["id"])["chunks"]]
    again = Eye()
    assert sources.read_figures(conn, out, source["id"], again)["total"] == 0 and again.calls == 0
    assert [c["id"] for c in sources.get_source(conn, source["id"])["chunks"]] == cited


@pytest.mark.parametrize("question", [
    "What does the diagram in Figure 713 show?",
    "What does the figure in section P430 illustrate?",
    "What does the figure in section [P438] illustrate?",
    "What does the diagram comparing retrieval methods illustrate?",
    "What does Figure 2 show about indexing?",
    "O que a figura mostra sobre indexação?",
])
def test_a_pair_that_needs_the_picture_or_a_passage_number_is_not_proposed(question):
    assert "talks about its source instead of the subject" in qa.check_pair(question, "It compares three systems.", "Section body.")


@pytest.mark.parametrize("question", [
    "How does the retrieval diagram language of p53 research treat the P53 protein?",
    "What is the figure of merit of the image encoder?",
    "What does the knowledge graph store?",
])
def test_ordinary_words_near_a_figure_are_not_mistaken_for_it(question):
    assert "talks about its source instead of the subject" not in qa.check_pair(question, "It stores triples.", "Section body.")


def test_the_figure_prompt_keeps_the_picture_and_its_number_out_of_the_pair():
    window = [{"index": 713, "kind": "figure_reading", "text": "Maps an LLM to the neocortex."}]
    prompt = qa.pair_prompt({"display_name": "D"}, "English", [], window)
    assert "[P713 · figure reading" in prompt
    assert "Never mention a figure, diagram or image, a figure number, or a [P#] marker." in prompt


def test_a_model_server_that_is_down_is_a_clear_503(client, monkeypatch):
    def down(_url):
        raise api.LLMError("ollama unreachable at http://x: refused")
    monkeypatch.setattr(api, "installed_models", down)
    project = client.post("/projects", json={"display_name": "Down"})
    assert project.status_code < 300, project.text
    response = client.post(f"/projects/{project.json()['id']}/sources/none/figures/read", json={"model": "m"})
    assert response.status_code == 503
    assert "ollama unreachable" in response.json()["detail"]


# --- A person changes a pair's kind ---

REFUSAL_ANSWER = "That is not something I know about this subject."


def _answered(conn, tmp_path, project):
    generate(conn, Stub(pairs=[pair()]), upload(conn, tmp_path, project))
    return qa.list_samples(conn, project["id"], origin="file")[0]


def test_answered_becomes_unanswered_without_quote_and_back_to_review(conn, tmp_path, project):
    sample = _answered(conn, tmp_path, project)
    qa.decide(conn, sample["id"], "approve")
    with pytest.raises(ValueError, match="rewrite the answer"):
        kinds.change_kind(conn, sample["id"], "refusal")
    changed = kinds.change_kind(conn, sample["id"], "refusal", answer=REFUSAL_ANSWER)
    assert (changed["origin"], changed["status"], changed["quote"], changed["chunk_id"]) == ("refusal", "proposed", "", None)
    assert changed["revision"] == sample["revision"] + 1
    assert qa.get_theme(conn, changed["theme_id"])["kind"] == "limits"


def test_unanswered_becomes_answered_only_with_a_quote_in_the_files_and_a_theme(conn, tmp_path, project):
    sample = _answered(conn, tmp_path, project)
    refusal = kinds.change_kind(conn, sample["id"], "refusal", answer=REFUSAL_ANSWER)
    theme = sample["theme_id"]
    new_answer = "Above 40 dB most viewers see no difference at all."
    with pytest.raises(ValueError, match="needs a quote"):
        kinds.change_kind(conn, refusal["id"], "file", answer=new_answer, theme_id=theme)
    with pytest.raises(ValueError, match="not in the files"):
        kinds.change_kind(conn, refusal["id"], "file", answer=new_answer, quote="Nothing like this was written", theme_id=theme)
    with pytest.raises(ValueError, match="choose a theme"):
        kinds.change_kind(conn, refusal["id"], "file", answer=new_answer, quote=PSNR_QUOTE)
    with pytest.raises(ValueError, match="rewrite the answer"):
        kinds.change_kind(conn, refusal["id"], "file", quote=PSNR_QUOTE, theme_id=theme)
    with pytest.raises(ValueError, match="numbers"):
        kinds.change_kind(conn, refusal["id"], "file", answer="Above 90 dB nobody sees it.", quote=PSNR_QUOTE, theme_id=theme)
    changed = kinds.change_kind(conn, refusal["id"], "file", answer=new_answer, quote=PSNR_QUOTE, theme_id=theme)
    assert changed["origin"] == "file" and sources.quote_holds(conn, changed["chunk_id"], changed["quote"])
    assert changed["theme_id"] == theme and changed["source_name"]


def test_answered_becomes_a_false_premise_that_can_be_exported(conn, tmp_path, project):
    sample = _answered(conn, tmp_path, project)
    wrong_q, fixed = "Why is 10 dB invisible to viewers?", "It is not: the difference stops showing above 40 dB."
    with pytest.raises(ValueError, match="false claim"):
        kinds.change_kind(conn, sample["id"], "false_premise", question=wrong_q, answer=fixed)
    with pytest.raises(ValueError, match="same question"):
        kinds.change_kind(conn, sample["id"], "false_premise", answer=fixed, false_claim="10 dB is invisible.")
    changed = kinds.change_kind(conn, sample["id"], "false_premise", question=wrong_q, answer=fixed, false_claim="10 dB is invisible.")
    assert changed["origin"] == "false_premise" and changed["quote"] == sample["quote"]
    qa.decide(conn, changed["id"], "approve")
    kept, excluded = datasets._candidates(conn, project["id"], None)
    assert [k["id"] for k in kept] == [changed["id"]] and not excluded
    back = kinds.change_kind(conn, changed["id"], "file", question=sample["question"], answer=sample["answer"])
    assert (back["origin"], back["false_claim"], back["status"]) == ("file", "", "proposed")


def test_a_pair_others_rest_on_keeps_its_kind_and_a_changed_child_loses_its_link(conn, tmp_path, project):
    sample = _answered(conn, tmp_path, project)
    child = kinds._insert(conn, Stub(), sample, project["id"], "false_premise", "Why is 10 dB invisible to viewers?",
                          "It is not: the difference stops showing above 40 dB.", "digest", "10 dB is invisible.", None)
    conn.commit()
    with pytest.raises(ValueError, match="rest on this one"):
        kinds.change_kind(conn, sample["id"], "refusal", answer=REFUSAL_ANSWER)
    other = kinds._insert(conn, Stub(), sample, project["id"], "true_premise", "Does 40 dB look the same to viewers?",
                          "Yes, above 40 dB it does.", "digest2", "", None)
    conn.commit()
    qa.decide(conn, other, "reject")
    changed = kinds.change_kind(conn, child, "file", question="Which PSNR value stays invisible to viewers?",
                                answer="Above 40 dB the difference stays invisible.")
    assert changed["based_on"] == []
    assert kinds.change_kind(conn, sample["id"], "refusal", answer=REFUSAL_ANSWER)["origin"] == "refusal"


def test_other_kinds_cannot_be_changed(conn, tmp_path, project):
    sample = _answered(conn, tmp_path, project)
    for target in ("connection", "behavior", "true_premise"):
        with pytest.raises(ValueError, match="can change kind"):
            kinds.change_kind(conn, sample["id"], target)
    with pytest.raises(ValueError, match="already has"):
        kinds.change_kind(conn, sample["id"], "file")
    true_version = kinds._insert(conn, Stub(), sample, project["id"], "true_premise", "Does 40 dB look the same to viewers?",
                                 "Yes, above 40 dB it does.", "digest", "", None)
    conn.commit()
    with pytest.raises(ValueError, match="can change kind"):
        kinds.change_kind(conn, true_version, "file", answer="Other words.")


def test_kind_change_over_http_reports_what_is_missing(client, monkeypatch):
    monkeypatch.setattr(api, "OllamaClient", lambda **kw: Stub(pairs=[pair()]))
    p = client.post("/projects", json={"display_name": "Metrics", "max_themes": 4}).json()
    base = f"/projects/{p['id']}"
    source = client.post(f"{base}/sources/upload", files={"file": ("a.txt", TEXT.encode(), "text/plain")}).json()
    client.post(f"{base}/sources/{source['id']}/generate", json={"model": "m"})
    samples = client.get(f"{base}/samples").json()
    url = f"{base}/samples/{samples[0]['id']}/kind"
    assert "rewrite the answer" in client.post(url, json={"origin": "refusal"}).json()["detail"]
    done = client.post(url, json={"origin": "refusal", "answer": REFUSAL_ANSWER})
    assert done.status_code == 200 and done.json()["origin"] == "refusal"


# --- choosing what an export writes ---

def test_an_export_writes_only_the_outputs_chosen(conn, tmp_path, project):
    first, _ = approved_export(conn, tmp_path, project)
    only_memory = datasets.export_dataset(conn, tmp_path / "a", "m", project["id"], outputs=["memory"])
    folder = Path(only_memory["folder"])
    assert sorted(p.name for p in folder.iterdir()) == ["manifest.json", "memory.jsonl", "sources.json"]
    assert only_memory["memory_count"] == 1 and json.loads((folder / "manifest.json").read_text())["outputs"] == ["memory"]

    only_training = datasets.export_dataset(conn, tmp_path / "b", "t", project["id"], outputs=["finetune"])
    folder = Path(only_training["folder"])
    assert (folder / "samples.jsonl").exists() and (folder / "train.jsonl").exists()
    assert not (folder / "memory.jsonl").exists() and not (folder / "wiki").exists()

    only_wiki = datasets.export_dataset(conn, tmp_path / "c", "w", project["id"], outputs=["wiki"])
    assert (Path(only_wiki["folder"]) / "wiki").is_dir() and not (Path(only_wiki["folder"]) / "samples.jsonl").exists()
    assert datasets.list_datasets(conn, project["id"])[0]["outputs"] in ("memory", "finetune", "wiki")

    with pytest.raises(ValueError):
        datasets.export_dataset(conn, tmp_path / "d", "n", project["id"], outputs=[])


def test_an_output_with_nothing_to_write_refuses_and_leaves_no_export(conn, tmp_path, project):
    pattern = workshop.create_pattern(conn, project_id=project["id"], title="Quiet company", intent="stay with the person",
                                      tone="calm", guidelines="one detail", description="a hard day")
    workshop.set_pattern_status(conn, pattern["id"], "approved")
    workshop.generate_batch(conn, Writer(), pattern["id"], count=1)
    qa.decide(conn, qa.list_samples(conn, project["id"])[0]["id"], "approve")
    with pytest.raises(ValueError, match="nothing to write"):
        datasets.export_dataset(conn, tmp_path / "out", "b", project["id"], outputs=["memory", "wiki"])
    assert datasets.list_datasets(conn, project["id"]) == [] and not (tmp_path / "out").exists()


def test_the_count_says_what_was_written_not_what_was_approved(conn, tmp_path, project):
    approved_export(conn, tmp_path, project)
    pattern = workshop.create_pattern(conn, project_id=project["id"], title="Quiet company", intent="stay with the person",
                                      tone="calm", guidelines="one detail", description="a hard day")
    workshop.set_pattern_status(conn, pattern["id"], "approved")
    workshop.generate_batch(conn, Writer(), pattern["id"], count=1)
    behavior = next(s for s in qa.list_samples(conn, project["id"]) if s["origin"] == "behavior")
    qa.decide(conn, behavior["id"], "approve")
    assert datasets.export_dataset(conn, tmp_path / "t", "t", project["id"], outputs=["finetune"])["sample_count"] == 2
    assert datasets.export_dataset(conn, tmp_path / "m", "m", project["id"], outputs=["memory"])["sample_count"] == 1
    assert datasets.export_dataset(conn, tmp_path / "w", "w", project["id"], outputs=["wiki"])["sample_count"] == 1


# --- similar pairs ---

def similar_project(conn, tmp_path, project, pairs):
    source = upload(conn, tmp_path, project)
    assert generate(conn, Stub(pairs=pairs), source)
    return {s["question"]: s for s in qa.list_samples(conn, project["id"])}


def test_rewordings_are_grouped_and_nothing_changes(conn, tmp_path, project):
    a, b = "What PSNR value is usually invisible to viewers?", "To viewers, which PSNR value is usually invisible?"
    pairs = similar_project(conn, tmp_path, project, [pair(a), pair(b), pair("How does structural similarity compare images?", "It compares luminance and contrast.")])
    groups = qa.similar_groups(conn, project["id"])
    assert len(pairs) == 3 and [{s["question"] for s in g["samples"]} for g in groups] == [{a, b}]
    assert {s["status"] for s in qa.list_samples(conn, project["id"])} == {"proposed"}


def test_a_close_question_needs_a_close_answer_too(conn, tmp_path, project):
    similar_project(conn, tmp_path, project, [
        pair("What PSNR value do viewers usually miss on screens?", "Above 40 dB most viewers see no difference."),
        pair("What PSNR value do viewers usually accept in photos?", "Above 40 dB most viewers see no difference at all."),
        pair("What PSNR value do people usually miss on phones?", "Phones hide compression below thirty decibels."),
    ])
    grouped = [{s["question"] for s in g["samples"]} for g in qa.similar_groups(conn, project["id"])]
    assert grouped == [{"What PSNR value do viewers usually miss on screens?", "What PSNR value do viewers usually accept in photos?"}]


def test_different_kinds_are_not_compared(conn, tmp_path, project):
    pairs = similar_project(conn, tmp_path, project, [pair(), pair("To viewers, which PSNR value is usually invisible?")])
    first, second = pairs.values()
    conn.execute("UPDATE qa_samples SET origin = 'refusal' WHERE id = ?", (first["id"],))
    assert qa.similar_groups(conn, project["id"]) == []
    conn.execute("UPDATE qa_samples SET origin = 'file' WHERE id = ?", (first["id"],))
    assert len(qa.similar_groups(conn, project["id"])) == 1


def test_keep_one_rejects_the_others_and_can_go_back(conn, tmp_path, project):
    first, second = similar_project(conn, tmp_path, project, [pair(), pair("To viewers, which PSNR value is usually invisible?")]).values()
    assert qa.keep_one(conn, project["id"], first["id"], [first["id"], second["id"]]) == {"rejected": 1}
    assert qa.get_sample(conn, first["id"])["status"] == "proposed"
    assert qa.get_sample(conn, second["id"])["status"] == "rejected"
    assert qa.similar_groups(conn, project["id"]) == []
    qa.decide(conn, second["id"], "reset")
    assert len(qa.similar_groups(conn, project["id"])) == 1


def test_keep_apart_stays_until_undone_and_keeps_decisions(conn, tmp_path, project):
    first, second = similar_project(conn, tmp_path, project, [pair(), pair("To viewers, which PSNR value is usually invisible?")]).values()
    ids = [second["id"], first["id"]]
    qa.keep_apart(conn, project["id"], ids)
    qa.keep_apart(conn, project["id"], ids)
    assert qa.similar_groups(conn, project["id"]) == []
    assert qa.get_sample(conn, first["id"])["status"] == "proposed"
    qa.keep_apart(conn, project["id"], ids, undo=True)
    assert len(qa.similar_groups(conn, project["id"])) == 1


def test_similar_decisions_refuse_pairs_of_another_project(conn, tmp_path, project):
    first, second = similar_project(conn, tmp_path, project, [pair(), pair("To viewers, which PSNR value is usually invisible?")]).values()
    other = projects.create(conn, display_name="Other", language="en", slug="other", max_themes=8)
    with pytest.raises(workshop.NotFound):
        qa.keep_one(conn, other["id"], first["id"], [first["id"], second["id"]])
    with pytest.raises(workshop.NotFound):
        qa.keep_apart(conn, other["id"], [first["id"], second["id"]])
    assert qa.get_sample(conn, second["id"])["status"] == "proposed"
    with pytest.raises(ValueError):
        qa.keep_one(conn, project["id"], "missing", [first["id"], second["id"]])


def test_every_pair_stands_on_one_pillar_and_the_counts_follow_decisions(conn, tmp_path, project):
    assert set(qa.PILLAR.values()) == set(qa.PILLARS)
    source = upload(conn, tmp_path, project)
    generate(conn, Stub(pairs=[pair()]), source)
    sample = qa.list_samples(conn, project["id"])[0]
    assert sample["pillar"] == "known"
    assert qa.pillar_counts(conn, project["id"])["known"] == {"proposed": 1, "approved": 0, "rejected": 0}
    qa.decide(conn, sample["id"], "approve")
    assert qa.pillar_counts(conn, project["id"])["known"] == {"proposed": 0, "approved": 1, "rejected": 0}
    assert qa.pillar_counts(conn, project["id"])["not_known"] == {"proposed": 0, "approved": 0, "rejected": 0}


# --- quotes the model shortened, numbers it spaced ---

def test_a_quote_cut_with_dots_is_found_as_the_sources_own_span():
    text = "The first stage reads every file carefully. Then the second stage writes the pairs for the reviewers."
    found = sources.find_quote("The first stage reads every file ... writes the pairs for the reviewers", text)
    assert found == "The first stage reads every file carefully. Then the second stage writes the pairs for the reviewers"


def test_a_quote_with_different_spaces_and_capitals_is_found():
    text = "Graph retrieval improves recall on multi-hop questions."
    assert sources.find_quote("graph  retrieval improves RECALL on multi-hop questions", text)


def test_a_cut_quote_is_refused_when_its_parts_are_out_of_order_or_too_far():
    text = "Alpha part of the sentence here. Beta part of the sentence here."
    assert sources.find_quote("Beta part of the sentence ... Alpha part of the sentence", text) is None
    far = "Alpha part of the sentence here. " + "filler words " * 100 + "Beta part of the sentence here."
    assert sources.find_quote("Alpha part of the sentence ... Beta part of the sentence", far) is None


def test_a_number_written_with_a_space_after_the_comma_is_still_the_same_number():
    section = "The corpus holds 86, 864 documents in total."
    assert not [r for r in qa.check_pair("How many documents does the corpus hold?", "It holds 86,864 documents.", section) if "number" in r]


def test_quote_is_expanded_to_complete_sentence_and_metadata_questions_are_filtered():
    text = "Arthropods and nematodes account for 15–20% of the count. Tardigrades account for 2%. The next sentence explains the result."
    chunk, quote = qa.locate_quote("15–20% of the count", [{"index": 0, "text": text}])
    assert chunk and quote == "Arthropods and nematodes account for 15–20% of the count."
    assert any("publication" in why for why in qa.check_pair("What date was the paper accepted?", "It was accepted in 2020.", text))


def test_reference_affiliation_acknowledgement_and_metadata_sections_are_left_out():
    chunks = [{"text": "Author and address records. " * 30, "locator": {"section": "Affiliations"}},
              {"text": "Grant details and funders. " * 30, "locator": {"section": "Funding"}},
              {"text": "Thanks to the contributors. " * 30, "locator": {"section": "Acknowledgements"}}]
    plan = qa.read_plan(chunks)
    assert not plan["windows"]
    assert {entry["reason"] for entry in plan["left_out"]} >= {"affiliations", "metadata", "acknowledgements"}


def test_only_rare_unsupported_technical_terms_are_rejected():
    quote = "The cells protect proteins during drying."
    reasons = qa.check_pair("How do the cells protect proteins?", "They protect proteins. They use hyperphosphorylation.", quote)
    assert any("rare technical word" in why for why in reasons)


def test_technical_term_in_passage_or_inflected_form_is_allowed_even_if_not_in_quote():
    passage = "Osmoprotective compounds preserve proteins during drying."
    assert not any("rare technical word" in why for why in qa.check_pair(
        "How do the cells protect proteins?", "They use osmoprotective mechanisms.", passage))


def test_technical_synonym_supported_by_passage_is_allowed():
    assert not any("rare technical word" in why for why in qa.check_pair(
        "What happens to the proteins?", "They remain stable through osmoprotection.",
        "The cells protect proteins during drying."))


def test_answer_cannot_assign_a_neighbouring_subjects_percentage_to_the_question_subject():
    quote = "Arthropods and nematodes account for 15–20% of the count."
    reasons = qa.check_pair("What share do tardigrades make up?", "Tardigrades account for 15–20%.", quote)
    assert not any("rare technical word" in why for why in reasons)


def test_machine_process_language_is_rejected_from_pairs():
    reasons = qa.check_pair("What does the original statement claim?", "The corrected information gives the result.", "The result is 18 meters.")
    assert any("process" in why for why in reasons)


def test_false_premise_claim_supported_by_quote_is_rejected():
    from amelia_academy import kinds
    quote = "Saltreach was completed in 1998 and is 18 meters tall."
    assert "the quote supports the supposed false claim" in kinds.check_false_premise(
        "Was Saltreach finished in 1998?", "Yes, it was.", "Saltreach completed in 1998.", {"quote": quote})


def test_false_claim_that_quote_affirms_is_rejected():
    from amelia_academy import kinds
    quote = "CAHS3 expression increased cell proliferation and improved viability."
    reasons = kinds.check_false_premise(
        "Does CAHS3 expression fail to impact proliferation or viability?", "It did not.",
        "CAHS3 expression does not impact proliferation or viability.", {"quote": quote})
    assert "the quote supports the supposed false claim" in reasons


def test_curate_similarity_threshold_is_reused_for_prepare_and_compare():
    assert qa.questions_similar("How does retrieval improve recall?", "How does retrieval improve recall for linked passages?")
    assert not qa.questions_similar("How does retrieval improve recall?", "What colour was the sample?")


# --- one reading, three groups ---

class Reader(Stub):
    def __init__(self, known=None, false=None, doubts=None, **kw):
        super().__init__(**kw)
        self.group = {"known": known or [], "false_premise": false or [], "not_known": doubts or []}

    def complete_json(self, prompt, schema, temperature=0.9):
        if "known" in schema["properties"]:
            self.calls += 1
            self.prompts.append(prompt)
            return self.group
        if "answered" in schema.get("properties", {}):
            self.prompts.append(prompt)
            return {"answered": False, "quote": ""}
        return super().complete_json(prompt, schema, temperature)


def read_three(conn, llm, source, falses=2, doubts=2):
    return qa.run(conn, llm, qa.start(conn, source["id"], llm.model, false_per_section=falses, doubts_per_section=doubts))


def test_one_reading_writes_all_three_pillars(conn, tmp_path, project):
    llm = Reader(known=[pair()],
                 false=[{"false_claim": "A PSNR above 40 dB is always visible.", "question": "Why is a PSNR above 40 dB always visible?",
                         "answer": "It is not: above 40 dB the difference is usually invisible.", "quote": PSNR_QUOTE, "theme": "image-metrics"}],
                     doubts=[{"question": "What survival rate did the PSNR trials report?", "answer": "I don't know the survival rate they reported."}])
    assert read_three(conn, llm, upload(conn, tmp_path, project))["status"] == "succeeded"
    assert qa.pillar_counts(conn, project["id"])["known"]["proposed"] == 1
    samples = {s["origin"]: s for s in qa.list_samples(conn, project["id"])}
    assert samples["false_premise"]["quote"] == PSNR_QUOTE + " to most viewers looking at the two pictures." and samples["false_premise"]["false_claim"].startswith("A PSNR")
    assert samples["refusal"]["quote"] == "" or samples["refusal"]["quote"] is None
    assert samples["refusal"]["theme_title"]
    assert sources.extraction_progress(conn, samples["file"]["source_id"])["reading"]["groups"] == {"false_premise": 1, "not_known": 1}


def test_themes_and_pillars_cross(conn, tmp_path, project):
    llm = Reader(known=[pair()],
                 doubts=[{"question": "Which survival rate did the PSNR trials report?", "answer": "I don't know which rate they reported.", "theme": "image-metrics"},
                         {"question": "Which colour model did the PSNR trials assume?", "answer": "I don't know which one they assumed.", "theme": "made-up"}])
    assert read_three(conn, llm, upload(conn, tmp_path, project))["status"] == "succeeded"
    doubts = {s["question"]: s for s in qa.list_samples(conn, project["id"]) if s["origin"] == "refusal"}
    known = next(s for s in qa.list_samples(conn, project["id"]) if s["origin"] == "file")
    assert doubts["Which survival rate did the PSNR trials report?"]["theme_id"] == known["theme_id"]
    assert doubts["Which colour model did the PSNR trials assume?"]["theme_id"] != known["theme_id"]
    theme = next(t for t in qa.list_themes(conn, project["id"]) if t["id"] == known["theme_id"])
    assert theme["pillars"]["known"]["proposed"] == 1 and theme["pillars"]["not_known"]["proposed"] == 1


def test_not_known_is_checked_against_other_project_files(conn, tmp_path, project):
    upload(conn, tmp_path, project, name="answer.txt",
           content="The CAHS proteins contain three exons. CAHS proteins are abundant in tardigrades.")
    llm = Reader(known=[pair()], doubts=[{
        "question": "How many exons are in the CAHS proteins?",
        "answer": "I don't know how many exons are in the CAHS proteins.",
    }])
    current = upload(conn, tmp_path, project, name="question.txt", content=TEXT)
    run = read_three(conn, llm, current, falses=0, doubts=1)
    assert run["status"] == "succeeded"
    assert not [s for s in qa.list_samples(conn, project["id"]) if s["origin"] == "refusal"]
    rejected = json.loads(db.row(conn, "SELECT rejected FROM extractions WHERE id = ?", (run["id"],))["rejected"])
    assert any("project answers the question" in row["reason"] for row in rejected)


def test_each_group_answers_for_its_own_rules(conn, tmp_path, project):
    llm = Reader(known=[pair()],
                 false=[{"false_claim": "x", "question": "Why?", "answer": "It is 77 dB.", "quote": PSNR_QUOTE, "theme": "image-metrics"}],
                 doubts=[{"question": "What does Appendix H of the PSNR work list?", "answer": "I don't know."}])
    run = read_three(conn, llm, upload(conn, tmp_path, project))
    assert {s["origin"] for s in qa.list_samples(conn, project["id"])} == {"file"}
    reasons = " ".join(r["reason"] for r in json.loads(db.row(conn, "SELECT rejected FROM extractions WHERE id = ?", (run["id"],))["rejected"]))
    assert "number not in the quote" in reasons and "talks about its source" in reasons


def test_a_broken_group_does_not_cost_the_reading(conn, tmp_path, project):
    llm = Reader(known=[pair()])
    llm.group["false_premise"] = "nothing"
    assert read_three(conn, llm, upload(conn, tmp_path, project))["status"] == "succeeded"
    assert len(qa.list_samples(conn, project["id"])) == 1


def test_a_false_premise_from_one_reading_exports_without_a_parent(conn, tmp_path, project):
    llm = Reader(false=[{"false_claim": "A PSNR above 40 dB is always visible.", "question": "Why is a PSNR above 40 dB always visible?",
                         "answer": "It is not: above 40 dB the difference is usually invisible.", "quote": PSNR_QUOTE, "theme": "image-metrics"}], known=[pair()])
    read_three(conn, llm, upload(conn, tmp_path, project))
    false = [s for s in qa.list_samples(conn, project["id"]) if s["origin"] == "false_premise"][0]
    qa.decide(conn, false["id"], "approve")
    found = datasets.export_dataset(conn, tmp_path / "out", "x", project["id"], None, outputs=["memory"])
    assert found["sample_count"] == 1 and not found["excluded"]


def test_without_asking_for_groups_the_reading_stays_as_it_was(conn, tmp_path, project):
    llm = Stub(pairs=[pair()])
    generate(conn, llm, upload(conn, tmp_path, project))
    assert not any('"not_known"' in p for p in llm.prompts)


def test_a_question_has_to_name_what_it_is_about():
    section = "HippoRAG uses retrieval encoders. Sistema Alfa uses a graph."
    for vague in ("How does the system respond to hyperparameter changes?", "What is the primary motivation behind the proposed research?", "Como o sistema responde a mudanças?"):
        assert "question does not name its subject" in qa.check_pair(vague, "It responds well to every change tried.", section)
    for named in ("How does the HippoRAG system respond to hyperparameter changes?", "What is a model allowed to retrieve in HippoRAG?", "How does the method of loci relate to HippoRAG?"):
        assert "question does not name its subject" not in qa.check_pair(named, "It responds well to every change tried.", section)


def test_a_stuck_window_is_skipped_visibly_and_the_rest_is_read(conn, tmp_path, project):
    """The model runs away on one window, on the retry too: the file still gets read, and the skip is on record."""
    class Stuck:
        model = "stub-model"
        calls = 0
        retried_with = None

        def complete_json(self, prompt, schema, temperature=0.9, options=None):
            if "themes" in schema["properties"]:
                return {"themes": [{"title": "Image metrics", "description": "How pictures are compared."}]}
            self.calls += 1
            if self.calls == 3:
                self.retried_with = options
            if self.calls in (2, 3):
                raise OutputCapped("model stub-model reached the 4000-token cap")
            return {"items": [pair()]}

    source = upload(conn, tmp_path, project, content=TEXT + "\n\n" + "\n\n".join(f"Paragraph {i} about something else entirely. " * 40 for i in range(6)))
    llm = Stuck()
    done = generate(conn, llm, source)
    assert llm.calls >= 4, "the windows after the stuck one were read"
    assert llm.retried_with == {"repeat_penalty": qa.REPEAT_PENALTY}
    assert done["status"] == "succeeded"
    assert any("kept repeating itself" in r["reason"] for r in done["rejected"])


def test_a_neutral_or_repeated_false_premise_is_turned_down(conn, tmp_path, project):
    source = upload(conn, tmp_path, project)
    answer = "A PSNR above 40 dB is usually invisible."
    claim = {"false_claim": "A PSNR above 40 dB is always visible.", "answer": answer, "quote": PSNR_QUOTE, "theme": "image-metrics"}
    llm = Reader(false=[{**claim, "question": "Why is a PSNR above 40 dB always visible?"},
                        {**claim, "question": "Why is a PSNR above 40 dB always visible to people?"},
                        {**claim, "false_claim": "Colour errors at 60 dB always ruin a picture.", "question": "How does PSNR relate to pictures?"}])
    result = read_three(conn, llm, source, falses=3, doubts=0)
    assert [s["question"] for s in qa.list_samples(conn, project["id"]) if s["origin"] == "false_premise"] == ["Why is a PSNR above 40 dB always visible?"]
    reasons = " ".join(r["reason"] for r in result["rejected"])
    assert "too close to a false premise" in reasons and "does not state the false claim" in reasons


def test_many_decisions_skip_what_needs_a_look_and_can_be_undone(conn, tmp_path, project):
    pairs = [pair(), pair(question="How does structural similarity compare two images?",
                          answer="It compares luminance, contrast and structure.",
                          quote="compares luminance, contrast and structure")]
    generate(conn, Stub(pairs=pairs), upload(conn, tmp_path, project))
    first, second = qa.list_samples(conn, project["id"])
    conn.execute("UPDATE qa_samples SET review_note = 'Read this one.' WHERE id = ?", (first["id"],))
    conn.commit()

    assert qa.decide_many(conn, project["id"], [first["id"], second["id"]], "approve") == {"changed": [second["id"]]}
    assert qa.get_sample(conn, first["id"])["status"] == "proposed"
    assert qa.get_sample(conn, first["id"])["review_note"] == "Read this one."

    assert qa.decide_many(conn, project["id"], [second["id"]], "reset") == {"changed": [second["id"]]}
    assert qa.get_sample(conn, second["id"])["status"] == "proposed"
    with pytest.raises(ValueError):
        qa.decide_many(conn, project["id"], [second["id"]], "maybe")
