"""Approved-pair training variants and their deterministic review state."""
import hashlib
import json
import re

from . import console, db, projects, qa, runs, training

COUNTS = {'known': 5, 'not_known': 3, 'false_premise': 3}
SOURCE_WORDS = re.compile(r'\b(the reference|the passage|the text|mentioned in|according to|the source|the document)\b', re.I)
PROCESS_TALK = re.compile(r'\b(?:original statement|corrected information|false premise|wrong detail|the source pair|training variant|prepared question)\b', re.I)
REFUSAL = re.compile(r"\b(i don't know|i do not know|cannot answer|can't answer)\b", re.I)
TOKEN = re.compile(r"\b[\w]+\b", re.UNICODE)


def counts_for_amount(amount):
    scale = {'quick': .5, 'normal': 1, 'everything': 2}.get(amount or 'normal', 1)
    return {kind: max(1, round(count * scale)) for kind, count in COUNTS.items()}


def version(pair):
    raw = '\0'.join(str(pair.get(k) or '') for k in ('question', 'answer', 'quote', 'origin'))
    return hashlib.sha256(raw.encode()).hexdigest()


def _tokens(text):
    return {x.casefold() for x in TOKEN.findall(text)}


def _similar(a, b):
    aa, bb = _tokens(a), _tokens(b)
    return len(aa & bb) / max(1, len(aa | bb))


def _tests(conn, project_id):
    # Questions explicitly prepared or entered in Compare are held out from generated training prompts.
    return [r['question'] for r in db.rows(conn, "SELECT question FROM train_comparisons c JOIN train_runs r ON r.id=c.run_id WHERE r.project_id=? AND c.set_name IN ('held_out','manual','general')", (project_id,))]


def filter_variant(row, pair, questions, test_questions):
    q, a, quote = row['question'].strip(), row['answer'].strip(), pair.get('quote', '')
    if not q or not a: return 'empty question or answer'
    if SOURCE_WORDS.search(a): return 'talked about the source'
    if PROCESS_TALK.search(q) or PROCESS_TALK.search(a): return 'talked about the process'
    kind = row['kind']
    if kind in ('known', 'false_premise'):
        extra = (_tokens(a) - _tokens(quote) - _tokens(q))
        if kind == 'false_premise':
            extra -= _tokens(row.get('false_claim') or '')
        # Numbers and technical tokens are the dangerous unsupported additions.
        invented = [t for t in extra if any(c.isdigit() for c in t) or (len(t) > 8 and any(c.isupper() for c in t))]
        if invented: return 'used a number or technical term that is not in the file'
        for sentence in qa.rules.sentences(a):
            sentence_extra = _tokens(sentence) - _tokens(quote) - _tokens(q)
            unsupported = [t for t in sentence_extra if any(c.isdigit() for c in t) or (len(t) > 8 and any(c.isupper() for c in t))]
            if unsupported: return 'a sentence adds a number or technical term not in the quote'
    if kind == 'known' and REFUSAL.search(a): return 'refused to answer a known fact'
    if kind == 'not_known' and a.strip() != 'NOT_FOUND' and not REFUSAL.search(a):
        return 'the answer was in a nearby file passage'
    if kind == 'false_premise' and re.match(r'\W*yes\b', a, re.I): return 'agreed with the wrong detail'
    if kind == 'false_premise':
        wrong = _tokens(pair.get('false_claim') or '')
        corrected = _tokens(a) & (_tokens(quote) | _tokens(pair.get('answer', '')))
        negates_wrong = bool(wrong & _tokens(a)) and bool(re.search(r"\b(?:not|no|never|n't|isn't|wasn't|doesn't|cannot|can't|untrue|false)\b", a, re.I))
        if wrong and not corrected and not negates_wrong: return 'did not correct the wrong detail'
    if any(qa.questions_similar(q, old) for old in [*questions, pair['question']]): return 'repeated a question'
    if any(_similar(q, test) >= .5 for test in test_questions): return 'too close to a test question'
    return ''


def list_variants(conn, project_id, question_model=None):
    project = projects.get(conn, project_id)
    question_model = question_model or project.get('prepare_question_model') or None
    pairs = {p['id']: p for p in qa.list_samples(conn, project_id)}
    rows = db.rows(conn, 'SELECT * FROM training_variants WHERE project_id=? ORDER BY created_at,id', (project_id,))
    limits = {key: max(1, round(value * {'few': .5, 'normal': 1, 'many': 2}.get(project.get('prepare_count') or 'normal', 1))) for key, value in COUNTS.items()}
    used = {}
    for row in rows:
        pair = pairs.get(row['pair_id'])
        kind = {'file': 'known', 'refusal': 'not_known'}.get(pair.get('origin') if pair else '', pair.get('origin') if pair else '')
        row['stale'] = (not pair or pair['status'] != 'approved' or version(pair) != row['pair_version']
                        or (row.get('answer_model') and row['answer_model'] != (project.get('train_model') or training.CATALOG[0]['id'])))
        if question_model and row.get('question_model') and row['question_model'] != question_model:
            row['stale'] = True
        bucket = (row['pair_id'], row['kind'])
        if not row['stale']:
            used[bucket] = used.get(bucket, 0) + 1
            row['excess'] = used[bucket] > limits.get(kind, 0)
        else:
            row['excess'] = False
    return rows


def summary(conn, project_id):
    rows = list_variants(conn, project_id)
    counts = {}
    dropped_reasons = {}
    for row in rows:
        bucket = counts.setdefault(row['kind'], {'kept': 0, 'dropped': 0, 'stale': 0})
        if row['stale']: bucket['stale'] += 1
        elif row['status'] == 'kept' and not row.get('excess'): bucket['kept'] += 1
        else:
            bucket['dropped'] += 1
            reason = row.get('reason') or ('over the selected examples per pair' if row.get('excess') else 'removed by you')
            dropped_reasons[reason] = dropped_reasons.get(reason, 0) + 1
    prepared = {r['pair_id'] for r in rows}
    waiting = [p for p in qa.list_samples(conn, project_id, status='approved')
               if p['origin'] in ('file', 'refusal', 'false_premise') and p['id'] not in prepared]
    approved = qa.list_samples(conn, project_id, status='approved')
    eligible = [p for p in approved if p['origin'] in ('file', 'refusal', 'false_premise')]
    return {'variants': rows, 'counts': counts, 'stale_pairs': len({r['pair_id'] for r in rows if r['stale']}),
            'new_pairs': len(waiting), 'approved_pairs': len(approved), 'eligible_pairs': len(eligible),
            'excluded_pairs': len(approved) - len(eligible), 'dropped_reasons': dropped_reasons}


def drop(conn, project_id, variant_id):
    changed = conn.execute("UPDATE training_variants SET status='dropped_by_person',reason='Removed by you' WHERE id=? AND project_id=? AND status='kept'", (variant_id, project_id)).rowcount
    if not changed: raise ValueError('This example is no longer available.')
    conn.commit()
    return summary(conn, project_id)


def undo_drop(conn, project_id, variant_id):
    changed = conn.execute("UPDATE training_variants SET status='kept',reason='' WHERE id=? AND project_id=? AND status='dropped_by_person'", (variant_id, project_id)).rowcount
    if not changed: raise ValueError('There is no removal to undo.')
    conn.commit()
    return summary(conn, project_id)


def generate(conn, project_id, llm, root, url, connection, *, train_model=None, prepare_count=None):
    """Creates questions through the selected project model; MLX answers are delegated to the isolated worker."""
    project = projects.get(conn, project_id)
    train_model = train_model or project.get('train_model') or training.CATALOG[0]['id']
    if train_model not in {m['id'] for m in training.CATALOG}: raise ValueError('Choose a supported training model from Train.')
    prepare_count = prepare_count or project.get('prepare_count') or 'normal'
    if prepare_count not in ('few', 'normal', 'many'): raise ValueError('Choose Few, Normal or Many examples per pair.')
    scale = {'few': .5, 'normal': 1, 'many': 2}[prepare_count]
    counts_for = counts_for_amount(project.get('last_read_amount'))
    question_model = getattr(llm, 'model', '')
    conn.execute('UPDATE projects SET train_model=?,prepare_count=?,prepare_question_model=?,updated_at=? WHERE id=?',
                 (train_model, prepare_count, question_model, db.now(), project_id)); conn.commit()
    samples = [p for p in qa.list_samples(conn, project_id, status='approved')
               if p['origin'] in ('file', 'refusal', 'false_premise')]
    if not samples: raise ValueError('Approve pairs first.')
    existing = [r for r in list_variants(conn, project_id, getattr(llm, 'model', '')) if not r['stale']]
    counts = {p['id']: 0 for p in samples}
    for row in existing: counts[row['pair_id']] = counts.get(row['pair_id'], 0) + 1
    current = {p['id'] for p in samples if counts.get(p['id'], 0) >= counts_for[{'file':'known','refusal':'not_known'}.get(p['origin'], p['origin'])]}
    pending = [p for p in samples if p['id'] not in current]
    if not pending: return summary(conn, project_id)
    tests = _tests(conn, project_id)
    from . import agents
    prepared = []
    kept = dropped = 0
    label = {'known': 'known', 'not_known': 'not known', 'false_premise': 'false premise'}
    tally = lambda: f" · {kept} kept, {dropped} dropped so far" if kept or dropped else ''
    for number, pair in enumerate(pending, 1):
        runs.check()
        runs.progress(number - 1, len(pending))
        kind = {'file':'known', 'refusal':'not_known'}.get(pair['origin'], pair['origin'])
        schema = {'type':'object','properties':{'questions':{'type':'array','items':{'type':'object','properties':{'question':{'type':'string'},'false_claim':{'type':'string'}},'required':['question']}}},'required':['questions']}
        prompt = agents.prompt('question_varier', 'wrong_detail' if kind == 'false_premise' else 'same_fact', count=counts_for[kind],
                               question=pair['question'], answer=pair['answer'], false_claim=pair.get('false_claim') or '', quote=pair.get('quote') or '')
        runs.say(f"Pair {number} of {len(pending)}: writing new questions{tally()}")
        with console.acting('question_varier'):
            raw = llm.complete_json(prompt, schema, temperature=.5)
        prepared = []
        for item in raw.get('questions', [])[:counts_for[kind]]:
            if isinstance(item, str): item = {'question': item}
            prepared.append({'id': pair['id'], 'kind': kind, 'question': item.get('question',''), 'false_claim': item.get('false_claim',''), 'answer': '', 'quote': pair.get('quote','')})
        if kind == 'not_known':
            from . import kb
            chunks = db.rows(conn, "SELECT c.text FROM source_chunks c JOIN sources s ON s.id=c.source_id WHERE s.project_id=? ORDER BY s.created_at,s.id,c.idx", (project_id,))
            for item in prepared:
                item['quote'] = '\n\n'.join(kb.nearest_passages(item['question'], chunks, top=4)[:4])
        # One pair per subprocess: a completed pair is durable and Continue skips it.
        if kind == 'not_known':
            # The small training model cannot judge reliably whether the passages answer; the project model checks it.
            # A question the passages do not answer gets the pair's approved refusal below.
            runs.say(f"Pair {number} of {len(pending)} ({label[kind]}): checking the file does not answer them{tally()}")
            check = {'type':'object','properties':{'answered':{'type':'boolean'}},'required':['answered']}
            for item in prepared:
                with console.acting('answer_checker'):
                    found = llm.complete_json(agents.prompt('answer_checker', 'nearby', question=item['question'], passages=item['quote']), check, temperature=0)
                item['answer'] = 'FOUND' if found.get('answered') else 'NOT_FOUND'
            answers = {pair['id']: prepared}
        else:
            runs.say(f"Pair {number} of {len(pending)} ({label[kind]}): writing answers{tally()}")
            answers = training.answer_variants(root, prepared, url, connection, train_model=train_model)
        conn = connection()
        now = db.now()
        rows = answers.get(pair['id'], [])
        seen = []
        for item in rows:
            row = {'question': item['question'], 'answer': item['answer'], 'kind': item['kind']}
            if row['kind'] == 'not_known' and row['answer'].strip() == 'NOT_FOUND':
                # The approved refusal of the source pair names the same subject, in the project language.
                row['answer'] = pair.get('answer') or ''
            reason = filter_variant({**row, 'false_claim': item.get('false_claim','')}, pair, seen, tests)
            if not reason: seen.append(row['question'])
            if reason: dropped += 1
            else: kept += 1
            conn.execute('INSERT INTO training_variants(id,project_id,pair_id,pair_version,kind,question,answer,status,reason,question_model,answer_model,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                (db.new_id('var'), project_id, pair['id'], version(pair), item['kind'], row['question'], row['answer'], 'dropped_by_rule' if reason else 'kept', reason, getattr(llm, 'model', ''), train_model, now))
        conn.commit()
    return summary(conn, project_id)
