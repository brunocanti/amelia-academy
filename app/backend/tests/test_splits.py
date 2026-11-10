"""Spec 014: what stays together, what spreads by kind, and what the export says it could not balance."""
import hashlib
import json
from pathlib import Path

import jsonschema
import pytest
from amelia_academy import datasets, qa, workshop
from test_qa import conn, project, Stub, pair, upload, generate

KINDS = ("file", "unanswered", "false_premise", "true_premise", "neighbour", "behavior")


def item(i, kind, group=None):
    return {"id": f"{kind}{i}", "kind": kind, "scenario_key": f"sc-{kind}{i}", "source_group": group or f"g-{kind}{i}"}


def by(items, splits, kind):
    return {s: sum(1 for i in items if i["kind"] == kind and splits[i["id"]] == s) for s in datasets.SPLIT_TARGET}


def test_every_split_gets_every_kind_with_ten_of_each():
    items = [item(i, k) for k in KINDS for i in range(10)]
    splits = datasets.assign_splits(items)
    for kind in KINDS:
        assert by(items, splits, kind) == {"train": 8, "validation": 1, "test": 1}
    assert datasets.split_warnings(items, splits) == []


def test_a_rare_kind_among_many_still_reaches_every_split():
    items = [item(i, "file") for i in range(200)] + [item(i, "false_premise") for i in range(5)]
    splits = datasets.assign_splits(items)
    assert by(items, splits, "false_premise") == {"train": 3, "validation": 1, "test": 1}
    assert 150 <= by(items, splits, "file")["train"] <= 170


def test_a_kind_too_small_goes_out_with_a_warning_naming_the_split():
    items = [item(i, "file") for i in range(20)] + [item(i, "false_premise") for i in range(2)]
    splits = datasets.assign_splits(items)
    assert by(items, splits, "false_premise")["train"] == 2
    found = datasets.split_warnings(items, splits)
    assert [w["kind"] for w in found] == ["false_premise"]
    assert found[0]["missing"] == ["validation", "test"]
    assert "False premise: 2 pair(s)" in found[0]["message"] and "cannot be measured" in found[0]["message"]


def test_leakage_is_never_traded_for_balance():
    items = [item(i, "false_premise", "passage:one") for i in range(12)] + [item(i, "file") for i in range(40)]
    splits = datasets.assign_splits(items)
    assert len({splits[i["id"]] for i in items if i["kind"] == "false_premise"}) == 1
    assert datasets.split_warnings(items, splits)[0]["kind"] == "false_premise"


def test_the_same_pairs_split_the_same_way_in_any_order():
    items = [item(i, k) for k in KINDS for i in range(7)]
    assert datasets.assign_splits(items) == datasets.assign_splits(list(reversed(items)))


def test_duplicate_questions_group_within_the_current_theme():
    items = [
        {"id":"a", "scenario_key":None, "content_hash":"a", "user":"How is image quality measured?", "theme_id":"one"},
        {"id":"b", "scenario_key":None, "content_hash":"b", "user":"How is image quality measured?", "theme_id":"two"},
    ]
    datasets._scenario_groups(items)
    assert items[0]["scenario_key"] != items[1]["scenario_key"]


def test_an_equal_share_is_not_taken_from_training_when_a_kind_would_vanish():
    items = [item(0, "behavior"), item(0, "file"), item(1, "file"), item(2, "file")]
    splits = datasets.assign_splits(items)
    assert set(splits.values()) == {"train", "validation", "test"}
    assert by(items, splits, "behavior")["train"] == 1


def many(conn, tmp_path, project, n=12):
    pairs = [pair(question=f"Topic {w} asks what the threshold of {w} is in this setup?", answer=f"For {w} the difference is usually invisible.")
             for w in ("alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima".split()[:n])]
    generate(conn, Stub(pairs=pairs), upload(conn, tmp_path, project))
    samples = qa.list_samples(conn, project["id"])
    return [qa.decide(conn, s["id"], "approve") for s in samples]


def test_the_manifest_proves_each_file_and_says_what_it_holds(conn, tmp_path, project):
    many(conn, tmp_path, project)
    ds = datasets.export_dataset(conn, tmp_path / "out", "x", project["id"], outputs=["finetune"])
    folder = Path(ds["folder"])
    manifest = json.loads((folder / "training-manifest.json").read_text())
    schema = Path(__file__).resolve().parents[3] / "contracts/json-schema/training-manifest.schema.json"
    jsonschema.validate(manifest, json.loads(schema.read_text()))
    assert manifest["split_policy"] == datasets.SPLIT_POLICY and manifest["identity_sha256"] is None
    for name in ("train.jsonl",):
        asset = manifest["files"][name]
        data = (folder / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == asset["sha256"]
        assert sum(asset["by_kind"].values()) == asset["lines"] == data.decode().count("\n")
    assert manifest["split_warnings"] == ds["split_warnings"]


def test_two_exports_write_the_same_files_and_a_change_shows(conn, tmp_path, project):
    samples = many(conn, tmp_path, project)
    one = datasets.export_dataset(conn, tmp_path / "out", "a", project["id"], outputs=["finetune"])
    two = datasets.export_dataset(conn, tmp_path / "out", "b", project["id"], outputs=["finetune"])
    for name in ("train.jsonl", "samples.jsonl", "training-manifest.json", "README.md", "curation.jsonl"):
        assert (Path(one["folder"]) / name).read_bytes() == (Path(two["folder"]) / name).read_bytes(), name
    qa.edit(conn, samples[0]["id"], answer="For that case the difference is usually invisible too.")
    qa.decide(conn, samples[0]["id"], "approve")
    three = datasets.export_dataset(conn, tmp_path / "out", "c", project["id"], outputs=["finetune"])
    first = json.loads((Path(one["folder"]) / "training-manifest.json").read_text())
    third = json.loads((Path(three["folder"]) / "training-manifest.json").read_text())
    assert first["canonical_sha256"] != third["canonical_sha256"]


def test_identity_reaches_every_line_only_when_it_exists(conn, tmp_path, project):
    many(conn, tmp_path, project)
    plain = datasets.export_dataset(conn, tmp_path / "out", "a", project["id"], outputs=["finetune"])
    lines = (Path(plain["folder"]) / "train.jsonl").read_text().splitlines()
    assert all(json.loads(l)["messages"][0]["role"] == "user" for l in lines)
    conn.execute("UPDATE projects SET identity = 'You are careful.' WHERE id = ?", (project["id"],))
    conn.commit()
    named = datasets.export_dataset(conn, tmp_path / "out", "b", project["id"], outputs=["finetune"])
    lines = (Path(named["folder"]) / "train.jsonl").read_text().splitlines()
    assert all(json.loads(l)["messages"][0] == {"role": "system", "content": "You are careful."} for l in lines)
    manifest = json.loads((Path(named["folder"]) / "training-manifest.json").read_text())
    assert manifest["identity_sha256"] == hashlib.sha256(b"You are careful.").hexdigest()


def test_similar_pairs_stay_together_unless_a_person_kept_them_apart(conn, tmp_path, project):
    question = "What is the threshold of hearing for this setup in the room?"
    generate(conn, Stub(pairs=[pair(question=question), pair(question="What is the threshold of hearing for this setup in the room today?", answer="It is usually invisible for this setup.")]
                        + [pair(question=f"Topic {w} asks what {w} measures here?", answer=f"For {w} the difference is usually invisible.") for w in "alpha bravo charlie delta echo foxtrot golf hotel india juliet".split()]),
             upload(conn, tmp_path, project))
    samples = [qa.decide(conn, s["id"], "approve") for s in qa.list_samples(conn, project["id"])]
    groups = qa.similar_groups(conn, project["id"])
    assert groups, "the two questions should read as similar"
    ids = {s["id"] for s in groups[0]["samples"]}
    ds = datasets.export_dataset(conn, tmp_path / "out", "a", project["id"], outputs=["finetune"])
    entries = {e["sample_id"]: e["split"] for e in json.loads((Path(ds["folder"]) / "manifest.json").read_text())["entries"]}
    assert len({entries[datasets.canonical_id(i)] for i in ids}) == 1
    # Kept apart, nothing ties them any more: they are ordinary pairs again.
    qa.keep_apart(conn, project["id"], sorted(ids))
    assert not any(ids <= {s["id"] for s in g["samples"]} for g in qa.similar_groups(conn, project["id"]))
    items, _ = datasets._candidates(conn, project["id"], None)
    datasets._scenario_groups(items)
    pair_items = [i for i in items if i["id"] in ids]
    assert not any(l.startswith("similar:") for i in pair_items for l in i["linked_groups"])


def test_behavior_pairs_of_one_pattern_can_spread_across_splits(conn, project):
    class Writer:
        model = "stub-model"
        def complete_json(self, prompt, schema, temperature=0.9):
            return {"items": [{"user_message": f"I finally repainted the old {w} in my garden this weekend.",
                               "response_text": f"A repainted {w} changes the whole garden. What colour did you pick?"}
                              for w in ("bench", "fence")]}
    pattern = workshop.create_pattern(conn, project_id=project["id"], title="Quiet company", intent="stay with the person",
                                      tone="calm", guidelines="one detail", description="a hard day")
    workshop.set_pattern_status(conn, pattern["id"], "approved")
    workshop.generate_batch(conn, Writer(), pattern["id"], count=2)
    for s in qa.list_samples(conn, project["id"]):
        qa.decide(conn, s["id"], "approve")
    items, _ = datasets._candidates(conn, project["id"], None)
    assert len({i["source_group"] for i in items}) == len(items) >= 2


def test_the_readme_says_what_is_there_without_paths(conn, tmp_path, project):
    many(conn, tmp_path, project)
    ds = datasets.export_dataset(conn, tmp_path / "out", "x", project["id"], outputs=["finetune"])
    text = (Path(ds["folder"]) / "README.md").read_text()
    assert "| Known |" in text and "mlx_lm.lora" in text and "reasoned/" not in text
    assert str(tmp_path) not in text
