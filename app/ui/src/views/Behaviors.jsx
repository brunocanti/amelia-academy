import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import { projectApi } from '../lib/api.js';
import { useProjects } from '../ProjectContext.jsx';
import { Panel } from '../components/Panel.jsx';
import { Card } from '../components/Card.jsx';
import { Button } from '../components/Button.jsx';
import { Expander } from '../components/Expander.jsx';
import { useRuns } from '../components/Runs.jsx';

const EMPTY = { title: '', intent: '', tone: '', guidelines: '', description: '', style: 'task', about_identity: false };
const STYLES = [['task', 'Doing a job for someone'], ['companion', 'Keeping someone company']];
const FIELDS = [
  ['title', 'Title', 1, 'Short name of this behavior'],
  ['description', 'When it applies', 2, 'What situation triggers it?'],
  ['intent', 'Intent', 2, 'What should the reply achieve?'],
  ['tone', 'Tone', 1, 'How should it sound?'],
  ['guidelines', 'Guidelines', 3, 'What must it do, and never do?'],
];
const VARIATIONS = [['positive', 'Clear cases'], ['edge_cases', 'Edge cases']];

export function Behaviors({ project, model, onNavigate }) {
  const api = useMemo(() => projectApi(project.id), [project.id]);
  const { update } = useProjects();
  const [identity, setIdentity] = useState(project.identity || '');
  const [cards, setCards] = useState(null);
  const [form, setForm] = useState(null);
  const [count, setCount] = useState(5);
  const [variation, setVariation] = useState('positive');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const { runs, refresh: refreshRuns } = useRuns();
  const writing = runs.find((r) => r.kind === 'behavior' && r.status === 'running')?.subject;

  const load = useCallback(async () => {
    try { setCards(await api.listPatterns()); } catch (e) { setError(e.message); }
  }, [api]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { setIdentity(project.identity || ''); }, [project.id, project.identity]);

  const needsIdentity = (card) => Boolean(card.about_identity) && !(project.identity || '').trim();

  async function saveIdentity() {
    setError('');
    setBusy('identity');
    try {
      await update(project.id, { identity });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy('');
    }
  }

  async function save(e) {
    e.preventDefault();
    setError('');
    setBusy('save');
    try {
      await api.createPattern(form);
      setForm(null);
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy('');
    }
  }

  async function generate(card) {
    setError('');
    setBusy(card.id);
    try {
      if (card.status !== 'approved') await api.setPatternStatus(card.id, 'approved');
      await api.createBatch(card.id, { count: Number(count), variation_type: variation, model });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy('');
      await Promise.all([load(), refreshRuns()]);
    }
  }

  return (
    <div className="qa-page">
      {error && <div className="qa-error">{error}</div>}
      <Panel className="qa-card-form">
        <label className="qa-field">Who the model is
          <textarea rows={4} maxLength={2000} value={identity} onChange={(e) => setIdentity(e.target.value)}
                    placeholder="Its name, where it comes from, what it does and what it does not know." />
        </label>
        <Expander field="identity" text={identity} language={project.language} model={model} onUse={setIdentity}
                  context={`The assistant specializes in: ${project.description || project.display_name}`} />
        <p className="qa-muted">Every new conversation is written to agree with this. Conversations already written do not change.</p>
        {identity.trim() !== (project.identity || '') && (
          <div className="qa-pair-actions">
            <Button variant="primary" disabled={busy === 'identity'} title="Saves who the model is." onClick={saveIdentity}>Save</Button>
            <Button variant="ghost" title="Goes back to what was saved." onClick={() => setIdentity(project.identity || '')}>Cancel</Button>
          </div>
        )}
      </Panel>
      <div className="qa-toolbar">
        <p className="qa-muted qa-grow">A card describes how the model should behave. Conversations are written from it, and you curate them with every other pair.</p>
        <label className="qa-inline">Conversations
          <input type="number" min={1} max={20} value={count} onChange={(e) => setCount(e.target.value)} />
        </label>
        <select aria-label="Kind of conversation" value={variation} onChange={(e) => setVariation(e.target.value)}>
          {VARIATIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        {!form && <Button variant="primary" title="Describe a new way the model should behave." onClick={() => setForm(EMPTY)}>New card</Button>}
      </div>

      {form && (
        <Panel as="form" className="qa-card-form" onSubmit={save}>
          <label className="qa-field">Kind of conversation
            <select value={form.style} onChange={(e) => setForm({ ...form, style: e.target.value })}>
              {STYLES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          {FIELDS.map(([key, label, rows, placeholder]) => (
            <Fragment key={key}>
              <label className="qa-field">{label}
                <textarea rows={rows} required value={form[key]} placeholder={placeholder}
                          onChange={(e) => setForm({ ...form, [key]: e.target.value })} />
              </label>
              {key !== 'title' && (
                <Expander field={`card_${key}`} text={form[key]} language={project.language} model={model}
                          context={`The card is about: ${form.title}`} onUse={(text) => setForm((f) => ({ ...f, [key]: text }))} />
              )}
            </Fragment>
          ))}
          <label className="qa-inline">
            <input type="checkbox" checked={form.about_identity}
                   onChange={(e) => setForm({ ...form, about_identity: e.target.checked })} />
            This card is about who the model is
          </label>
          <div className="qa-pair-actions">
            <Button type="submit" variant="primary" disabled={busy === 'save'} title="Saves this card. Nothing is written yet.">Save card</Button>
            <Button variant="ghost" title="Closes this without saving." onClick={() => setForm(null)}>Cancel</Button>
          </div>
        </Panel>
      )}

      <div className="qa-pairs">
        {cards?.length === 0 && !form && <p className="qa-empty">No behavior cards. They are optional.</p>}
        {cards?.map((card) => (
          <Card className="qa-behavior" key={card.id}>
            <div className="qa-grow">
              <strong>{card.title}</strong>
              <p>{card.intent}</p>
              <small className="qa-muted">{card.tone} · {STYLES.find(([v]) => v === card.style)?.[1]}</small>
              {needsIdentity(card) && <p className="qa-muted">Save who the model is first. Without it, the model would make up a story.</p>}
            </div>
            <Button variant={card.status === 'approved' ? 'secondary' : 'primary'} disabled={!!busy || !!writing || needsIdentity(card)} title={needsIdentity(card) ? 'Save who the model is first.' : card.status === 'approved' ? 'Writes more pairs for you to review.' : 'Approves this card and writes pairs for you to review.'} onClick={() => generate(card)}>
              {busy === card.id || writing === card.id ? 'Writing…' : card.status === 'approved' ? 'Write more' : 'Approve and write'}
            </Button>
          </Card>
        ))}
      </div>
    </div>
  );
}
