import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { projectApi } from '../lib/api.js';
import { Panel } from '../components/Panel.jsx';
import { Card } from '../components/Card.jsx';
import { Button } from '../components/Button.jsx';
import { PillarBar } from '../components/PillarBar.jsx';
import { PILLAR_OF, KIND_LABEL } from '../lib/pillars.js';
import { useRuns } from '../components/Runs.jsx';
import { useI18n } from '../i18n/index.jsx';

const OUTPUTS = [
  ['finetune', 'Fine-tuning', 'Final answers and optional approved explanations, with shared train, validation and test splits.'],
  ['memory', 'Memory file', 'memory.jsonl, to look answers up, with evidence and each pair\'s kind.'],
  ['wiki', 'Wiki', 'OKF pages, one per theme.'],
];
const FINETUNE_ONLY = ['true_premise', 'neighbour', 'behavior'];

export function Export({ project, model, onNavigate }) {
  const { t } = useI18n();
  const api = useMemo(() => projectApi(project.id), [project.id]);
  const [themes, setThemes] = useState([]);
  const [unchecked, setUnchecked] = useState(() => new Set());
  const [datasets, setDatasets] = useState([]);
  const [name, setName] = useState(project.slug);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);
  const [approved, setApproved] = useState([]);
  const [profile, setProfile] = useState('direct');
  const [highOnly, setHighOnly] = useState(false);
  const [onlyKind, setOnlyKind] = useState('');
  const [excludedIds, setExcludedIds] = useState(() => new Set());
  const [outputs, setOutputs] = useState(() => new Set(['finetune']));
  const [repeated, setRepeated] = useState([]);
  const [reworded, setReworded] = useState(null);
  const [preparation, setPreparation] = useState({ variants: [], counts: {}, stale_pairs: 0, new_pairs: 0 });
  const { runs, refresh: refreshRuns } = useRuns();
  const rewording = runs.find((r) => r.kind === 'reword' && r.subject === project.id && r.status === 'running');

  const load = useCallback(async () => {
    try {
      const [t, d, a, r, p] = await Promise.all([api.listThemes(), api.listDatasets(), api.listSamples({ status: 'approved' }), api.repeatedAnswers(), api.trainingVariants()]);
      setThemes(t);
      setRepeated(r);
      setApproved(a);
      setDatasets(d);
      setPreparation(p);
    } catch (e) {
      setError(e.message);
    }
  }, [api]);
  useEffect(() => { load(); }, [load]);
  // When the rewording ends, the pairs it changed have left the approved list.
  const wasRewording = useRef(false);
  useEffect(() => {
    if (wasRewording.current && !rewording) load();
    wasRewording.current = Boolean(rewording);
  }, [rewording, load]);

  async function reword(warning) {
    setError('');
    try {
      const started = await api.reword(warning.rewordable, model);
      setReworded({ batch: started.batch_id, undone: false });
      await refreshRuns();
    } catch (e) {
      setError(e.message);
    }
  }

  async function undoReword() {
    setError('');
    try {
      await api.undoReword(reworded.batch);
      setReworded({ ...reworded, undone: true });
      await load();
    } catch (e) {
      setError(e.message);
    }
  }

  const ready = themes.filter((t) => t.approved > 0);
  const keptVariants = preparation.variants.filter((v) => !v.stale && v.status === 'kept');
  const answerModels = [...new Set(keptVariants.map((v) => v.answer_model).filter(Boolean))];
  const chosen = ready.filter((t) => !unchecked.has(t.id));
  const total = chosen.reduce((sum, t) => sum + t.approved, 0);
  const pending = themes.reduce((sum, t) => sum + t.proposed, 0);

  // The percentages only set what is written; curation decides what goes out.
  const mix = {};
  for (const s of approved) {
    if (!unchecked.has(s.theme_id)) mix[s.origin] = (mix[s.origin] || 0) + 1;
  }

  const byPillar = {};
  for (const [kind, n] of Object.entries(mix)) byPillar[PILLAR_OF[kind]] = (byPillar[PILLAR_OF[kind]] || 0) + n;
  const kindsOf = (key) => PILLARS.find((p) => p.key === key).kinds.filter((kind) => mix[kind] && KIND_LABEL[kind] !== PILLARS.find((p) => p.key === key).label);

  // Without fine-tuning, the pairs that only go there do not come out at all.
  const eligible = approved.filter(s => !unchecked.has(s.theme_id) && s.curation?.level !== 'low' && (!highOnly || s.curation?.level === 'high') && (!onlyKind || s.origin === onlyKind) && !excludedIds.has(s.id));
  const going = outputs.has('finetune') ? eligible.filter(s => profile !== 'reasoned' || s.curation?.rationale?.usable).length : total - FINETUNE_ONLY.reduce((sum, key) => sum + (mix[key] || 0), 0);

  function toggleOutput(key) {
    setOutputs((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  }

  function toggle(id) {
    setUnchecked((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  async function run() {
    setBusy(true);
    setError('');
    setResult(null);
    try {
      setResult(await api.exportDataset({ name, theme_ids: chosen.map((t) => t.id), outputs: [...outputs], profile, confidence_levels: highOnly ? ['high'] : ['medium', 'high'], sample_ids: outputs.has('finetune') ? eligible.map(s => s.id) : null }));
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="qa-page">
      {error && <div className="qa-error">{error}</div>}
      <Panel className="qa-export">
        {keptVariants.length > 0 && <p className="qa-muted">{t('export.prepared', { count: keptVariants.length, model: answerModels.join(', ') || 'the selected model' })}</p>}
        <h3>What goes in</h3>
        {ready.length === 0 && <p className="qa-muted">Nothing approved yet.</p>}
        <div className="qa-checks">
          {ready.map((t) => (
            <label key={t.id} className="qa-check">
              <input type="checkbox" checked={!unchecked.has(t.id)} onChange={() => toggle(t.id)} />
              <span>{t.title}</span>
              <small>{t.approved}</small>
            </label>
          ))}
        </div>
        {repeated.map((w) => (
          <div className="qa-bad" key={w.answer}>
            {w.message}
            {w.rewordable.length > 0 && !rewording && (
              <> <Button variant="secondary" disabled={!model} title={model ? 'The model rewrites each one to say what it does not know. They come back to Curate for you to approve.' : 'Choose a model first.'} onClick={() => reword(w)}>Reword them</Button></>
            )}
          </div>
        ))}
        {rewording && <p className="qa-muted">Rewording answers{rewording.total > 0 ? ` (${rewording.done} of ${rewording.total})` : ''}…</p>}
        {reworded && !rewording && (
          <p className="qa-muted">
            {reworded.undone ? 'The old answers are back.' : 'The new answers are in Curate to read. '}
            {!reworded.undone && <><button className="qa-link" onClick={() => onNavigate('curate')}>Curate them</button> · <button className="qa-link" title="Puts the old answers back as they were." onClick={undoReword}>Undo</button></>}
          </p>
        )}
        {pending > 0 && (
          <p className="qa-muted">{pending} {pending === 1 ? 'pair' : 'pairs'} still to review stay out. <button className="qa-link" title="Go review the pairs still waiting." onClick={() => onNavigate('curate')}>Curate them</button></p>
        )}
        {total > 0 && (
          <PillarBar counts={byPillar} detail={(key) => [`${Math.round((byPillar[key] / total) * 100)}%`, ...kindsOf(key).map((kind) => `${KIND_LABEL[kind]} ${mix[kind]}`)].join(' · ')} />
        )}
        <h3>What comes out</h3>
        <div className="qa-checks">
          {OUTPUTS.map(([key, label, hint]) => (
            <label key={key} className="qa-check" title={hint}>
              <input type="checkbox" checked={outputs.has(key)} onChange={() => toggleOutput(key)} />
              <span>{label}</span>
            </label>
          ))}
        </div>
        {outputs.has('finetune') && <>
          <label className="qa-field">What should the model learn?
            <select value={profile} onChange={e => setProfile(e.target.value)}>
              <option value="direct">Final answers</option><option value="reasoned">Answers with explanations</option><option value="both">Both</option>
            </select>
          </label>
          <label className="qa-check"><input type="checkbox" checked={highOnly} onChange={e => setHighOnly(e.target.checked)} />Only fully checked pairs (high confidence)</label>
          <p className="qa-muted">{eligible.length} answers can go in · {eligible.filter(s => s.curation?.rationale?.usable).length} explanations approved.</p>
          <details><summary>Choose pairs</summary>
            <label className="qa-field">Kind<select value={onlyKind} onChange={e => setOnlyKind(e.target.value)}>
              <option value="">All kinds</option>{[...new Set(approved.map(s => s.origin))].map(k => <option key={k} value={k}>{KIND_LABEL[k] || k}</option>)}
            </select></label>
            {approved.filter(s => !unchecked.has(s.theme_id) && (!onlyKind || s.origin === onlyKind)).map(s => <label className="qa-check" key={s.id}>
              <input type="checkbox" checked={!excludedIds.has(s.id)} onChange={e => setExcludedIds(old => {const next = new Set(old); if(e.target.checked) next.delete(s.id); else next.add(s.id); return next;})} />{s.question}
            </label>)}
          </details>
          {profile !== 'direct' && <p className="qa-muted">Explanations are exported for preparation. Training them still needs a verified renderer for your model.</p>}
        </>}
        <div className="qa-export-go">
          <label className="qa-field">Name<input value={name} onChange={(e) => setName(e.target.value)} /></label>
          <Button variant="primary" disabled={busy || going === 0 || outputs.size === 0} title={going === 0 ? 'Approve some pairs first.' : outputs.size === 0 ? 'Choose what comes out first.' : 'Saves the approved pairs to a new folder.'} onClick={run}>{busy ? 'Exporting…' : `Export ${going} ${going === 1 ? 'pair' : 'pairs'}`}</Button>
        </div>
        <p className="qa-muted">{OUTPUTS.filter(([key]) => outputs.has(key)).map(([, label, hint]) => `${label}: ${hint}`).join(' ')} In the memory file and the wiki, false premises and what is not known come labeled. True versions, neighbouring subjects and behaviors go to fine-tuning only.</p>
      </Panel>

      {result && (
        <div className="qa-notice">
          Exported {result.sample_count} {result.sample_count === 1 ? 'pair' : 'pairs'}{result.outputs.includes('memory') && result.outputs.includes('finetune') ? `, ${result.memory_count} of them as memory records,` : ''} to <code>{result.folder}</code>.
          {result.profile_counts && ` ${result.profile_counts.direct} answers; ${result.profile_counts.reasoned} with approved explanations.`}
          {result.excluded?.length > 0 && ` ${result.excluded.length} approved ${result.excluded.length === 1 ? 'pair was' : 'pairs were'} left out: ${[...new Set(result.excluded.flatMap((e) => e.reasons))].join('; ')}.`}
          {result.warnings?.length > 0 && ` ${result.warnings.join(' ')}`}
        </div>
      )}
      {result?.outputs.includes('finetune') && (
        <Panel title="How the pairs were divided">
          <table className="qa-split-table">
            <thead><tr><th>Kind</th><th>Train</th><th>Validation</th><th>Test</th></tr></thead>
            <tbody>{Object.entries(result.kinds).map(([kind, n]) => <tr key={kind}>
              <td>{KIND_LABEL[kind] || KIND_LABEL[kind === 'unanswered' ? 'refusal' : kind] || kind}</td><td>{n.train}</td><td>{n.validation}</td><td>{n.test}</td>
            </tr>)}</tbody>
          </table>
          {result.split_warnings?.map((w) => <p className="qa-bad" key={w.kind}>{w.message}</p>)}
          {result.answer_warnings?.map((w) => <p className="qa-bad" key={w.answer}>{w.message}</p>)}
        </Panel>
      )}

      <div className="qa-pairs">
        {datasets.map((d) => (
          <Card className="qa-behavior" key={d.id}>
            <div className="qa-grow">
              <strong>{d.name}</strong>
              <small className="qa-muted"> {d.sample_count} {d.sample_count === 1 ? 'pair' : 'pairs'} · {(d.outputs ? OUTPUTS.filter(([key]) => d.outputs.split(',').includes(key)) : OUTPUTS).map(([, label]) => label).join(', ')} · {new Date(d.created_at).toLocaleString()}</small>
              <div><code className="qa-muted">{d.manifest_hash?.slice(0, 12)}</code></div>
            </div>
            <a className="aa-btn aa-btn-secondary qa-download" title="Downloads this export to your computer." href={api.downloadUrl(d.id)}>Download</a>
          </Card>
        ))}
      </div>
    </div>
  );
}
