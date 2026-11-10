import { useEffect, useState } from 'react';
import { useRuns } from './Runs.jsx';
import { Button } from './Button.jsx';
import { useI18n } from '../i18n/index.jsx';
import './activity.css';

const AGENT_ACTIVITY = {
  theme_proposer: 'activity.findingTopics', passage_reader: 'activity.writingAnswers',
  figure_reader: 'activity.readingFigure', conflict_finder: 'activity.checkingAnswers',
  question_varier: 'activity.writingPractice', behavior_writer: 'activity.writingExamples',
  doubt_writer: 'activity.writingUnknowns', neighbour_writer: 'activity.writingNeighbors',
  connection_writer: 'activity.connectingAnswers', false_premise_writer: 'activity.writingMistakes',
  answer_checker: 'activity.checkingAnswer', draft_writer: 'activity.draftingExplanation',
  text_expander: 'activity.improvingWording',
};

export { useRuns } from './Runs.jsx';
export const useActivity = useRuns;

export function ActivityBar({ onGo, onConsole, projectId }) {
  const { t } = useI18n();
  const { runs, notices, trouble, stop, resume, dismiss, refresh } = useActivity();
  const [selected, setSelected] = useState(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [consoleState, setConsoleState] = useState(null);
  useEffect(() => {
    const update = (event) => setConsoleState(event.detail);
    window.addEventListener('academy-console-state', update);
    return () => window.removeEventListener('academy-console-state', update);
  }, []);
  const hidden = (() => { try { return JSON.parse(localStorage.getItem('academy.runs.hidden') || '[]'); } catch { return []; } })();
  const visibleRuns = runs.filter((run) => run.status === 'running' || !hidden.includes(`${run.key}@${run.started_at}`));
  const chips = [...visibleRuns.map((run) => ({ id: run.key, run, text: run.title, tone: run.status })),
    ...notices.map((item) => ({ ...item, text: item.text }))];
  const active = chips.slice(-5);
  const overflow = chips.slice(0, -5);
  const choose = (item) => setSelected(selected?.id === item.id ? null : item);
  async function action(item) {
    try { await item.action.onClick(); dismiss(item.id); setSelected(null); }
    catch (error) { item.text = error.message; item.tone = 'error'; }
  }
  return <>
    {selected && <aside className="activity-popover" role="dialog"><strong>{selected.text}</strong>
      {selected.run?.error && <p>{selected.run.error}</p>}{selected.run?.message && <p>{selected.run.message}</p>}
      {selected.run?.status === 'running' && <Button onClick={() => stop(selected.run.kind, selected.run.subject)}>Stop</Button>}
      {selected.run?.can_continue && <Button onClick={() => resume(selected.run.kind, selected.run.subject)}>Continue</Button>}
      {selected.run?.where && <Button onClick={() => { onGo(selected.run.where.view, selected.run.where.params); setSelected(null); }}>Go to it</Button>}
      {selected.action && <Button onClick={() => action(selected)}>{selected.action.label}</Button>}
      <Button onClick={() => { selected.run ? localStorage.setItem('academy.runs.hidden', JSON.stringify([...JSON.parse(localStorage.getItem('academy.runs.hidden') || '[]'), `${selected.run.key}@${selected.run.started_at}`].slice(-200))) : dismiss(selected.id); setSelected(null); }}>OK</Button>
    </aside>}
    {historyOpen && <aside className="activity-history"><strong>Recent activity</strong>{(() => { try { return JSON.parse(sessionStorage.getItem(`academy.activity.history.${projectId}`) || '[]').slice(-30).reverse().map((event) => <button key={event.id} onClick={() => { setHistoryOpen(false); }}>{new Date(event.at).toLocaleTimeString()} · {event.text}</button>); } catch { return null; } })()}{chips.slice(-30).reverse().map((item) => <button key={item.id} onClick={() => { setHistoryOpen(false); choose(item); }}>{item.text}</button>)}</aside>}
    <footer className="activity-bar" aria-label="Activity">
      {trouble && <button className="activity-chip is-error" onClick={refresh}>{trouble} · Retry</button>}
      {overflow.length > 0 && <button className="activity-chip" onClick={() => setHistoryOpen(!historyOpen)}>+{overflow.length}</button>}
      {active.map((item) => <button key={item.id} className={`activity-chip is-${item.tone || 'info'}`} onClick={() => choose(item)} title={item.text}>{item.run?.status === 'running' && item.run.total > 0 ? `${item.run.done}/${item.run.total} · ` : ''}{item.run?.status === 'done' ? '✓ ' : item.run?.status === 'failed' ? '✕ ' : ''}{item.text}{item.action ? ` · ${item.action.label}` : ''}</button>)}
      <span className={`activity-model-state${consoleState?.running?.length ? ' is-busy' : ''}`}>{consoleState?.error ? t('activity.needsAttention') : consoleState?.running?.length ? t(AGENT_ACTIVITY[consoleState.running[0].agent] || 'activity.working') : t('activity.idle')}</span>
      <button className="activity-history-button" aria-label="Activity history" onClick={() => setHistoryOpen(!historyOpen)}>◷</button>
      <button className="activity-console-button" onClick={onConsole}>Console</button>
    </footer>
  </>;
}
