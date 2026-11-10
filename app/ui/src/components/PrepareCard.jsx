import { useEffect, useMemo, useRef, useState } from 'react';
import { api as rootApi, projectApi } from '../lib/api.js';
import { Card } from './Card.jsx';
import { Button } from './Button.jsx';
import { ModelSelect, useModel } from './ModelSelect.jsx';
import { PILLARS, PILLAR_COLOR } from '../lib/pillars.js';
import { useRuns } from './Runs.jsx';
import { useI18n } from '../i18n/index.jsx';

export function PrepareCard({ project, trainModel, onReadinessChange }) {
  const api = useMemo(() => projectApi(project.id), [project.id]);
  const { t } = useI18n();
  const reasonLabel = (reason) => {
    const keys = {
      'over the selected examples per pair': 'prepare.reason.overLimit', 'removed by you': 'prepare.reason.removed',
      'empty question or answer': 'prepare.reason.empty', 'talked about the source': 'prepare.reason.source',
      'talked about the process': 'prepare.reason.process', 'used a number or technical term that is not in the file': 'prepare.reason.unsupported',
      'a sentence adds a number or technical term not in the quote': 'prepare.reason.unsupported',
      'the answer uses a rare technical word the passage does not support': 'prepare.reason.unsupported',
      'refused to answer a known fact': 'prepare.reason.refusal', 'the answer was in a nearby file passage': 'prepare.reason.found',
      'agreed with the wrong detail': 'prepare.reason.agreed', 'did not correct the wrong detail': 'prepare.reason.notCorrected',
      'repeated a question': 'prepare.reason.repeated', 'too close to a test question': 'prepare.reason.testOverlap',
    };
    return t(keys[reason] || 'prepare.reason.other');
  };
  const { model, items, choose } = useModel();
  const { runs, refresh } = useRuns();
  const [preparation, setPreparation] = useState({ variants: [], counts: {}, stale_pairs: 0, new_pairs: 0 });
  const [trainModels, setTrainModels] = useState([]);
  const [prepareCount, setPrepareCount] = useState(project.prepare_count || 'normal');
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [dropped, setDropped] = useState(null);
  const [shown, setShown] = useState(3);
  const running = runs.find((r) => r.kind === 'prepare_training' && r.subject === project.id && r.status === 'running');
  const variants = useMemo(() => preparation.variants.filter((v) => !v.stale && v.status === 'kept'), [preparation.variants]);
  const [loaded, setLoaded] = useState(false);
  const prepared = preparation.variants.length > 0;
  const changed = preparation.variants.some((v) => !v.stale && v.answer_model && v.answer_model !== trainModel);
  const pending = (preparation.stale_pairs || 0) + (preparation.new_pairs || 0) + (changed ? 1 : 0);
  const wasRunning = useRef(false);
  async function load() {
    try { const data = await api.trainingVariants(); setPreparation(data); setLoaded(true); }
    catch (e) { setError(e.message); }
  }
  const questionModels = [...new Set(preparation.variants.filter((v) => !v.stale).map((v) => v.question_model).filter(Boolean))];
  useEffect(() => { onReadinessChange?.({ prepared, pending }); }, [prepared, pending, onReadinessChange]);
  useEffect(() => { load(); api.trainModels().then(setTrainModels).catch(() => {}); }, [api]);
  useEffect(() => { if (wasRunning.current && !running) load(); wasRunning.current = Boolean(running); }, [running]);
  async function save(patch) {
    setSaving(true); setError('');
    try { await rootApi.updateProject(project.id, patch); if (patch.prepare_count) setPrepareCount(patch.prepare_count); }
    catch (e) { setError(e.message); } finally { setSaving(false); }
  }
  async function prepare() {
    setBusy(true); setError('');
    try { await api.prepareTraining(model, trainModel, prepareCount); await refresh(); await load(); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function drop(id) {
    try { await api.dropTrainingVariant(id); setDropped(id); await load(); }
    catch (e) { setError(e.message); }
  }
  async function undo() { if (!dropped) return; try { await api.undoTrainingVariant(dropped); setDropped(null); await load(); } catch (e) { setError(e.message); } }
  return <Card className="qa-prepare">
    <div className="qa-prepare-head"><div><h2>{t('prepare.title')}</h2><p className="qa-muted">{t('prepare.desc')}</p></div>
      {!loaded ? null : running ? <span className="qa-muted">{t('prepare.running')}</span> : !prepared ? <Button variant="primary" disabled={busy || !model} onClick={prepare}>{t('prepare.button')}</Button> : pending ? <Button disabled={busy || !model} onClick={prepare}>{changed ? t('prepare.again') : t('prepare.update')}</Button> : <span className="qa-muted">{t('prepare.current')}</span>}
    </div>
    <p className="qa-muted prepare-model-line">{questionModels.length > 0 ? t('prepare.questionsBy', { questions: questionModels.map((id) => items.find((item) => item.id === id)?.label || id).join(', ') }) : t('prepare.questionsNext', { questions: model || '—' })}{trainModels.find((m) => m.id === trainModel)?.label && ` · ${t('prepare.answersBy', { answers: trainModels.find((m) => m.id === trainModel).label })}`} · <button className="qa-link" onClick={() => setOpen(!open)}>{t('prepare.change')}</button></p>
    <p className="qa-muted">{trainModels.find((m) => m.id === trainModel)?.label ? t('prepare.answerExplanation', { model: trainModels.find((m) => m.id === trainModel).label }) : ''} {t('prepare.checkFew')}</p>
    {open && <div className="prepare-settings"><ModelSelect label={t('prepare.change.questions')} model={model} items={items} onChange={choose} />
      <label>{t('prepare.change.count')}<select disabled={saving} value={prepareCount} onChange={(e) => save({ prepare_count: e.target.value })}><option value="few">{t('prepare.count.few')}</option><option value="normal">{t('prepare.count.normal')}</option><option value="many">{t('prepare.count.many')}</option></select></label>
      <Button disabled={saving} onClick={() => setOpen(false)}>{t('prepare.done')}</Button>{saving && <span>{t('prepare.saving')}</span>}</div>}
    {error && <p className="qa-error" role="alert">{error}</p>}{running?.message && <p className="qa-muted">{running.message}</p>}
    {loaded && !prepared && !running && <p className="qa-muted">{t('prepare.less')}</p>}{pending > 0 && prepared && <p className="qa-prepare-note">{pending === 1 ? t('prepare.waiting.one') : t('prepare.waiting.many', { count: pending })}</p>}
    {loaded && preparation.excluded_pairs > 0 && <p className="qa-muted">{t('prepare.excluded', { count: preparation.excluded_pairs })}</p>}
    {prepared && <p className="qa-muted">{t('prepare.countMeaning')}{Object.entries(preparation.dropped_reasons || {}).length > 0 && ` ${Object.entries(preparation.dropped_reasons).map(([reason, count]) => t('prepare.droppedReason', { count, reason: reasonLabel(reason) })).join('; ')}`}</p>}
    {prepared && <div className="qa-prepare-counts">{PILLARS.filter((p) => preparation.counts[p.key]).map((p) => { const c = preparation.counts[p.key]; return <div key={p.key} className="qa-prepare-count" style={{ '--pillar': PILLAR_COLOR[p.key] }}><span>{p.label}</span><strong>{c.kept}</strong><small>{t('prepare.ready')}{c.dropped ? ` · ${t('prepare.aside', { count: c.dropped })}` : ''}{c.stale ? ` · ${t('prepare.old', { count: c.stale })}` : ''}</small></div>; })}</div>}
    {variants.length > 0 && <div className="qa-prepare-review"><h3>{t('prepare.review')}</h3>{variants.slice(0, shown).map((v) => <article key={v.id} className="qa-prepare-item" style={{ '--pillar': PILLAR_COLOR[v.kind] }}><div><span className="qa-prepare-kind">{PILLARS.find((p) => p.key === v.kind)?.label || v.kind}</span><p className="qa-prepare-q">{v.question}</p><p className="qa-prepare-a">{v.answer}</p></div><Button onClick={() => drop(v.id)}>{t('prepare.drop')}</Button></article>)}<div className="qa-prepare-foot">{dropped ? <span>{t('prepare.removed')} <Button onClick={undo}>{t('prepare.undo')}</Button></span> : <span/>}{variants.length > shown && <Button onClick={() => setShown(shown + 3)}>{t('prepare.more', { count: variants.length - shown })}</Button>}</div></div>}
  </Card>;
}
