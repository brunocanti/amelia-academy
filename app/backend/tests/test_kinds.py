"""Spec 012, section 8: the three kinds of pair, from the reading to every export. The model is a stub."""

import json
from pathlib import Path

import pytest

from amelia_academy import datasets, db, kb, kinds, projects, qa, sources
from amelia_academy.llm import LLMError
from test_kb import Q_A, REFUSAL, Stub, TEXT_A, conn, seed  # noqa: F401

CLAIM = "Above 90 dB most viewers see no difference."
FALSE_Q = "Why do viewers stop seeing a difference only above 90 dB?"
FALSE_A = "They do not: the difference is invisible above 40 dB, not 90 dB."
TRUE_Q = "The difference becomes invisible above 40 dB, right?"
TRUE_A = "Yes, above 40 dB it is invisible to most viewers."


def premise(label="P1", **change):
    return {"fact": label, "false_claim": CLAIM, "question": FALSE_Q, "answer": FALSE_A,
            "true_question": TRUE_Q, "true_answer": TRUE_A, **change}


def parent_index(prompt, question=Q_A):
    return next(line.split("]")[0][1:] for line in prompt.splitlines() if line.endswith(f"Q: {question}"))


class Script:
    """Answers each model call by what it asks for, in the order the stage makes them."""
    model = "stub-model"
    answered, quote = False, ""

    def __init__(self, refusals=(), premises=(), fail_on=""):
        self.refusals, self.premises, self.fail_on, self.prompts = list(refusals), list(premises), fail_on, []

    def complete_json(self, prompt, schema, temperature=0.9):
        self.prompts.append(prompt)
        if "answered" in schema["properties"]:
            if self.fail_on == "check":
                raise LLMError("model went away")
            return {"answered": self.answered, "quote": self.quote if self.answered else ""}
        kind = "premise" if "false_claim" in json.dumps(schema) else "refusal"
        if kind == self.fail_on:
            raise LLMError("model went away")
        if kind == "refusal":
            return {"items": [self.refusals.pop(0)] if self.refusals else []}
        return {"items": [premise(parent_index(prompt), **self.premises.pop(0))] if self.premises else []}


def by_origin(conn, project_id, origin):
    return qa.list_samples(conn, project_id, origin=origin)


def write_one(conn, project):
    assert kinds.write_false_premises(conn, Stub([premise()]), project["id"], 1)["false"] == 1
    return by_origin(conn, project["id"], "false_premise")[0], by_origin(conn, project["id"], "true_premise")[0]




@pytest.fixture
def seeded(conn, tmp_path):
    project, source, theme, made = seed(conn, tmp_path)
    # Both parents hold the claim's numbers, so whichever the draw picks passes the checks.
    conn.execute("UPDATE qa_samples SET quote = 'above 40 dB' WHERE project_id = ?", (project["id"],))
    chunk = next(c for c in source["chunks"] if "above 40 dB" in c["text"])
    conn.execute("UPDATE qa_samples SET chunk_id = ? WHERE project_id = ?", (chunk["id"], project["id"]))
    conn.commit()
    return project, source, theme, made


def approve_everything(conn, project):
    qa.decide_many(conn, project["id"], [s["id"] for s in qa.list_samples(conn, project["id"])], "approve")


# --- Section 4: how a percentage becomes a quantity ---

@pytest.mark.parametrize("answered, un, fp, expected", [
    (100, 10, 10, (13, 13, 0)),
    (100, 0, 10, (0, 12, 0)),
    (100, 0, 0, (0, 0, 0)),
    (0, 10, 10, (0, 0, 0)),
    (1, 30, 30, (1, 1, 0)),
])
def test_quota(answered, un, fp, expected):
    assert kinds.quotas(answered, un, fp) == expected


def test_neighbours_take_their_own_share():
    assert kinds.quotas(80, 10, 5, 5) == (10, 5, 5)


def test_true_versions_count_inside_the_share():
    assert kinds.split_share(13) == (7, 6)


# --- Section 8 ---

def test_1_each_kind_goes_where_the_spec_says(conn, tmp_path, seeded):
    project, _, _, _ = seeded
    fp, tp = write_one(conn, project)
    assert fp["false_claim"] == CLAIM and fp["quote"] == "above 40 dB" and fp["based_on"]
    assert kb.write_refusals(conn, Stub([REFUSAL]), project["id"])["kept"] == 1
    approve_everything(conn, project)

    ds = datasets.export_dataset(conn, tmp_path / "out", "x", project["id"])
    assert not ds["excluded"], ds["excluded"]
    assert ds["sample_count"] == 5
    folder = Path(ds["folder"])

    chats = "".join((folder / f).read_text() for f in ("train.jsonl", "valid.jsonl", "test.jsonl") if (folder / f).exists())
    for text in (FALSE_Q, TRUE_Q, REFUSAL["question"]):
        assert text in chats

    canonical = [json.loads(l) for l in (folder / "samples.jsonl").read_text().splitlines()]
    assert {r["kind"] for r in canonical} == {"file", "false_premise", "true_premise", "unanswered"}
    assert next(r for r in canonical if r["kind"] == "false_premise")["false_claim"] == CLAIM

    statistics = json.loads((folder / "manifest.json").read_text())["statistics"]
    assert statistics["by_kind"]["false_premise"]["total"] == 1
    assert sum(v["total"] for v in statistics["by_kind"].values()) == 5

    memory = [json.loads(l) for l in (folder / "memory.jsonl").read_text().splitlines()]
    assert {r["kind"] for r in memory} == {"file", "false_premise", "unanswered"}
    assert TRUE_Q not in json.dumps(memory)
    wrong = next(r for r in memory if r["kind"] == "false_premise")
    assert wrong["false_claim"] == CLAIM and wrong["corrects"] == datasets.canonical_id(fp["based_on"][0]["id"])
    assert wrong["evidence"][0]["quote"] == "above 40 dB"
    gap = next(r for r in memory if r["kind"] == "unanswered")
    assert "answer" not in gap and gap["checked_against"][0]["source"] == "a.txt"

    wiki = "\n".join(p.read_text() for p in (folder / "wiki" / "themes").glob("*.md"))
    assert TRUE_Q not in wiki
    assert f"## {FALSE_Q}" not in wiki and CLAIM in wiki
    before, after = wiki.split("## Possible mistakes", 1)
    assert CLAIM not in before and f"### Wrong: {CLAIM}\nCorrect: {FALSE_A}" in after
    assert f"## {REFUSAL['question']}" not in wiki
    assert f"- {REFUSAL['question']}" in wiki.split("## Not answered here", 1)[1]
    assert REFUSAL["answer"] not in wiki


def test_2_false_true_and_parent_share_a_split(conn, tmp_path, seeded):
    project, _, _, _ = seeded
    fp, tp = write_one(conn, project)
    approve_everything(conn, project)
    ds = datasets.export_dataset(conn, tmp_path / "out", "x", project["id"])
    entries = json.loads((Path(ds["folder"]) / "manifest.json").read_text())["entries"]
    split = {e["sample_id"]: e["split"] for e in entries}
    wanted = {split[datasets.canonical_id(i)] for i in (fp["id"], tp["id"], fp["based_on"][0]["id"])}
    assert len(wanted) == 1


def test_3_without_an_approved_parent_it_stays_out_and_is_counted(conn, tmp_path, seeded):
    project, _, _, made = seeded
    fp, tp = write_one(conn, project)
    qa.decide(conn, fp["id"], "approve")
    qa.decide(conn, tp["id"], "approve")
    qa.decide(conn, fp["based_on"][0]["id"], "reject")
    ds = datasets.export_dataset(conn, tmp_path / "out", "x", project["id"])
    assert {e["sample_id"] for e in ds["excluded"]} == {fp["id"], tp["id"]}
    assert "not approved" in ds["excluded"][0]["reasons"][0]
    assert FALSE_Q not in (Path(ds["folder"]) / "samples.jsonl").read_text()


def test_4_editing_the_parent_returns_it_to_review(conn, seeded):
    project, _, _, _ = seeded
    fp, tp = write_one(conn, project)
    qa.decide(conn, fp["id"], "approve")
    qa.decide(conn, tp["id"], "approve")
    qa.edit(conn, fp["based_on"][0]["id"], answer="Above 40 dB nobody notices.")
    assert qa.get_sample(conn, fp["id"])["status"] == "proposed"
    assert qa.get_sample(conn, tp["id"])["status"] == "proposed"


def test_the_false_claim_can_be_edited_and_cannot_go_empty(conn, seeded):
    project, _, _, made = seeded
    fp, _ = write_one(conn, project)
    qa.decide(conn, fp["id"], "approve")
    edited = qa.edit(conn, fp["id"], false_claim="Above 95 dB nobody notices.")
    assert edited["false_claim"] == "Above 95 dB nobody notices." and edited["status"] == "proposed"
    with pytest.raises(ValueError, match="needs its false claim"):
        qa.edit(conn, fp["id"], false_claim="  ")
    with pytest.raises(ValueError, match="only a false premise"):
        qa.edit(conn, made[0], false_claim="x")


def read(conn, tmp_path, llm, **options):
    """A real reading of a short file through qa.run, with the stage at its end."""
    project = projects.create(conn, display_name="Metrics", language="en", slug="metrics", max_themes=8)
    text = f"{TEXT_A} " + "Lorem ipsum dolor sit amet. " * 20
    source = sources.ingest(conn, tmp_path / "s", project_id=project["id"], name="a.txt", content=text,
                            purpose="qa-dataset", license_basis="unspecified")
    eid = qa.start(conn, source["id"], llm.model, **options)
    return project, source, eid, qa.run(conn, llm, eid)


class Reader(Script):
    """The reading's own calls, then the stage's."""

    def complete_json(self, prompt, schema, temperature=0.9):
        properties = schema["properties"]
        if "answered" in properties:
            return super().complete_json(prompt, schema, temperature)
        if "themes" in properties:
            self.prompts.append(prompt)
            return {"themes": [{"title": "Image metrics", "description": "How images are measured"}]}
        if "quote" in json.dumps(schema):
            self.prompts.append(prompt)
            return {"items": [{"question": Q_A, "answer": "Above 40 dB most viewers see no difference.",
                               "quote": "above 40 dB", "theme": "image-metrics"}]}
        return super().complete_json(prompt, schema, temperature)


def test_5_zero_percent_makes_no_extra_call(conn, tmp_path):
    llm = Reader()
    _, _, _, run = read(conn, tmp_path, llm)
    assert run["status"] == "succeeded" and run["kept"] == 1
    assert len(llm.prompts) == 2  # themes, one section
    assert "kinds" not in run["reading"]


def test_6_a_failed_stage_keeps_the_answered_and_repeats_alone(conn, tmp_path):
    llm = Reader(refusals=[REFUSAL], fail_on="premise")
    project, source, eid, run = read(conn, tmp_path, llm, unanswered_pct=30, false_premise_pct=30)
    assert run["status"] == "succeeded" and run["kept"] == 1
    report = run["reading"]["kinds"]
    assert "model went away" in report["error"] and report["running"] is False
    assert report["unanswered"]["written"] == 1
    assert len(by_origin(conn, project["id"], "file")) == 1

    again = Script(premises=[{}])
    done = kinds.repeat(conn, again, source["id"], 30, 30)
    assert done["status"] == "succeeded" and done["kept"] == 1
    report = done["reading"]["kinds"]
    assert report["error"] == "" and report["false_premises"]["false"] == 1
    assert len(again.prompts) == 1, "nothing is read again and the unanswered already written are not asked twice"
    assert len(by_origin(conn, project["id"], "refusal")) == 1


def test_7_a_new_file_returns_the_question_it_answers(conn, tmp_path, seeded):
    project, _, _, _ = seeded
    question = "What does the lighthouse keeper measure during autumn storms?"
    assert kb.write_refusals(conn, Stub([{"question": question, "answer": "I don't know what the lighthouse keeper measures in those storms."}]), project["id"])["kept"] == 1
    refusal = by_origin(conn, project["id"], "refusal")[0]
    qa.decide(conn, refusal["id"], "approve")

    other = sources.ingest(conn, tmp_path / "s", project_id=project["id"], name="b.txt",
                           content="The lighthouse keeper will measure wind during autumn storms, every night. " * 4,
                           purpose="qa-dataset", license_basis="unspecified")
    silent = Script()
    assert kinds.recheck_unanswered(conn, silent, other["id"]) == []
    assert qa.get_sample(conn, refusal["id"])["status"] == "approved"

    says = Script()
    says.answered, says.quote = True, "measure wind during autumn storms"
    assert kinds.recheck_unanswered(conn, says, other["id"])[0]["id"] == refusal["id"]
    back = qa.get_sample(conn, refusal["id"])
    assert back["status"] == "proposed" and "b.txt" in back["review_note"] and "measure wind" in back["review_note"]
    assert qa.decide(conn, refusal["id"], "approve")["review_note"] == ""


def test_a_question_the_files_answer_is_not_written(conn, tmp_path, seeded):
    project, _, _, _ = seeded
    says = Script(refusals=[REFUSAL])
    says.answered, says.quote = True, "above 40 dB"
    result = kb.write_refusals(conn, says, project["id"], 1)
    assert result["kept"] == 0 and result["checks"] == 1
    assert result["rejected"] == [{"question": REFUSAL["question"], "reason": "the files answer this question", "quote": "above 40 dB"}]
    assert by_origin(conn, project["id"], "refusal") == []


def test_a_failed_check_stops_the_stage_visibly_and_writes_nothing(conn, tmp_path):
    llm = Reader(refusals=[REFUSAL], fail_on="check")
    project, _, _, run = read(conn, tmp_path, llm, unanswered_pct=30, false_premise_pct=0)
    assert run["status"] == "succeeded" and "model went away" in run["reading"]["kinds"]["error"]
    assert by_origin(conn, project["id"], "refusal") == []


def test_the_check_shows_the_passages_nearest_the_question_with_their_neighbours():
    chunks = [{"text": t} for t in ("alpha one", "before it", "the hops limit is four", "after it", "alpha two", "alpha three")]
    assert kb.nearest_passages("How many hops are allowed?", chunks) == ["before it", "the hops limit is four", "after it"]
    assert kb.nearest_passages("zzz", chunks) == []


def test_a_broken_answer_from_the_check_is_an_error_not_a_no():
    class Broken:
        model = "m"
        def complete_json(self, prompt, schema, temperature=0.9):
            return {"items": []}
    with pytest.raises(LLMError):
        kb.answered_in(Broken(), "How many hops?", [{"text": "the hops limit is four"}])


def test_8_the_count_matches_and_what_is_short_shows_as_discarded(conn, tmp_path):
    llm = Reader(refusals=[REFUSAL], premises=[{"answer": "It is 77 dB in truth, not 90 dB."}])
    _, _, _, run = read(conn, tmp_path, llm, unanswered_pct=30, false_premise_pct=30)
    report = run["reading"]["kinds"]
    assert report["answered"] == 1
    assert report["unanswered"] == {"asked": 1, "written": 1, "discarded": []}
    share = report["false_premises"]
    assert share["asked"] == 1 and share["false"] == 0
    assert "number not in the quote: 77" in share["discarded"][0]["reason"]
    assert report["calls"] == 3  # one question, its check, one premise


def test_nothing_answered_writes_nothing_more(conn, tmp_path, seeded):
    project, source, _, _ = seeded
    with pytest.raises(ValueError, match="read this file first"):
        kinds.repeat(conn, Script(), source["id"], 10, 10)


# --- The checks that discard ---

PARENT = {"question": Q_A, "quote": "above 40 dB"}


@pytest.mark.parametrize("question, answer, claim, reason", [
    (Q_A, FALSE_A, CLAIM, "same question"),
    (FALSE_Q, FALSE_A, "above 40 dB", "false claim is in the quote"),
    (FALSE_Q, FALSE_A, "", "no false claim"),
    (FALSE_Q, "It is 55 dB.", CLAIM, "number not in the quote"),
    (FALSE_Q, "I don't know about that one.", CLAIM, "does not know"),
    (FALSE_Q, "Não sei dizer.", CLAIM, "does not know"),
    (FALSE_Q, "The document says otherwise.", CLAIM, "talks about its source"),
])
def test_a_bad_false_premise_is_discarded(question, answer, claim, reason):
    assert any(reason in r for r in kinds.check_false_premise(question, answer, claim, PARENT))


def test_a_correction_may_repeat_the_wrong_number_it_corrects():
    assert kinds.check_false_premise(FALSE_Q, FALSE_A, CLAIM, PARENT) == []


def test_refusals_skip_publication_editor_instrument_and_model_settings():
    for question in ("When were the results accepted for publication?", "Who is the editor of this study?",
                     "Which encoder settings were used in the trials?", "What instrument was used for flow cytometry?"):
        assert any("publication details or technical settings" in reason for reason in kb.check_written_refusal(
            question, "I don't know that detail.", []))


def test_refusal_question_filler_reason_uses_plain_words():
    assert "the question is vague" in kb.check_written_refusal(
        "What exact settings were used?", "I don't know those settings.", [])


def test_a_true_version_needs_its_numbers_in_the_quote():
    assert kinds.check_true_version(TRUE_Q, TRUE_A, PARENT, FALSE_Q) == []
    assert any("number" in r for r in kinds.check_true_version("Is it 41 dB?", "Yes, 41 dB.", PARENT, FALSE_Q))


def test_the_draw_goes_across_themes_and_is_deterministic(conn, seeded):
    project, _, theme, made = seeded
    second = qa.create_theme(conn, project["id"], "Other metrics")
    qa.edit(conn, made[1], theme_id=second["id"])
    first = kinds._drawn(conn, project["id"], 2, None)
    assert {r["theme_id"] for r in first} == {theme["id"], second["id"]}
    assert first == kinds._drawn(conn, project["id"], 2, None)


def test_a_written_false_premise_must_hold_the_mistake():
    claim = "The enwik8 dataset compresses better than enwik9 under every model."
    assert kinds.states_the_claim("Why does the enwik8 dataset compress better than enwik9 under every model?", claim) == []
    for neutral in ("What is the relationship between enwik8 and enwik9?",):
        assert kinds.states_the_claim(neutral, claim) == ["question does not state the false claim"]
    assert kinds.states_the_claim("Which dataset compresses better under every model, enwik8 or enwik9?", claim) == []
