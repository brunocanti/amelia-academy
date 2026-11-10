import json
from pathlib import Path

from amelia_academy import db, prepare
from amelia_academy import datasets, qa
from test_qa import Stub, conn, generate, pair, project, upload  # noqa: F401


def test_prepare_reformulation_count_follows_read_amount():
    quick = prepare.counts_for_amount('quick')
    normal = prepare.counts_for_amount('normal')
    everything = prepare.counts_for_amount('everything')
    assert quick['known'] < normal['known'] < everything['known']
    assert quick['not_known'] < normal['not_known'] < everything['not_known']


class VariantStub:
    model = 'fake'
    def complete_json(self, prompt, schema, temperature=0):
        if "DIFFERENT wrong detail" in prompt:
            return {'questions': [{'question': 'How much did it weigh?', 'false_claim': 'It weighed 90 tons.'}]}
        return {'questions': [{'question': 'What was its mass?'}]}


def test_variant_version_tracks_pair_content():
    pair = {'question':'What?', 'answer':'This.', 'quote':'Text.', 'origin':'file'}
    original = prepare.version(pair)
    pair['answer'] = 'Changed.'
    assert prepare.version(pair) != original


def test_variant_rules_filter_source_refusal_duplicates_and_test_overlap():
    pair = {'question':'What is the speed?', 'answer':'The speed is 12 m/s.', 'quote':'The speed is 12 m/s.', 'false_claim':'', 'origin':'file'}
    base = {'kind':'known'}
    assert prepare.filter_variant({**base,'question':'What is the speed?','answer':'According to the passage, it is 12 m/s.'}, pair, [], []) == 'talked about the source'
    assert prepare.filter_variant({**base,'question':'What is the speed?','answer':"I don't know."}, pair, [], []) == 'refused to answer a known fact'
    assert prepare.filter_variant({**base,'question':'What is the speed?','answer':'It is 12 m/s.'}, pair, ['What is the speed?'], []) == 'repeated a question'
    assert prepare.filter_variant({**base,'question':'What speed does it reach?','answer':'It is 12 m/s.'}, pair, [], ['What speed does it reach?']) == 'too close to a test question'


def test_not_known_keeps_not_found_as_subject_specific_refusal_and_drops_facts(conn, tmp_path, project, monkeypatch):
    quote = 'The instrument uses a blue key.'
    source = upload(conn, tmp_path, project, name='refusal.txt', content=quote + ' This description includes enough context for the source passage to be indexed for retrieval.')
    generate(conn, Stub(pairs=[pair(question='What does the device use?', answer='I do not know about the device.', quote=quote)]), source)
    sample = qa.list_samples(conn, project['id'])[0]
    conn.execute("UPDATE qa_samples SET origin='refusal', answer='I do not know about the device.' WHERE id=?", (sample['id'],)); conn.commit()
    qa.decide(conn, sample['id'], 'approve')
    class TwoQuestions(VariantStub):
        def complete_json(self, prompt, schema, temperature=0):
            if 'answered' in schema['properties']:
                return {'answered': 'Which color key?' in prompt}
            return {'questions': [{'question': 'What is the device?',}, {'question': 'Which color key?'}]}
    def worker(root, rows, url, connection, **kwargs):
        raise AssertionError('not known questions must not go to the training model')
    monkeypatch.setattr('amelia_academy.training.answer_variants', worker)
    prepare.generate(conn, project['id'], TwoQuestions(), tmp_path, '', lambda: conn)
    saved = db.rows(conn, 'SELECT question,answer,status,reason FROM training_variants WHERE pair_id=? ORDER BY rowid', (sample['id'],))
    assert saved[0]['status'] == 'kept'
    assert 'device' in saved[0]['answer'].lower()
    assert prepare.REFUSAL.search(saved[0]['answer'])
    assert saved[1]['reason'] == 'the answer was in a nearby file passage'


def test_false_premise_answer_that_agrees_is_dropped():
    pair = {'question':'How tall is Saltreach?', 'answer':'Saltreach is 18 meters tall.', 'quote':'Saltreach is 18 meters tall, finished in 1998.', 'false_claim':''}
    row = {'kind':'false_premise', 'question':'Was Saltreach finished in 2005?', 'answer':'Yes, Saltreach was finished in 2005.', 'false_claim':'finished in 2005'}
    assert prepare.filter_variant(row, pair, [], []) == 'agreed with the wrong detail'


def test_false_claim_tokens_are_exempt_from_unsupported_number_check():
    pair = {'question':'How tall is Saltreach?', 'answer':'Saltreach is 18 meters tall.', 'quote':'Saltreach is 18 meters tall.', 'false_claim':'Saltreach is 30 meters tall.'}
    row = {'kind':'false_premise', 'question':'Is Saltreach 30 meters tall?', 'answer':'No, Saltreach is not 30 meters tall; it is 18 meters tall.', 'false_claim':'Saltreach is 30 meters tall.'}
    assert prepare.filter_variant(row, pair, [], []) == ''


def test_prepare_accepts_paraphrased_denial_and_rejects_process_language():
    pair = {'question':'How tall is Saltreach?', 'answer':'Saltreach is 18 meters tall.', 'quote':'Saltreach is 18 meters tall.', 'false_claim':'Saltreach is 30 meters tall.'}
    denied = {'kind':'false_premise', 'question':'Is Saltreach 30 meters tall?', 'answer':'No, its height is eighteen metres.', 'false_claim':pair['false_claim']}
    assert prepare.filter_variant(denied, pair, [], []) == ''
    process = {'kind':'known', 'question':'What is its height?', 'answer':'The corrected information says 18 meters tall.'}
    assert prepare.filter_variant(process, pair, [], []) == 'talked about the process'


def test_variants_table_is_created_by_database_migration(tmp_path):
    conn = db.connect(tmp_path / 'migration.sqlite3')
    columns = {row['name'] for row in db.rows(conn, 'PRAGMA table_info(training_variants)')}
    assert {'pair_version','kind','question','answer','status','reason','question_model','answer_model'} <= columns
    project_columns = {row['name'] for row in db.rows(conn, 'PRAGMA table_info(projects)')}
    assert {'train_model', 'prepare_count'} <= project_columns
    project = __import__('amelia_academy.projects', fromlist=['get']).get(conn, db.row(conn, 'SELECT id FROM projects')['id']) if db.row(conn, 'SELECT id FROM projects') else None
    assert project is None  # the empty migration has no project rows
    conn.close()


def test_prepare_count_profiles_scale_prompt_and_store_answer_model(conn, tmp_path, project, monkeypatch):
    from amelia_academy import training
    quote = 'The turbine produces 120 units of power during operation.'
    source = upload(conn, tmp_path, project, name='profiles.txt', content=quote + ' This passage contains enough explanatory text to be indexed and reviewed independently by the people who maintain this technical dataset.')
    generate(conn, Stub(pairs=[pair(question='How much power does the turbine produce?', answer=quote, quote=quote)]), source)
    sample = qa.list_samples(conn, project['id'])[0]
    qa.decide(conn, sample['id'], 'approve')
    prompts = []
    class Capture(VariantStub):
        def complete_json(self, prompt, schema, temperature=0):
            prompts.append(prompt)
            return {'questions': [{'question': f'Alternative question number {i}?'} for i in range(10)]}
    calls = []
    def worker(root, rows, url, connection, *, train_model=None):
        calls.append(train_model)
        return {sample['id']: [{**row, 'answer': quote} for row in rows]}
    monkeypatch.setattr(training, 'answer_variants', worker)
    selected = training.CATALOG[0]['id']
    prepare.generate(conn, project['id'], Capture(), tmp_path, '', lambda: conn, train_model=selected, prepare_count='few')
    assert '2' in prompts[0]  # half of the five known questions
    assert calls == [selected]
    saved = db.rows(conn, 'SELECT answer_model,question_model FROM training_variants WHERE pair_id=?', (sample['id'],))
    assert saved and all(row['answer_model'] == selected and row['question_model'] == 'fake' for row in saved)


def test_export_keeps_derived_variant_with_its_pair_split(conn, tmp_path, project):
    quote = 'A blue whale can weigh 150 tons.'
    content = quote + ' This observation describes a basic process found in the natural world and can be checked independently by researchers studying ocean mammals.'
    source = upload(conn, tmp_path, project, name='variant.txt', content=content)
    generate(conn, Stub(pairs=[pair(question='How heavy can a blue whale be?', answer=quote, quote=quote)]), source)
    sample = qa.list_samples(conn, project['id'])[0]
    qa.decide(conn, sample['id'], 'approve')
    sample = qa.get_sample(conn, sample['id'])
    conn.execute('INSERT INTO training_variants(id,project_id,pair_id,pair_version,kind,question,answer,status,created_at) VALUES (?,?,?,?,?,?,?,?,?)',
        ('var_test', project['id'], sample['id'], prepare.version(sample), 'file', 'What is the maximum whale mass?', '150 tons.', 'kept', db.now()))
    conn.commit()
    result = datasets.export_dataset(conn, tmp_path / 'datasets', 'prepared', project['id'], outputs=['finetune'])
    records = [__import__('json').loads(line) for line in (tmp_path / 'datasets' / (result['name'] + '-' + result['id']) / 'samples.jsonl').read_text().splitlines()]
    pair_row = next(row for row in records if row['sample_id'] != 'var_test')
    variant = next(row for row in records if row.get('derived_from'))
    assert variant['derived_from'] == pair_row['sample_id']
    assert result['sample_count'] == 2
    manifest = __import__('json').loads((tmp_path / 'datasets' / (result['name'] + '-' + result['id']) / 'training-manifest.json').read_text())
    splits = {entry['sample_id']: entry['split'] for entry in manifest['entries']}
    assert splits[variant['sample_id']] == splits[pair_row['sample_id']]


def test_files_curate_prepare_and_training_dataset_totals_reconcile_without_models(conn, tmp_path, project, monkeypatch):
    from amelia_academy import sources, training

    quotes = [f'The blue sensor {i} records pressure at {12 + i} kPa.' for i in range(5)]
    source_files = []
    original_pairs = []
    for i, quote in enumerate(quotes):
        content = quote + ' This measured value is part of a documented laboratory procedure and is checked by the project team.'
        source = upload(conn, tmp_path, project, name=f'reconciliation-{i}.txt', content=content)
        source_files.append(source)
        generate(conn, Stub(pairs=[pair(question=f'What does sensor {i} record?', answer=quote, quote=quote)]), source)
        original_pairs.extend(qa.list_samples(conn, project['id'], source_id=source['id']))
    for sample in original_pairs:
        qa.decide(conn, sample['id'], 'approve')
    conn.execute("UPDATE qa_samples SET origin='neighbour' WHERE id=?", (original_pairs[-1]['id'],))
    conn.commit()

    class Questions:
        model = 'fake-question-model'
        number = 0
        def complete_json(self, prompt, schema, temperature=0):
            self.number += 1
            return {'questions': [{'question': f'What exact pressure does sensor record number {self.number} report?'}]}

    def fake_answers(root, rows, url, connection, **kwargs):
        return {row['id']: [{**row, 'answer': row['quote']}] for row in rows}

    monkeypatch.setattr(training, 'answer_variants', fake_answers)
    files_total = sum(sources.extraction_progress(conn, source['id'])['kept'] for source in source_files)
    curate_total = len(qa.list_samples(conn, project['id']))
    prepared = prepare.generate(conn, project['id'], Questions(), tmp_path, '', lambda: conn,
                                prepare_count='few')
    kept_variants = sum(bucket['kept'] for bucket in prepared['counts'].values())
    assert files_total == 4 and curate_total == len(original_pairs) == 5
    assert prepared['eligible_pairs'] == 4 and prepared['excluded_pairs'] == 1
    assert kept_variants == 4

    exported = datasets.export_dataset(conn, tmp_path / 'datasets', 'reconciled', project['id'], outputs=['finetune'])
    folder = Path(exported['folder'])
    manifest = json.loads((folder / 'training-manifest.json').read_text())
    canonical_manifest = json.loads((folder / 'manifest.json').read_text())
    canonical = [json.loads(line) for line in (folder / 'samples.jsonl').read_text().splitlines()]
    split_counts = canonical_manifest['statistics']['by_split']
    assert len(canonical) == len(manifest['entries']) == exported['sample_count'] == 9
    assert len([row for row in canonical if row.get('derived_from')]) == kept_variants
    assert len([row for row in canonical if not row.get('derived_from')]) == curate_total
    assert sum(split_counts.values()) == len(canonical)
    for filename, split in (('train.jsonl', 'train'), ('valid.jsonl', 'validation'), ('test.jsonl', 'test')):
        assert len((folder / filename).read_text().splitlines()) == manifest['files'][filename]['lines'] == split_counts[split]


def test_not_known_generation_passes_four_nearest_project_excerpts_to_worker(conn, tmp_path, project, monkeypatch):
    source = upload(conn, tmp_path, project, name='nearby.txt', content='Whales live in the ocean. ' * 100)
    quote = 'Whales live in the ocean.'
    generate(conn, Stub(pairs=[pair(question='Where do whales live?', answer='Whales live in the ocean.', quote=quote)]), source)
    sample = qa.list_samples(conn, project['id'])[0]
    conn.execute("UPDATE qa_samples SET origin='refusal', answer='I do not know about the protocol.' WHERE id=?", (sample['id'],)); conn.commit()
    qa.decide(conn, sample['id'], 'approve')
    captured = []
    excerpts = ['near one', 'near two', 'near three', 'near four', 'extra']
    monkeypatch.setattr('amelia_academy.kb.nearest_passages', lambda question, chunks, top: excerpts)
    class Checker(VariantStub):
        def complete_json(self, prompt, schema, temperature=0):
            if 'answered' in schema['properties']:
                captured.append(prompt)
                return {'answered': False}
            return super().complete_json(prompt, schema, temperature)
    prepare.generate(conn, project['id'], Checker(), tmp_path, '', lambda: conn)
    assert captured[0].split('Passages:\n', 1)[1] == '\n\n'.join(excerpts[:4])
    stored = db.rows(conn, 'SELECT reason FROM training_variants WHERE pair_id=?', (sample['id'],))
    assert stored[0]['reason'] == ''


def test_false_premise_claim_reaches_worker_and_filter(conn, tmp_path, project, monkeypatch):
    quote = 'A blue whale can weigh 150 tons.'
    source = upload(conn, tmp_path, project, name='false.txt', content=quote + ' This observation describes marine life in a well understood natural environment and is independently checked by researchers studying whales and other large mammals.')
    generate(conn, Stub(pairs=[pair(question='How heavy can it be?', answer='It can weigh 150 tons.', quote=quote)]), source)
    sample = qa.list_samples(conn, project['id'])[0]
    qa.decide(conn, sample['id'], 'approve')
    sample = qa.get_sample(conn, sample['id'])
    conn.execute("UPDATE qa_samples SET origin='false_premise', false_claim='It weighs 90 tons.' WHERE id=?", (sample['id'],)); conn.commit()
    received = []
    def worker(root, rows, url, connection, **kwargs):
        received.extend(rows)
        return {sample['id']: [{**rows[0], 'answer':'It weighs 150 tons.', 'false_claim':rows[0]['false_claim']}]}
    monkeypatch.setattr('amelia_academy.training.answer_variants', worker)
    prepare.generate(conn, project['id'], VariantStub(), tmp_path, '', lambda: conn)
    assert received[0]['false_claim'] == 'It weighed 90 tons.'
    saved = db.rows(conn, 'SELECT reason FROM training_variants WHERE pair_id=?', (sample['id'],))[0]
    assert saved['reason'] == ''


def test_answer_variants_runs_bounded_batches_of_eight_and_returns_all(tmp_path, monkeypatch):
    from amelia_academy import training
    monkeypatch.setattr(training, 'model_info', lambda model: {'cached':True, 'base_path':'/model'})
    monkeypatch.setattr(training.gpu, 'reserve', lambda lease: None)
    monkeypatch.setattr(training.gpu, 'exclusive', lambda lease, url: __import__('contextlib').nullcontext())
    monkeypatch.setattr(training.gpu, 'release', lambda lease: None)
    calls = []
    class Result:
        returncode = 0
        stderr = ''
        def __init__(self, config): self.stdout = json.dumps({'type':'result','payload':{'answers': {r['id']:[{**r,'answer':'ok'}] for r in config['rows']}}})
    def run(command, **kwargs):
        config = json.loads(Path(command[3]).read_text())
        calls.append((len(config['rows']), kwargs['timeout']))
        return Result(config)
    monkeypatch.setattr(training.subprocess, 'run', run)
    rows = [{'id':str(i), 'kind':'known', 'question':'Q'} for i in range(17)]
    answers = training.answer_variants(tmp_path, rows, '', lambda: None, train_model=training.CATALOG[0]['id'])
    assert [size for size, _ in calls] == [8, 8, 1]
    assert all(timeout < 3600 for _, timeout in calls)
    assert len(answers) == 17
