import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { projectApi } from '../lib/api.js';
import { Button } from './Button.jsx';
import { useI18n } from '../i18n/index.jsx';

const FAST_MS = 1200;
const SLOW_MS = 5000;
const HIDDEN_KEY = 'academy.runs.hidden';

const Runs = createContext(null);
export const useRuns = () => useContext(Runs);

const mark = (run) => `${run.key}@${run.started_at}`;

function storedHidden() {
  try { return JSON.parse(localStorage.getItem(HIDDEN_KEY) || '[]'); } catch { return []; }
}

// What is going on in a project, known above the screens, so leaving a screen changes nothing.
export function RunsProvider({ projectId, children }) {
  const api = useMemo(() => projectApi(projectId), [projectId]);
  const [runs, setRuns] = useState([]);
  const [runsChanged, setRunsChanged] = useState(0);
  const [trouble, setTrouble] = useState('');
  const [notices, setNotices] = useState([]);
  const notify = useCallback(({ text, tone = 'info', action, ms } = {}) => {
    const id = `${Date.now()}-${Math.random()}`;
    const item = { id, text, tone, action, expires: ms ?? (action ? 10000 : tone === 'error' ? 0 : 5000) };
    setNotices((old) => [...old.filter((n) => n.text !== text), item]);
    const historyKey = `academy.activity.history.${projectId}`;
    try {
      const history = JSON.parse(sessionStorage.getItem(historyKey) || '[]');
      history.push({ id, text, tone, at: new Date().toISOString(), projectId });
      sessionStorage.setItem(historyKey, JSON.stringify(history.slice(-30)));
    } catch { /* Session history is best effort; live actions stay in memory. */ }
    if (item.expires) setTimeout(() => setNotices((old) => old.filter((n) => n.id !== id)), item.expires);
    return id;
  }, [projectId]);
  const dismiss = useCallback((id) => setNotices((old) => old.filter((n) => n.id !== id)), []);
  const known = useRef(null);

  const refresh = useCallback(async () => {
    try {
      const next = await api.listRuns();
      const before = known.current;
      known.current = new Map(next.map((run) => [mark(run), run.status]));
      if (before && next.some((run) => before.get(mark(run)) !== run.status)) setRunsChanged((n) => n + 1);
      setRuns(next);
      setTrouble('');
      return next;
    } catch (e) {
      setTrouble(e.message);
      return null;
    }
  }, [api]);

  useEffect(() => {
    let gone = false;
    let timer;
    async function poll() {
      const next = await refresh();
      if (!gone) timer = setTimeout(poll, next?.some((run) => run.status === 'running') ? FAST_MS : SLOW_MS);
    }
    poll();
    return () => { gone = true; clearTimeout(timer); };
  }, [refresh]);

  const act = useCallback(async (fn) => {
    setTrouble('');
    try { await fn(); } catch (e) { setTrouble(e.message); }
    await refresh();
  }, [refresh]);

  const value = useMemo(() => {
    const find = (kind, subject) => runs.find((run) => run.kind === kind && run.subject === subject);
    return {
      runs,
      notices, notify, dismiss,
      runsChanged,
      trouble,
      find,
      isRunning: (kind, subject) => find(kind, subject)?.status === 'running',
      refresh,
      stop: (kind, subject) => act(() => api.stopRun(kind, subject)),
      resume: (kind, subject) => act(() => api.continueRun(kind, subject)),
    };
  }, [runs, runsChanged, trouble, refresh, act, api, notices, notify, dismiss]);

  return <Runs.Provider value={value}>{children}</Runs.Provider>;
}

const count = (run) => (run.total > 0 && run.done > 0 ? `${run.done} of ${run.total}` : '');

function Row({ run, onGo, onStop, onResume, onHide }) {
  const { t } = useI18n();
  const title = (
    <button type="button" className="runs-title" title="Go to it" onClick={() => onGo(run.where.view, run.where.params)}>{run.title}</button>
  );
  if (run.status === 'running') {
    const progress = /^Checking pair (\d+) of (\d+)$/.exec(run.message || '');
    const figureProgress = /^Reading figure (\d+) of (\d+)$/.exec(run.message || '');
    const progressText = progress ? t('runs.challengeProgress', { current: progress[1], total: progress[2] })
      : figureProgress ? t('runs.figureProgress', { current: figureProgress[1], total: figureProgress[2] }) : run.message;
    return (
      <div className="runs-row">
        {title}
        <span className="qa-muted">{run.stopping ? 'Stopping when the model answers…' : run.waiting ? 'Waiting for the file before it' : progressText || count(run) || 'Working…'}</span>
        {run.total > 0 && <div className="qa-track runs-track"><span style={{ width: `${Math.round((run.done / run.total) * 100)}%` }} /></div>}
        <span className="qa-gap" />
        <Button variant="ghost" disabled={run.stopping} title="Stops as soon as the model can. What is done stays." onClick={onStop}>{run.stopping ? 'Stopping…' : 'Stop'}</Button>
      </div>
    );
  }
  const stopped = run.status === 'stopped';
  const failed = run.status === 'failed';
  return (
    <div className={`runs-row is-${run.status}`}>
      {title}
      {stopped && <span>Stopped{count(run) && ` at ${count(run)}`}. What is done stays.</span>}
      {failed && <span className="qa-bad">Failed: {run.error}</span>}
      {run.message && <span className="qa-muted">{run.message}</span>}
      {run.status === 'done' && !run.message && <span className="qa-muted">Finished.</span>}
      <span className="qa-gap" />
      {run.can_continue && <Button variant="primary" title="Picks up where it stopped. What is done stays." onClick={onResume}>Continue</Button>}
      <Button variant="ghost" title="Hides this line. Nothing is lost." onClick={onHide}>{run.can_continue ? 'Not now' : 'OK'}</Button>
    </div>
  );
}

// One line per run, above every screen. Stop lives here, so it is in the same place wherever the person went.
export function RunsStrip({ onGo }) {
  const { runs, trouble, stop, resume } = useRuns();
  const [hidden, setHidden] = useState(storedHidden);

  function hide(run) {
    const next = [...hidden, mark(run)].slice(-200);
    localStorage.setItem(HIDDEN_KEY, JSON.stringify(next));
    setHidden(next);
  }

  const shown = runs.filter((run) => run.status === 'running' || !hidden.includes(mark(run)));
  if (!shown.length && !trouble) return null;
  return (
    <section className="runs" aria-label="What is running">
      {trouble && <div className="qa-error">{trouble}</div>}
      {shown.map((run) => (
        <Row key={run.key} run={run} onGo={onGo} onHide={() => hide(run)}
             onStop={() => stop(run.kind, run.subject)} onResume={() => resume(run.kind, run.subject)} />
      ))}
    </section>
  );
}
