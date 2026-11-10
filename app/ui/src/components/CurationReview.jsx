import { useEffect, useState } from 'react';
import { Button } from './Button.jsx';
import { Expander } from './Expander.jsx';

function standing(rationale) {
  if (!rationale) return 'No explanation yet';
  if (rationale.usable) return 'Explanation in use';
  return rationale.current ? 'Explanation to read' : 'Explanation to read again';
}

export function CurationReview({ sample, api, model, language, onChanged, onUndoable, onError }) {
  const c = sample.curation;
  const rationale = c?.rationale;
  const saved = rationale?.text || '';
  const [text, setText] = useState(saved);
  const [busy, setBusy] = useState(false);
  const [writing, setWriting] = useState(false);
  const [why, setWhy] = useState('');
  useEffect(() => setText(saved), [rationale?.id]);
  if (!c) return null;
  const inUse = rationale?.usable && text === saved;
  async function act(work) {
    setBusy(true);
    try { await work(); await onChanged(); } catch (e) { onError(e.message); } finally { setBusy(false); }
  }
  function checks(next) {
    return act(async () => {
      await api.confirmChecks(sample.id, { input_hash: c.input_hash, checks: next });
      onUndoable?.('Saved.', () => api.confirmChecks(sample.id, { input_hash: c.input_hash, checks: c.checks }));
    });
  }
  const keep = (next) => act(() => api.saveRationale(sample.id, { input_hash: c.input_hash, text: next, approve: false }));
  function use() {
    return act(async () => {
      const result = await api.saveRationale(sample.id, { input_hash: c.input_hash, text, approve: true });
      onUndoable?.('This explanation is in use.', () => api.resetRationale(sample.id, result.rationale.id));
    });
  }
  function stop() {
    return act(async () => {
      await api.resetRationale(sample.id, rationale.id);
      onUndoable?.('This explanation is no longer in use.', () => api.saveRationale(sample.id, { input_hash: c.input_hash, text: saved, approve: true }));
    });
  }
  async function write() {
    const before = text;
    setBusy(true); setWriting(true); setWhy('');
    try {
      await api.draftRationale(sample.id, model);
      await onChanged();
      if (before.trim()) onUndoable?.('Wrote a new explanation.', () => api.saveRationale(sample.id, { input_hash: c.input_hash, text: before, approve: false }));
    } catch (e) {
      setWhy(`${e.message} You can write it here or try again.`);
    } finally { setBusy(false); setWriting(false); }
  }
  // A click on a button of this card does its own saving.
  function left(e) {
    if (!e.relatedTarget?.closest?.('.qa-curation') && text.trim() && text !== saved) keep(text);
  }
  return <details className="qa-curation">
    {rationale && <summary title={c.reasons.join(' ')}>Confidence: {c.level} · {standing(rationale)}</summary>}
    <p className="qa-muted">{c.reasons.join(' ')} This shows what you reviewed, not a chance of being right.</p>
    {sample.status === 'approved' && c.required.map(check => <label className="qa-check" key={check.key}>
      <input type="checkbox" disabled={busy} checked={!!c.checks[check.key]} onChange={e => checks({ ...c.checks, [check.key]: e.target.checked })} />{check.label}
    </label>)}
    <label className="qa-field">Why is this answer right?<textarea rows={3} value={text} maxLength={4000} onChange={e => setText(e.target.value)} onBlur={left} /></label>
    {rationale && !rationale.current && <p className="qa-bad">The answer or its evidence changed. Read this again.</p>}
    {why && <p className="qa-bad">{why}</p>}
    <Expander field="answer" text={text} language={language} model={model} onUse={next => { setText(next); keep(next); }} context={`Explain why this answer follows, preserving the facts. Question: ${sample.question}\nAnswer: ${sample.answer}\nEvidence: ${sample.quote}`} />
    <p className="qa-muted">It goes into the training files only if you use it.</p>
    {inUse
      ? <Button disabled={busy} title="Takes this explanation out of the training files. You can undo this." onClick={stop}>Stop using it</Button>
      : <Button variant="primary" disabled={busy || !text.trim() || c.level === 'low'} title={c.level === 'low' ? c.reasons.join(' ') : 'Puts this explanation in the training files. You can undo this.'} onClick={use}>Use this explanation</Button>}
    <Button disabled={busy || !model} title={model ? 'The model writes it from this pair and its evidence. Nothing is used until you choose.' : 'Choose a model at the top to have this written.'} onClick={write}>{writing ? 'Writing…' : text.trim() ? 'Write it again' : 'Write it for me'}</Button>
  </details>;
}
