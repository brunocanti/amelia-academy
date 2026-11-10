"""Versioned editorial checks and rationales. Confidence is a projection, never an LLM score."""
import hashlib
import json
from . import db, sources, workshop

RULE = 'curation-1'
CHECKS = {
    'file': ('evidence',), 'true_premise': ('evidence',),
    'false_premise': ('correction',), 'refusal': ('scope',),
    'neighbour': ('boundary', 'general_answer'), 'behavior': ('behavior',),
    'connection': ('evidence', 'combination'), 'complex': ('positions',),
}
LABELS = {'evidence': 'The evidence supports this answer and its conditions.',
          'correction': 'The evidence rules out the wrong claim and supports the correction.',
          'scope': 'I checked that this detail is not established in these files.',
          'boundary': 'The answer separates this subject from the neighbouring subject.',
          'general_answer': 'The general answer is correct.',
          'behavior': 'The answer follows this card and the project identity.',
          'combination': 'These facts together support the answer.',
          'positions': 'The answer fairly describes both positions and their limits.'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def basis(conn, sample):
    """Hash only meaning-bearing inputs; moving theme or toggling approval does not rewrite evidence."""
    project = db.row(conn, 'SELECT identity FROM projects WHERE id = ?', (sample['project_id'],))
    parents = db.rows(conn, 'SELECT q.* FROM qa_sample_links l JOIN qa_samples q ON q.id=l.based_on_id WHERE l.sample_id=? ORDER BY q.id', (sample['id'],))
    def content(s):
        chunk = db.row(conn, 'SELECT text, hash FROM source_chunks WHERE id=?', (s['chunk_id'],)) if s['chunk_id'] else None
        return {k: s.get(k) for k in ('id', 'revision', 'question', 'answer', 'origin', 'quote', 'false_claim', 'pattern_id')} | {'chunk': chunk}
    all_parents = {p['id']: p for p in parents}
    pending = list(parents)
    while pending:
        parent = pending.pop()
        for row in db.rows(conn, 'SELECT q.* FROM qa_sample_links l JOIN qa_samples q ON q.id=l.based_on_id WHERE l.sample_id=?', (parent['id'],)):
            if row['id'] != sample['id'] and row['id'] not in all_parents:
                all_parents[row['id']] = row
                pending.append(row)
    data = {'sample': content(sample), 'parents': [content(all_parents[k]) for k in sorted(all_parents)]}

    if sample['origin'] == 'refusal':
        data['files'] = db.rows(conn, 'SELECT id,sha256,status FROM sources WHERE project_id=? ORDER BY id', (sample['project_id'],))
        data['corpus'] = db.rows(conn, 'SELECT c.id,c.hash FROM source_chunks c JOIN sources s ON s.id=c.source_id WHERE s.project_id=? ORDER BY c.id', (sample['project_id'],))
    if sample['origin'] == 'behavior':
        data['card'] = db.row(conn, 'SELECT * FROM patterns WHERE id=?', (sample['pattern_id'],))
        data['identity'] = project['identity']
    return data


def snapshot(conn, sample):
    return digest(basis(conn, sample))


def event(conn, sample, action, payload=None):
    eid = db.new_id('cev')
    conn.execute('INSERT INTO curation_events(id,project_id,sample_id,input_hash,action,payload,actor,created_at) VALUES (?,?,?,?,?,?,?,?)',
                 (eid, sample['project_id'], sample['id'], snapshot(conn, sample), action,
                  json.dumps({'value': payload or {}, 'basis': basis(conn, sample)}, ensure_ascii=False), 'local_operator', db.now()))
    return eid


def state(conn, sample):
    stamp = snapshot(conn, sample)
    required = CHECKS.get(sample['origin'], ('evidence',))
    checks = {}
    for row in db.rows(conn, 'SELECT action,payload FROM curation_events WHERE sample_id=? AND input_hash=? ORDER BY rowid', (sample['id'], stamp)):
        if row['action'] == 'checks':
            checks = json.loads(row['payload'])['value']
    reasons = []
    if sample['status'] != 'approved': reasons.append('This pair is not approved.')
    if sample.get('review_note'): reasons.append('This pair has a review warning.')
    conflicts = db.rows(conn, "SELECT first_id,second_id FROM qa_conflicts WHERE project_id=? AND status='open' AND (first_id=? OR second_id=?)", (sample['project_id'], sample['id'], sample['id']))
    for conflict in conflicts:
        ids = [conflict['first_id'], conflict['second_id']]
        statuses = [db.row(conn, 'SELECT status FROM qa_samples WHERE id=?', (i,)) for i in ids if i]
        if not any(s and s['status'] == 'rejected' for s in statuses):
            reasons.append('A conflict still needs your choice.'); break
    if sample['origin'] not in ('refusal', 'neighbour', 'behavior'):
        if sample.get('chunk_id'):
            if not sources.quote_holds(conn, sample['chunk_id'], sample['quote']): reasons.append('The evidence has changed or is missing.')
        elif sample['origin'] not in ('connection', 'complex'):
            reasons.append('The evidence is missing.')
    if sample['origin'] == 'behavior':
        from . import qa
        reasons.extend(qa.behavior_reasons(conn, sample, sample['question'], sample['answer']))
    if sample['origin'] in ('connection', 'complex') and not sample.get('based_on'):
        reasons.append('The supporting positions are missing.')
    pending = [(p, {sample['id']}) for p in sample.get('based_on', [])]
    seen = set()
    while pending:
        parent, ancestors = pending.pop()
        if parent['id'] in ancestors:
            reasons.append('The supporting pairs contain a cycle.'); continue
        if parent['id'] in seen: continue
        seen.add(parent['id'])
        # Historical positions of a tension are deliberately set aside, not endorsed as facts.
        if sample['origin'] != 'complex':
            if parent['status'] != 'approved' or parent.get('review_note'):
                reasons.append('A supporting pair needs review.')
            if parent.get('chunk_id') and parent.get('quote') and not sources.quote_holds(conn, parent['chunk_id'], parent['quote']):
                reasons.append('Supporting evidence has changed.')
            for conflict in db.rows(conn, "SELECT first_id,second_id FROM qa_conflicts WHERE status='open' AND (first_id=? OR second_id=?)", (parent['id'], parent['id'])):
                statuses = [db.row(conn, 'SELECT status FROM qa_samples WHERE id=?', (i,)) for i in (conflict['first_id'], conflict['second_id']) if i]
                if not any(x and x['status'] == 'rejected' for x in statuses): reasons.append('A supporting pair has an open conflict.')
        pending.extend((p, ancestors | {parent['id']}) for p in db.rows(conn, 'SELECT q.* FROM qa_sample_links l JOIN qa_samples q ON q.id=l.based_on_id WHERE l.sample_id=?', (parent['id'],)))

    level = 'low' if reasons else 'high' if all(checks.get(k) for k in required) else 'medium'
    if not reasons:
        reasons.append('The required checks are confirmed.' if level == 'high' else 'Approved; the required checks are not all confirmed.')
    rationale = db.row(conn, 'SELECT * FROM curation_rationales WHERE sample_id=? ORDER BY rowid DESC LIMIT 1', (sample['id'],))
    if rationale:
        rationale['current'] = rationale['input_hash'] == stamp
        rationale['usable'] = rationale['current'] and rationale['status'] == 'approved' and level != 'low'
    return {'level': level, 'rule_version': RULE, 'input_hash': stamp, 'reasons': reasons,
            'checks': checks, 'required': [{'key': k, 'label': LABELS[k]} for k in required], 'rationale': rationale}


def check(conn, sample, input_hash, checks):
    if snapshot(conn, sample) != input_hash: raise workshop.Conflict('This pair changed. Read it again before confirming.')
    allowed = CHECKS.get(sample['origin'], ('evidence',))
    if set(checks) - set(allowed): raise ValueError('Unknown check for this kind of pair.')
    if sample['status'] != 'approved': raise ValueError('Approve this pair before confirming its checks.')
    event(conn, sample, 'checks', checks)
    conn.commit()
    return state(conn, sample)


def write_rationale(conn, sample, input_hash, text, approve=False):
    if snapshot(conn, sample) != input_hash: raise workshop.Conflict('This pair changed. Read it again before saving.')
    text = text.strip()
    if not text or len(text) > 4000: raise ValueError('Write a short explanation, up to 4000 characters.')
    if approve and state(conn, sample)['level'] == 'low': raise ValueError('Resolve the review warnings before approving this explanation.')
    rid = db.new_id('rat')
    conn.execute('INSERT INTO curation_rationales(id,sample_id,input_hash,text,status,created_at) VALUES (?,?,?,?,?,?)',
                 (rid, sample['id'], input_hash, text, 'approved' if approve else 'proposed', db.now()))
    event(conn, sample, 'rationale', {'id': rid, 'approved': approve})
    conn.commit()
    return state(conn, sample)


def reset_rationale(conn, sample, rid):
    latest = db.row(conn, 'SELECT * FROM curation_rationales WHERE sample_id=? ORDER BY rowid DESC LIMIT 1', (sample['id'],))
    if not latest or latest['id'] != rid: raise workshop.Conflict('The explanation changed. Read it again.')
    conn.execute("INSERT INTO curation_rationales(id,sample_id,input_hash,text,status,created_at) VALUES (?,?,?,?, 'proposed',?)",
                 (db.new_id('rat'), sample['id'], latest['input_hash'], latest['text'], db.now()))
    event(conn, sample, 'rationale_reset', {'id': rid})
    conn.commit()
    return state(conn, sample)


def draft(conn, sample, llm):
    """The model's text is only a proposal. One that breaks the rules is left out, and the reason is said in plain words."""
    from . import challenge, qa
    from .llm import LLMError, plain_error
    stamp = snapshot(conn, sample)
    context = {'kind': sample['origin'], 'question': sample['question'], 'answer': sample['answer'],
               'quote': sample['quote'], 'false_claim': sample['false_claim'],
               'based_on': [{k: p.get(k) for k in ('question', 'answer', 'quote', 'status')} for p in sample.get('based_on', [])]}
    from . import agents, console
    prompt = agents.prompt('draft_writer', 'rationale', context=json.dumps(context, ensure_ascii=False))
    try:
        with console.acting('draft_writer'):
            result = llm.complete_json(prompt, {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text']}, temperature=0.2)
    except LLMError as exc:
        raise ValueError(f'The model could not write this: {plain_error(exc)}.') from exc
    text = str(result.get('text') or '').strip()
    if not text:
        raise ValueError('The model did not find enough to explain this.')
    if challenge.DRAFT_TALK.search(text):
        raise ValueError("The model's text was left out: it talks about the material instead of the subject.")
    evidence = ' '.join(filter(None, [sample['question'], sample['answer'], sample['quote'], sample['false_claim'],
                                      *(t for p in sample.get('based_on', []) for t in (p.get('question'), p.get('answer'), p.get('quote')))]))
    stray = sorted(qa._numbers(text) - qa._numbers(evidence))
    if stray:
        raise ValueError(f"The model's text was left out: it states numbers the evidence does not hold: {', '.join(stray)}.")
    return write_rationale(conn, qa.get_sample(conn, sample['id']), stamp, text)
