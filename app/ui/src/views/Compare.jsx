import { useEffect, useMemo, useState } from 'react';
import { projectApi } from '../lib/api.js';
import { Panel } from '../components/Panel.jsx';
import { Button } from '../components/Button.jsx';
import { useRuns } from '../components/Runs.jsx';
import { useModel } from '../components/ModelSelect.jsx';
import { Prose } from '../components/Prose.jsx';
import { useI18n } from '../i18n/index.jsx';
import './training.css';

const LABELS = { studied: 'studied', new: 'new', general: 'general', yours: 'yours' };
const answerText = (v) => typeof v === 'string' ? v : v?.answer ?? v?.text ?? '';

export function Compare({ project, initial, onNavigate }) {
  const { t } = useI18n();
  const api = useMemo(() => projectApi(project.id), [project.id]);
  const runsContext = useRuns();
  const [runs, setRuns] = useState(null), [runId, setRunId] = useState(initial?.run_id || '');
  const [comparison, setComparison] = useState(null), [question, setQuestion] = useState('');
  const [cardIndex, setCardIndex] = useState(0);
  const [ownQuestions, setOwnQuestions] = useState(''), [showOwn, setShowOwn] = useState(false);
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const run = runs?.find((r) => r.id === runId), items = comparison?.items || [];
  const judged = items.filter((i) => i.set_name !== 'try');
  const active = runsContext?.runs.some((r) => r.kind === 'comparison' && r.subject === runId && ['running','preparing','queued'].includes(r.status));
  useEffect(() => { api.listTrainRuns().then((rs) => { setRuns(rs); setRunId((id) => id || rs.find((r) => r.status === 'finished')?.id || ''); }).catch((e) => setError(e.message)); }, [api]);
  useEffect(() => { if (!runId) return; let stop = false; const poll = async () => { try { const [c,r] = await Promise.all([api.trainComparison(runId), api.trainRun(runId)]); if (!stop) { setComparison(c); setRuns((old) => [r, ...(old || []).filter((x) => x.id !== r.id)]); } } catch (e) { if (!stop) setError(e.message); } if (!stop) setTimeout(poll, 1800); }; poll(); return () => { stop = true; }; }, [api, runId]);
  const { model: questionModel } = useModel();
  async function start(body = {}) { setBusy(true); setError(''); setNotice(''); try { await api.compareTraining(runId, { ...body, model: questionModel || undefined }); runsContext?.refresh(); } catch (e) { setError(`${t('compare.failed')}: ${e.message}`); } finally { setBusy(false); } }
  async function choose(item, choice) { setBusy(true); setError(''); try { setComparison(await api.chooseComparison(runId, item.id, choice)); if (choice !== null) setCardIndex((i) => Math.min(i + 1, Math.max(0, judged.length - 1))); } catch (e) { setError(e.message); } finally { setBusy(false); } }
  async function ask(e) { e.preventDefault(); if (!question.trim()) return; setBusy(true); setError(''); try { await api.tryTraining(runId, { question: question.trim() }); setQuestion(''); runsContext?.refresh(); } catch (err) { setError(err.message); } finally { setBusy(false); } }
  const revealed = comparison?.revealed === true;
  const trainedSide = (item) => comparison?.base_side?.[item.id] === 'left' ? 'right' : 'left';
  const groups = Object.keys(LABELS);
  return <div className="qa-page training-page compare-simple">
    <div className="page-intro"><h2>{t('compare.title', { n: run?.version || 1 })}</h2><p>{t('compare.intro')}</p></div>
    {error && <div className="qa-error" role="alert">{error}</div>}{notice && <div className="qa-notice" role="status">{notice}</div>}
    {!initial?.run_id && runs?.filter((r) => r.status === 'finished').length > 1 && <label className="qa-field">{t('train.chooseVersion')}<select value={runId} onChange={(e) => setRunId(e.target.value)}>{runs.filter((r) => r.status === 'finished').map((r) => <option key={r.id} value={r.id}>{r.label || `Version ${r.version}`}</option>)}</select></label>}
    {runs && !runs.some((r) => r.status === 'finished') && <Panel className="train-panel"><p>{t('compare.trainFirst')}</p><Button variant="primary" onClick={() => onNavigate('train')}>{t('compare.goTrain')}</Button></Panel>}
    {run && <>
      {!judged.length && <Panel className="train-panel"><p>{t('compare.startText')}</p><Button variant="primary" disabled={busy || active} onClick={() => start()}>{active ? t('compare.preparing') : t('compare.start')}</Button><details open={showOwn} onToggle={(e) => setShowOwn(e.currentTarget.open)}><summary>{t('compare.addOwn')}</summary><label className="qa-field"><textarea rows={4} value={ownQuestions} onChange={(e) => setOwnQuestions(e.target.value)} placeholder={t('compare.ownPlaceholder')} /></label><Button disabled={busy || active || !ownQuestions.trim()} onClick={() => start({questions: ownQuestions.split('\n').map((s) => s.trim()).filter(Boolean)})}>{t('compare.addToTest')}</Button></details></Panel>}
      {active && <p className="train-warning" role="status">{t('compare.writing', { count: items.length, total: comparison?.expected_count || 14 })}</p>}
      {judged[cardIndex] && (() => { const item = judged[cardIndex]; return <Panel key={item.id} className="train-panel compare-item"><p className="qa-muted">{t(`compare.group.${LABELS[item.set_name] || 'yours'}`)} · {cardIndex + 1} {t('compare.of')} {judged.length}</p><h3>{item.question}</h3>{item.expected && <section className="compare-expected"><strong>{t('compare.expected')}</strong><p>{answerText(item.expected)}</p></section>}
        <div className="compare-answers">{['left','right'].map((side, n) => <section className="compare-answer" key={side}><h4>{t('compare.answer')} {n + 1}{revealed && ` · ${side === trainedSide(item) ? t('compare.after') : t('compare.before')}`}</h4><div className="compare-answer-text">{answerText(item[side]) ? <Prose text={answerText(item[side])} /> : t('compare.noAnswer')}</div></section>)}</div>
        <div className="train-actions"><strong>{t('compare.which')}</strong>{[['left',t('compare.answer')+' 1'],['right',t('compare.answer')+' 2'],['both_right',t('compare.bothRight')],['both_wrong',t('compare.bothWrong')]].map(([v,label]) => <Button key={v} variant={item.choice === (v === 'both_right' ? 'same' : v) ? 'primary':'secondary'} disabled={busy || revealed} onClick={() => choose(item,v)}>{label}</Button>)}{cardIndex > 0 && <Button disabled={busy} onClick={() => setCardIndex((i) => i - 1)}>{t('compare.back')}</Button>}{item.choice && !revealed && <Button onClick={() => choose(item,null)}>{t('compare.undo')}</Button>}</div><p className="qa-muted">{t('compare.hidden')}</p></Panel>; })()}
      {revealed && <Panel className="train-panel compare-results"><h3>{t('compare.score')}</h3><p>{t('compare.versionWon', { n: run?.version || 1 })} {Object.values(comparison.sets || {}).reduce((a,s)=>a+(s.better||0),0)} · {t('compare.originalWon')} {Object.values(comparison.sets || {}).reduce((a,s)=>a+(s.worse||0),0)} · {t('compare.ties')} {Object.values(comparison.sets || {}).reduce((a,s)=>a+(s.same||0),0)}</p>{groups.map((g) => { const s = comparison.sets?.[g]; if (!s?.count) return null; return <section key={g}><h4>{t(`compare.group.${g}`)}</h4><p>{s.better ? t('compare.better', {better:s.better,total:s.count}) : s.worse ? t('compare.worse',{worse:s.worse,total:s.count}) : t('compare.noLoss')}</p>{s.both_wrong > 0 && <p>{t('compare.bothWrongCount',{count:s.both_wrong})}</p>}</section>; })}<Button variant="primary" disabled={busy || active} onClick={() => start()}>{t('compare.again')}</Button></Panel>}
      <Panel className="train-panel compare-ask"><h3>{t('compare.askTitle')}</h3><form onSubmit={ask}><label className="qa-field"><textarea rows={2} value={question} onChange={(e)=>setQuestion(e.target.value)} placeholder={t('compare.askPlaceholder')} /></label><Button variant="primary" type="submit" disabled={busy || active || !question.trim()}>{t('compare.ask')}</Button></form>{(comparison?.tries || []).map((item)=><div key={item.id}><h4>{item.question}</h4><div className="compare-answers"><section><h4>{t('compare.before')}</h4><Prose text={item.left} /></section><section><h4>{t('compare.after')}</h4><Prose text={item.right} /></section></div></div>)}</Panel>
    </>}
  </div>;
}
