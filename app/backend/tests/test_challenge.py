"""Every pillar against the others. The model is a stub: these cover what gets compared, what opens a conflict, and how each ends."""

import json

import pytest
from fastapi.testclient import TestClient

from amelia_academy import api, challenge, datasets, db, kb, projects, qa, sources
from amelia_academy.llm import LLMError

TEXT = """Peak signal-to-noise ratio measures how close a compressed image stays to the original picture.

A value above 40 dB usually means the difference is invisible to most viewers looking at the two pictures.

Structural similarity compares luminance, contrast and structure between two images instead of raw pixels alone.

Later trials found that a value above 40 dB is clearly visible to trained viewers looking at the two pictures.
"""
INVISIBLE = "A value above 40 dB usually means the difference is invisible"
VISIBLE = "a value above 40 dB is clearly visible to trained viewers"
SSIM = "Structural similarity compares luminance, contrast and structure"
SSIM_FULL = "Structural similarity compares luminance, contrast and structure between two images instead of raw pixels alone."


class Judge:
    """Says what it was told to about each kind of comparison, and counts."""

    model = "stub-model"

    def __init__(self, pair="complement", claim="contradicts", answered=None, fail_at=None, draft=None):
        self.pair, self.claim, self.answered, self.fail_at = pair, claim, answered, fail_at
        self.draft = draft or {"question": "Is a PSNR above 40 dB visible to viewers?", "answer": "A PSNR above 40 dB stays invisible to most viewers.",
                               "complex": "Some findings call a PSNR above 40 dB invisible to most viewers, others clearly visible to trained viewers, and the two stand in tension."}
        self.calls = 0

    def complete_json(self, prompt, schema, temperature=0.9):
        self.calls += 1
        if self.fail_at and self.calls >= self.fail_at:
            raise LLMError("model went away")
        props = schema["properties"]
        if "complex" in props:
            return self.draft
        if "answered" in props:
            return {"answered": bool(self.answered), "quote": self.answered or ""}
        if "same" in props["verdict"]["enum"]:
            return {"verdict": self.pair, "why": "Because of what they state."}
        verdict = self.claim(prompt) if callable(self.claim) else self.claim
        return {"verdict": verdict, "why": "Because of what it states."}


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "t.sqlite3")


@pytest.fixture
def project(conn, tmp_path):
    made = projects.create(conn, display_name="Metrics", language="en", slug="metrics", max_themes=8)
    made["source"] = sources.ingest(conn, tmp_path / "sources", project_id=made["id"], name="a.txt", content=TEXT, purpose="qa-dataset", license_basis="own")
    return made


def add(conn, project, origin="file", question="Is a PSNR above 40 dB visible?", answer="It is invisible to most viewers.", quote=INVISIBLE, false_claim=""):
    theme = _theme(conn, project)
    chunk = sources.get_source(conn, project["source"]["id"])["chunks"][0]
    sid = db.new_id("qa")
    conn.execute("INSERT INTO qa_samples (id, project_id, theme_id, origin, source_id, chunk_id, quote, model, question, answer, false_claim, content_hash, status, created_at)"
                 " VALUES (?,?,?,?,?,?,?, 'stub', ?,?,?,?, 'proposed', ?)",
                 (sid, project["id"], theme, origin, project["source"]["id"], chunk["id"], quote, question, answer, false_claim, f"h-{sid}", db.now()))
    conn.commit()
    return sid


def _theme(conn, project):
    found = db.row(conn, "SELECT id FROM qa_themes WHERE project_id = ?", (project["id"],))
    if found:
        return found["id"]
    tid = db.new_id("thm")
    conn.execute("INSERT INTO qa_themes (id, project_id, slug, title, description, kind, created_at) VALUES (?,?, 'metrics', 'Metrics', '', 'topic', ?)", (tid, project["id"], db.now()))
    return tid


def contradicting(conn, project):
    first = add(conn, project)
    second = add(conn, project, question="Is a PSNR above 40 dB visible to viewers?", answer="It is clearly visible to trained viewers.", quote=VISIBLE)
    return first, second


def run(conn, project, llm):
    return challenge.run(conn, llm, challenge.start(conn, project["id"], llm.model))


def status(conn, sample_id):
    return qa.get_sample(conn, sample_id)["status"]


def only(conn, project):
    found = challenge.list_conflicts(conn, project["id"])
    assert len(found) == 1
    return found[0]


# --- what gets compared ---

def test_nearest_pairs_finds_what_shares_rare_words_and_skips_the_rest():
    pool = [{"id": "a", "question": "What sets the zygomatic threshold?", "answer": "Calibration sets it.", "quote": "qa", "theme_id": "t"},
            {"id": "b", "question": "Who controls the zygomatic threshold?", "answer": "The operator does.", "quote": "qb", "theme_id": "t"},
            {"id": "c", "question": "How long do penguins sleep?", "answer": "Eleven hours a night.", "quote": "qc", "theme_id": "t"}]
    found = {(a["id"], b["id"]) for a, b in challenge.nearest_pairs(pool)}
    assert found == {("a", "b")}


def test_two_pairs_from_one_quote_are_not_compared():
    pool = [{"id": "a", "question": "What sets the threshold?", "answer": "Calibration.", "quote": "same", "theme_id": "t"},
            {"id": "b", "question": "Who sets the threshold?", "answer": "Calibration.", "quote": "same", "theme_id": "t"}]
    assert challenge.nearest_pairs(pool) == []


def test_nearest_pairs_only_compares_within_theme_and_skips_identical_content():
    pool = [
        {"id": "a", "question": "What sets the zygomatic threshold?", "answer": "Calibration sets it.", "quote": "qa", "theme_id": "t1", "content_hash": "h1"},
        {"id": "b", "question": "Who controls the zygomatic threshold?", "answer": "The operator does.", "quote": "qb", "theme_id": "t2", "content_hash": "h2"},
        {"id": "c", "question": "Who controls the zygomatic threshold?", "answer": "The operator does.", "quote": "qc", "theme_id": "t1", "content_hash": "h1"},
        {"id": "d", "question": "Who controls the zygomatic threshold?", "answer": "The operator does.", "quote": "qd", "theme_id": "t1", "content_hash": "h4"},
    ]
    assert {(a["id"], b["id"]) for a, b in challenge.nearest_pairs(pool)} == {("a", "d"), ("c", "d")}


def test_known_comparison_batch_returns_one_judgment_per_pair():
    class BatchJudge:
        def __init__(self): self.calls = 0
        def complete_json_batch(self, prompt, schema, temperature):
            self.calls += 1
            assert "1. A:" in prompt and "2. A:" in prompt
            return {"results": [{"verdict": "same", "why": "same fact"}, {"verdict": "complement", "why": "different detail"}]}
    judge = BatchJudge()
    pairs = [({"id":"a", "question":"Q1", "answer":"A1", "quote":"X"}, {"id":"b", "question":"Q2", "answer":"A2", "quote":"Y"}),
             ({"id":"c", "question":"Q3", "answer":"A3", "quote":"Z"}, {"id":"d", "question":"Q4", "answer":"A4", "quote":"W"})]
    result = challenge._judge_known_batch(judge, pairs)
    assert judge.calls == 1


def test_a_batch_with_a_missing_judgment_is_judged_one_pair_at_a_time():
    class ShortJudge:
        def __init__(self): self.singles = 0
        def complete_json_batch(self, prompt, schema, temperature):
            return {"results": [{"verdict": "same", "why": "only one"}]}
        def complete_json(self, prompt, schema, temperature):
            self.singles += 1
            return {"verdict": "unrelated", "why": "different"}
    judge = ShortJudge()
    pairs = [({"id": f"a{i}", "question": "Q", "answer": "A", "quote": "X"},
              {"id": f"b{i}", "question": "Q", "answer": "A", "quote": "Y"}) for i in range(3)]
    result = challenge._judge_known_batch(judge, pairs)
    assert judge.singles == 3 and [r["verdict"] for r in result] == ["unrelated"] * 3


def test_201_known_comparisons_use_seven_model_calls_with_32_pair_batches():
    class BatchJudge:
        def __init__(self): self.calls = 0
        def complete_json_batch(self, prompt, schema, temperature):
            self.calls += 1
            import re
            count = len(re.findall(r"(?m)^\d+\. A:", prompt))
            return {"results": [{"verdict": "unrelated", "why": "different"} for _ in range(count)]}
    judge = BatchJudge()
    pairs = [({"id": f"a{i}", "question": "Q", "answer": "A", "quote": "X"},
              {"id": f"b{i}", "question": "Q", "answer": "A", "quote": "Y"}) for i in range(201)]
    for start in range(0, len(pairs), challenge.BATCH_SIZE):
        challenge._judge_known_batch(judge, pairs[start:start + challenge.BATCH_SIZE])
    assert challenge.BATCH_SIZE == 32
    assert judge.calls == 7


def test_nonknown_batches_use_array_schema_and_fall_back_for_every_item():
    class BatchJudge:
        model = "stub"
        def __init__(self): self.batches = 0; self.singles = 0
        def complete_json_batch(self, prompt, schema, temperature):
            self.batches += 1
            assert "1. CLAIM:" in prompt and schema["properties"]["results"]["type"] == "array"
            return {"results": [{"verdict": "contradicts", "why": "one"}]}
        def complete_json(self, prompt, schema, temperature=0):
            self.singles += 1
            return {"verdict": "contradicts", "why": "single"}
    judge = BatchJudge()
    items = [("claim_own", {"false_claim": "Claim", "quote": "Evidence"}, None) for _ in range(3)]
    results = challenge._judge_test_batch(judge, "claim_own", items, [])
    assert judge.batches == 1 and judge.singles == 3
    assert [r["why"] for r in results] == ["single"] * 3


def test_nonknown_tests_are_batched_for_n_items(conn, project):
    for i in range(5):
        add(conn, project, origin="false_premise", question=f"What is disputed {i}?", answer="No.", quote=INVISIBLE,
            false_claim=f"The PSNR rises in case {i}.")
    class BatchJudge:
        model = "stub"
        def __init__(self): self.batch_calls = 0; self.single_calls = 0
        def complete_json_batch(self, prompt, schema, temperature):
            self.batch_calls += 1
            import re
            count = len(re.findall(r"(?m)^\d+\. CLAIM:", prompt))
            return {"results": [{"verdict": "contradicts", "why": "own quote"} for _ in range(count)]}
        def complete_json(self, prompt, schema, temperature=0):
            self.single_calls += 1
            return {"verdict": "contradicts", "why": "own quote"}
    judge = BatchJudge()
    assert run(conn, project, judge)["status"] == "succeeded"
    assert judge.batch_calls == 1 and judge.single_calls == 0


def test_n_doubts_use_one_numbered_batch_with_results_array():
    class BatchJudge:
        model = "stub"
        def __init__(self): self.calls = 0
        def complete_json_batch(self, prompt, schema, temperature):
            self.calls += 1
            assert "1. QUESTION:" in prompt and "2. QUESTION:" in prompt
            assert schema["properties"]["results"]["type"] == "array"
            return {"results": [{"answered": False, "quote": ""} for _ in range(5)]}
    judge = BatchJudge()
    doubts = [("doubt", {"question": f"Question {i}"}, None) for i in range(5)]
    results = challenge._judge_test_batch(judge, "doubt", doubts, [{"text": "supporting passage"}])
    assert len(results) == 5 and judge.calls == 1


def test_conflict_opening_verdict_from_batch_is_confirmed_alone(conn, project):
    first = add(conn, project, origin="false_premise", question="What is disputed?", answer="No.", quote=INVISIBLE,
                false_claim="The PSNR rises.")
    second = add(conn, project, origin="false_premise", question="What else is disputed?", answer="No.", quote=SSIM,
                 false_claim="The SSIM rises.")
    class BatchJudge:
        model = "stub"
        def __init__(self): self.batch_calls = 0; self.single_calls = 0
        def complete_json_batch(self, prompt, schema, temperature):
            self.batch_calls += 1
            return {"results": [{"verdict": "unrelated", "why": "batch"}, {"verdict": "unrelated", "why": "batch"}]}
        def complete_json(self, prompt, schema, temperature=0):
            self.single_calls += 1
            if "complex" in schema.get("properties", {}):
                return {"question": "Q", "answer": "A", "complex": "C"}
            return {"verdict": "unrelated", "why": "single"}
    judge = BatchJudge()
    def opening_batch(prompt, schema, temperature):
        judge.batch_calls += 1
        return {"results": [{"verdict": "unrelated", "why": "batch"}, {"verdict": "contradicts", "why": "batch"}]}
    judge.complete_json_batch = opening_batch
    result = run(conn, project, judge)
    assert result["status"] == "succeeded"
    assert judge.batch_calls == 1 and judge.single_calls == 1
    assert db.row(conn, "SELECT verdict, why FROM qa_comparisons WHERE first_id = ? AND test = 'claim_own'", (first,)) == {
        "verdict": "unrelated", "why": "single"}


# --- what opens a conflict ---

def test_a_disagreement_opens_a_conflict_with_both_pairs_and_changes_nothing(conn, project):
    first, second = contradicting(conn, project)
    done = run(conn, project, Judge(pair="disagree"))
    assert done["status"] == "succeeded" and done["conflicts"] == 1
    found = only(conn, project)
    assert found["kind"] == "known_disagree" and {found["first_id"], found["second_id"]} == {first, second}
    assert found["draft_complex"]
    assert status(conn, first) == status(conn, second) == "proposed"


def test_pairs_that_agree_open_nothing(conn, project):
    contradicting(conn, project)
    assert run(conn, project, Judge(pair="complement"))["conflicts"] == 0
    assert challenge.list_conflicts(conn, project["id"]) == []


def test_a_false_claim_another_quote_supports_opens_a_conflict(conn, project):
    add(conn, project, question="What does structural similarity compare?", answer="It compares luminance, contrast and structure.", quote=SSIM)
    add(conn, project, origin="false_premise", question="Does a PSNR above 40 dB show?", answer="No, it stays invisible.", quote=INVISIBLE,
        false_claim="Structural similarity compares luminance and structure between images.")
    # Its own quote rules the claim out, so only the other quote is in tension with it.
    judge = Judge(claim=lambda prompt: "supports" if SSIM in prompt else "contradicts")
    assert run(conn, project, judge)["conflicts"] == 1
    assert only(conn, project)["kind"] == "false_confirmed"


def test_a_false_premise_its_own_quote_does_not_rule_out_can_only_go_or_stay(conn, project):
    claim = add(conn, project, origin="false_premise", question="Does it show?", answer="No.", quote=INVISIBLE, false_claim="A PSNR above 40 dB always shows.")
    assert run(conn, project, Judge(claim="unrelated"))["conflicts"] == 1
    found = only(conn, project)
    assert found["kind"] == "false_unsettled" and found["second"] is None
    with pytest.raises(ValueError):
        challenge.resolve(conn, project["id"], found["id"], "complex")
    challenge.resolve(conn, project["id"], found["id"], "keep_second")
    assert qa.get_sample(conn, claim)["status"] == "rejected"
    challenge.reopen(conn, project["id"], found["id"])
    assert qa.get_sample(conn, claim)["status"] == "proposed"


def test_a_doubt_with_a_real_quote_opens_a_conflict_pointing_at_the_passage(conn, project):
    add(conn, project, origin="refusal", question="What does structural similarity compare?", answer="The material does not say.", quote="")
    assert run(conn, project, Judge(answered=SSIM))["conflicts"] == 1
    found = only(conn, project)
    assert found["kind"] == "doubt_answered" and found["quote"] == SSIM_FULL and found["quote_source"] == "a.txt"


def test_a_doubt_whose_quote_is_not_in_the_files_opens_nothing_and_says_so(conn, project):
    doubt = add(conn, project, origin="refusal", question="What does it compare?", answer="The material does not say.", quote="")
    assert run(conn, project, Judge(answered="words nowhere in this file at all"))["conflicts"] == 0
    assert db.row(conn, "SELECT verdict FROM qa_comparisons WHERE first_id = ?", (doubt,))["verdict"] == "unverified"


# --- the run ---

def test_a_second_run_only_pays_for_what_changed(conn, project):
    first, _ = contradicting(conn, project)
    llm = Judge()
    run(conn, project, llm)
    calls = llm.calls
    run(conn, project, llm)
    assert llm.calls == calls
    conn.execute("UPDATE qa_samples SET content_hash = 'edited' WHERE id = ?", (first,))
    conn.commit()
    run(conn, project, llm)
    assert llm.calls > calls


def test_a_model_failure_stops_the_run_and_is_shown(conn, project):
    contradicting(conn, project)
    done = run(conn, project, Judge(fail_at=1))
    assert done["status"] == "failed" and "model went away" in done["error"]


def test_rerunning_does_not_reopen_a_resolved_conflict(conn, project):
    contradicting(conn, project)
    llm = Judge(pair="disagree")
    run(conn, project, llm)
    challenge.resolve(conn, project["id"], only(conn, project)["id"], "no_conflict")
    conn.execute("UPDATE qa_samples SET content_hash = content_hash || 'x'")
    conn.commit()
    assert run(conn, project, llm)["conflicts"] == 0


def test_two_runs_cannot_overlap(conn, project):
    contradicting(conn, project)
    challenge.start(conn, project["id"], "m")
    with pytest.raises(challenge.workshop.Conflict):
        challenge.start(conn, project["id"], "m")
    assert challenge.stop_interrupted(conn) == 1


# --- how it ends ---

def test_keeping_one_rejects_the_other_and_undo_brings_it_back(conn, project):
    contradicting(conn, project)
    run(conn, project, Judge(pair="disagree"))
    found = only(conn, project)
    challenge.resolve(conn, project["id"], found["id"], "keep_first")
    assert status(conn, found["first_id"]) == "proposed" and status(conn, found["second_id"]) == "rejected"
    challenge.reopen(conn, project["id"], found["id"])
    assert status(conn, found["second_id"]) == "proposed"
    assert only(conn, project)["id"] == found["id"]


def test_the_tension_stays_as_a_complex_pair_holding_both_quotes(conn, project):
    contradicting(conn, project)
    run(conn, project, Judge(pair="disagree"))
    found = only(conn, project)
    done = challenge.resolve(conn, project["id"], found["id"], "complex")
    made = qa.get_sample(conn, done["result_id"])
    assert made["origin"] == "complex" and made["pillar"] == "known" and made["status"] == "proposed"
    assert {p["id"] for p in made["based_on"]} == {found["first_id"], found["second_id"]}
    assert status(conn, found["first_id"]) == status(conn, found["second_id"]) == "rejected"


def test_undo_removes_the_pair_it_made_unless_it_was_approved(conn, project):
    contradicting(conn, project)
    run(conn, project, Judge(pair="disagree"))
    found = only(conn, project)
    done = challenge.resolve(conn, project["id"], found["id"], "complex")
    qa.decide(conn, done["result_id"], "approve")
    with pytest.raises(ValueError):
        challenge.reopen(conn, project["id"], found["id"])
    qa.decide(conn, done["result_id"], "reject")
    challenge.reopen(conn, project["id"], found["id"])
    assert db.row(conn, "SELECT 1 AS x FROM qa_samples WHERE id = ?", (done["result_id"],)) is None
    assert status(conn, found["first_id"]) == "proposed"


def test_an_answered_doubt_becomes_a_known_pair_with_its_quote(conn, project):
    doubt = add(conn, project, origin="refusal", question="What does structural similarity compare?", answer="The material does not say.", quote="")
    run(conn, project, Judge(answered=SSIM, draft={"question": "What does structural similarity compare?", "answer": "It compares luminance, contrast and structure.", "complex": ""}))
    done = challenge.resolve(conn, project["id"], only(conn, project)["id"], "answer")
    made = qa.get_sample(conn, done["result_id"])
    assert made["origin"] == "file" and made["quote"] == SSIM_FULL and status(conn, doubt) == "rejected"


def test_a_person_can_write_the_answer_but_the_rules_still_hold(conn, project):
    contradicting(conn, project)
    run(conn, project, Judge(pair="disagree", draft={"question": "Q?", "answer": "", "complex": ""}))
    found = only(conn, project)
    with pytest.raises(ValueError, match="write the answer"):
        challenge.resolve(conn, project["id"], found["id"], "complex")
    with pytest.raises(ValueError, match="numbers"):
        challenge.resolve(conn, project["id"], found["id"], "complex", answer="Trials say 77 dB.")
    done = challenge.resolve(conn, project["id"], found["id"], "complex", question="Is 40 dB visible?", answer="Whether 40 dB shows remains in tension.")
    assert qa.get_sample(conn, done["result_id"])["answer"] == "Whether 40 dB shows remains in tension."


def test_a_draft_that_breaks_the_rules_is_left_for_a_person(conn, project):
    contradicting(conn, project)
    run(conn, project, Judge(pair="disagree", draft={"question": "Q?", "answer": "", "complex": "It measured 99 dB according to the text."}))
    assert only(conn, project)["draft_complex"] == ""


def test_a_conflict_whose_pair_was_rejected_in_curation_has_nothing_left_to_decide(conn, project):
    first, _ = contradicting(conn, project)
    run(conn, project, Judge(pair="disagree"))
    qa.decide(conn, first, "reject")
    assert challenge.list_conflicts(conn, project["id"]) == []


def test_a_wrong_resolution_is_refused(conn, project):
    contradicting(conn, project)
    run(conn, project, Judge(pair="disagree"))
    with pytest.raises(ValueError):
        challenge.resolve(conn, project["id"], only(conn, project)["id"], "answer")


# --- what was judged the same ---

def worded_apart(conn, project):
    """Close enough to be compared, too far apart in words to be grouped without the judge."""
    return (add(conn, project, question="Is a PSNR above 40 dB visible?", answer="It is invisible to most viewers.", quote=INVISIBLE),
            add(conn, project, question="What do trained viewers notice at a PSNR above 40 dB in compressed pictures?", answer="They notice faint damage clearly.", quote=VISIBLE))


def test_pairs_judged_the_same_are_offered_as_similar_until_one_is_edited(conn, project):
    first, second = worded_apart(conn, project)
    assert qa.similar_groups(conn, project["id"]) == []
    run(conn, project, Judge(pair="same"))
    assert {s["id"] for s in qa.similar_groups(conn, project["id"])[0]["samples"]} == {first, second}
    conn.execute("UPDATE qa_samples SET content_hash = 'edited' WHERE id = ?", (first,))
    conn.commit()
    assert qa.similar_groups(conn, project["id"]) == []


def test_pairs_kept_apart_stay_apart_even_if_judged_the_same(conn, project):
    first, second = worded_apart(conn, project)
    run(conn, project, Judge(pair="same"))
    qa.keep_apart(conn, project["id"], [first, second])
    assert qa.similar_groups(conn, project["id"]) == []


# --- export ---

def test_a_complex_pair_exports_with_both_passages_in_the_memory_file(conn, project, tmp_path):
    contradicting(conn, project)
    run(conn, project, Judge(pair="disagree"))
    done = challenge.resolve(conn, project["id"], only(conn, project)["id"], "complex")
    qa.decide(conn, done["result_id"], "approve")
    themes = [t["id"] for t in qa.list_themes(conn, project["id"])]
    found = datasets.export_dataset(conn, tmp_path / "out", "x", project["id"], themes, outputs=["memory", "finetune"])
    assert found["sample_count"] == 1 and not found["excluded"]
    record = json.loads((tmp_path / "out" / found["folder"].split("/")[-1] / "memory.jsonl").read_text().splitlines()[0])
    assert len(record["evidence"]) == 2


def test_an_open_conflict_is_an_edge_of_the_graph_until_it_is_resolved(conn, project):
    first, second = contradicting(conn, project)
    run(conn, project, Judge(pair="disagree"))
    edges = lambda: [l for l in kb.graph(conn, project["id"])["links"] if l["kind"] == "tension"]
    assert [{e["source"], e["target"]} for e in edges()] == [{first, second}]
    challenge.resolve(conn, project["id"], only(conn, project)["id"], "no_conflict")
    assert edges() == []


NO_DRAFT = {"question": "Is 40 dB visible?", "answer": "", "complex": ""}
HELD = "Whether a PSNR above 40 dB shows remains in tension: most viewers miss it, trained viewers see it."


def test_choosing_is_enough_the_model_writes_a_pair_to_review(conn, project):
    first, second = contradicting(conn, project)
    run(conn, project, Judge(pair="disagree", draft=NO_DRAFT))
    found = only(conn, project)
    done = challenge.resolve(conn, project["id"], found["id"], "complex", llm=Judge(draft={**NO_DRAFT, "complex": HELD}))
    made = qa.get_sample(conn, done["result_id"])
    assert made["answer"] == HELD and made["status"] == "proposed" and made["model"] == "stub-model"
    assert status(conn, first) == status(conn, second) == "rejected"
    challenge.reopen(conn, project["id"], found["id"])
    assert status(conn, first) == status(conn, second) == "proposed"
    silent = Judge(fail_at=1)
    again = challenge.resolve(conn, project["id"], found["id"], "complex", llm=silent)  # already written: no second call
    assert silent.calls == 0 and qa.get_sample(conn, again["result_id"])["answer"] == HELD


def test_when_the_model_fails_the_conflict_stays_open_and_says_why(conn, project):
    first, second = contradicting(conn, project)
    run(conn, project, Judge(pair="disagree", draft=NO_DRAFT))
    found = only(conn, project)
    with pytest.raises(ValueError, match="could not write this: model went away"):
        challenge.resolve(conn, project["id"], found["id"], "complex", llm=Judge(fail_at=1))
    with pytest.raises(ValueError, match="left out: states numbers the evidence does not hold: 77"):
        challenge.resolve(conn, project["id"], found["id"], "complex", llm=Judge(draft={**NO_DRAFT, "complex": "Trials say 77 dB."}))
    with pytest.raises(ValueError, match="left out: it wrote nothing"):
        challenge.resolve(conn, project["id"], found["id"], "complex", llm=Judge(draft=NO_DRAFT))
    assert only(conn, project)["status"] == "open" and status(conn, first) == status(conn, second) == "proposed"


def test_a_draft_may_repeat_a_number_from_either_answer_and_is_not_numbered(conn, project):
    add(conn, project, answer="It stays invisible at 42 dB.")
    add(conn, project, question="Is a PSNR above 40 dB visible to viewers?", answer="It shows at 45 dB.", quote=VISIBLE)
    judge = Judge(pair="disagree", draft={**NO_DRAFT, "complex": "One position calls 42 dB invisible, another sees it at 45 dB, and they stand in tension."})
    run(conn, project, judge)
    assert "42 dB" in only(conn, project)["draft_complex"]
    prompt = challenge.draft_prompt("known_disagree", "en", qa.get_sample(conn, only(conn, project)["first_id"]), qa.get_sample(conn, only(conn, project)["second_id"]), "", "")
    assert "Statement 1" not in prompt


def test_a_doubt_answered_writes_the_answer_on_yes(conn, project):
    add(conn, project, origin="refusal", question="Does a PSNR above 40 dB show?", answer="The files do not say.", quote="")
    run(conn, project, Judge(pair="disagree", answered=INVISIBLE, draft=NO_DRAFT))
    found = only(conn, project)
    assert found["kind"] == "doubt_answered"
    done = challenge.resolve(conn, project["id"], found["id"], "answer", llm=Judge(draft={**NO_DRAFT, "answer": "It stays invisible to most viewers."}))
    assert qa.get_sample(conn, done["result_id"])["origin"] == "file"


def test_what_a_person_writes_stays_theirs(conn, project):
    contradicting(conn, project)
    run(conn, project, Judge(pair="disagree", draft=NO_DRAFT))
    found = only(conn, project)
    done = challenge.resolve(conn, project["id"], found["id"], "complex", answer=HELD, llm=Judge(fail_at=1))
    assert qa.get_sample(conn, done["result_id"])["model"] == "person"


def test_undo_and_choosing_again_keeps_who_wrote_it(conn, project):
    contradicting(conn, project)
    run(conn, project, Judge(pair="disagree", draft=NO_DRAFT))
    found = only(conn, project)
    writer = Judge(draft={**NO_DRAFT, "complex": HELD})
    writer.model = "the-writer"
    challenge.resolve(conn, project["id"], found["id"], "complex", llm=writer)
    challenge.reopen(conn, project["id"], found["id"])
    again = challenge.resolve(conn, project["id"], found["id"], "complex", llm=Judge(fail_at=1))
    assert qa.get_sample(conn, again["result_id"])["model"] == "the-writer"


def test_a_draft_that_talks_about_the_debate_is_written_again(conn, project):
    contradicting(conn, project)
    run(conn, project, Judge(pair="disagree", draft=NO_DRAFT))
    found = only(conn, project)
    with pytest.raises(ValueError, match="material instead of the subject"):
        challenge.resolve(conn, project["id"], found["id"], "complex", llm=Judge(draft={**NO_DRAFT, "complex": "One claim says it is invisible; another claim says it shows."}))
    conn.execute("UPDATE qa_conflicts SET draft_complex = 'One claim says it is invisible.' WHERE id = ?", (found["id"],))
    done = challenge.resolve(conn, project["id"], found["id"], "complex", llm=Judge(draft={**NO_DRAFT, "complex": HELD}))
    assert qa.get_sample(conn, done["result_id"])["answer"] == HELD


