import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api as rootApi, projectApi } from '../lib/api.js';
import { Panel } from '../components/Panel.jsx';
import { Button } from '../components/Button.jsx';
import { CoverFlow } from '../components/CoverFlow.jsx';
import { useRuns } from '../components/Runs.jsx';
import { modelName } from '../components/ModelSelect.jsx';
import { useI18n } from '../i18n/index.jsx';

const ACCEPT = '.txt,.md,.html,.htm,.json,.jsonl,.csv,.tsv,.pdf,.docx,.pptx,.xlsx,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.gif';
const POLL_MS = 1200;
const OPTIONS_KEY = 'academy.reading';
const DEFAULTS = { amount: 'normal', care: 'balanced', mix: { false: 15, doubts: 15, neighbour: 5 } };
const LIMITS = { pairs_per_section: [1, 12], section_chars: [2000, 8000], false_per_section: [0, 4], doubts_per_section: [0, 4], neighbour_pct: [0, 30] };
const FIGURE_STATUS = { completed: 'Read', empty: 'Nothing found', failed: 'Failed', skipped: 'Skipped', not_attempted: 'Not read' };
const RIGHTS = [['unspecified', 'Rights not declared'], ['own', 'My own work'], ['permission', 'I have permission'], ['open-license', 'Open license'], ['public-domain', 'Public domain']];

function clockMinutes(sources) {
  const runs = sources.filter((source) => source.run?.status === 'succeeded' && source.run.duration_seconds != null && source.run.created_at)
    .map((source) => ({ start: Date.parse(source.run.created_at), end: Date.parse(source.run.created_at) + source.run.duration_seconds * 1000 }));
  return runs.length ? Math.max(1, Math.round((Math.max(...runs.map((run) => run.end)) - Math.min(...runs.map((run) => run.start))) / 60000)) : null;
}

function storedOptions() {
  try {
    const old = JSON.parse(localStorage.getItem(OPTIONS_KEY) || '{}');
    if (old.amount && old.care && old.mix) {
      if (old.care === 'direct' && (old.false_per_section || old.doubts_per_section)) {
        return { ...DEFAULTS, ...old, care: 'balanced', mix: { ...old.mix, false: 15, doubts: 15 } };
      }
      if (old.care === 'direct' && !(old.mix.false || old.mix.doubts)) {
        return { ...DEFAULTS, ...old, mix: { ...old.mix, false: 7, doubts: 8 } };
      }
      return { ...DEFAULTS, ...old };
    }
    const oldPct = Math.max(old.unanswered_pct || 0, old.false_premise_pct || 0);
    const legacyKinds = Boolean(old.false_per_section || old.doubts_per_section);
    const care = oldPct > 0 || legacyKinds ? 'balanced' : (['direct', 'balanced', 'careful'].includes(old.care) ? old.care : 'direct');
    return { amount: (old.pairs_per_section || 6) <= 4 ? 'quick' : (old.pairs_per_section || 6) >= 9 ? 'everything' : 'normal',
      care,
      mix: { false: old.false_premise_pct || (legacyKinds ? 15 : care === 'careful' ? 25 : care === 'balanced' ? 15 : 7),
        doubts: old.unanswered_pct || (legacyKinds ? 15 : care === 'careful' ? 25 : care === 'balanced' ? 15 : 8), neighbour: old.neighbour_pct || 0 } };
  } catch { return DEFAULTS; }
}

function Hint({ children }) {
  return (
    <span className="qa-hint" tabIndex={0} role="note">
      ?
      <span className="qa-hint-text">{children}</span>
    </span>
  );
}

function ReadingOptions({ options, onChange, disabled }) {
  const { t } = useI18n();
  const previousMix = useRef(null);
  const [canUndoMix, setCanUndoMix] = useState(false);
  const presets = { amount: [['quick', t('files.quick')], ['normal', t('files.normal')], ['everything', t('files.everything')]], care: [['direct', t('files.direct')], ['balanced', t('files.balanced')], ['careful', t('files.careful')]] };
  const mix = options.mix || DEFAULTS.mix;
  const total = mix.false + mix.doubts;
  const known = Math.max(0, 100 - total);
  function updateMix(next) {
    previousMix.current = { mix: { ...mix }, care: options.care };
    setCanUndoMix(true);
    onChange({ ...options, mix: next });
  }
  function choose(key, value) {
    if (key === 'amount') return onChange({ ...options, amount: value });
    const nextMix = { ...mix, false: value === 'direct' ? 7 : value === 'careful' ? 25 : 15,
      doubts: value === 'direct' ? 8 : value === 'careful' ? 25 : 15 };
    previousMix.current = { mix: { ...mix }, care: options.care };
    setCanUndoMix(true);
    onChange({ ...options, care: value, mix: nextMix });
  }
  return <div className="qa-options">
    {Object.entries(presets).map(([key, choices]) => <fieldset key={key} className="qa-choice">
      <legend>{key === 'amount' ? t('files.amountQuestion') : t('files.careQuestion')}</legend>
      {choices.map(([value, label]) => <button type="button" key={value} disabled={disabled} aria-pressed={options[key] === value}
        className={options[key] === value ? 'on' : ''} onClick={() => choose(key, value)}>{label}</button>)}
    </fieldset>)}
    <label className="qa-mix">{known}% {t('files.knows')} · {mix.false}% {t('files.corrects')} · {mix.doubts}% {t('files.doesNotKnow')}
      <input aria-label="Adjust reading mix" type="range" min="0" max="30" value={mix.false} disabled={disabled}
        onChange={(e) => updateMix({ ...mix, false: Number(e.target.value) })} />
    </label>
    <button type="button" className="qa-link" disabled={disabled || !canUndoMix} onClick={() => {
      const restore = previousMix.current;
      previousMix.current = null;
      setCanUndoMix(false);
      onChange({ ...options, care: restore.care, mix: restore.mix });
    }}>{t('activity.undo')}</button>
  </div>;
}

function Stat({ label, value, note, bad }) {
  return (
    <div className="qa-stat">
      <small>{label}</small>
      <strong>{value}</strong>
      {note && <small className={bad ? 'qa-bad' : 'qa-muted'}>{note}</small>}
    </div>
  );
}

function Totals({ source, t }) {
  const totals = source.totals;
  const run = source.run;
  const failed = (source.assets || []).filter((f) => f.ocr_status === 'failed').length;
  const warnings = (source.latest_ingestion?.warnings || []).filter((w) => !w.includes('stored but not read'));
  return (
    <>
      <div className="qa-stats">
        {totals?.pages > 0 && <Stat label="Pages" value={totals.pages} />}
        {totals && <Stat label="Passages" value={totals.passages} />}
        {totals && <Stat label="Characters" value={totals.chars.toLocaleString()} />}
        {totals?.figures > 0 && (
          <Stat label="Figures read" value={`${totals.figures_read} of ${totals.figures}`} note={failed > 0 ? `${failed} failed` : null} bad />
        )}
        {run && <Stat label="Pairs" value={source.pairs} note={source.rejected_pairs ? t('files.rejectedPairs', { count: source.rejected_pairs }) : null} />}
        {run && <Stat label="Discarded" value={run.rejected} />}
      </div>
      {warnings.map((warning) => <span key={warning} className="qa-muted">{warning}</span>)}
    </>
  );
}

function FigureReading({ figure }) {
  if (figure.ocr_status === 'failed' || figure.ocr_status === 'skipped') {
    return (
      <div className={figure.ocr_status === 'failed' ? 'qa-figure-error' : 'qa-figure-skip'}>
        <strong>{figure.ocr_status === 'failed' ? 'Why it could not be read' : 'Why it was skipped'}</strong>
        <p>{figure.ocr_error || 'The reason was not recorded. Read it again to see it.'}</p>
      </div>
    );
  }
  if (!figure.figure_reading && !figure.ocr_text) {
    return <p className="qa-muted">{figure.ocr_status === 'empty' ? 'The model found nothing to say about this figure.' : 'No reading of this figure yet.'}</p>;
  }
  return (
    <div className="qa-figure-texts">
      <section>
        <small>What it shows</small>
        <p>{figure.figure_reading || 'No description.'}</p>
      </section>
      <section>
        <small>Text in the figure</small>
        <p className="qa-figure-transcript">{figure.ocr_text || 'No readable text.'}</p>
      </section>
    </div>
  );
}

function Figures({ source, opened, model, sees, busy, disabled, onRead }) {
  const [figureId, setFigureId] = useState(null);
  const figures = source.assets || [];
  if (!figures.length) return null;
  const shown = figures.find((f) => f.id === figureId) || figures[0];
  const unread = figures.filter((f) => f.ocr_status === 'not_attempted' || f.ocr_status === 'failed').length;
  const failed = figures.filter((f) => f.ocr_status === 'failed').length;
  return (
    <details className="qa-why qa-figures" open={opened}>
      <summary>
        {figures.length} figure(s) extracted
        {failed > 0 && <span className="qa-bad"> · {failed} could not be read</span>}
      </summary>
      <CoverFlow
        items={figures.map((f) => ({
          id: f.id,
          url: f.preview_available ? f.url : '',
          alt: `Figure on page ${f.locator?.page ?? '?'}`,
          flag: f.ocr_status === 'failed' ? 'Failed' : null,
        }))}
        selectedId={shown.id}
        onSelect={setFigureId}
      />
      <div className="qa-figure-strip" role="group" aria-label="All figures">
        {figures.map((f, i) => (
          <button key={f.id} type="button" aria-pressed={f.id === shown.id}
                  className={`qa-figure-chip is-${f.ocr_status}${f.id === shown.id ? ' on' : ''}`}
                  title={`Figure ${i + 1}, page ${f.locator?.page ?? '?'}: ${FIGURE_STATUS[f.ocr_status] || f.ocr_status}`}
                  onClick={() => setFigureId(f.id)}>
            p. {f.locator?.page ?? '?'}
          </button>
        ))}
      </div>
      <div className="qa-figure-note">
        <div className="qa-figure-head">
          <strong>Page {shown.locator?.page ?? '?'}</strong>
          {shown.locator?.section && <span className="qa-muted">{shown.locator.section}</span>}
          <span className={`qa-badge is-${shown.ocr_status}`}>{FIGURE_STATUS[shown.ocr_status] || shown.ocr_status}</span>
          {shown.ocr_model && <small className="qa-muted">{shown.ocr_model}</small>}
          <span className="qa-gap" />
          {unread > 0 && (
            <Button variant="ghost" disabled={busy || disabled || sees === false}
                    title={sees === false ? 'This model does not see images' : 'Read the figures not read yet. No pairs are written.'}
                    onClick={onRead}>
              {busy ? 'Reading figures…' : `Read ${unread} figure(s)`}
            </Button>
          )}
        </div>
        <FigureReading figure={shown} />
      </div>
    </details>
  );
}

function reasonCounts(reasons = []) {
  const counts = new Map();
  for (const reason of reasons) counts.set(reason, (counts.get(reason) || 0) + 1);
  return [...counts.entries()].sort((a, b) => b[1] - a[1]);
}

function Reading({ reading }) {
  if (!reading?.left_out || reading.by_section) return null;
  return <span className="qa-muted">No headings found in this file, so it was read page by page.</span>;
}

function why(discarded) {
  const counts = {};
  for (const item of discarded) {
    // A single rejection can contain the same reason more than once (for example
    // from two checks). Count those too, so the report stays compact and honest.
    for (const reason of new Set(String(item.reason || 'unknown').split(';').map((part) => part.trim()).filter(Boolean))) {
      counts[reason] = (counts[reason] || 0) + 1;
    }
  }
  return Object.entries(counts).map(([reason, n]) => (n > 1 ? `${n} ${reason}` : reason)).join('; ');
}

function Kinds({ run, options, busy, onWrite }) {
  const report = run.reading?.kinds;
  const wanted = options.neighbour_pct > 0;
  if (!report) {
    if (run.status === 'running' || !run.kept || !wanted) return null;
    return (
      <div className="qa-kinds">
        <Button variant="ghost" disabled={busy} title="Uses the percentage above and this reading's answered pairs. The file is not read again."
                onClick={onWrite}>Write the other kinds</Button>
      </div>
    );
  }
  const { unanswered: u, neighbours: n, false_premises: f } = report;
  const fWritten = f.false + f.true;
  return (
    <div className="qa-kinds">
      {u.asked > 0 && (
        <span>Not known: {u.asked} asked, {u.written} written
          {!report.running && u.discarded.length > 0 && `, ${u.discarded.length} discarded (${why(u.discarded)})`}</span>
      )}
      {n?.asked > 0 && (
        <span>Neighbouring subjects: {n.asked} asked, {n.written} written
          {!report.running && n.discarded.length > 0 && `, ${n.discarded.length} discarded (${why(n.discarded)})`}</span>
      )}
      {f.asked > 0 && (
        <span>False premises: {f.asked} asked, {fWritten} written ({f.false} false, {f.true} true versions)
          {!report.running && f.discarded.length > 0 && `, ${f.discarded.length} discarded (${why(f.discarded)})`}</span>
      )}
      {report.returned?.length > 0 && (
        <span className="qa-bad">{report.returned.length} question(s) marked as not in the files went back to review, because this file seems to answer them.</span>
      )}
      {report.stopped && !report.error && (
        <span>Stopped before finishing.{' '}
          {run.status !== 'stopped' && <Button variant="ghost" disabled={busy} title="Only this step. The file is not read again." onClick={onWrite}>Try this step again</Button>}
        </span>
      )}
      {report.error && (
        <span className="qa-bad">
          This step failed, and the answered pairs are kept: {report.error}{' '}
          <Button variant="ghost" disabled={busy} title="Only this step. The file is not read again." onClick={onWrite}>Try this step again</Button>
        </span>
      )}
    </div>
  );
}

function Breakdown({ run }) {
  const leftOut = run?.reading?.left_out || [];
  const total = leftOut.reduce((sum, item) => sum + item.passages, 0);
  const reasons = run?.status === 'running' ? [] : reasonCounts(run?.reasons);
  if (!total && !reasons.length) return null;
  return (
    <div className="qa-breakdown">
      {total > 0 && (
        <section>
          <strong>{total} passage(s) left out of the reading</strong>
          <ul>{leftOut.map((item) => <li key={item.reason}><b>{item.passages}</b>{item.reason}</li>)}</ul>
        </section>
      )}
      {reasons.length > 0 && (
        <section>
          <strong>{run.rejected} pair(s) discarded</strong>
          <ul>{reasons.map(([reason, n]) => <li key={reason}><b>{n}</b>{reason}</li>)}</ul>
        </section>
      )}
    </div>
  );
}

function stoppedAt(run) {
  const figures = run.reading?.figures;
  if (!run.passages_read && figures?.read < figures?.total) return `Stopped at figure ${figures.read} of ${figures.total}`;
  return run.passages_read ? `Stopped at section ${run.passages_read} of ${run.passages_total}` : 'Stopped';
}

function RunState({ source, chosen, busy, waiting, onWriteKinds, t }) {
  const { run } = source;
  if (!run) return <span className="qa-muted">Not read yet</span>;
  const figures = run.reading?.figures;
  const options = run.reading?.options;
  if (run.status === 'running') {
    const onFigures = figures && figures.read < figures.total;
    const pct = onFigures
      ? Math.round((figures.read / figures.total) * 100)
      : run.passages_total ? Math.round((run.passages_read / run.passages_total) * 100) : 0;
    const step = waiting ? t('files.waiting')
      : run.reading?.kinds?.running ? 'Writing the other kinds…'
      : onFigures ? `Figure ${figures.read + 1} of ${figures.total}`
      : run.passages_total ? `Section ${run.passages_read} of ${run.passages_total}` : 'Choosing themes…';
    return (
      <div className="qa-run">
        <span>{step} · {run.kept} pair(s) · {modelName(run.model)}</span>
        <div className="qa-track"><span style={{ width: `${pct}%` }} /></div>
        <Reading reading={run.reading} />
        <Kinds run={run} options={chosen} busy={busy} onWrite={onWriteKinds} />
      </div>
    );
  }
  return (
    <div className="qa-run">
      <span>
        <span className={run.status === 'failed' ? 'qa-bad' : run.status === 'stopped' ? '' : 'qa-run-done'}>
          {run.status === 'failed' ? 'Failed' : run.status === 'stopped' ? stoppedAt(run) : 'Done'}
        </span>
        {' · '}{modelName(run.model)}
        {options && ` · ${options.amount || 'normal'} · ${options.care || 'balanced'}`}
      </span>
      {run.error && <span className="qa-bad">{run.error}</span>}
      <Reading reading={run.reading} />
      {run.reading?.groups && <span>Known {run.kept} · False premise {run.reading.groups.false_premise} · Not known {run.reading.groups.not_known}</span>}
      {options && <details><summary>Details</summary><small>{options.pairs_per_section} pairs/window · {options.section_chars} characters/window · images {options.images ? 'on' : 'off'} · false {options.false_per_section}/window · not known {options.doubts_per_section}/window</small></details>}
      <Kinds run={run} options={chosen} busy={busy} onWrite={onWriteKinds} />
    </div>
  );
}

function FilePicker({ sources, chosen, onChoose }) {
  return (
    <div className="qa-file-picker" role="group" aria-label="Which files to show">
      <button type="button" className={!chosen ? 'on' : ''} aria-pressed={!chosen} title="Show every file" onClick={() => onChoose(null)}>
        All files <small>{sources.length}</small>
      </button>
      {sources.map((source) => {
        const trouble = source.run?.status === 'failed' || (source.assets || []).some((f) => f.ocr_status === 'failed');
        return (
          <button key={source.id} type="button" className={source.id === chosen ? 'on' : ''} aria-pressed={source.id === chosen}
                  title={`Show only ${source.name}`} onClick={() => onChoose(source.id)}>
            {source.run?.status === 'running' && <i className="is-running" />}
            {trouble && <i className="is-trouble" />}
            <span>{source.name}</span>
            <small>{source.pairs}</small>
          </button>
        );
      })}
    </div>
  );
}

export function Files({ project, model, modelSees, onNavigate, initial }) {
  const { t } = useI18n();
  const api = useMemo(() => projectApi(project.id), [project.id]);
  const [sources, setSources] = useState(null);
  const [projectPairs, setProjectPairs] = useState(null);
  const [visionModel, setVisionModel] = useState('');
  const [visionChecked, setVisionChecked] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [undoRights, setUndoRights] = useState(null);
  const [uploading, setUploading] = useState('');
  const [dragging, setDragging] = useState(false);
  const [options, setOptions] = useState(storedOptions);
  const [scopeDraft, setScopeDraft] = useState(project.about_scope || '');
  const [scopeUndo, setScopeUndo] = useState(null);
  const [estimate, setEstimate] = useState(null);
  const [chosen, setChosen] = useState(initial?.source || null);
  const { runs, runsChanged, find, isRunning, resume, refresh: refreshRuns } = useRuns();

  const refresh = useCallback(async () => {
    try {
      const [files, pairs] = await Promise.all([api.listSources(), api.listSamples()]);
      setSources(files);
      setProjectPairs(pairs);
    } catch (e) { setError(e.message); }
  }, [api]);

  useEffect(() => { if (initial?.source) setChosen(initial.source); }, [initial]);
  useEffect(() => { let live = true; api.readingEstimate(model, options.amount, options.care, options.mix).then((value) => { if (live) setEstimate(value); }).catch(() => {}); return () => { live = false; }; }, [api, model, options.amount, options.care, options.mix?.false, options.mix?.doubts, sources?.length]);
  useEffect(() => { rootApi.listModels().then(({ models = [] }) => {
    const local = models.find((m) => !m.online && m.vision);
    if (local) setVisionModel(local.name);
  }).catch(() => {}).finally(() => setVisionChecked(true)); }, []);
  const running = (sources || []).some((s) => s.run?.status === 'running') || runs.some((r) => r.kind === 'figures' && r.status === 'running');
  useEffect(() => { refresh(); }, [refresh, runsChanged]);
  useEffect(() => {
    if (!running) return undefined;
    const timer = setInterval(refresh, POLL_MS);
    return () => clearInterval(timer);
  }, [running, refresh]);

  async function generate(sourceId) {
    setError('');
    try { await api.generate(sourceId, model, options); } catch (e) { setError(e.message); }
    await Promise.all([refresh(), refreshRuns()]);
  }

  async function writeKinds(sourceId) {
    setError('');
    try { await api.writeKinds(sourceId, model, options); } catch (e) { setError(e.message); }
    await Promise.all([refresh(), refreshRuns()]);
  }

  function chooseOptions(next) {
    setOptions(next);
    localStorage.setItem(OPTIONS_KEY, JSON.stringify(next));
  }

  async function readFigures(sourceId, useModel = model) {
    setError('');
    try { await api.readFigures(sourceId, useModel); } catch (e) { setError(e.message); }
    await Promise.all([refresh(), refreshRuns()]);
  }

  async function goOn(sourceId) {
    setError('');
    await resume('reading', sourceId);
    await refresh();
  }

  async function addFiles(files) {
    setError('');
    setNotice('');
    for (const file of files) {
      setUploading(file.name);
      try {
        const known = new Set((await api.listSources()).map((s) => s.id));
        const source = await api.uploadSourceFile(file);
        setChosen(source.id);
        const listed = (await api.listSources()).find((s) => s.id === source.id);
        await refresh();
        if (known.has(source.id) && listed?.run?.status !== 'failed' && listed?.run) {
          setNotice(`${file.name} is already in this dataset, so it was not read again.`);
        } else {
          setUploading('');
          await generate(source.id);
        }
      } catch (e) {
        setError(`${file.name}: ${e.message}`);
      }
    }
    setUploading('');
  }

  function pick(list) {
    const files = [...list];
    if (files.length) addFiles(files);
  }

  const archived = project.status === 'archived';
  const several = (sources?.length || 0) > 1;
  const one = sources?.find((s) => s.id === chosen) || (sources?.length === 1 ? sources[0] : null);
  const listed = one ? [one] : sources;
  return (
    <div className="qa-page">
      {error && <div className="qa-error">{error}</div>}
      {notice && <div className="qa-notice">{notice}{undoRights && <> · <button className="qa-link" onClick={async () => { try { await api.setLicense(undoRights.id, undoRights.before); setUndoRights(null); setNotice(''); await refresh(); } catch (err) { setError(err.message); } }}>Undo</button></>}</div>}
      <label
        className={`qa-drop${dragging ? ' over' : ''}${archived ? ' off' : ''}`}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); if (!archived) pick(e.dataTransfer.files); }}
      >
        <input type="file" multiple accept={ACCEPT} disabled={archived}
               onChange={(e) => { pick(e.target.files); e.target.value = ''; }} />
        <strong>{uploading ? `Reading ${uploading}…` : 'Drop files here, or click to choose'}</strong>
        <small>PDF, Word, Markdown, text and more. Each file becomes pairs to curate.</small>
      </label>

      <ReadingOptions options={options} onChange={chooseOptions} disabled={archived} />

      <section className="qa-reading-options"><h3>{t('files.aboutTitle')}</h3><textarea aria-label={t('files.aboutTitle')} value={scopeDraft} disabled={archived} onChange={(e) => setScopeDraft(e.target.value)} />
        <Button disabled={archived || !sources?.length} onClick={async () => { try { const draft = await rootApi.draftAboutScope(project.id, model); setScopeDraft(draft.about_scope); } catch (e) { setError(e.message); } }}>{t('files.aboutDraft')}</Button>
        <Button disabled={archived || scopeDraft === project.about_scope} onClick={async () => { try { setScopeUndo(project.about_scope || ''); await rootApi.updateProject(project.id, { about_scope: scopeDraft }); } catch (e) { setError(e.message); } }}>{scopeDraft !== (project.about_scope || '') ? t('files.aboutSave') : t('files.aboutAccept')}</Button>
        {scopeUndo !== null && <Button onClick={async () => { await rootApi.updateProject(project.id, { about_scope: scopeUndo }); setScopeDraft(scopeUndo); setScopeUndo(null); }}>{t('files.aboutUndo')}</Button>}
        <label>{t('files.answerStyle')}<select value={project.answer_style || 'short'} disabled={archived} onChange={(e) => rootApi.updateProject(project.id, { answer_style: e.target.value })}><option value="short">{t('files.short')}</option><option value="explains">{t('files.explains')}</option></select></label>
        <label title={t('files.methodDetailsHelp')}>{t('files.includeMethod')}<select value={project.include_method ? 'yes' : 'no'} disabled={archived} onChange={(e) => rootApi.updateProject(project.id, { include_method: e.target.value === 'yes' })}><option value="no">{t('files.no')}</option><option value="yes">{t('files.yes')}</option></select></label>
      </section>

      {several && <FilePicker sources={sources} chosen={one?.id ?? null} onChoose={setChosen} />}

      {!one && sources?.length > 0 && projectPairs?.length > 0 && (() => {
        const fromFiles = sources.reduce((sum, source) => sum + source.pairs, 0);
        const visiblePairs = projectPairs.filter((pair) => pair.status !== 'rejected');
        const withoutFile = visiblePairs.filter((pair) => !pair.source_id).length;
        const total = sources.reduce((sum, source) => sum + source.pairs, 0) + withoutFile;
        return <p className="qa-muted">{t('files.projectPairTotal', { total, files: fromFiles, other: withoutFile })}</p>;
      })()}

      {sources?.filter((s) => !s.run && !archived).length > 1 && <div className="qa-file-actions qa-read-all">
        <Button variant="primary" disabled={running} onClick={async () => {
        for (const source of sources.filter((s) => !s.run)) await generate(source.id);
      }}>{t('files.readAll')}</Button> {estimate && <span>{t('files.estimate', { pairs: estimate.pairs, minutes: estimate.minutes, model: modelName(model) })}</span>}</div>}
      {estimate && sources?.some((s) => s.run?.status === 'succeeded') && <p className="qa-muted">{t('files.actualEstimate', { actual: sources.reduce((n, s) => n + (s.run?.status === 'succeeded' ? s.pairs : 0), 0), actualMinutes: clockMinutes(sources) == null ? '' : `, ${clockMinutes(sources)} min`, estimate: estimate.pairs, estimateMinutes: estimate.minutes })}</p>}
      <Panel flush fill className="qa-list">
        {sources === null && <p className="qa-empty">Loading…</p>}
        {sources?.length === 0 && <p className="qa-empty">No files yet.</p>}
        {listed?.map((source) => (
          <div className="qa-file" key={source.id}>
            <div className="qa-file-head">
              <div className="qa-file-name">
                {one
                  ? <strong title={source.name}>{source.name}</strong>
                  : <button type="button" className="qa-file-open" title={`Show only ${source.name}`} onClick={() => setChosen(source.id)}>{source.name}</button>}
                <RunState source={source} chosen={options} busy={running} waiting={find('reading', source.id)?.waiting} onWriteKinds={() => writeKinds(source.id)} t={t} />
              </div>
              <div className="qa-file-actions">
                {source.license_basis === 'unspecified' && source.license_suggestion && <Button variant="ghost" title={`Suggested from this file: ${source.license_suggestion.evidence}`} onClick={async () => {
                  try { setUndoRights({ id: source.id, before: source.license_basis }); await api.setLicense(source.id, source.license_suggestion.license_basis); setNotice(t('files.licenseSuggestion')); await refresh(); }
                  catch (err) { setError(err.message); }
                }}>{t('files.licenseSuggestion')}</Button>}
                <label className="qa-rights-label">{t('files.rightsOptional')}<select aria-label={`${t('files.rightsOptional')}: ${source.name}`} value={RIGHTS.some(([v]) => v === source.license_basis) ? source.license_basis : 'unspecified'} disabled={archived}
                        onChange={async (e) => {
                          try { setUndoRights({ id: source.id, before: source.license_basis }); await api.setLicense(source.id, e.target.value); setNotice(t('files.licenseUpdated')); await refresh(); } catch (err) { setError(err.message); }
                        }}>
                  {RIGHTS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select></label>
                {source.pairs > 0 && <Button variant="ghost" title="Review the pairs from this file." onClick={() => onNavigate('curate', { source: source.id })}>Curate</Button>}
                {source.run?.can_continue && !archived && <Button variant="primary" title="Picks up where it stopped. What is done stays." onClick={() => goOn(source.id)}>Continue</Button>}
                {source.run?.status !== 'running' && !archived && (
                  <Button variant={source.run ? 'ghost' : 'primary'} title={source.run ? 'Reads from the start with the options above. Pairs you have stay, and repeats are not added.' : 'Reads this file and writes pairs for you to review.'} onClick={() => generate(source.id)}>
                    {source.run ? 'Read again' : 'Read'}
                  </Button>
                )}
              </div>
            </div>
            <Totals source={source} t={t} />
            {visionChecked && !visionModel && source.assets?.some((asset) => ['not_attempted', 'failed'].includes(asset.ocr_status)) && (
              <p className="qa-muted">{t('files.noLocalVision', { count: source.assets.filter((asset) => ['not_attempted', 'failed'].includes(asset.ocr_status)).length })}</p>
            )}
            {one && <Breakdown run={source.run} />}
            {one && (
              <Figures key={source.id} source={source} opened model={model} sees={visionModel ? true : modelSees}
                       busy={isRunning('figures', source.id)} disabled={archived || source.run?.status === 'running'}
                       onRead={() => readFigures(source.id, modelSees === false ? visionModel : model)} />
            )}
          </div>
        ))}
      </Panel>
    </div>
  );
}
