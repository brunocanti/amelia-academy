"""The knowledge base over the same pairs: graph, connected pairs, refusals, memory file, rights. The model is a stub."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from amelia_academy import api, datasets, db, kb, kinds, projects, qa, rules, sources, workshop
from amelia_academy.llm import LLMError

TEXT_A = "Peak signal-to-noise ratio above 40 dB means the difference is invisible to most viewers of a picture."
TEXT_B = "Structural similarity compares luminance, contrast and structure between two images instead of raw pixels."
FILLER = " Lorem ipsum dolor sit amet." * 20  # long enough that the paragraphs land in separate passages
Q_A = "What PSNR value is usually invisible to viewers?"
Q_B = "What does structural similarity compare between images?"


@pytest.mark.parametrize("text,count", [
    ("Chlorella vulgaris (C. vulgaris) grows quickly.", 1),
    ("Dr. Smith measured it. It grew.", 2),
    ("It grew. It split.", 2),
])
def test_sentence_count_ignores_common_abbreviations_and_binomial_names(text, count):
    assert len(rules.sentences(text)) == count
    assert kb._sentences(text) == count


class Stub:
    model = "stub-model"

    def __init__(self, items=None, fail=False):
        self.items, self.fail, self.prompts = items or [], fail, []

    def complete_json(self, prompt, schema, temperature=0.9):
        self.prompts.append(prompt)
        if self.fail:
            raise LLMError("model went away")
        if "answered" in schema["properties"]:
            return {"answered": False, "quote": ""}
        return {"items": self.items}


@pytest.fixture
def conn(tmp_path: Path):
    return db.connect(tmp_path / "t.sqlite3")


def seed(conn, tmp_path, status="approved"):
    """One project, one theme, two pairs from two passages."""
    project = projects.create(conn, display_name="Metrics", language="en", slug="metrics", max_themes=8)
    source = sources.ingest(conn, tmp_path / "s", project_id=project["id"], name="a.txt", content=f"{TEXT_A}{FILLER}\n\n{TEXT_B}{FILLER}\n",
                            purpose="qa-dataset", license_basis="unspecified")
    theme = qa.create_theme(conn, project["id"], "Image metrics")
    made = []
    chunks = source["chunks"]
    for chunk, question, answer, quote in (
            (chunks[0], Q_A, "Above 40 dB most viewers see no difference.", "above 40 dB"),
            (chunks[-1], Q_B, "It compares luminance, contrast and structure.", "luminance, contrast and structure")):
        sid = db.new_id("qa")
        conn.execute(
            "INSERT INTO qa_samples (id, project_id, theme_id, origin, source_id, chunk_id, quote, question, answer,"
            " content_hash, status, created_at) VALUES (?,?,?, 'file', ?,?,?,?,?,?,?,?)",
            (sid, project["id"], theme["id"], source["id"], chunk["id"], quote, question, answer, sid, status, db.now()))
        made.append(sid)
    conn.commit()
    assert chunks[0]["id"] != chunks[-1]["id"]
    return project, source, theme, made


CONNECTED = {"question": "How do PSNR and structural similarity differ when judging a picture?",
             "answer": "PSNR gives a value where above 40 dB looks the same, while structural similarity compares luminance, contrast and structure.",
             "facts": ["F1", "F2"]}


def test_connect_records_the_pairs_it_rests_on(conn, tmp_path):
    project, _, theme, made = seed(conn, tmp_path)
    result = kb.connect(conn, Stub([CONNECTED]), theme["id"])
    assert result == {"kept": 1, "rejected": []}
    sample = next(s for s in qa.list_samples(conn, project["id"]) if s["origin"] == "connection")
    assert sample["status"] == "proposed" and {p["id"] for p in sample["based_on"]} == set(made)


@pytest.mark.parametrize("change,reason", [
    ({"facts": ["F1"]}, "two different passages"),
    ({"facts": ["F1", "F9"]}, "two different passages"),
    ({"answer": "PSNR above 90 dB and structural similarity disagree."}, "numbers"),
    ({"question": Q_A}, "near-duplicate"),
])
def test_connect_discards_what_does_not_hold(conn, tmp_path, change, reason):
    _, _, theme, _ = seed(conn, tmp_path)
    result = kb.connect(conn, Stub([{**CONNECTED, **change}]), theme["id"])
    assert result["kept"] == 0 and ("too close to a question already asked" in result["rejected"][0]["reason"] if reason == "near-duplicate" else reason in result["rejected"][0]["reason"])


def test_connect_needs_two_passages_and_shows_model_failure(conn, tmp_path):
    project, _, theme, made = seed(conn, tmp_path)
    with pytest.raises(workshop.Conflict, match="model went away"):
        kb.connect(conn, Stub(fail=True), theme["id"])
    qa.decide(conn, made[1], "reject")
    with pytest.raises(ValueError, match="two passages"):
        kb.connect(conn, Stub([CONNECTED]), theme["id"])


def test_editing_a_pair_sends_what_rests_on_it_back_to_review(conn, tmp_path):
    project, _, theme, made = seed(conn, tmp_path)
    kb.connect(conn, Stub([CONNECTED]), theme["id"])
    sample = next(s for s in qa.list_samples(conn, project["id"]) if s["origin"] == "connection")
    qa.decide(conn, sample["id"], "approve")
    qa.edit(conn, made[0], answer="Above 40 dB nobody notices.")
    assert qa.get_sample(conn, sample["id"])["status"] == "proposed"


def test_a_connected_pair_stays_out_when_its_basis_is_not_approved_and_shares_a_split_when_it_is(conn, tmp_path):
    project, _, theme, made = seed(conn, tmp_path)
    kb.connect(conn, Stub([CONNECTED]), theme["id"])
    sample = next(s for s in qa.list_samples(conn, project["id"]) if s["origin"] == "connection")
    qa.decide(conn, sample["id"], "approve")
    items, _ = datasets._candidates(conn, project["id"], None)
    datasets._scenario_groups(items)
    assert len(set(datasets.assign_splits(items).values())) == 1

    qa.decide(conn, made[0], "reject")
    _, excluded = datasets._candidates(conn, project["id"], None)
    assert any("not approved" in r for e in excluded for r in e["reasons"])


REFUSAL = {"question": "How much does a license for the measuring software cost per year?",
           "answer": "I don't know what a license for the measuring software costs."}


def test_refusals_land_in_their_own_theme_outside_the_limit(conn, tmp_path):
    project, _, _, _ = seed(conn, tmp_path)
    assert kb.write_refusals(conn, Stub([REFUSAL]), project["id"])["kept"] == 1
    theme = next(t for t in qa.list_themes(conn, project["id"]) if t["kind"] == "limits")
    assert theme["proposed"] == 1 and len(qa._topics(conn, project["id"])) == 1


@pytest.mark.parametrize("change,reason", [
    ({"answer": "It costs about 200 per year."}, "numbers"),
    ({"answer": "I do not know. Nobody knows. It varies. Ask someone."}, "sentences"),
    ({"question": "Does structural similarity compare luminance, contrast and structure between images?"}, "seem to answer"),
    ({"answer": "In the text there is nothing on this."}, "source"),
])
def test_a_bad_refusal_is_discarded_visibly(conn, tmp_path, change, reason):
    project, _, _, _ = seed(conn, tmp_path)
    result = kb.write_refusals(conn, Stub([{**REFUSAL, **change}]), project["id"])
    assert result["kept"] == 0 and reason in result["rejected"][0]["reason"]


def test_refusals_need_a_file_first(conn):
    project = projects.create(conn, display_name="Empty", language="en", slug="empty", max_themes=8)
    with pytest.raises(ValueError, match="read a file first"):
        kb.write_refusals(conn, Stub([REFUSAL]), project["id"])


def test_graph_holds_real_links_and_no_rejected_pair(conn, tmp_path):
    project, source, theme, made = seed(conn, tmp_path)
    kb.connect(conn, Stub([CONNECTED]), theme["id"])
    graph = kb.graph(conn, project["id"])
    types = {n["id"]: n["type"] for n in graph["nodes"]}
    assert types[f"project:{project['id']}"] == "project" and types[f"file:{source['id']}"] == "file"
    assert types[theme["id"]] == "theme" and types[made[0]] == "pair"
    assert {l["kind"] for l in graph["links"]} >= {"theme", "member", "file", "combines"}
    assert all(l["source"] in types and l["target"] in types for l in graph["links"])

    qa.decide(conn, made[0], "reject")
    graph = kb.graph(conn, project["id"])
    assert made[0] not in {n["id"] for n in graph["nodes"]}
    assert all(made[0] not in (l["source"], l["target"]) for l in graph["links"])


def test_export_writes_memory_with_kinds_and_declares_rights(conn, tmp_path):
    project, source, theme, _ = seed(conn, tmp_path)
    kb.connect(conn, Stub([CONNECTED]), theme["id"])
    kb.write_refusals(conn, Stub([REFUSAL]), project["id"])
    qa.decide_many(conn, project["id"], [s["id"] for s in qa.list_samples(conn, project["id"])], "approve")

    ds = datasets.export_dataset(conn, tmp_path / "out", "x", project["id"])
    assert not ds["excluded"], ds["excluded"]
    assert ds["sample_count"] == 4 and ds["memory_count"] == 4
    assert any("no rights declared" in w for w in ds["warnings"])
    folder = Path(ds["folder"])
    records = [json.loads(line) for line in (folder / "memory.jsonl").read_text().splitlines()]
    assert {r["kind"] for r in records} == {"file", "connection", "unanswered"}
    connected = next(r for r in records if r["kind"] == "connection")
    assert {e["quote"] for e in connected["evidence"]} == {"above 40 dB", "luminance, contrast and structure"}
    assert json.loads((folder / "sources.json").read_text())[0]["license_basis"] == "unspecified"

    kb.set_license(conn, source["id"], "own")
    ds = datasets.export_dataset(conn, tmp_path / "out", "y", project["id"])
    assert not any("no rights declared" in w for w in ds["warnings"])
    with pytest.raises(ValueError, match="license must be"):
        kb.set_license(conn, source["id"], "whatever")


def test_groups_to_spare_fill_validation_and_test():
    items = [{"id": f"s{i}", "scenario_key": f"sc{i}", "source_group": f"passage:{i // 3}"} for i in range(9)]
    splits = datasets.assign_splits(items)
    assert set(splits.values()) == {"train", "validation", "test"}
    for group in range(3):
        assert len({splits[f"s{i}"] for i in range(9) if i // 3 == group}) == 1


def test_a_task_card_gets_its_own_prompt_and_length(conn):
    project = projects.create(conn, display_name="Help", language="en", slug="help", max_themes=8)
    card = workshop.create_pattern(conn, project_id=project["id"], title="Summaries", intent="Summarize what is asked.",
                                   tone="plain", guidelines="Keep it short.", description="A request to summarize.", style="task")
    prompt = workshop.build_prompt(card, "positive", 2, "English")
    assert "does a job for people" in prompt and "want company" not in prompt
    assert workshop.max_sentences(card) == 4
    with pytest.raises(ValueError, match="style"):
        workshop.create_pattern(conn, project_id=project["id"], title="x", intent="i", tone="t", guidelines="g",
                                description="d", style="nope")


def test_routes_are_scoped_to_the_project(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DATA_DIR", tmp_path)
    monkeypatch.setattr(api, "DB_PATH", tmp_path / "academy.sqlite3")
    monkeypatch.setattr(api, "_conn", None)
    monkeypatch.setattr(api, "OllamaClient", lambda **kw: Stub([REFUSAL]))
    client = TestClient(api.app)
    a = client.post("/projects", json={"display_name": "Alpha"}).json()
    b = client.post("/projects", json={"display_name": "Beta"}).json()
    theme = client.post(f"/projects/{a['id']}/themes", json={"title": "T"}).json()

    assert client.get(f"/projects/{a['id']}/kb/graph").json()["nodes"][0]["type"] == "project"
    assert client.post(f"/projects/{b['id']}/themes/{theme['id']}/connect", json={"model": "m"}).status_code == 404
    assert client.post(f"/projects/{a['id']}/themes/{theme['id']}/connect", json={"model": "m"}).status_code == 422
    assert client.post(f"/projects/{a['id']}/refusals", json={"model": "m"}).status_code == 422


def test_routes_running_at_once_do_not_answer_not_found(tmp_path, monkeypatch):
    """Polling while something else writes used to share one connection and could 404 on a project that exists."""
    from concurrent.futures import ThreadPoolExecutor

    from fastapi.testclient import TestClient

    from amelia_academy import api

    monkeypatch.setattr(api, "DB_PATH", tmp_path / "academy.sqlite3")
    monkeypatch.setattr(api, "DATA_DIR", tmp_path)
    monkeypatch.setattr(api, "_conn", None)
    client = TestClient(api.app)
    project = client.post("/projects", json={"display_name": "Alpha"}).json()["id"]
    theme = client.post(f"/projects/{project}/themes", json={"title": "One"}).json()["id"]

    def read(_):
        return client.get(f"/projects/{project}/sources").status_code

    def write(n):
        return client.patch(f"/projects/{project}/themes/{theme}", json={"description": f"round {n}"}).status_code

    with ThreadPoolExecutor(12) as pool:
        jobs = [pool.submit(read if n % 3 else write, n) for n in range(600)]
        codes = {job.result() for job in jobs}
    assert codes == {200}


def test_a_refusal_speaks_for_itself_not_about_the_dataset():
    for answer in ("The dataset does not cover pricing.", "The documents do not mention it.", "Os arquivos não falam disso."):
        assert any("source" in r for r in kb.check_refusal("What did it cost in the first release?", answer, []))
    assert any("source" in r for r in kb.check_refusal("Which techniques are not covered in the dataset?", "I don't know that.", []))
    assert kb.check_refusal("What did it cost in the first release?", "I don't know what it cost.", []) == []
    assert kb.check_refusal("What is the size limit of PNG files?", "I don't know the file size limit.", []) == []


def test_upload_reads_the_file_off_the_event_loop(tmp_path, monkeypatch):
    """A PDF with figures takes minutes; on the event loop it answers no other request meanwhile."""
    import asyncio
    monkeypatch.setattr(api, "DATA_DIR", tmp_path)
    monkeypatch.setattr(api, "DB_PATH", tmp_path / "academy.sqlite3")
    monkeypatch.setattr(api, "_conn", None)
    on_loop = []

    def fake_ingest(conn, out_dir, **kw):
        try:
            asyncio.get_running_loop()
            on_loop.append(True)
        except RuntimeError:
            on_loop.append(False)
        return {"id": "src_fake"}

    monkeypatch.setattr(api.sources, "ingest_bytes", fake_ingest)
    client = TestClient(api.app)
    project = client.post("/projects", json={"display_name": "Alpha"}).json()
    r = client.post(f"/projects/{project['id']}/sources/upload", files={"file": ("a.txt", b"hello")})
    assert r.status_code == 200 and on_loop == [False]


def test_refusal_prompt_asks_for_details_a_model_would_invent():
    prompt = kb.refusal_prompt({"display_name": "P"}, "English", [{"title": "T"}], ["Q?"], 3)
    assert "one concrete scientific detail of this work" in prompt
    assert "work out by reasoning" in prompt
    assert "neighbouring subject" not in prompt


NEIGHBOUR = {"question": "How do audio codecs reduce the size of a recording?",
             "answer": "That is not what I studied, which is image metrics. In general, audio codecs drop what listeners barely hear."}


def test_neighbours_land_with_the_limits_and_export_only_for_training(conn, tmp_path):
    project, _, _, _ = seed(conn, tmp_path)
    stub = Stub([NEIGHBOUR])
    assert kb.write_neighbours(conn, stub, project["id"])["kept"] == 1
    assert "neighbouring subject" in stub.prompts[0]
    pair = next(s for s in qa.list_samples(conn, project["id"]) if s["origin"] == "neighbour")
    assert pair["theme_id"] == kb.limits_theme(conn, project["id"])["id"] and pair["status"] == "proposed"
    assert not pair["quote"]

    qa.decide_many(conn, project["id"], [s["id"] for s in qa.list_samples(conn, project["id"])], "approve")
    ds = datasets.export_dataset(conn, tmp_path / "out", "x", project["id"])
    assert not ds["excluded"], ds["excluded"]
    assert ds["sample_count"] == 3 and ds["memory_count"] == 2
    folder = Path(ds["folder"])
    assert "audio codecs" not in (folder / "memory.jsonl").read_text()
    assert not any("audio codecs" in p.read_text() for p in folder.rglob("*.md"))


@pytest.mark.parametrize("change,reason", [
    ({"answer": "I don't know. It is another subject."}, "does not know"),
    ({"answer": "That is not what I studied."}, "general answer"),
    ({"answer": "That is not what I studied. Codecs reach 128 kbps."}, "numbers"),
    ({"answer": "That is not in the files. Codecs drop what listeners barely hear."}, "source"),
    ({"answer": "Not what I studied. Codecs compress. They drop sounds. People barely hear them."}, "sentences"),
    ({"answer": "I did not study codecs; I studied " + "themes and more themes, " * 10 + "and memory. Codecs drop what listeners barely hear."}, "recites"),
])
def test_a_bad_neighbour_is_discarded_visibly(conn, tmp_path, change, reason):
    project, _, _, _ = seed(conn, tmp_path)
    result = kb.write_neighbours(conn, Stub([{**NEIGHBOUR, **change}]), project["id"])
    assert result["kept"] == 0 and reason in result["rejected"][0]["reason"]


def test_a_person_can_turn_an_unanswered_pair_into_a_neighbour(conn, tmp_path):
    project, _, _, _ = seed(conn, tmp_path)
    kb.write_refusals(conn, Stub([REFUSAL]), project["id"])
    pair = next(s for s in qa.list_samples(conn, project["id"]) if s["origin"] == "refusal")
    with pytest.raises(ValueError, match="mark the limit"):
        kinds.change_kind(conn, pair["id"], "neighbour")
    changed = kinds.change_kind(conn, pair["id"], "neighbour", answer=NEIGHBOUR["answer"])
    assert changed["origin"] == "neighbour" and changed["status"] == "proposed"


def test_neighbours_are_checked_again_when_a_file_arrives(conn, tmp_path):
    project, _, _, _ = seed(conn, tmp_path)
    kb.write_neighbours(conn, Stub([NEIGHBOUR]), project["id"])
    assert [r["question"] for r in kinds.open_unanswered(conn, project["id"])] == [NEIGHBOUR["question"]]


def test_a_question_may_ask_about_a_benchmark_dataset_but_an_answer_may_not_name_one():
    question = "What F1 score did it reach on the HotpotQA dataset?"
    assert not kb.check_refusal(question, "I don't know that score.", [])
    assert kb.check_refusal(question, "It is not in this dataset.", [])


def test_a_written_refusal_cannot_lean_on_a_filler_word_but_a_persons_can():
    question = "What specific encoder settings did the trials use?"
    named = "I don't know which encoder settings the trials used."
    assert "the question is vague" in kb.check_written_refusal(question, named, [])
    assert kb.check_refusal(question, "I don't know that.", []) == []
    assert "asks about publication details or technical settings" in kb.check_written_refusal("Which encoder settings did the trials use?", named, [])
    assert kb.check_written_refusal("What precision did the trials reach?", "I don't know what precision the trials reached.", []) == []


def test_a_written_refusal_names_what_it_does_not_know():
    question = "Which encoder settings did the trials use?"
    assert "says only that it does not know, without naming what" in kb.check_written_refusal(question, "I don't know.", [])
    assert "says only that it does not know, without naming what" in kb.check_written_refusal(question, "I don't know that.", [])
    assert kb.bare_refusal(question, "I don't know.") and not kb.bare_refusal(question, "I don't know the encoder settings.")
    assert kb.check_refusal(question, "I don't know.", []) == []  # a person may answer briefly


def test_graph_relation_review_does_not_follow_approval_or_repetition(conn, tmp_path):
    from amelia_academy import curation
    project, source, theme, made = seed(conn, tmp_path)
    kb.connect(conn, Stub([CONNECTED]), theme['id'])
    child = next(s for s in qa.list_samples(conn, project['id']) if s['origin'] == 'connection')
    def support():
        return [l for l in kb.graph(conn, project['id'])['links'] if l['kind'] == 'combines']
    assert all(l['review_state'] == 'proposed' for l in support())
    child = qa.decide(conn, child['id'], 'approve')
    assert all(l['review_state'] == 'proposed' for l in support())
    stamp = child['curation']['input_hash']
    curation.check(conn, child, stamp, {'combination': True, 'evidence': True})
    assert all(l['review_state'] == 'confirmed' for l in support())
    nodes = {n['id']: n for n in kb.graph(conn, project['id'])['nodes']}
    assert nodes[child['id']]['confidence'] == 'high'
    assert all('review_state' not in l for l in kb.graph(conn, project['id'])['links'] if l['kind'] in ('theme', 'member', 'file', 'passage'))
    curation.check(conn, child, stamp, {})
    assert all(l['review_state'] == 'proposed' for l in support())
    curation.check(conn, child, stamp, {'combination': True, 'evidence': True})
    qa.edit(conn, made[0], answer='Most viewers cannot see a difference above 40 dB.')
    assert all(l['review_state'] == 'proposed' for l in support())


def bare_refusals(conn, project_id, questions):
    """Refusals as an older model wrote them: the same bare words for every question."""
    plain = {q.replace(" exactly", ""): q for q in questions}  # older questions also leaned on filler words
    kb.write_refusals(conn, Stub([{"question": q, "answer": f"I don't know {q.lower().rstrip('?')}."} for q in plain]), project_id)
    made = by_refusal(conn, project_id)
    for s in made:
        conn.execute("UPDATE qa_samples SET question = ?, answer = 'I don''t know.' WHERE id = ?", (plain[s["question"]], s["id"]))
        qa.decide(conn, s["id"], "approve")
    conn.commit()
    return by_refusal(conn, project_id)


def by_refusal(conn, project_id):
    return [s for s in qa.list_samples(conn, project_id) if s["origin"] == "refusal"]


def test_repeated_answers_are_found_above_the_limit_only():
    def pairs(n, answer="I don't know.", origin="refusal"):
        return [{"id": f"s{i}", "question": f"How many encoder layers in trial {i}?", "answer": answer, "origin": origin} for i in range(n)]
    assert kb.repeated_answers(pairs(kb.REPEAT_MIN - 1)) == []
    found = kb.repeated_answers(pairs(kb.REPEAT_MIN) + pairs(3, "I don't know!"))
    assert len(found) == 1 and found[0]["count"] == kb.REPEAT_MIN + 3, "punctuation does not make a new answer"
    assert len(found[0]["rewordable"]) == kb.REPEAT_MIN + 3 and "every question" in found[0]["message"]
    many = [{**p, "id": f"k{i}"} for i, p in enumerate(pairs(200, origin="file"))]
    assert kb.repeated_answers(pairs(kb.REPEAT_MIN, "Yes.") + [{**m, "answer": f"answer {i}"} for i, m in enumerate(many)]) == [], \
        "a few repeats among many different answers are not a pattern"
    assert kb.repeated_answers(pairs(kb.REPEAT_MIN, origin="file"))[0]["rewordable"] == [], "only written refusals are reworded"


def test_reword_sends_pairs_back_to_review_and_undo_restores_them(conn, tmp_path):
    project, _, _, _ = seed(conn, tmp_path)
    questions = ["How much exactly does the measuring software license cost?", "Who sells the calibration kit?",
                 "When does the warranty on the sensors end?"]
    old = bare_refusals(conn, project["id"], questions)
    ids = {s["question"]: s["id"] for s in old}
    reply = Stub([{"id": ids[questions[0]], "answer": "I don't know how much exactly the measuring software license costs."},
                  {"id": ids[questions[1]], "answer": "The kit is sold online."},  # not a refusal: skipped
                  {"id": ids[questions[2]], "answer": "I don't know when the warranty on the sensors ends."}])
    done = kb.reword_refusals(conn, reply, project["id"], list(ids.values()), "rwd_1")
    assert done == {"batch_id": "rwd_1", "reworded": 2, "left": 1}
    now = {s["question"]: s for s in by_refusal(conn, project["id"])}
    assert now[questions[0]]["status"] == "proposed" and "license" in now[questions[0]]["answer"]
    assert now[questions[1]]["status"] == "approved" and now[questions[1]]["answer"] == "I don't know."
    assert kb.repeated_answers(qa.list_samples(conn, project["id"], status="approved")) == []

    qa.edit(conn, now[questions[2]]["id"], question=questions[2], answer="I don't know the warranty term.")
    assert kb.undo_reword(conn, project["id"], "rwd_1") == {"restored": 1}, "a pair changed since is left as it is"
    after = {s["question"]: s for s in by_refusal(conn, project["id"])}
    assert after[questions[0]]["answer"] == "I don't know." and after[questions[0]]["status"] == "approved"
    assert after[questions[2]]["answer"] == "I don't know the warranty term."
    assert kb.undo_reword(conn, project["id"], "rwd_1") == {"restored": 0}
