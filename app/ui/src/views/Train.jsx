import { useEffect, useMemo, useRef, useState } from 'react';
import { projectApi } from '../lib/api.js';
import { api as rootApi } from '../lib/api.js';
import { Panel } from '../components/Panel.jsx';
import { Button } from '../components/Button.jsx';
import { useRuns } from '../components/Runs.jsx';
import { PrepareCard } from '../components/PrepareCard.jsx';
import { useI18n } from '../i18n/index.jsx';
import './training.css';

const DEFAULTS = { epochs: 3, batch_size: 4, learning_rate: 1e-5 };
const VARIANT_DEFAULTS = { epochs: 2.8, batch_size: 4, learning_rate: 5e-5 };
const ACTIVE = ['preparing', 'training'];
const finite = (n) => typeof n === 'number' && Number.isFinite(n);
const number = (n) => finite(n) ? n.toLocaleString(undefined, { maximumFractionDigits: 4 }) : 'Not measured';
const message = (value) => typeof value === 'string' ? value : value?.message || value?.detail || JSON.stringify(value);

// Keep only actual measurements. Missing, null and non-finite values never become zero.
export function trainingMetrics(events) {
  return events.flatMap((event) => {
    const p = event.payload || {};
    const step = p.iteration ?? p.step ?? p.iter;
    if (!finite(step)) return [];
    const practice = p.train_loss ?? p.training_loss ?? (p.split === 'train' ? p.loss : undefined);
    const check = p.val_loss ?? p.validation_loss ?? (['valid', 'validation'].includes(p.split) ? p.loss : undefined);
    return [{ seq: event.seq, step, practice, check, memory: p.peak_memory_gb ?? p.peak_memory, remaining: p.remaining_seconds }];
  });
}

function LossChart({ events, total }) {
  const accepted = events.map((event, index) => event.type === 'accepted' ? index : -1).filter((index) => index >= 0);
  const segment = accepted.length ? events.slice(accepted.at(-1)) : events;
  const metrics = trainingMetrics(segment);
  const points = metrics.flatMap((m) => [m.practice, m.check].filter(finite).map((value) => ({ step: m.step, value })));
  const checks = metrics.filter((m) => finite(m.check));
  const practices = metrics.filter((m) => finite(m.practice));
  const latest = metrics.at(-1);
  const memory = segment.map((e) => e.payload?.peak_gb ?? e.payload?.peak_memory_gb ?? e.payload?.peak_memory).filter(finite).at(-1);
  const low = points.length ? Math.min(...points.map((p) => p.value)) : 0;
  const high = points.length ? Math.max(...points.map((p) => p.value)) : 1;
  const maxStep = Math.max(1, ...points.map((p) => p.step));
  const x = (step) => 48 + (step / maxStep) * 624;
  const y = (value) => 205 - ((value - low) / (high - low || 1)) * 170;
  const lastCheck = checks.at(-1)?.check;
  const worsening = checks.length > 1 && lastCheck > Math.min(...checks.slice(0, -1).map((p) => p.check));
  return <section className="train-chart" aria-label="Training progress">
    <h3 title="Training and validation loss">How far off it still is</h3>
    <p className="qa-muted">Lower is better. Practice is what it learns from; Check uses answers kept aside.</p>
    {accepted.length > 1 && <p className="qa-muted">Showing the latest training segment</p>}
    {points.length ? <>
      <svg viewBox="0 0 700 245" role="img" aria-label={`Practice: ${number(practices.at(-1)?.practice)}. Check: ${number(lastCheck)}. Lower is better.`}>
        <title>Training and validation loss over steps</title>
        <line x1="48" y1="205" x2="672" y2="205" className="train-axis" />
        {[low, low + (high - low) / 2, high].map((v, i) => <g key={i}><line x1="48" y1={y(v)} x2="672" y2={y(v)} className="train-grid" /><text x="40" y={y(v) + 4} textAnchor="end">{number(v)}</text></g>)}
        {[['practice', practices], ['check', checks]].map(([key, series]) => <g key={key} className={`train-series-${key}`}>
          <polyline fill="none" strokeWidth="2.5" points={series.map((p) => `${x(p.step)},${y(p[key])}`).join(' ')} />
          {series.map((p) => <circle key={p.seq} cx={x(p.step)} cy={y(p[key])} r="3"><title>{key === 'practice' ? 'Practice' : 'Check'} at step {p.step}: {p[key]}</title></circle>)}
        </g>)}
        <text x="48" y="229">Start</text><text x="672" y="229" textAnchor="end">Step {maxStep}</text>
      </svg>
      <div className="train-legend"><span>● Practice: {number(practices.at(-1)?.practice)}</span><span>┄ Check: {number(lastCheck)}</span></div>
    </> : <p className="qa-empty">Waiting for the first measurement.</p>}
    {worsening && <p className="train-warning" role="status">Check is getting worse than its best result. You can stop; the best result is kept.</p>}
    {latest && <p className="qa-muted">Step {latest.step}{finite(total) ? ` of ${total}` : ''}{finite(memory) ? ` · ${number(memory)} GB used` : ''}{finite(latest.remaining) ? ` · About ${Math.ceil(latest.remaining / 60)} min left` : ''}</p>}
    {latest && finite(total) && total > 0 && <progress aria-label="Training steps completed" max={total} value={Math.min(latest.step, total)} />}
  </section>;
}

export function Train({ project, initial, onNavigate }) {
  const { t } = useI18n();
  const api = useMemo(() => projectApi(project.id), [project.id]);
  const runsContext = useRuns();
  const [models, setModels] = useState([]);
  const [datasets, setDatasets] = useState([]);
  const [runs, setRuns] = useState([]);
  const [changes, setChanges] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const [step, setStep] = useState(0);
  const [prepareState, setPrepareState] = useState({ prepared: false, pending: 0 });
  const [error, setError] = useState('');
  const [model, setModel] = useState('');
  const [dataset, setDataset] = useState(initial?.dataset_id || '');
  const [settings, setSettings] = useState(DEFAULTS);
  const [preflight, setPreflight] = useState(null);
  const [busy, setBusy] = useState('');
  const [runId, setRunId] = useState(initial?.run_id || '');
  const [run, setRun] = useState(null);
  const [events, setEvents] = useState([]);
  const [pollError, setPollError] = useState('');
  const cursor = useRef(0);
  const settingsVersion = useRef(0);
  const body = { ...(dataset ? { dataset_id: dataset } : {}), model, profile: 'direct', ...settings };
  const chosenModel = models.find((m) => m.id === model);
  const selectedDataset = datasets.find((d) => d.id === dataset);
  const answerModels = [...new Set(selectedDataset?.answer_models || [])];
  const otherAnswerModels = answerModels.filter((id) => id !== model);
  const occupied = runs.some((r) => ACTIVE.includes(r.status)) || ACTIVE.includes(run?.status);
  const valid = (!dataset || datasets.some((d) => d.id === dataset)) && chosenModel && finite(settings.epochs) && settings.epochs > 0 && settings.epochs <= 10 && Number.isInteger(settings.batch_size) && settings.batch_size > 0 && settings.batch_size <= 8 && finite(settings.learning_rate) && settings.learning_rate > 0 && settings.learning_rate <= 0.001;

  async function load() {
    setError('');
    const results = await Promise.allSettled([api.trainModels(), api.listDatasets(), api.listTrainRuns(), api.trainingVariants(), api.trainChanges()]);
    const [m, d, r, p, c] = results;
    if (m.status === 'fulfilled') {
      const allowed = m.value.filter((item) => finite(item.parameters_b) && item.parameters_b > 0 && item.parameters_b <= 4);
      setModels(allowed);
      setModel((current) => current || (allowed.some((item) => item.id === project.train_model) ? project.train_model : allowed[0]?.id) || '');
    }
    if (d.status === 'fulfilled') {
      const eligible = d.value.filter((item) => (Array.isArray(item.outputs) ? item.outputs : (item.outputs || '').split(',')).includes('finetune') && item.profile !== 'reasoned');
      setDatasets(eligible);
      setDataset((current) => eligible.some((item) => item.id === current) ? current : '');
    }
    if (r.status === 'fulfilled') {
      setRuns(r.value);
      setRunId((current) => current || r.value.find((item) => ACTIVE.includes(item.status))?.id || r.value[0]?.id || '');
    }
    if (c.status === 'fulfilled') setChanges(c.value);
    if (p.status === 'fulfilled') {
      const chosen = project.train_model || (m.status === 'fulfilled' ? m.value.find((item) => item.parameters_b <= 4)?.id : '');
      const answerChanged = p.value.variants?.some((variant) => !variant.stale && variant.answer_model && variant.answer_model !== chosen);
      setPrepareState({ prepared: (p.value.variants || []).length > 0, pending: (p.value.stale_pairs || 0) + (p.value.new_pairs || 0) + (answerChanged ? 1 : 0) });
    }
    setError(results.filter((result) => result.status === 'rejected').map((result) => result.reason.message).join(' '));
    setLoaded(true);
    setStep((current) => current || 1);
  }
  useEffect(() => { load(); }, [api]); // Project changes remount this view.

  const opened = useRef(false);
  useEffect(() => {
    // Open once on the first step still missing; after that the person moves.
    if (!loaded || opened.current) return;
    opened.current = true;
    setStep(!model ? 0 : (prepareState.prepared && !prepareState.pending ? 2 : 1));
  }, [loaded, model, prepareState.prepared, prepareState.pending]);

  useEffect(() => {
    if (!runId) return;
    let gone = false;
    let timer;
    cursor.current = 0;
    setRun(null);
    setEvents([]);
    setPollError('');
    async function poll() {
      try {
        const [next, batch] = await Promise.all([api.trainRun(runId), api.trainEvents(runId, cursor.current)]);
        if (gone) return;
        setRun(next);
        setRuns((old) => old.map((r) => (r.id === next.id ? { ...r, ...next } : r)));
        if (batch.length) {
          const fresh = batch.filter((e) => e.seq > cursor.current);
          setEvents((old) => [...old, ...fresh]);
          cursor.current = Math.max(cursor.current, ...batch.map((e) => e.seq));
        }
        setPollError('');
      } catch (e) { if (!gone) setPollError(e.message); }
      if (!gone) timer = setTimeout(poll, 1800);
    }
    poll();
    return () => { gone = true; clearTimeout(timer); };
  }, [api, runId]);

  function change(fn) {
    settingsVersion.current += 1;
    setPreflight(null);
    fn();
  }

  async function renameVersion(item) {
    const name = window.prompt(t('train.versionName'), item.name || item.label);
    if (name === null) return;
    try { await api.updateTrainRun(item.id, { name }); setRuns(await api.listTrainRuns()); }
    catch (e) { setError(e.message); }
  }

  async function useVersion(item) {
    try { await api.updateTrainRun(item.id, { in_use: true }); setRuns(await api.listTrainRuns()); }
    catch (e) { setError(e.message); }
  }

  async function deleteVersion(item) {
    try {
      await api.deleteTrainRun(item.id);
      setRuns((old) => old.filter((r) => r.id !== item.id));
      runsContext?.notify({ text: t('train.undoDelete', { label: item.label }), action: { label: t('activity.undo') || 'Undo', onClick: async () => { await api.undoDeleteTrainRun(item.id); setRuns(await api.listTrainRuns()); } } });
    } catch (e) { setError(e.message); }
  }

  async function act(action) {
    setBusy(action);
    setError('');
    const version = settingsVersion.current;
    try {
      if (action === 'check') {
        const result = await api.trainPreflight(body);
        if (version === settingsVersion.current) {
          setPreflight(result);
          if (!dataset && result.config?.dataset_id) {
            setDataset(result.config.dataset_id);
            setDatasets(await api.listDatasets());
          }
        }
      } else {
        const next = await (action === 'start' ? api.startTraining(body) : action === 'stop' ? api.stopTraining(runId) : api.continueTraining(runId));
        setRun(next);
        setRunId(next.id);
        setRuns((old) => [next, ...old.filter((r) => r.id !== next.id)]);
        if (action === 'start') setPreflight(null);
        runsContext?.refresh();
      }
    } catch (e) { setError(e.message); }
    finally { setBusy(''); }
  }

  return <div className="qa-page training-page">
    {error && <div className="qa-error" role="alert">{error} <button className="qa-link" onClick={load}>Refresh</button></div>}
    {!loaded && <p className="qa-empty">Loading training options…</p>}
    <nav className="train-steps" aria-label="Training steps">{['Model', 'Get it ready', 'Teach'].map((label, index) => <button key={label} className={step === index ? 'is-current' : ''} onClick={() => index < step && setStep(index)} disabled={index > step}><span>{index < step ? '✓' : index + 1}</span>{label}</button>)}</nav>
    {step === 0 && <Panel className="train-panel">
      <h2>Which model should learn this?</h2>
      <p className="qa-muted">Teach a small model with your approved answers, then check whether it improved.</p>
      <div className="train-fields">
          <label className="qa-field">Model<select disabled={!!busy || !models.length} value={model} onChange={(e) => change(() => { const value = e.target.value; setModel(value); rootApi.updateProject(project.id, { train_model: value }).catch((err) => setError(err.message)); })}>
            <option value="" disabled>Choose a model</option>{models.map((m) => <option key={m.id} value={m.id}>{m.label} · {m.parameters_b}B{m.cached ? ' · Downloaded' : ' · Download needed'}</option>)}
          </select></label>
        </div>
        <div className="train-step-next"><Button variant="primary" disabled={!model} onClick={() => setStep(1)}>Next</Button></div>
    </Panel>}
    {step === 1 && <Panel className="train-panel">
        <PrepareCard project={project} trainModel={model} onReadinessChange={setPrepareState} />
        <div className="train-step-next"><Button variant="primary" onClick={() => setStep(2)}>Next</Button></div>
    </Panel>}
    {step === 2 && <Panel className="train-panel">
        <h2>Teach</h2>
        {otherAnswerModels.length > 0 && <div className="train-warning" role="status">These examples were written by {[...new Set(answerModels)].map((id) => models.find((m) => m.id === id)?.label || id).join(', ')}. Training another model on them teaches it their way of writing. <Button onClick={() => { const value = otherAnswerModels[0]; setModel(value); rootApi.updateProject(project.id, { train_model: value }).catch((err) => setError(err.message)); }}>Prepare again for {models.find((m) => m.id === otherAnswerModels[0])?.label || otherAnswerModels[0]}</Button></div>}
        {loaded && !models.length && <p className="qa-bad">No supported models up to 4B are available on this machine.</p>}
        <p className="qa-muted">{t('train.directOnly')}</p>
        <details><summary>More settings</summary><div className="train-fields">
          <label className="qa-field">Choose an exported dataset<select disabled={!!busy || !datasets.length} value={dataset} onChange={(e) => change(() => { const id = e.target.value; setDataset(id); setSettings(datasets.find((d) => d.id === id)?.has_variants ? VARIANT_DEFAULTS : DEFAULTS); })}><option value="">Use this project’s approved answers</option>{datasets.map((d) => <option key={d.id} value={d.id}>{d.name} · {d.sample_count} pairs</option>)}</select></label>
          {[["epochs", 'Passes through the answers', 0.5, 10], ['batch_size', 'Answers at a time', 1, 8], ['learning_rate', 'Learning rate', 'any', 0.001]].map(([key, label, step, max]) => <label className="qa-field" key={key}>{label}<input type="number" min={key === 'learning_rate' ? '0.000000001' : key === 'epochs' ? '0.5' : '1'} max={max} step={step} value={settings[key]} disabled={!!busy} onChange={(e) => change(() => setSettings((old) => ({ ...old, [key]: e.target.value === '' ? '' : Number(e.target.value) })))} /><small>Default: {DEFAULTS[key]}</small></label>)}
        </div></details>
        {chosenModel && !chosenModel.cached && <p className="train-warning">This model needs to be downloaded before training. Automatic downloads are not available yet. <a href={`https://huggingface.co/${chosenModel.id}`} target="_blank" rel="noreferrer">Open the model page</a>, then refresh after downloading it.</p>}
        {!prepareState.prepared && <p className="qa-muted">Without getting it ready the model learns less.</p>}
        {preflight && <div aria-live="polite">
          <p>{preflight.ready ? 'Ready to train.' : 'A few things need attention before training.'}{finite(preflight.train_count) ? ` ${preflight.train_count} practice examples.` : ''}{finite(preflight.valid_count) ? ` ${preflight.valid_count} check examples.` : ''}</p>
          {finite(preflight.train_count) && finite(preflight.valid_count) && <p className="qa-muted">{t('train.teachCountMeaning')}{finite(preflight.test_count) ? ` ${preflight.test_count} test examples.` : ''}</p>}
          {(preflight.warnings || []).map((w, i) => <p className="train-warning" key={i}>{message(w)}</p>)}
          {(preflight.errors || []).map((e, i) => <p className="qa-bad" key={i}>{message(e)}</p>)}
        </div>}
        <div className="train-actions"><Button variant="primary" disabled={!valid || !!busy || occupied || (preflight?.ready && !chosenModel?.cached)} onClick={() => act(preflight?.ready ? 'start' : 'check')}>{busy === 'check' ? 'Checking…' : busy === 'start' ? 'Starting…' : preflight?.ready ? 'Start training' : 'Check before training'}</Button>{!valid && model && <span className="qa-muted">Use up to 10 passes, 1–8 answers at a time, and a learning rate above 0 and up to 0.001.</span>}</div>
    </Panel>}
    {step === 2 && runs.length > 0 && <Panel className="train-panel"><h3>{t('train.versions')}</h3>
      {changes?.pairs_changed > 0 && changes.since_version && <p className="train-warning">{t('train.changedPairs', { count: changes.pairs_changed, label: `Version ${changes.since_version}` })}</p>}
      {runs.map((item) => <section key={item.id} className="train-version-row">
        <button className="qa-link" onClick={() => setRunId(item.id)}><strong>{item.label}</strong>{item.in_use ? ` · ${t('train.inUse')}` : ''}</button>
        <span className="qa-muted"> · {item.model?.split('/').at(-1) || 'Qwen3 4B'} · {item.created_at ? new Date(item.created_at).toLocaleDateString() : ''} · {t(`train.${item.status === 'finished' ? 'ready' : item.status === 'training' || item.status === 'preparing' ? 'training' : item.status}`)}</span>
        <p className="qa-muted">{item.answer_model ? t('train.examplesSummary', { samples: item.samples, pairs: item.pairs, model: item.answer_model }) : t('train.examplesSummaryNoModel', { samples: item.samples, pairs: item.pairs })}{finite(item.best_val_loss) ? ` · ${t('train.bestCheck', { value: number(item.best_val_loss) })}` : ''}{item.total ? ` · ${t('train.comparisonScore', { better: item.better, total: item.total })}` : ''}</p>
        <p className="qa-muted">{t('train.versionCountMeaning')}</p>
        {item.error && <p className="qa-error">{item.error}</p>}
        <div className="train-actions">{!item.in_use && item.status === 'finished' && <Button onClick={() => useVersion(item)}>{t('train.useThis')}</Button>}<Button onClick={() => renameVersion(item)}>{t('train.rename')}</Button><details><summary aria-label="More version actions">⋯</summary><Button onClick={() => deleteVersion(item)}>{t('train.delete')}</Button></details></div>
      </section>)}
      {runs.some((item) => !item.in_use && !ACTIVE.includes(item.status)) && <Button onClick={async () => { try { const result = await api.deleteOtherTrainRuns(); const deleted = runs.filter((item) => result.ids.includes(item.id)); setRuns((old) => old.filter((item) => !result.ids.includes(item.id))); runsContext?.notify({ text: t('train.deleteOthers'), action: { label: t('activity.undo') || 'Undo', onClick: async () => { await Promise.all(deleted.map((item) => api.undoDeleteTrainRun(item.id))); setRuns(await api.listTrainRuns()); } } }); } catch (e) { setError(e.message); } }}>{t('train.deleteOthers')}</Button>}
    </Panel>}
    {pollError && <div className="qa-error" role="alert">Could not refresh this training: {pollError}. Retrying…</div>}
    {step === 2 && runId && !run && !pollError && <p className="qa-muted">Loading training progress…</p>}
    {step === 2 && run && <Panel className="train-panel">
      <div className="train-heading"><h2>{run.label || `Version ${run.version || ''}`} — {run.status === 'finished' ? 'Training finished. Is it better?' : run.status === 'failed' ? 'Training stopped with a problem.' : run.status === 'stopped' ? 'Training stopped. Your progress is kept.' : run.status === 'preparing' ? 'Getting ready to train…' : 'Learning from your answers…'}</h2><span className="qa-muted">{run.model || run.base_repo}</span></div>
      {run.error && <div className="qa-error" role="alert">{message(run.error)}</div>}
      {run.status === 'failed' && <p className="qa-muted">Your saved progress is kept. If memory ran out, try fewer answers at a time in More settings.</p>}
      {['stopped', 'failed'].includes(run.status) && <p className="qa-muted">Continue from the saved progress. The learning settings start fresh.</p>}
      <LossChart events={events} total={run.config?.iters} />
      {finite(run.best_val_loss) && <p className="qa-muted" title="Lowest validation loss">Best Check: {number(run.best_val_loss)}{finite(run.best_iteration) ? ` at step ${run.best_iteration}` : ''}.</p>}
      <div className="train-actions">
        {ACTIVE.includes(run.status) && <Button disabled={!!busy} onClick={() => act('stop')}>{busy === 'stop' ? 'Stopping…' : 'Stop'}</Button>}
        {['stopped', 'failed'].includes(run.status) && <Button variant="primary" disabled={!!busy || occupied} onClick={() => act('continue')}>{busy === 'continue' ? 'Continuing…' : 'Continue'}</Button>}
        {run.status === 'finished' && <Button variant="primary" onClick={() => onNavigate('compare', { run_id: run.id })}>Compare</Button>}
        {(run.status === 'finished' || finite(run.best_val_loss) || run.best_iteration != null) && <a className="aa-btn aa-btn-secondary" href={api.downloadTrainUrl(run.id)}>Download your model</a>}
      </div>
      <details><summary>Training details</summary><p className="qa-muted">The download includes your trained model and what it needs to run. It also needs the original base model.</p></details>
    </Panel>}
  </div>;
}
