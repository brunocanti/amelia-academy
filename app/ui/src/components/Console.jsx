import { useEffect, useRef, useState } from 'react';
import { api } from '../lib/api.js';
import './console.css';

const POLL_OPEN_MS = 1500;
const POLL_CLOSED_MS = 4000;
const MAX_LINES = 400;
const OPEN_KEY = 'academy.console.open';

const number = (n) => (n || 0).toLocaleString();
const clock = (at) => new Date(at).toLocaleTimeString();

function plural(n, one, many = `${one}s`) {
  return `${number(n)} ${n === 1 ? one : many}`;
}

function lineText(line) {
  if (line.kind === 'outcome') return `${line.where}: kept ${line.kept}, turned down ${line.turned_down}`;
  return line.error || line.text || '';
}

function isBad(line) {
  return Boolean(line.error) || (line.kind === 'outcome' && line.turned_down > 0);
}

// What the agent is writing right now, following the end of the text.
function Live({ now, name }) {
  const box = useRef(null);
  useEffect(() => {
    if (box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [now.text]);
  return (
    <div className="console-live">
      <h4>{name} · writing now · {number(now.tokens)} tokens · {Math.round(now.seconds)} s</h4>
      <pre ref={box}>{now.text || 'Waiting for the first words…'}</pre>
    </div>
  );
}

function Line({ line, who }) {
  const [open, setOpen] = useState(false);
  const [whole, setWhole] = useState(null);
  const [gone, setGone] = useState('');

  async function toggle() {
    if (!open && line.kind === 'call' && !whole) {
      try {
        setWhole(await api.readConsoleLine(line.seq));
      } catch (e) {
        setGone(e.message);
      }
    }
    setOpen(!open);
  }

  return (
    <li className={`console-line${line.error ? ' is-error' : ''}`}>
      <button className="console-line-row" title={open ? 'Hide the details' : line.kind === 'call' ? 'Show what was asked and what came back' : 'Show the details'} onClick={toggle} aria-expanded={open}>
        <time>{clock(line.at)}</time>
        <strong title={line.agent}>{who(line.agent)}</strong>
        <span className="console-line-text">{lineText(line)}</span>
        {line.kind === 'call' && (
          <small>{number(line.prompt_tokens)} in · {number(line.output_tokens)} out · {line.seconds} s</small>
        )}
      </button>
      {open && (
        <div className="console-line-whole">
          {gone && <p>{gone}</p>}
          {line.reasons?.length > 0 && <ul>{line.reasons.map((reason, i) => <li key={i}>{reason}</li>)}</ul>}
          {line.kind === 'outcome' && !line.reasons?.length && <p>Nothing turned down.</p>}
          {line.kind === 'problem' && <p>{line.error}</p>}
          {whole && (
            <>
              <h4>Asked</h4>
              <pre>{whole.prompt}</pre>
              <h4>Replied</h4>
              <pre>{whole.reply || whole.error || 'Nothing.'}</pre>
            </>
          )}
        </div>
      )}
    </li>
  );
}

// The foot of the page: one line says what the model is doing; opening it shows every call and how it went.
export function Console() {
  const [open, setOpen] = useState(() => localStorage.getItem(OPEN_KEY) === '1');
  const [state, setState] = useState(null);
  const [lines, setLines] = useState([]);
  const [failed, setFailed] = useState('');
  const [onlyProblems, setOnlyProblems] = useState(false);
  const seen = useRef(0);

  useEffect(() => {
    let stopped = false;
    let timer;
    async function poll() {
      try {
        const next = await api.readConsole(seen.current);
        if (stopped) return;
        const restarted = next.last_seq < seen.current;
        seen.current = next.last_seq;
        setState(next);
        setFailed('');
        window.dispatchEvent(new CustomEvent('academy-console-state', { detail: next }));
        if (restarted) setLines([]);
        else if (next.lines.length) setLines((old) => [...old, ...next.lines].slice(-MAX_LINES));
      } catch (e) {
        if (!stopped) { setFailed(e.message); window.dispatchEvent(new CustomEvent('academy-console-state', { detail: { error: e.message } })); }
      }
      if (!stopped) timer = setTimeout(poll, open ? POLL_OPEN_MS : POLL_CLOSED_MS);
    }
    poll();
    return () => { stopped = true; clearTimeout(timer); };
  }, [open]);

  useEffect(() => {
    const toggle = () => setOpen((current) => { localStorage.setItem(OPEN_KEY, current ? '0' : '1'); return !current; });
    window.addEventListener('academy-console-toggle', toggle);
    return () => window.removeEventListener('academy-console-toggle', toggle);
  }, []);

  const group = state?.agents || [];
  const named = Object.fromEntries(group.map((agent) => [agent.name, agent]));
  const who = (name) => named[name]?.nickname || 'Unnamed';
  const all = state ? [...group, { ...state.unnamed, name: '', nickname: 'Unnamed' }] : [];
  const sum = (key) => all.reduce((total, agent) => total + agent[key], 0);
  const tokens = sum('prompt_tokens') + sum('output_tokens');
  const problems = state ? sum('problems') : 0;
  const turnedDown = state ? sum('turned_down') : 0;
  const now = state?.running[0];
  const shown = (onlyProblems ? lines.filter(isBad) : lines).slice().reverse();

  return (
    <section className={`console${open ? ' is-open' : ''}`} aria-label="Console">
      {open && state && (
        <div className="console-body">
          <table className="console-agents">
            <thead>
              <tr><th>Agent</th><th>Calls</th><th>Tokens</th><th>Problems</th><th>Kept</th><th>Turned down</th></tr>
            </thead>
            <tbody>
              {group.map((agent) => (
                <tr key={agent.name} className={agent.calls ? '' : 'is-quiet'} title={agent.doing}>
                  <td><strong>{agent.nickname}</strong><code>{agent.name}</code></td>
                  <td>{number(agent.calls)}</td>
                  <td>{number(agent.prompt_tokens + agent.output_tokens)}</td>
                  <td className={agent.problems ? 'console-bad' : ''}>{number(agent.problems)}</td>
                  <td>{number(agent.kept)}</td>
                  <td>{number(agent.turned_down)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="console-log">
            {now && now.text !== undefined && <Live now={now} name={who(now.agent)} />}
            <label className="console-filter">
              <input type="checkbox" checked={onlyProblems} onChange={(e) => setOnlyProblems(e.target.checked)} /> Only what went wrong
            </label>
            {shown.length === 0 && <p className="console-empty">{onlyProblems ? 'Nothing went wrong.' : 'Nothing yet since the server started.'}</p>}
            <ol>{shown.map((line) => <Line key={line.seq} line={line} who={who} />)}</ol>
          </div>
        </div>
      )}
    </section>
  );
}
