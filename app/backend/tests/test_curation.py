"""Confidence, stale evidence, reviewed explanations and frozen profile exports."""
import json
from pathlib import Path

import pytest
from amelia_academy import curation, datasets, db, qa, workshop
from test_qa import conn, project, Stub, pair, upload, generate


def approved(conn, tmp_path, project):
    generate(conn, Stub(pairs=[pair()]), upload(conn, tmp_path, project))
    sample = qa.list_samples(conn, project['id'])[0]
    return qa.decide(conn, sample['id'], 'approve')


def test_checks_are_explicit_versioned_and_undoable(conn, tmp_path, project):
    sample = approved(conn, tmp_path, project)
    assert sample['curation']['level'] == 'medium'
    before = sample['curation']
    assert curation.check(conn, sample, before['input_hash'], {'evidence': True})['level'] == 'high'
    assert curation.check(conn, sample, before['input_hash'], {})['level'] == 'medium'
    assert conn.execute('SELECT count(*) FROM curation_events').fetchone()[0] == 3
    qa.edit(conn, sample['id'], answer='The difference is usually invisible above 40 dB.')
    new = qa.get_sample(conn, sample['id'])
    with pytest.raises(workshop.Conflict): curation.check(conn, new, before['input_hash'], {'evidence': True})
    assert new['curation']['level'] == 'low'


def test_corpus_change_invalidates_unknown_scope(conn, tmp_path, project):
    sample = approved(conn, tmp_path, project)
    conn.execute("UPDATE qa_samples SET origin='refusal', quote='', chunk_id=NULL WHERE id=?", (sample['id'],))
    conn.commit()
    sample = qa.get_sample(conn, sample['id'])
    assert curation.check(conn, sample, sample['curation']['input_hash'], {'scope': True})['level'] == 'high'
    upload(conn, tmp_path, project, name='new.txt', content='A new file changes what was checked.')
    current = qa.get_sample(conn, sample['id'])
    # Upload may not extract chunks yet: invalidation must happen on corpus membership, not only extracted chunks.
    assert current['curation']['level'] == 'medium'


def test_explanation_needs_approval_and_current_inputs(conn, tmp_path, project):
    sample = approved(conn, tmp_path, project); stamp = sample['curation']['input_hash']
    assert not curation.write_rationale(conn, sample, stamp, 'The evidence establishes the threshold.')['rationale']['usable']
    result = curation.write_rationale(conn, sample, stamp, 'The evidence establishes the threshold.', True)
    assert result['rationale']['usable']
    curation.reset_rationale(conn, sample, result['rationale']['id'])
    assert not curation.state(conn, sample)['rationale']['usable']
    curation.write_rationale(conn, sample, stamp, 'The evidence establishes the threshold.', True)
    qa.edit(conn, sample['id'], answer='The difference is usually invisible above 40 dB.')
    assert not qa.get_sample(conn, sample['id'])['curation']['rationale']['usable']


def test_open_conflict_blocks_an_approved_pair(conn, tmp_path, project):
    sample = approved(conn, tmp_path, project)
    conn.execute("INSERT INTO qa_challenges(id,project_id,model,status,created_at) VALUES ('chl_test',?,'stub','done',?)", (project['id'], db.now()))
    conn.execute("INSERT INTO qa_conflicts(id,project_id,challenge_id,kind,first_id,second_id,status,created_at) VALUES ('cfl_test',?,'chl_test','false_unsettled',?,'','open',?)", (project['id'], sample['id'], db.now()))
    conn.commit()
    assert qa.get_sample(conn, sample['id'])['curation']['level'] == 'low'
    with pytest.raises(ValueError, match='no approved'): datasets.export_dataset(conn, tmp_path/'out', 'x', project['id'])


def test_profile_exports_freeze_approval_and_keep_shared_splits(conn, tmp_path, project):
    sample = approved(conn, tmp_path, project)
    with pytest.raises(ValueError, match='No approved explanations'):
        datasets.export_dataset(conn, tmp_path/'out', 'x', project['id'], outputs=['finetune'], profile='reasoned')
    curation.write_rationale(conn, sample, sample['curation']['input_hash'], 'The evidence establishes the threshold.', True)
    ds = datasets.export_dataset(conn, tmp_path/'out', 'x', project['id'], outputs=['finetune'], profile='both')
    folder = Path(ds['folder']); manifest = json.loads((folder/'training-manifest.json').read_text())
    assert ds['profile_counts'] == {'direct': 1, 'reasoned': 1}
    assert json.loads((folder/'train.jsonl').read_text())['messages'][-1]['content'] == sample['answer']
    assert json.loads((folder/'reasoned/train.jsonl').read_text())['final'] == sample['answer']
    assert manifest['reasoned_renderer'] is None
    import hashlib
    for path, asset in manifest['files'].items():
        assert hashlib.sha256((folder/path).read_bytes()).hexdigest() == asset['sha256']
    curation.reset_rationale(conn, sample, curation.state(conn, sample)['rationale']['id'])
    assert manifest['statistics']['reasoned'] == 1  # immutable export


def test_invalid_checks_and_unapproved_explanations_do_not_raise_confidence(conn, tmp_path, project):
    sample = approved(conn, tmp_path, project)
    with pytest.raises(ValueError): curation.check(conn, sample, sample['curation']['input_hash'], {'model_says_high': True})
    ds = datasets.export_dataset(conn, tmp_path/'out', 'x', project['id'], outputs=['finetune'], profile='both')
    assert ds['profile_counts']['reasoned'] == 0


def test_neutral_contracts_validate_export(conn, tmp_path, project):
    import jsonschema
    sample = approved(conn, tmp_path, project)
    curation.write_rationale(conn, sample, sample['curation']['input_hash'], 'The evidence establishes the threshold.', True)
    ds = datasets.export_dataset(conn, tmp_path/'out', 'x', project['id'], outputs=['finetune'], profile='both')
    folder = Path(ds['folder'])
    schemas = Path(__file__).resolve().parents[3] / 'contracts/json-schema'
    manifest = json.loads((folder/'training-manifest.json').read_text())
    jsonschema.validate(manifest, json.loads((schemas/'training-manifest.schema.json').read_text()))
    schema = json.loads((schemas/'editorial-rationale.schema.json').read_text())
    rationale = json.loads((folder/'reasoned/train.jsonl').read_text())
    jsonschema.validate(rationale, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**rationale, 'private_thoughts': 'should not be accepted'}, schema)


def test_subset_uses_same_split_as_full_pool(conn, tmp_path, project):
    sample = approved(conn, tmp_path, project)
    full = datasets.export_dataset(conn, tmp_path/'out', 'full', project['id'], outputs=['finetune'])
    subset = datasets.export_dataset(conn, tmp_path/'out', 'subset', project['id'], outputs=['finetune'], sample_ids=[sample['id']])
    one = json.loads((Path(full['folder'])/'training-manifest.json').read_text())
    two = json.loads((Path(subset['folder'])/'training-manifest.json').read_text())
    assert one['entries'] == two['entries']


class Says:
    def __init__(self, text=None, fails=None): self.text, self.fails = text, fails
    def complete_json(self, *a, **k):
        if self.fails: raise self.fails
        return {'text': self.text} if self.text is not None else {}


@pytest.mark.parametrize('text', [None, '', '   '])
def test_a_model_with_nothing_to_say_is_said_plainly(conn, tmp_path, project, text):
    sample = approved(conn, tmp_path, project)
    with pytest.raises(ValueError, match='did not find enough'):
        curation.draft(conn, sample, Says(text))
    assert curation.state(conn, sample)['rationale'] is None


def test_a_failed_model_keeps_its_own_words_without_the_wrapping(conn, tmp_path, project):
    from amelia_academy.llm import LLMError
    sample = approved(conn, tmp_path, project)
    with pytest.raises(ValueError, match="could not write this: model 'x' not found"):
        curation.draft(conn, sample, Says(fails=LLMError('ollama returned 404: {"error":"model \'x\' not found"}')))


@pytest.mark.parametrize('text,why', [('The threshold is 73 dB.', 'numbers'), ('The provided information settles it.', 'material')])
def test_an_explanation_that_breaks_the_rules_is_left_out(conn, tmp_path, project, text, why):
    sample = approved(conn, tmp_path, project)
    with pytest.raises(ValueError, match=why):
        curation.draft(conn, sample, Says(text))
    assert curation.state(conn, sample)['rationale'] is None


def test_a_good_explanation_waits_for_a_person(conn, tmp_path, project):
    sample = approved(conn, tmp_path, project)
    state = curation.draft(conn, sample, Says('The evidence establishes the threshold.'))
    assert state['rationale']['status'] == 'proposed' and not state['rationale']['usable']
