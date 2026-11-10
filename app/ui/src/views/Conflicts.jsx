import { useCallback, useEffect, useRef, useState } from 'react';
import { Button } from '../components/Button.jsx';
import { Expander } from '../components/Expander.jsx';
import { PILLAR_COLOR, KIND_LABEL } from '../lib/pillars.js';
import { useRuns } from '../components/Runs.jsx';

const POLL_MS = 1500;

const BOTH_TIP = 'Both stay, and this stops being a conflict. You can undo this.';
const DEPENDS_TIP = 'Saves one pair that holds both sides, for you to review. You can undo this.';

// Each conflict is one plain question with short answers. What sits behind them stays out of sight.
const KINDS = {
  known_disagree: {
    question: 'Which one is right?',
    picks: ['This one', 'This one'],
    answers: [{ label: 'Both are right', resolution: 'no_conflict', tip: BOTH_TIP }, { label: 'It depends', write: 'complex', tip: DEPENDS_TIP }],
    done: { no_conflict: 'Both stay' },
  },
  false_confirmed: {
    question: 'Which one is right?',
    picks: ['It really is false', 'This one'],
    answers: [{ label: 'Both are right', resolution: 'no_conflict', tip: BOTH_TIP }, { label: 'It depends', write: 'complex', tip: DEPENDS_TIP }],
    done: { no_conflict: 'Both stay' },
  },
  false_unsettled: {
    question: 'Is this claim wrong, based on the quote?',
    answers: [{ label: 'Yes', resolution: 'no_conflict', tip: 'The claim stays as it is. You can undo this.' }, { label: 'No, set it aside', resolution: 'keep_second', primary: true, tip: 'The claim is set aside. You can undo this.' }],
    done: { no_conflict: 'The claim stays', keep_second: 'Set aside' },
  },
  doubt_answered: {
    question: 'Does this answer the question?',
    answers: [{ label: 'Yes', write: 'answer', primary: true, tip: 'Saves the answer as a new pair for you to review. You can undo this.' }, { label: 'Partly', write: 'complex', tip: 'Saves what the passage does and does not answer, for you to review. You can undo this.' }, { label: 'No', resolution: 'no_conflict', tip: 'The doubt stays as it is. You can undo this.' }],
    done: { no_conflict: 'The doubt stays' },
  },
};

const RESOLVED = {
  keep_first: 'Kept the first, set the other aside',
  keep_second: 'Kept the second, set the other aside',
  complex: 'Saved a new pair to review',
  answer: 'Saved a new pair to review',
  no_conflict: 'Not a conflict',
};

const resolvedLabel = (kind, resolution) => KINDS[kind]?.done?.[resolution] || RESOLVED[resolution];

function Side({ sample, quote, quoteSource, quotePage, label, action, onKeep, busy }) {
  const shown = quote || sample?.quote;
  const where = quoteSource || sample?.source_name;
  const page = quotePage ?? sample?.page;
  return (
    <article className="qa-side-card" style={sample ? { '--pillar': PILLAR_COLOR[sample.pillar] } : undefined}>
      <small className="qa-side-kind"><i />{label}</small>
      {sample?.false_claim && <p className="qa-side-claim">{sample.false_claim}</p>}
      {sample && !sample.false_claim && (
        <>
          <p className="qa-side-q">{sample.question}</p>
          <p className="qa-side-a">{sample.answer}</p>
        </>
      )}
      {shown && <blockquote>{shown}</blockquote>}
      {where && <small className="qa-muted">{where}{page ? ` · page ${page}` : ''}</small>}
      {action && <Button className="qa-side-pick" disabled={busy} title="Keeps this one and sets the other aside. You can undo this." onClick={onKeep}>{action}</Button>}
    </article>
  );
}

function Conflict({ conflict, api, model, language, onChanged, onError }) {
  const [writing, setWriting] = useState(''); // the resolution a person writes, when the model could not
  const [why, setWhy] = useState('');
  const [drafting, setDrafting] = useState(''); // the answer the model is writing right now
  const [question, setQuestion] = useState(conflict.draft_question || conflict.first.question);
  const [answer, setAnswer] = useState('');
  const [busy, setBusy] = useState(false);
  const words = KINDS[conflict.kind];
  const evidence = [conflict.quote, conflict.first.quote, conflict.second?.quote].filter(Boolean).join('\n');

  // The choice is enough: the model writes it and it waits in To review. Only when that fails does a person write.
  async function choose(label, kind) {
    const stored = kind === 'answer' ? conflict.draft_answer : conflict.draft_complex;
    if (!stored && !model) {
      setWhy('Choose a model at the top to have this written, or write it here.');
      setAnswer('');
      setWriting(kind);
      return;
    }
    setBusy(true);
    setDrafting(label);
    onError('');
    try {
      await api.resolveConflict(conflict.id, { resolution: kind, model });
      await onChanged({ id: conflict.id, label: resolvedLabel(conflict.kind, kind) });
    } catch (e) {
      setWhy(`${e.message} You can write it here or try again.`);
      setAnswer(stored || '');
      setWriting(kind);
    } finally {
      setBusy(false);
      setDrafting('');
    }
  }

  async function resolve(resolution, written = {}) {
    setBusy(true);
    onError('');
    setWhy('');
    try {
      await api.resolveConflict(conflict.id, { resolution, ...written });
      await onChanged({ id: conflict.id, label: resolvedLabel(conflict.kind, resolution) });
    } catch (e) {
      onError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const doubt = conflict.kind === 'doubt_answered';
  const unsettled = conflict.kind === 'false_unsettled';
  const [firstPick, secondPick] = words.picks || [];
  return (
    <section className="qa-conflict">
      <header>
        <strong>{words.question}</strong>
        {conflict.kind !== 'doubt_answered' && <p className="qa-muted">{conflict.why}</p>}
      </header>
      <div className="qa-conflict-sides">
        <Side sample={conflict.first} label={KIND_LABEL[conflict.first.origin]} busy={busy}
              action={firstPick} onKeep={() => resolve('keep_first')} />
        {unsettled ? null : doubt ? (
          <Side quote={conflict.quote} quoteSource={conflict.quote_source} quotePage={conflict.quote_page} label="What a passage says" />
        ) : (
          <Side sample={conflict.second} label={KIND_LABEL[conflict.second.origin]} busy={busy}
                action={secondPick} onKeep={() => resolve('keep_second')} />
        )}
      </div>
      {writing ? (
        <div className="qa-conflict-write">
          {why && <p className="qa-bad">{why}</p>}
          <label className="qa-field">Question<textarea rows={2} value={question} onChange={(e) => setQuestion(e.target.value)} /></label>
          <Expander field="question" text={question} context={evidence} language={language} model={model} onUse={setQuestion} />
          <label className="qa-field">Answer
            <textarea rows={4} value={answer} onChange={(e) => setAnswer(e.target.value)}
                      placeholder={writing === 'answer' ? 'What the passage says.' : 'Both positions, and that they stand in tension.'} />
          </label>
          <Expander field="answer" text={answer} context={evidence} language={language} model={model} onUse={setAnswer} />
          <div className="qa-pair-actions">
            <Button variant="primary" disabled={busy || !question.trim() || !answer.trim()} title="Saves this as a new pair to review." onClick={() => resolve(writing, { question, answer })}>Save</Button>
            <Button variant="ghost" disabled={busy} title="Closes this without saving." onClick={() => { setWriting(''); setWhy(''); }}>Cancel</Button>
          </div>
        </div>
      ) : (
        <footer className="qa-conflict-answers">
          {words.answers.map(({ label, resolution, write: writes, primary, tip }) => (
            <Button key={label} variant={primary ? 'primary' : 'secondary'} disabled={busy} title={tip} onClick={() => (writes ? choose(label, writes) : resolve(resolution))}>{drafting === label ? 'Writing…' : label}</Button>
          ))}
        </footer>
      )}
    </section>
  );
}

// Every pair that needs a person's choice: what does not hold against the rest, then whatever else the screen passes in.
export function Conflicts({ project, api, model, onChanged, onError, onCount, fits, alsoHere = 0, children }) {
  const [open, setOpen] = useState(null);
  const [resolved, setResolved] = useState([]);
  const [report, setReport] = useState(null);
  const [running, setRunning] = useState(false);
  const { runsChanged, resume, refresh: refreshRuns } = useRuns();
  const [showResolved, setShowResolved] = useState(false);
  const [lastDone, setLastDone] = useState(null);
  const alive = useRef(true);

  const load = useCallback(async () => {
    const [o, r, rep] = await Promise.all([api.listConflicts(), api.listConflicts('resolved'), api.challenge()]);
    if (!alive.current) return;
    setOpen(o);
    setResolved(r);
    setReport(rep);
    setRunning(rep.latest?.status === 'running');
    onCount?.(o.length);
  }, [api, onCount]);

  useEffect(() => {
    alive.current = true;
    load().catch((e) => onError(e.message));
    return () => { alive.current = false; };
  }, [load, onError, runsChanged]);

  useEffect(() => {
    if (!running) return undefined;
    const timer = setInterval(() => load().catch((e) => onError(e.message)), POLL_MS);
    return () => clearInterval(timer);
  }, [running, load, onError]);

  async function start() {
    if (!model) { onError('Choose a model at the top first.'); return; }
    onError('');
    try {
      await api.runChallenge(model);
    } catch (e) {
      onError(e.message);
    }
    await Promise.all([load().catch((e) => onError(e.message)), refreshRuns()]);
  }

  async function goOn() {
    onError('');
    await resume('challenge', project.id);
    await load().catch((e) => onError(e.message));
  }

  async function changed(done) {
    setLastDone(done);
    await load();
    await onChanged();
  }

  async function reopen(id) {
    onError('');
    try {
      await api.reopenConflict(id);
      setLastDone(null);
      await load();
      await onChanged();
    } catch (e) {
      onError(e.message);
    }
  }

  const latest = report?.latest;
  const progress = latest?.total ? Math.round((latest.done / latest.total) * 100) : 0;
  const shown = open?.filter((conflict) => !fits || [conflict.first, conflict.second].some((pair) => pair && fits(pair)));
  const nothing = shown?.length === 0 && alsoHere === 0 && !running;
  const canGoOn = !running && (latest?.status === 'stopped' || latest?.status === 'failed');
  return (
    <>
      <div className="qa-challenge">
        <div className="qa-grow">
          <strong>Challenge</strong>
          <p className="qa-muted">Puts what is known, what is false and what is not known against each other. What does not hold shows up here, and nothing changes until you choose.</p>
          {running && (
            <div className="qa-run">
              <span>{latest?.total ? `${latest.done} of ${latest.total} comparisons` : 'Choosing what to compare…'}</span>
              <div className="qa-track"><span style={{ width: `${progress}%` }} /></div>
            </div>
          )}
          {!running && latest?.status === 'failed' && <p className="qa-bad">{latest.error}</p>}
          {!running && latest?.status === 'stopped' && (
            <p className="qa-muted">Stopped at {latest.done} of {latest.total}. What was compared stays.{latest.error ? ` ${latest.error}.` : ''}</p>
          )}
          {!running && latest?.status === 'succeeded' && (
            <p className="qa-muted">Last run: {latest.total} comparison(s), {latest.conflicts} new conflict(s), {new Date(latest.finished_at).toLocaleString()}.</p>
          )}
        </div>
        {canGoOn && <Button variant="primary" title="Picks up where it stopped. What was compared stays." onClick={goOn}>Continue</Button>}
        <Button variant={canGoOn ? 'ghost' : 'primary'} disabled={running || !model} title={model ? 'Compares everything from the start. Nothing changes until you choose.' : 'Choose a model at the top first.'} onClick={start}>
          {running ? 'Challenging…' : latest ? 'Challenge again' : 'Run the challenge'}
        </Button>
      </div>

      {lastDone && (
        <div className="qa-notice">{lastDone.label}. <button className="qa-link" title="Brings this question back to decide again." onClick={() => reopen(lastDone.id)}>Undo</button></div>
      )}

      {open === null && <p className="qa-empty">Loading…</p>}
      {nothing && <p className="qa-empty">{open.length > 0 ? 'Nothing to decide here. Other filters have more.' : latest ? 'Nothing to decide.' : 'Nothing to decide yet. Run the challenge to look for pairs that disagree.'}</p>}
      {shown?.map((conflict) => (
        <Conflict key={conflict.id} conflict={conflict} api={api} model={model} language={project.language} onChanged={changed} onError={onError} />
      ))}
      {children}

      {resolved.length > 0 && (
        <button className="qa-link qa-back" title="The questions you already decided." onClick={() => setShowResolved(!showResolved)}>{showResolved ? 'Hide' : 'Show'} {resolved.length} resolved</button>
      )}
      {showResolved && resolved.map((conflict) => (
        <div className="qa-conflict-done" key={conflict.id}>
          <span className="qa-grow"><strong>{conflict.first.question}</strong><small className="qa-muted"> {resolvedLabel(conflict.kind, conflict.resolution)}</small></span>
          <button className="qa-link" title="Brings this question back to decide again." onClick={() => reopen(conflict.id)}>Reopen</button>
        </div>
      ))}
    </>
  );
}
