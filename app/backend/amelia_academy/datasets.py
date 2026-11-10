"""Dataset export: approved pairs -> canonical records, a manifest with grouped splits, chat files, an OKF wiki and a memory file.

Rules applied here:
- an entry is an approved revision of this project, in the chosen themes;
- the checks run again at export, so a rule added after approval still keeps a bad line out,
  and a pair whose quote no longer sits in its passage is left out;
- samples that share a scenario group or a source group never land in different splits;
- the canonical file is serialized deterministically and identified by SHA-256;
- the wiki holds exactly the exported pairs. It is a rendering of them, never a second thing to review.

Ids in the canonical files are UUIDv5 of the Academy ids, so they satisfy the contract's id pattern and
stay stable across exports. `train.jsonl`, `valid.jsonl` and `test.jsonl` are a plain chat rendering with
no model template; the canonical `samples.jsonl` plus `manifest.json` are the source.
"""

import hashlib
import io
import json
import uuid
import zipfile
from collections import Counter
from pathlib import Path

from . import curation, db, kb, okf, projects, qa, rules, sources, workshop

NAMESPACE = uuid.UUID("6f1c2a3e-9b0d-5e4f-8a7b-2c3d4e5f6a7b")
SPLIT_TARGET = {"train": 0.8, "validation": 0.1, "test": 0.1}
KIND = {"refusal": "unanswered"}  # the export says what a pair is, not how it was asked for
OUTPUTS = ("finetune", "memory", "wiki")
MLX_FILE = {"train": "train.jsonl", "validation": "valid.jsonl", "test": "test.jsonl"}
SPLIT_POLICY = "balanced-by-kind-1"  # no seed: the order comes from a hash of each group, so the same pairs split the same way
SHARE = {"train": 8, "validation": 1, "test": 1}  # tenths of a pair, so the sums stay exact
MEASURABLE = 5  # with fewer independent groups of a kind, they teach better than they measure
KIND_WORDS = {"file": "Known", "unanswered": "Not known", "false_premise": "False premise", "true_premise": "True version",
              "neighbour": "Neighbouring subject", "behavior": "Behavior", "connection": "Connected", "complex": "In tension"}
EMPTY_SPLIT = {"train": "The training set has none, so the model will not learn this.",
               "validation": "The validation set has none, so training cannot be watched on this.",
               "test": "The test set has none, so this cannot be measured."}


def canonical_id(academy_id: str) -> str:
    return str(uuid.uuid5(NAMESPACE, academy_id))


def list_datasets(conn, project_id: str) -> list[dict]:
    rows = db.rows(
        conn,
        "SELECT id, name, path, manifest_path, sample_count, manifest_hash, outputs, created_at FROM datasets"
        " WHERE project_id = ? ORDER BY created_at DESC", (project_id,))
    for item in rows:
        manifest_path = Path(item.get('manifest_path') or '')
        if manifest_path.is_file():
            try:
                info = json.loads((manifest_path.parent / 'training-manifest.json').read_text())
                item['has_variants'] = bool(info.get('statistics', {}).get('by_origin', {}).get('variants', 0))
                canonical = json.loads(manifest_path.read_text())
                item['answer_models'] = sorted({x.get('answer_model') for x in canonical.get('entries', []) if x.get('answer_model')})
            except (OSError, ValueError):
                item['has_variants'] = False
        else:
            item['has_variants'] = False
    return rows


def _candidates(conn, project_id: str, theme_ids: list[str] | None) -> tuple[list[dict], list[dict]]:
    wanted = set(theme_ids) if theme_ids else None
    kept, excluded = [], []
    for s in qa.list_samples(conn, project_id, status="approved"):
        if wanted is not None and s["theme_id"] not in wanted:
            continue
        refs = [f"okf:/themes/{s['theme_slug']}.md"]
        linked = []
        if s["origin"] in ("refusal", "neighbour"):
            reasons = qa.text_limits(s["question"], s["answer"])
            group, kind = f"{s['origin']}:{s['id']}", "manual"
        elif s["origin"] == "connection":
            reasons = qa.text_limits(s["question"], s["answer"])
            if not s["based_on"] or any(p["status"] != "approved" for p in s["based_on"]):
                reasons.append("a pair it rests on is not approved")
            hashes = db.rows(conn, "SELECT c.hash FROM qa_sample_links l JOIN qa_samples q ON q.id = l.based_on_id"
                                   " JOIN source_chunks c ON c.id = q.chunk_id WHERE l.sample_id = ? ORDER BY c.hash", (s["id"],))
            refs += [f"academy:chunk/{h['hash']}" for h in hashes]
            linked = [f"passage:{p['chunk_id']}" for p in s["based_on"]]
            group, kind = f"connection:{s['id']}", "source"
        elif s["origin"] == "complex":
            # Its pairs were set aside on purpose: it holds their tension, so they need not be approved.
            reasons = qa.text_limits(s["question"], s["answer"])
            passages = [c for c in [s["chunk_id"], *(p["chunk_id"] for p in s["based_on"])] if c]
            if not passages:
                reasons.append("it has no passage behind it")
            hashes = db.rows(conn, f"SELECT hash FROM source_chunks WHERE id IN ({','.join('?' * len(passages))}) ORDER BY hash", tuple(passages))
            refs += [f"academy:chunk/{h['hash']}" for h in hashes]
            linked = [f"passage:{c}" for c in passages]
            group, kind = f"complex:{s['id']}", "source"
        elif s["origin"] in ("false_premise", "true_premise"):
            reasons = qa.text_limits(s["question"], s["answer"])
            # A person may turn an answered pair into a false premise: then it starts from no pair, only its quote.
            if (s["origin"] == "true_premise" and not s["based_on"]) or any(p["status"] != "approved" for p in s["based_on"]):
                reasons.append("the pair it starts from is not approved")
            chunk = db.row(conn, "SELECT hash FROM source_chunks WHERE id = ?", (s["chunk_id"],))
            if not chunk or not sources.quote_holds(conn, s["chunk_id"], s["quote"]):
                reasons.append("its quote no longer sits in its passage")
            else:
                refs.append(f"academy:chunk/{chunk['hash']}")
            # Same passage as the pair it starts from, or a split would hold its own answer.
            linked = [f"passage:{p['chunk_id']}" for p in s["based_on"]]
            group, kind = f"passage:{s['chunk_id']}", "source"
        elif s["origin"] == "behavior":
            reasons = qa.behavior_reasons(conn, s, s["question"], s["answer"])
            # A pattern is what is being taught, so its pairs spread across splits; only paraphrases stay together.
            group, kind = f"behavior:{s['id']}", "manual"
            refs.append(f"academy:pattern/{s['pattern_id']}")
        else:
            reasons = qa.text_limits(s["question"], s["answer"])
            chunk = db.row(conn, "SELECT text, hash FROM source_chunks WHERE id = ?", (s["chunk_id"],))
            if not chunk or not sources.quote_holds(conn, s["chunk_id"], s["quote"]):
                reasons.append("its quote no longer sits in its passage")
            else:
                refs.append(f"academy:chunk/{chunk['hash']}")
            group, kind = f"passage:{s['chunk_id']}", "source"
        if s['curation']['level'] == 'low':
            reasons.extend(s['curation']['reasons'])
        if reasons:
            excluded.append({"sample_id": s["id"], "reasons": reasons})
            continue
        kept.append({
            "id": s["id"], "revision": s["revision"], "content_hash": s["content_hash"], "theme": s["theme_title"],
            "user": s["question"], "assistant": s["answer"], "scenario_key": None, "source_group": group,
            "provenance_kind": kind, "evidence_refs": refs, "linked_groups": linked,
            "curation": s['curation'], "theme_id": s["theme_id"],
            "kind": KIND.get(s["origin"], s["origin"]), "false_claim": s["false_claim"],
        })
    return kept, excluded


def _scenario_groups(items: list[dict]) -> None:
    """Near-duplicate questions are grouped within their current theme; changing themes changes grouped test splits."""
    clusters: list[tuple[str, set]] = []
    for item in items:
        if item["scenario_key"]:
            item["scenario_key"] = f"{item['theme_id']}:{item['scenario_key']}"
            continue
        shingles = rules.word_shingles(item["user"])
        for key, other in clusters:
            if not key.startswith(f"{item['theme_id']}:"):
                continue
            if rules.jaccard(shingles, other) >= qa.NEAR_DUPLICATE:
                item["scenario_key"] = f"{item['theme_id']}:{key}"
                break
        else:
            item["scenario_key"] = f"{item['theme_id']}:situation:{item['content_hash'][:16]}"
            clusters.append((item["scenario_key"], shingles))


def assign_splits(items: list[dict]) -> dict[str, str]:
    """Union samples that share a scenario or source group; give each component one split, deterministically."""
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for item in items:
        a, b = find("s:" + item["scenario_key"]), find("g:" + item["source_group"])
        if a != b:
            parent[max(a, b)] = min(a, b)
        # A pair resting on two passages stays with both, or a split would hold its evidence.
        for group in item.get("linked_groups") or []:
            a, c = find("s:" + item["scenario_key"]), find("g:" + group)
            if a != c:
                parent[max(a, c)] = min(a, c)
    components: dict[str, list[dict]] = {}
    for item in items:
        components.setdefault(find("s:" + item["scenario_key"]), []).append(item)
    order = sorted(components, key=lambda k: hashlib.sha256(k.encode()).hexdigest())
    placed = _balance({key: Counter(m.get("kind", "") for m in components[key]) for key in order})
    # Rounding can leave a small dataset with no validation or test set though it has groups to spare.
    for split in ("validation", "test"):
        if split in placed.values():
            continue
        spare = [key for key in order if placed[key] == "train"]
        if len(spare) >= 2:
            in_train = Counter(m.get("kind", "") for key in spare for m in components[key])
            kinds = {key: Counter(m.get("kind", "") for m in components[key]) for key in spare}
            # Prefer a group whose kinds would still be in training without it.
            key = min(spare, key=lambda k: (any(in_train[kind] == n for kind, n in kinds[k].items()), len(components[k]), order.index(k)))
            placed[key] = split
    return {m["id"]: placed[key] for key in order for m in components[key]}


def _balance(groups: dict[str, Counter]) -> dict[str, str]:
    """The share holds for each kind, not only the total. The rarest kind still waiting goes first, each group to the
    split that most lacks it. A group is never broken to fit: leakage is not traded for balance."""
    total = Counter()
    for kinds in groups.values():
        total.update(kinds)
    need = {split: {kind: share * n for kind, n in total.items()} for split, share in SHARE.items()}
    overall = {split: share * sum(total.values()) for split, share in SHARE.items()}
    for kind in total:
        if sum(1 for kinds in groups.values() if kinds[kind]) >= MEASURABLE:
            for split in ("validation", "test"):
                need[split][kind] = max(need[split][kind], 10)
            need["train"][kind] = 10 * total[kind] - need["validation"][kind] - need["test"][kind]
    waiting, left, placed = list(groups), Counter(total), {}
    while waiting:
        rarest = min((k for k in left if left[k] > 0), key=lambda k: (left[k], k))
        key = next(g for g in waiting if groups[g][rarest])
        split = max(SHARE, key=lambda s: (need[s][rarest], overall[s], s == "train"))
        placed[key] = split
        waiting.remove(key)
        for kind, n in groups[key].items():
            need[split][kind] -= 10 * n
            overall[split] -= 10 * n
            left[kind] -= n
    return placed


def split_warnings(items: list[dict], split_of: dict[str, str]) -> list[dict]:
    """What could not be balanced, in plain words. The export still goes out."""
    found = []
    for kind in sorted({item["kind"] for item in items}):
        members = [item for item in items if item["kind"] == kind]
        missing = [s for s in SPLIT_TARGET if not any(split_of[item["id"]] == s for item in members)]
        if missing:
            word = KIND_WORDS.get(kind, kind)
            found.append({"kind": kind, "count": len(members), "missing": missing,
                          "message": f'{word}: {len(members)} pair(s). ' + " ".join(EMPTY_SPLIT[s] for s in missing)})
    return found


def _readme(profile: str, by_kind: dict, warnings: list[dict], rights: list[dict], reasoned: int) -> str:
    """What is in this folder, in plain words. No paths and no user names."""
    lines = ["# Fine-tuning export", "", "| Kind | Train | Validation | Test | Total |", "|---|---:|---:|---:|---:|"]
    for kind in sorted(by_kind):
        n = by_kind[kind]
        lines.append(f"| {KIND_WORDS.get(kind, kind)} | {n['train']} | {n['validation']} | {n['test']} | {n['total']} |")
    lines += ["", "## Where it came from", ""]
    lines += [f"- {r['name']}: {r['license_basis']}" for r in rights] or ["- No files. These pairs were written in the project."]
    if warnings:
        lines += ["", "## Warnings", ""] + [f"- {w['message']}" for w in warnings]
    lines += ["", "## Files", ""]
    if profile in ("direct", "both"):
        lines += ["`train.jsonl`, `valid.jsonl` and `test.jsonl` hold final answers as plain chat messages, with no model template.",
                  "To train with mlx-lm, from this folder:", "", "```", "mlx_lm.lora --model <base model> --train --data . --mask-prompt", "```", ""]
    if profile in ("reasoned", "both"):
        lines += [f"`reasoned/` holds {reasoned} approved explanation(s) with final answers, in the same splits.",
                  "These are neutral source files: a verified renderer for your model and a loss mask are needed before training.",
                  "Do not feed them directly into mlx-lm.", ""]
    lines += ["`samples.jsonl` is the common selection and `curation.jsonl` freezes its review status. A confidence level describes the review, not a chance of being right.",
              "`training-manifest.json` holds counts, hashes and missing explanations.", ""]
    return "\n".join(lines)


def export_dataset(conn, out_dir: Path, name: str, project_id: str, theme_ids: list[str] | None = None,
                   outputs: list[str] | None = None, *, profile: str = 'direct',
                   confidence_levels: list[str] | None = None, sample_ids: list[str] | None = None) -> dict:
    """Only this project's approved pairs; another project's work never enters the dataset.
    The manifest and the rights always come out; of the rest, only what was asked for."""
    outputs = [o for o in OUTPUTS if o in outputs] if outputs is not None else list(OUTPUTS)
    if not outputs:
        raise ValueError(f"choose at least one of: {', '.join(OUTPUTS)}")
    if profile not in ('direct', 'reasoned', 'both'):
        raise ValueError('Choose direct, reasoned or both.')
    levels = set(confidence_levels if confidence_levels is not None else ('medium', 'high'))
    if not levels or levels - {'medium', 'high'}:
        raise ValueError('Only medium and high confidence pairs can be exported.')
    project = projects.get(conn, project_id)
    items, excluded = _candidates(conn, project_id, None)
    _scenario_groups(items)
    # Same approved pool => same split even when exporting a subset or confidence profile.
    groups = qa.similar_groups(conn, project_id)
    for group in groups:
        marker = 'similar:' + min(s['id'] for s in group['samples'])
        ids = {s['id'] for s in group['samples']}
        for item in items:
            if item['id'] in ids: item['linked_groups'].append(marker)
    split_of = assign_splits(items)
    filtered = []
    for item in items:
        if theme_ids and item['theme_id'] not in theme_ids:
            continue
        if (sample_ids is not None and item['id'] not in sample_ids) or item['curation']['level'] not in levels:
            excluded.append({'sample_id': item['id'], 'reasons': ['Outside the selected pairs or confidence levels.']})
        else:
            filtered.append(item)
    items = filtered
    if not items:
        detail = f" ({len(excluded)} approved pair(s) fail the rules now)" if excluded else ""
        raise ValueError(f"no approved pairs to export{detail}")
    name = okf.slugify(name) if (name or "").strip() else "dataset"

    exported = {item["id"] for item in items}
    wiki = qa.wiki_files(conn, project_id, exported) if "wiki" in outputs else {}
    knowledge = kb.memory_records(conn, project_id, exported, canonical_id)
    memory = knowledge if "memory" in outputs else []
    # Without fine-tuning, the pairs that only go there are not written anywhere.
    written = len(items) if "finetune" in outputs else len(knowledge)
    has_pages = any(path.startswith("themes/") for path in wiki)
    empty = [o for o, full in (("memory", memory), ("wiki", has_pages)) if o in outputs and not full]
    if len(empty) == len(outputs):
        raise ValueError(f"nothing to write: the chosen pairs only go to fine-tuning, not to {' or '.join(empty)}")

    if 'finetune' in outputs and profile == 'reasoned' and not any(i['curation']['rationale'] and i['curation']['rationale']['usable'] for i in items):
        raise ValueError('No approved explanations yet. Review them in Curate first.')
    did = db.new_id("ds")
    folder = Path(out_dir) / f"{name}-{did}"
    folder.mkdir(parents=True, exist_ok=True)
    records, entries, rendered = [], [], {k: [] for k in SPLIT_TARGET}
    for item in sorted(items, key=lambda i: canonical_id(i["id"])):
        record = {
            "schema_version": "1.0", "sample_id": canonical_id(item["id"]), "project_id": canonical_id(project_id),
            "revision": item["revision"], "language": project["language"], "scenario_id": item["scenario_key"],
            "messages": [{"role": "user", "content": [{"type": "text", "text": item["user"]}]},
                         {"role": "assistant", "content": [{"type": "text", "text": item["assistant"]}]}],
            "provenance": {"kind": item["provenance_kind"], "evidence_refs": item["evidence_refs"]},
            "kind": item["kind"],
        }
        if project.get('identity'):
            record['messages'].insert(0, {'role': 'system', 'content': [{'type': 'text', 'text': project['identity']}]})
        if item["false_claim"]:
            record["false_claim"] = item["false_claim"]
        line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        records.append(line)
        entries.append({"sample_id": record["sample_id"], "sample_revision": item["revision"],
                        "sample_sha256": hashlib.sha256(line.encode("utf-8")).hexdigest(),
                        "split": split_of[item["id"]], "kind": item["kind"], "scenario_group": item["scenario_key"],
                        "source_group": item["source_group"]})
        rendered[split_of[item["id"]]].append(json.dumps(
            {"messages": ([{'role': 'system', 'content': project['identity']}] if project.get('identity') else []) + [{"role": "user", "content": item["user"]}, {"role": "assistant", "content": item["assistant"]}]},
            ensure_ascii=False))
    # Reviewed question variants stay in the source pair's group and can never leak into another split.
    from . import prepare
    included = {item['id']: item for item in items}
    for variant in db.rows(conn, "SELECT * FROM training_variants WHERE project_id=? AND status='kept' ORDER BY id", (project_id,)):
        item = included.get(variant['pair_id'])
        if not item or variant.get('excess') or variant['pair_version'] != prepare.version(qa.get_sample(conn, variant['pair_id'])):
            continue
        if theme_ids and item['theme_id'] not in theme_ids:
            continue
        split = split_of[item['id']]
        record = {'schema_version':'1.0', 'sample_id':canonical_id(variant['id']), 'derived_from':canonical_id(item['id']),
                  'project_id':canonical_id(project_id), 'language':project['language'], 'messages':[
                      {'role':'user','content':[{'type':'text','text':variant['question']}]},
                      {'role':'assistant','content':[{'type':'text','text':variant['answer']}]}],
                  'provenance':{'kind':'derived','evidence_refs':item['evidence_refs']}, 'kind':item['kind']}
        line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',',':'))
        records.append(line)
        entries.append({'sample_id':record['sample_id'], 'derived_from':record['derived_from'],
                        'sample_sha256':hashlib.sha256(line.encode()).hexdigest(), 'split':split, 'kind':item['kind'],
                        'scenario_group':item['scenario_key'], 'source_group':item['source_group'],
                        'answer_model':variant['answer_model'] or None, 'question_model':variant['question_model'] or None})
        rendered[split].append(json.dumps({'messages':([{'role':'system','content':project['identity']}] if project.get('identity') else []) +
            [{'role':'user','content':variant['question']},{'role':'assistant','content':variant['answer']}]}, ensure_ascii=False))
    body = "\n".join(records) + "\n"
    canonical_sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
    by_split = {k: len(v) for k, v in rendered.items()}
    by_kind: dict[str, dict] = {}
    for item in items:
        counts = by_kind.setdefault(item["kind"], {"total": 0, **{k: 0 for k in SPLIT_TARGET}})
        counts["total"] += 1
        counts[split_of[item["id"]]] += 1
    for entry in entries[len(items):]:
        counts = by_kind.setdefault(entry['kind'], {"total": 0, **{k: 0 for k in SPLIT_TARGET}})
        counts['total'] += 1
        counts[entry['split']] += 1
    manifest = {
        "schema_version": "1.0", "dataset_id": canonical_id(did), "project_id": canonical_id(project_id),
        "created_at": db.now(), "entries": entries,
        "statistics": {"total_samples": len(records), "by_split": by_split, "by_kind": by_kind,
                       "by_origin": {'pairs':len(items), 'variants':len(records)-len(items)}},
        "outputs": outputs,
    }
    if "finetune" in outputs:
        manifest["canonical_sha256"] = canonical_sha
    prepared_entries = [e for e in entries if e.get('derived_from') and e.get('answer_model')]
    if prepared_entries:
        configurations = sorted({(e.get('answer_model'), e.get('question_model')) for e in prepared_entries})
        manifest['preparation'] = {'configurations': [{'answer_model': a, 'question_model': q} for a, q in configurations],
                                   'prepare_count': project.get('prepare_count', 'normal')}
    manifest_text = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    (folder / "manifest.json").write_text(manifest_text, encoding="utf-8")
    if "finetune" in outputs:
        (folder / "samples.jsonl").write_text(body, encoding="utf-8")
        for split, lines in (rendered.items() if profile in ('direct', 'both') else []):
            if lines:
                (folder / MLX_FILE[split]).write_text("\n".join(lines) + "\n", encoding="utf-8")
    profile_stats = {}
    split_notes = []
    answer_notes = []
    if 'finetune' in outputs:
        # What a split lacks depends on what really went out: explanations alone can be far fewer than answers.
        split_notes = split_warnings([i for i in items if profile != 'reasoned' or (i['curation']['rationale'] and i['curation']['rationale']['usable'])], split_of)
        answer_notes = kb.repeated_answers([{'id': i['id'], 'question': i['user'], 'answer': i['assistant'],
                                             'origin': 'refusal' if i['kind'] == KIND.get('refusal') else ''} for i in items])
        neutral = []
        reasoned_excluded = []
        for item in sorted(items, key=lambda i: canonical_id(i['id'])):
            c = item['curation']; rationale = c['rationale']
            neutral.append({'sample_id': canonical_id(item['id']), 'revision': item['revision'],
                            'input_hash': c['input_hash'], 'level': c['level'], 'rule_version': c['rule_version'],
                            'reasons': c['reasons']})
            if not rationale or not rationale['usable']:
                reasoned_excluded.append({'sample_id': canonical_id(item['id']), 'reason': 'No current approved explanation.'})
        profile_stats = {'direct': len(items), 'reasoned': len(items) - len(reasoned_excluded)}
        assets = {}
        def write_asset(path, rows):
            data = ''.join(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n' for row in rows)
            (folder / path).parent.mkdir(parents=True, exist_ok=True)
            (folder / path).write_text(data, encoding='utf-8')
            assets[path] = {'sha256': hashlib.sha256(data.encode()).hexdigest(), 'lines': len(rows)}
        write_asset('curation.jsonl', neutral)
        if profile in ('reasoned', 'both'):
            for split in SPLIT_TARGET:
                rows = []
                for item in sorted(items, key=lambda i: canonical_id(i['id'])):
                    rationale = item['curation']['rationale']
                    if split_of[item['id']] != split or not rationale or not rationale['usable']: continue
                    rows.append({'schema_version': '1.0', 'sample_id': canonical_id(item['id']),
                                 'sample_revision': item['revision'], 'input_hash': item['curation']['input_hash'],
                                 'rationale_id': rationale['id'], 'question': item['user'],
                                 'rationale': rationale['text'], 'final': item['assistant'],
                                 'evidence_refs': item['evidence_refs'], 'review_basis': curation.basis(conn, qa.get_sample(conn, item['id']))})
                write_asset(f'reasoned/{MLX_FILE[split]}', rows)
        for split in SPLIT_TARGET:
            p = folder / MLX_FILE[split]
            if p.exists():
                in_file = Counter(e['kind'] for e in entries if e['split'] == split)
                assets[p.name] = {'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'lines': by_split[split], 'by_kind': dict(sorted(in_file.items()))}
        training_manifest = {'schema_version': '2.0', 'profile': profile, 'canonical_sha256': canonical_sha,
                             'confidence_rule': curation.RULE, 'confidence_levels': sorted(levels),
                             'statistics': profile_stats, 'files': assets, 'reasoned_excluded': reasoned_excluded,
                             'reasoned_format': 'editorial-rationale-v1', 'reasoned_renderer': None,
                             'identity': project.get('identity', ''),
                             'identity_sha256': hashlib.sha256(project['identity'].encode()).hexdigest() if project.get('identity') else None,
                             'split_policy': SPLIT_POLICY, 'split_warnings': split_notes,
                             'entries': entries}
        (folder / 'training-manifest.json').write_text(json.dumps(training_manifest, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
        (folder / 'README.md').write_text(_readme(profile, by_kind, split_notes + answer_notes, kb.source_rights(conn, project_id, exported), profile_stats['reasoned']), encoding='utf-8')
    if has_pages:
        okf.write_bundle(folder / "wiki", wiki)
    if memory:
        (folder / "memory.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in memory) + "\n", encoding="utf-8")
    rights = kb.source_rights(conn, project_id, exported)
    (folder / "sources.json").write_text(json.dumps(rights, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest_hash = hashlib.sha256(manifest_text.encode("utf-8")).hexdigest()
    main_file = folder / ("samples.jsonl" if "finetune" in outputs else "manifest.json")
    conn.execute(
        "INSERT INTO datasets (id, name, path, manifest_path, sample_count, manifest_hash, project_id, outputs, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (did, name, str(main_file), str(folder / "manifest.json"), written, manifest_hash,
         project_id, ",".join(outputs), db.now()))
    conn.commit()
    by_theme = {}
    for item in items:
        by_theme[item["theme"]] = by_theme.get(item["theme"], 0) + 1
    warnings = [f"no {split} split: every sample shares a group with the others" for split, n in by_split.items()
                if n == 0 and split != "train" and "finetune" in outputs]
    warnings += [f"nothing to write to {o}: the chosen pairs only go to fine-tuning" for o in empty]
    undeclared = [r["name"] for r in rights if r["license_basis"] == "unspecified"]
    if undeclared:
        warnings.append(f"no rights declared for: {', '.join(undeclared)}")
    if 'finetune' in outputs:
        written = len(records)
    return {"id": did, "name": name, "path": str(main_file), "folder": str(folder), "outputs": outputs,
            "sample_count": written, "memory_count": len(memory), "manifest_hash": manifest_hash, "splits": by_split,
            "profile": profile, "profile_counts": profile_stats, "split_warnings": split_notes,
            "answer_warnings": [{k: w[k] for k in ('answer', 'count', 'message')} for w in answer_notes],
            "excluded": excluded, "warnings": warnings, "themes": by_theme, "kinds": by_kind}


def zip_export(conn, dataset_id: str, root: Path) -> tuple[str, bytes]:
    """Everything one export wrote. Reads only under the datasets folder."""
    found = db.row(conn, "SELECT name, path FROM datasets WHERE id = ?", (dataset_id,))
    if not found:
        raise workshop.NotFound(f"dataset {dataset_id} not found")
    root = Path(root).resolve()
    folder = Path(found["path"]).resolve().parent
    if not folder.is_relative_to(root) or not folder.is_dir():
        raise workshop.NotFound(f"the files of dataset {dataset_id} are no longer on disk")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(folder).as_posix())
    return f"{found['name']}-{dataset_id}.zip", buffer.getvalue()
