import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import { projectApi } from '../lib/api.js';
import { useProjects } from '../ProjectContext.jsx';
import { Panel } from '../components/Panel.jsx';
import { Card } from '../components/Card.jsx';
import { Button } from '../components/Button.jsx';
import { Expander } from '../components/Expander.jsx';
import { PillarBar } from '../components/PillarBar.jsx';
import { PILLARS, PILLAR_COLOR, KIND_LABEL, arrangeByPillar } from '../lib/pillars.js';
import { CurationReview } from '../components/CurationReview.jsx';
import { Conflicts } from './Conflicts.jsx';
import { useRuns } from '../components/Runs.jsx';
import { useI18n } from '../i18n/index.jsx';

// three.js is heavy; only someone who opens the graph downloads it.
const BrainGraph = lazy(() => import('../components/BrainGraph.jsx').then((m) => ({ default: m.BrainGraph })));

const FILTERS = [['proposed', 'To review', 'Pairs waiting for your decision'], ['approved', 'Approved', 'Pairs that go to the export'], ['rejected', 'Rejected', 'Pairs left out of the export'], ['', 'All', 'Every pair, whatever you decided']];
const POLL_MS = 4000;
const ASKED = new Set(['connect', 'refusals', 'neighbours', 'premises']);
const VIEWS = [['list', 'List', 'See the pairs one by one'], ['graph', 'Graph', 'See how pairs, themes and files connect'], ['decide', 'Decide', 'Pairs side by side that need your choice: they disagree, or they say the same thing']];
const pillarLabel = (key) => PILLARS.find((p) => p.key === key)?.label;
const ORIGIN_NOTE = {
  file: 'The files answer this question: the quote proves the answer.',
  refusal: 'The files do not give this detail, and the answer says so. Approve if a model would otherwise make it up. If a model could work it out by reasoning, reject it.',
  neighbour: 'Another subject, not in the files. Approve if the answer marks the limit first, and the general part is right, short and does not mix the two subjects. The files do not check this answer.',
  false_premise: 'Approve if the question really is wrong and the answer corrects it.',
  true_premise: 'Approve if the question is right and the answer confirms it.',
  complex: 'Two things the files say stand in tension, and this answer holds both. Approve if it gives both fairly and does not invent a reason.',
};

// Behavior answers come from the card, not the files. A pair still worth keeping without the card is teaching a fact.
const VARIATION = {
  positive: ['Clear case', 'The card applies. Approve if the answer does what the card says. If the pair would still be worth keeping without the card, it teaches a fact: reject it. The files do not check this answer.'],
  edge_cases: ['Edge case', 'A hard case the card still covers. Approve if the answer still does what the card says. If the pair would still be worth keeping without the card, it teaches a fact: reject it. The files do not check this answer.'],
  negative: ['Should not apply', 'This variation is no longer written. Negatives are now Unanswered, False premise and Neighbouring subject. The files do not check this answer.'],
};

const CHANGEABLE = ['file', 'false_premise', 'refusal', 'neighbour'].map((key) => [key, KIND_LABEL[key]]);
const KIND_NEEDS = {
  file: 'Needs an answer that comes from the quote. The pair goes back to review.',
  refusal: 'Needs an answer that says, in the first person and without naming the files, that this is not known. The quote is removed and the pair moves to the theme of what is not known.',
  neighbour: 'Needs an answer that first says, in the first person, that this is not what was studied, then answers in general in one or two sentences, with no numbers. The quote is removed and the pair moves to the theme of what is not known.',
  false_premise: 'Needs the wrong claim, a question built on it and an answer that corrects it. The pair goes back to review.',
};

const wordsOf = (text) => text.toLowerCase().match(/[\p{L}\p{N}]+/gu) || [];

// The words only this question has: where two look alike, the difference is what decides.
function Differences({ text, others }) {
  const shared = new Set(others.flatMap(wordsOf));
  return text.split(/(\s+)/).map((piece, index) => (
    wordsOf(piece).some((word) => !shared.has(word)) ? <mark className="qa-diff" key={index}>{piece}</mark> : piece
  ));
}

function Pair({ sample, themes, api, onChanged, onError, onUndoable, model, language, compareWith, onKeep }) {
  const [editing, setEditing] = useState(false);
  const [question, setQuestion] = useState(sample.question);
  const [answer, setAnswer] = useState(sample.answer);
  const [claim, setClaim] = useState(sample.false_claim || '');
  const [kind, setKind] = useState(sample.origin);
  const [quote, setQuote] = useState('');
  const [theme, setTheme] = useState('');
  const [busy, setBusy] = useState(false);

  async function act(fn) {
    setBusy(true);
    onError('');
    try {
      await fn();
      await onChanged();
      return true;
    } catch (e) {
      onError(e.message);
      return false;
    } finally {
      setBusy(false);
    }
  }

  // Clicking is safe: the way back shows the moment the pair leaves the list.
  function decide(request, label) {
    const back = { approved: api.approve, rejected: api.reject, proposed: api.resetSample }[sample.status];
    return act(async () => {
      await request(sample.id);
      onUndoable(label, () => back(sample.id));
    });
  }

  const variation = sample.origin === 'behavior' ? VARIATION[sample.variation_type] : null;
  const changing = kind !== sample.origin;
  const canChange = CHANGEABLE.some(([value]) => value === sample.origin);
  const outsideFiles = kind === 'refusal' || kind === 'neighbour';
  const needsQuote = changing && !outsideFiles && !sample.quote;
  const inLimits = themes.find((t) => t.id === sample.theme_id)?.kind === 'limits';
  const needsTheme = changing && !outsideFiles && inLimits;
  const showClaim = changing ? kind === 'false_premise' : sample.origin === 'false_premise';

  const groundedIn = (quote || sample.quote) ? `What the files say: ${quote || sample.quote}` : '';

  function stopEditing() {
    setEditing(false);
    setQuestion(sample.question);
    setAnswer(sample.answer);
    setClaim(sample.false_claim || '');
    setKind(sample.origin);
    setQuote('');
    setTheme('');
  }

  async function save() {
    const request = changing
      ? () => api.changeKind(sample.id, { origin: kind, question, answer, quote, false_claim: claim, theme_id: theme || null })
      : () => api.editSample(sample.id, sample.origin === 'false_premise' ? { question, answer, false_claim: claim } : { question, answer });
    if (await act(request)) {
      setEditing(false);
      setQuote('');
      setTheme('');
    }
  }

  return (
    <Card className={`qa-pair is-${sample.status}`} style={{ '--pillar': PILLAR_COLOR[sample.pillar] }}>
      {KIND_LABEL[sample.origin] && (
        <small className="qa-origin" title={ORIGIN_NOTE[sample.origin]}>
          <i className="qa-origin-dot" />
          {pillarLabel(sample.pillar)}
          {KIND_LABEL[sample.origin] !== pillarLabel(sample.pillar) && <em> · {KIND_LABEL[sample.origin]}</em>}
          {variation && <b className={`qa-variation is-${sample.variation_type}`}>{variation[0]}</b>}
        </small>
      )}
      {variation && <p className="qa-check">{variation[1]}</p>}
      {sample.review_note && <p className="qa-bad">{sample.review_note}</p>}
      {editing ? (
        <>
          {canChange && (
            <label className="qa-field">Kind
              <select value={kind} onChange={(e) => setKind(e.target.value)}>
                {CHANGEABLE.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
          )}
          {changing && <p className="qa-kind-needs">{KIND_NEEDS[kind]}</p>}
          {needsTheme && (
            <label className="qa-field">Theme
              <select value={theme} onChange={(e) => setTheme(e.target.value)}>
                <option value="">Choose a theme</option>
                {themes.filter((t) => t.kind !== 'limits').map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}
              </select>
            </label>
          )}
          {needsQuote && (
            <label className="qa-field">Quote from the files<textarea rows={3} value={quote} onChange={(e) => setQuote(e.target.value)} /></label>
          )}
          {showClaim && (
            <>
              <label className="qa-field">False claim<textarea rows={2} value={claim} onChange={(e) => setClaim(e.target.value)} /></label>
              <Expander field="false_claim" text={claim} language={language} model={model} onUse={setClaim} context={groundedIn} />
            </>
          )}
          <label className="qa-field">Question<textarea rows={2} value={question} onChange={(e) => setQuestion(e.target.value)} /></label>
          <Expander field="question" text={question} language={language} model={model} onUse={setQuestion} context={groundedIn} />
          <label className="qa-field">Answer<textarea rows={4} value={answer} onChange={(e) => setAnswer(e.target.value)} /></label>
          <Expander field="answer" text={answer} language={language} model={model} onUse={setAnswer}
                    context={`Question: ${question}\n${groundedIn}`} />
        </>
      ) : (
        <>
          {sample.origin === 'false_premise' && <p className="qa-wrong"><b>Wrong:</b> {sample.false_claim}</p>}
          <p className="qa-q">{compareWith ? <Differences text={sample.question} others={compareWith} /> : sample.question}</p>
          <p className="qa-a">{sample.answer}</p>
        </>
      )}
      {sample.quote && (
        <blockquote className="qa-quote">
          “{sample.quote}”
          <footer>{sample.source_name}{sample.page ? ` · page ${sample.page}` : ''}</footer>
        </blockquote>
      )}
      {sample.based_on?.length > 0 && (
        <details className="qa-why">
          <summary>{sample.origin === 'connection' ? `Rests on ${sample.based_on.length} pairs` : 'Starts from this pair'}</summary>
          {sample.based_on.map((p) => (
            <blockquote className="qa-quote" key={p.id}>
              {p.question} <em>{p.status === 'approved' ? '' : `(${p.status})`}</em>
              <footer>“{p.quote}” · {p.source_name}{p.page ? ` · page ${p.page}` : ''}</footer>
            </blockquote>
          ))}
        </details>
      )}
      <CurationReview sample={sample} api={api} model={model} language={language} onChanged={onChanged} onError={onError} onUndoable={onUndoable} />
      <div className="qa-pair-actions">
        {editing ? (
          <>
            <Button variant="primary" disabled={busy} title="Saves your changes to this pair." onClick={save}>Save</Button>
            <Button variant="ghost" disabled={busy} title="Drops your changes." onClick={stopEditing}>Cancel</Button>
          </>
        ) : (
          <>
            {onKeep && <Button variant="primary" disabled={busy} title="Rejects the others in this group. This pair keeps its status." onClick={() => act(onKeep)}>Keep this one</Button>}
            {sample.status !== 'approved' && <Button variant={onKeep ? 'secondary' : 'primary'} disabled={busy} title="This pair goes to the export. You can send it back to review." onClick={() => decide(api.approve, 'Approved.')}>Approve</Button>}
            {sample.status !== 'rejected' && <Button disabled={busy} title="This pair stays out of the export. You can send it back to review." onClick={() => decide(api.reject, 'Rejected.')}>Reject</Button>}
            {sample.status !== 'proposed' && <Button variant="ghost" disabled={busy} title="Undoes your decision. The pair waits for review again." onClick={() => decide(api.resetSample, 'Back to review.')}>Back to review</Button>}
            <Button variant="ghost" disabled={busy} title="Change this pair yourself." onClick={() => setEditing(true)}>Edit</Button>
          </>
        )}
        <span className="qa-gap" />
        <select aria-label="Theme" value={sample.theme_id} disabled={busy}
                onChange={(e) => act(() => api.editSample(sample.id, { theme_id: e.target.value }))}>
          {themes.map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}
        </select>
      </div>
    </Card>
  );
}

function SimilarGroup({ group, ...pair }) {
  const { api, onChanged, onError, onUndoable, themes } = pair;
  const members = group.samples;
  const ids = members.map((s) => s.id);
  const samePassage = members.every((s) => s.chunk_id && s.chunk_id === members[0].chunk_id);
  const sameTheme = members.every((s) => s.theme_id === members[0].theme_id);
  const where = samePassage ? 'same passage' : sameTheme ? themes.find((t) => t.id === members[0].theme_id)?.title : 'different themes';

  async function keepOne(sample) {
    const others = members.filter((s) => s.id !== sample.id);
    await api.keepOne(sample.id, ids);
    onUndoable(`Kept one, rejected ${others.length}.`, () => Promise.all(others.map((s) => (s.status === 'approved' ? api.approve(s.id) : api.resetSample(s.id)))));
  }

  async function keepAll() {
    onError('');
    try {
      await api.keepApart(ids);
      onUndoable(`Kept all ${ids.length}. They will not be shown together again.`, () => api.keepApart(ids, true));
      await onChanged();
    } catch (e) {
      onError(e.message);
    }
  }

  return (
    <section className="qa-similar">
      <header>
        <strong>Do these say the same thing?</strong>
        {where && <small className="qa-muted">{where}</small>}
        <span className="qa-gap" />
        <Button variant="ghost" title="They ask different things. Each pair stays as it is." onClick={keepAll}>Keep all</Button>
      </header>
      <p className="qa-muted qa-similar-note">Nothing is removed until you choose. Highlighted words are the ones the other questions do not have.</p>
      <div className="qa-similar-pairs">
        {members.map((sample) => (
          <Pair {...pair} key={`${sample.id}:${sample.revision}:${sample.status}`} sample={sample}
                compareWith={members.filter((s) => s.id !== sample.id).map((s) => s.question)} onKeep={() => keepOne(sample)} />
        ))}
      </div>
    </section>
  );
}

function ThemeLimit({ project, used }) {
  const { update } = useProjects();
  const maxThemes = Number(project.max_themes) || 8;
  const [value, setValue] = useState(maxThemes);
  const [error, setError] = useState('');
  useEffect(() => setValue(maxThemes), [maxThemes]);

  async function save() {
    const limit = Number(value);
    if (limit === maxThemes) return;
    setError('');
    try {
      await update(project.id, { max_themes: limit });
    } catch (e) {
      setError(e.message);
      setValue(maxThemes);
    }
  }

  return (
    <div className="qa-limit">
      <label>{used} of {value || maxThemes} themes <input aria-label="Maximum themes" type="number" min={1} max={50} value={value} onChange={(e) => setValue(e.target.value)} onBlur={save} /></label>
      {error && <small className="qa-bad">{error}</small>}
    </div>
  );
}

function ThemeChip({ title, note, behavior, proposed, approved, active, onClick, shares }) {
  const counts = `${proposed} to review · ${approved} approved`;
  const parts = PILLARS.filter((p) => shares && shares[p.key].proposed + shares[p.key].approved > 0)
    .map((p) => ({ ...p, n: shares[p.key].proposed + shares[p.key].approved }));
  return (
    <button className={`qa-theme${active ? ' active' : ''}`} onClick={onClick} title={[note, counts, parts.map((p) => `${p.label} ${p.n}`).join(' · ')].filter(Boolean).join('\n')}>
      <span>{title}{behavior && <em> · behavior</em>}</span>
      {proposed > 0 && <small className="to-review" aria-label={`${proposed} to review`}>{proposed}</small>}
      {approved > 0 && <small className="approved" aria-label={`${approved} approved`}>{approved}</small>}
      {parts.length > 0 && (
        <i className="qa-theme-mix" aria-hidden="true">
          {parts.map((p) => <b key={p.key} style={{ flexGrow: p.n, background: PILLAR_COLOR[p.key] }} />)}
        </i>
      )}
    </button>
  );
}

export function Curate({ project, model, initial }) {
  const { t } = useI18n();
  const api = useMemo(() => projectApi(project.id), [project.id]);
  const [themes, setThemes] = useState([]);
  const [samples, setSamples] = useState(null);
  const [sources, setSources] = useState([]);
  const [themeId, setThemeId] = useState('');
  const [sourceId, setSourceId] = useState(initial?.source || '');
  const [status, setStatus] = useState('proposed');
  const [origin, setOrigin] = useState('');
  const [confidence, setConfidence] = useState('');
  const [pillar, setPillar] = useState('');
  const [pillars, setPillars] = useState(null);
  const [arrange, setArrange] = useState(() => (localStorage.getItem('academy.curate.arrange') === 'pillar' ? 'pillar' : 'theme'));
  const [error, setError] = useState('');
  const [newTheme, setNewTheme] = useState('');
  const [renaming, setRenaming] = useState(null);
  const [mergeTarget, setMergeTarget] = useState('');
  const [themeWorking, setThemeWorking] = useState(false);
  const [splitProposal, setSplitProposal] = useState(null);
  const [view, setView] = useState(() => {
    const saved = localStorage.getItem('academy.curate.view');
    if (initial?.view) return initial.view;
    if (saved === 'conflicts' || saved === 'similar') return 'decide'; // what these two tabs became
    return saved === 'graph' || saved === 'decide' ? saved : 'list';
  });
  const [themesOpen, setThemesOpen] = useState(() => localStorage.getItem('academy.curate.themes') !== 'closed');
  const [graph, setGraph] = useState(null);
  const [focus, setFocus] = useState(null); // a pair picked on the graph
  const [focused, setFocused] = useState(null);
  const { runs, runsChanged, refresh: refreshRuns } = useRuns();
  const working = runs.find((r) => r.status === 'running' && ASKED.has(r.kind))?.kind || '';
  const [similar, setSimilar] = useState(null);
  const [undoable, setUndoable] = useState(null); // the last group decision, until the next one
  const [clicked, setClicked] = useState(''); // the node last clicked on the graph
  const [removable, setRemovable] = useState([]); // what removing the node picked on the graph would take out
  const [conflictCount, setConflictCount] = useState(0);
  const [challengeReport, setChallengeReport] = useState(null);
  const [bulkNote, setBulkNote] = useState('');
  const [inConflict, setInConflict] = useState(() => new Set());

  const load = useCallback(async () => {
    try {
      const [t, s, f, near, alike, counts, open, challenge] = await Promise.all([
        api.listThemes(),
        api.listSamples({ theme: themeId, source: sourceId, status, origin }),
        api.listSources(),
        focus ? api.listSamples({ theme: focus.theme_id }) : null,
        api.listSimilar(),
        api.pillars(),
        api.listConflicts(),
        api.challenge(),
      ]);
      setChallengeReport(challenge);
      setConflictCount(open.length);
      setInConflict(new Set(open.flatMap((c) => [c.first_id, c.second_id])));
      setPillars(counts);
      setSimilar(alike);
      setFocused(near?.find((x) => x.id === focus.id) || null);
      setThemes(t);
      setSamples(s);
      setSources(f);
    } catch (e) {
      setError(e.message);
    }
  }, [api, themeId, sourceId, status, origin, focus]);

  // The list and its controls stay usable while the optional graph is fetched.
  useEffect(() => {
    if (view !== 'graph') return;
    let current = true;
    api.kbGraph().then((value) => { if (current) setGraph(value); }).catch((e) => { if (current) setError(e.message); });
    return () => { current = false; };
  }, [api, view]);

  const running = sources.some((s) => s.run?.status === 'running');
  useEffect(() => { load(); }, [load, runsChanged]);
  useEffect(() => {
    if (!running) return undefined;
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, [running, load]);

  async function act(fn) {
    setError('');
    try {
      const result = await fn();
      await load();
      return result;
    } catch (e) {
      setError(e.message);
      return false;
    }
  }

  function chooseView(next) {
    localStorage.setItem('academy.curate.view', next);
    setView(next);
    const hash = next === 'list' ? '#curate' : `#curate/${next}`;
    history.replaceState(null, '', hash);
  }

  function choosePillar(next) {
    setPillar(next);
    setOrigin('');
    setFocus(null);
  }

  function chooseArrange(next) {
    localStorage.setItem('academy.curate.arrange', next);
    setArrange(next);
  }

  function toggleThemes() {
    localStorage.setItem('academy.curate.themes', themesOpen ? 'closed' : 'open');
    setThemesOpen(!themesOpen);
  }

  function chooseTheme(id) {
    setThemeId(id);
    setFocus(null);
    setRenaming(null);
  }

  function pickNode(node) {
    setClicked(node.id);
    if (node.type === 'pair') setFocus({ id: node.id, theme_id: node.theme_id });
    else if (node.type === 'theme') chooseTheme(node.id);
    else if (node.type === 'pillar') choosePillar(node.pillar);
    else if (node.type === 'file') { setSourceId(node.id.replace('file:', '')); setFocus(null); }
    else { chooseTheme(''); setSourceId(''); }
  }

  const highlighted = focus?.id || (arrange === 'theme' && themeId) || (arrange === 'pillar' && pillar ? `pillar:${pillar}` : '') || (sourceId ? `file:${sourceId}` : '');
  // Only a node clicked on the graph can be removed. A filter left on must never put "Remove 210" where "Remove" just was.
  const picked = view === 'graph' && clicked === highlighted ? graph?.nodes.find((n) => n.id === clicked && ['pair', 'theme', 'file'].includes(n.type)) : null;

  // A theme or a file may hold a person's approvals: those stay. Removing a pair is one decision about that pair.
  useEffect(() => {
    if (!picked) { setRemovable([]); return undefined; }
    if (picked.type === 'pair') { setRemovable([{ id: picked.id, status: picked.status }]); return undefined; }
    let current = true;
    const filter = picked.type === 'theme' ? { theme: picked.id } : { source: picked.id.replace('file:', '') };
    api.listSamples({ ...filter, status: 'proposed' }).then((found) => { if (current) setRemovable(found); }).catch((e) => setError(e.message));
    return () => { current = false; };
  }, [api, picked?.id, picked?.type, picked?.status, graph]);

  async function removePicked() {
    const taken = removable;
    const kind = picked.type;
    const done = await act(() => Promise.all(taken.map((s) => api.reject(s.id))));
    if (!done) return;
    setClicked('');
    setFocus(null);
    if (kind === 'theme') setThemeId('');
    if (kind === 'file') setSourceId('');
    setUndoable({
      label: kind === 'pair' ? 'Removed the pair.' : `Removed ${taken.length} pair(s) to review. Approved pairs stayed.`,
      undo: () => Promise.all(taken.map((s) => (s.status === 'approved' ? api.approve(s.id) : api.resetSample(s.id)))),
    });
  }

  // A model call a person asked for. It goes on wherever they go; how it went shows above every screen.
  async function askModel(fn) {
    if (!model) { setError('Choose a model at the top first.'); return; }
    setError('');
    setStatus('proposed');
    try {
      await fn();
    } catch (e) {
      setError(e.message);
    }
    await refreshRuns();
  }

  async function undoLast() {
    const { undo } = undoable;
    setUndoable(null);
    await act(undo);
  }

  // A decision stays whole: it shows when any of its pairs fits the filters.
  const fits = (s) => (!themeId || s.theme_id === themeId) && (!sourceId || s.source_id === sourceId) && (!origin || s.origin === origin) && (!pillar || s.pillar === pillar);
  const shownGroups = similar?.filter((group) => group.samples.some(fits));
  const toDecide = (similar?.length || 0) + conflictCount;
  const shownSamples = samples?.filter((s) => (!pillar || s.pillar === pillar) && (!confidence || s.curation?.level === confidence));
  // Everything on screen, whatever the filters. A pair flagged for reading or waiting on a choice in Decide is not swept along.
  const onChoice = useMemo(() => new Set([...(similar || []).flatMap((g) => g.samples.map((s) => s.id)), ...inConflict]), [similar, inConflict]);
  const waiting = status === 'proposed' ? shownSamples || [] : [];
  const sweepable = waiting.filter((s) => !s.review_note && !onChoice.has(s.id));
  const held = waiting.filter((s) => onChoice.has(s.id)).length;
  const flagged = waiting.length - sweepable.length - held;

  async function decideShown(decision, word) {
    await act(async () => {
      const { changed } = await api.decideMany(sweepable.map((s) => s.id), decision);
      const heldBack = Math.max(0, sweepable.length - changed.length);
      setBulkNote(heldBack ? t('curate.bulkSetAside', { count: heldBack }) : '');
      setUndoable({ label: `${word} ${changed.length} pair(s).`, undo: () => api.decideMany(changed, 'reset') });
    });
  }

  async function startChallenge() {
    await askModel(() => api.runChallenge(model));
    await load();
  }

  const kindsHere = PILLARS.filter((p) => !pillar || p.key === pillar).flatMap((p) => p.kinds);
  const shownGraph = useMemo(() => (graph && arrange === 'pillar' && graph.nodes.length > 1 ? arrangeByPillar(graph) : graph), [graph, arrange]);
  // The pillars of what is on screen: one theme when one is chosen, the whole project otherwise.
  const standing = themes.find((t) => t.id === themeId)?.pillars || pillars;
  const live = standing && Object.fromEntries(Object.entries(standing).map(([key, n]) => [key, n.proposed + n.approved]));

  const theme = themes.find((t) => t.id === themeId);
  const used = themes.filter((t) => t.kind === 'topic').length;
  const totals = themes.reduce((sum, t) => ({ proposed: sum.proposed + t.proposed, approved: sum.approved + t.approved }), { proposed: 0, approved: 0 });
  const mergeTargets = themes.filter((t) => t.id !== themeId && t.kind !== 'behavior' && t.kind !== 'limits');

  async function addTheme(e) {
    e.preventDefault();
    if (await act(() => api.createTheme({ title: newTheme }))) setNewTheme('');
  }

  async function merge(into) {
    if (!into || !theme) return;
    const result = await act(() => api.mergeTheme(theme.id, into));
    if (result?.undo) {
      setThemeId(into);
      setUndoable({ label: t('curate.themeMerged'), undo: () => api.undoThemeOperation(result.undo) });
      setMergeTarget('');
    }
  }

  async function split() {
    if (!theme || !model) return;
    setThemeWorking(true);
    try {
      const result = await act(() => api.splitTheme(theme.id, model));
      if (result?.groups && result?.themes?.length === 2) setSplitProposal(result);
    } finally {
      setThemeWorking(false);
    }
  }

  async function confirmSplit() {
    if (!splitProposal || !theme) return;
    const result = await act(() => api.confirmSplitTheme(theme.id, splitProposal));
    if (result?.undo) {
      setThemeId(result.themes[0].id);
      setUndoable({ label: t('curate.themeSplit'), undo: () => api.undoThemeOperation(result.undo) });
      setSplitProposal(null);
    }
  }

  async function saveRename(e) {
    e.preventDefault();
    if (await act(() => api.editTheme(theme.id, { title: renaming }))) setRenaming(null);
  }

  // Beside the graph, not above it: choosing a theme must not resize the graph.
  const themeHead = theme && (
          <div className="qa-theme-head">
            {renaming !== null ? (
              <form className="qa-rename" onSubmit={saveRename}>
                <input autoFocus value={renaming} onChange={(e) => setRenaming(e.target.value)} />
                <Button type="submit" variant="primary" disabled={!renaming.trim()} title="Saves the new name.">Save</Button>
                <Button variant="ghost" title="Keeps the current name." onClick={() => setRenaming(null)}>Cancel</Button>
              </form>
            ) : (
              <>
                <div className="qa-theme-title">
                  <h3>{theme.title}</h3>
                  {theme.description && <p>{theme.description}</p>}
                </div>
                {theme.kind !== 'other' && <Button variant="ghost" title="Give this theme another name." onClick={() => setRenaming(theme.title)}>Rename</Button>}
                {theme.kind === 'topic' && (
                  <>
                  {theme.merge_suggestion && <span className="qa-muted">{t('curate.mergeSuggestion', { theme: themes.find((item) => item.id === theme.merge_suggestion)?.title })}</span>}
                  <select aria-label="Merge into" value={mergeTarget} onChange={(e) => setMergeTarget(e.target.value)}>
                    <option value="">Merge into…</option>
                    {mergeTargets.map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}
                  </select>
                  <Button variant="ghost" disabled={!mergeTarget || !!working || themeWorking} onClick={() => merge(mergeTarget)}>{t('curate.merge')}</Button>
                  {theme.merge_suggestion && <Button variant="ghost" disabled={!!working || themeWorking} onClick={() => merge(theme.merge_suggestion)}>{t('curate.merge')}</Button>}
                  <Button variant="ghost" disabled={!model || !!working || themeWorking} onClick={split}>{themeWorking ? t('curate.splitting') : t('curate.split')}</Button>
                  {splitProposal?.theme_id === theme.id && <div className="qa-notice qa-split-proposal">
                    <strong>{t('curate.splitReview')}</strong>
                    <ul>{splitProposal.themes.map((item, index) => <li key={index}>{item.title} · {t('curate.splitPairCount', { count: item.count })}</li>)}</ul>
                    <Button variant="primary" disabled={!!working || themeWorking} onClick={confirmSplit}>{t('curate.confirmSplit')}</Button>
                    <Button variant="ghost" onClick={() => setSplitProposal(null)}>{t('curate.cancelSplit')}</Button>
                  </div>}
                  </>
                )}
                {(theme.kind === 'topic' || theme.kind === 'other') && (
                  <Button variant="ghost" disabled={!!working} title="New pairs that put facts from different passages of this theme together"
                          onClick={() => askModel(() => api.connectTheme(theme.id, model))}>
                    {working === 'connect' ? 'Connecting…' : 'Connect pairs'}
                  </Button>
                )}
              </>
            )}
          </div>
  );

  return (
    <div className="qa-curate">
      <Panel flush className="qa-themes">
        <div className="qa-themes-bar">
          <button className="qa-themes-toggle" aria-expanded={themesOpen} onClick={toggleThemes}
                  title={themesOpen ? 'Collapse themes' : 'Expand themes'}>
            {themesOpen ? '▾ Themes' : `▸ Themes${theme ? `: ${theme.title}` : ''}`}
          </button>
          {themesOpen && (
            <>
              <ThemeLimit project={project} used={used} />
              <form className="qa-new-theme" onSubmit={addTheme}>
                <input value={newTheme} placeholder="New theme" onChange={(e) => setNewTheme(e.target.value)} />
                <Button type="submit" disabled={!newTheme.trim()} title={newTheme.trim() ? 'Adds a theme with this name.' : 'Write a name first.'}>Add</Button>
              </form>
            </>
          )}
        </div>
        {themesOpen && (
          <div className="qa-theme-list">
            <ThemeChip title="All themes" proposed={totals.proposed} approved={totals.approved} active={themeId === ''} onClick={() => chooseTheme('')} />
            {themes.map((t) => (
              <ThemeChip key={t.id} title={t.title} note={t.description} behavior={t.kind === 'behavior'}
                         proposed={t.proposed} approved={t.approved} shares={t.pillars} active={themeId === t.id} onClick={() => chooseTheme(t.id)} />
            ))}
          </div>
        )}
      </Panel>

      <div className="qa-main">
        {error && <div className="qa-error">{error}</div>}
        {undoable && <div className="qa-notice">{undoable.label} <button className="qa-link" title="Undoes this decision." onClick={undoLast}>Undo</button></div>}
        {bulkNote && <p className="qa-muted" role="status">{bulkNote}</p>}
        {view !== 'decide' && totals.approved > 0 && !challengeReport?.latest && <div className="qa-notice">{t('curate.challenge.prompt')} <span className="qa-muted">{t('curate.challenge.time')}</span> <Button onClick={startChallenge} disabled={!model || !!working}>{working === 'challenge' ? 'Checking…' : 'Check'}</Button></div>}
        {live && (
          <PillarBar counts={live} active={pillar} onChoose={choosePillar}
                     detail={(key) => `${standing[key].proposed} to review · ${standing[key].approved} approved`} />
        )}
        <div className="qa-toolbar">
          <div className="qa-tabs" role="tablist" aria-label="View">
            {VIEWS.map(([value, label, tip]) => (
              <button key={value} role="tab" aria-selected={view === value} className={view === value ? 'active' : ''} title={tip} onClick={() => chooseView(value)}>
                {label}{value === 'decide' && toDecide > 0 ? ` ${toDecide}` : ''}
              </button>
            ))}
          </div>
          {view !== 'decide' && (
            <div className="qa-tabs" role="tablist" aria-label="Status">
              {FILTERS.map(([value, label, tip]) => (
                <button key={value} role="tab" aria-selected={status === value} className={status === value ? 'active' : ''} title={tip} onClick={() => setStatus(value)}>{label}</button>
              ))}
            </div>
          )}
          <select aria-label="File" value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
            <option value="">All files</option>
            {sources.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          <select aria-label="Kind" value={origin} onChange={(e) => setOrigin(e.target.value)}>
            <option value="">All kinds</option>
            {kindsHere.map((value) => <option key={value} value={value}>{KIND_LABEL[value]}</option>)}
          </select>
          {view !== 'decide' && <select aria-label="Confidence" value={confidence} onChange={e => setConfidence(e.target.value)}>
            <option value="">All confidence levels</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option>
          </select>}
          {running && <span className="qa-muted">Still reading a file…</span>}
          <span className="qa-gap" />
          <details className="qa-more">
            <summary className="aa-btn aa-btn-ghost" title="The model drafts new pairs for you to review">{working && working !== 'connect' ? 'Writing…' : 'Write more pairs'}</summary>
            <div className="qa-more-menu">
              <Button variant="ghost" disabled={!!working} title="Not known: details of this work the files do not give, answered by saying so"
                      onClick={() => askModel(() => api.writeRefusals(model))}>
                Not known
              </Button>
              <Button variant="ghost" disabled={!!working} title="Questions on another subject that sounds like this one, answered by marking the limit, then in general"
                      onClick={() => askModel(() => api.writeNeighbours(model))}>
                Neighbouring subject
              </Button>
              <Button variant="ghost" disabled={!!working} title="Questions that assume something a quote contradicts, answered by correcting it, each with its true version"
                      onClick={() => askModel(() => api.writeFalsePremises(model))}>
                False premises
              </Button>
            </div>
          </details>
        </div>

        {view !== 'graph' && themeHead}

        <div className={view === 'graph' ? 'qa-brain' : 'qa-brain-off'}>
          {view === 'graph' && (
            <Panel flush className="qa-brain-graph">
              <div className="qa-tabs qa-graph-arrange" role="tablist" aria-label="Arrange by">
                {[['theme', 'By theme', 'Group the graph by what the pairs are about'], ['pillar', 'By pillar', 'Group the graph into known, false and not known']].map(([value, label, tip]) => (
                  <button key={value} role="tab" aria-selected={arrange === value} className={arrange === value ? 'active' : ''} title={tip} onClick={() => chooseArrange(value)}>{label}</button>
                ))}
              </div>
              {graph?.nodes.length > 1 ? (
                <Suspense fallback={<p className="qa-empty">Loading the graph…</p>}>
                  <BrainGraph key={arrange} graph={shownGraph} kind={origin} pillar={pillar}
                              selectedId={highlighted} onSelect={pickNode} />
                </Suspense>
              ) : <p className="qa-empty">{graph ? 'Upload a file and its knowledge shows up here.' : 'Loading…'}</p>}
              {picked && (
                <div className="qa-graph-picked">
                  <span className="qa-grow" title={picked.label}>{picked.label}</span>
                  <Button variant="ghost" title="Unselects this and shows everything again." onClick={() => { setClicked(''); setFocus(null); if (picked.type === 'theme') setThemeId(''); if (picked.type === 'file') setSourceId(''); }}>Clear</Button>
                  <Button disabled={!removable.length} title="Rejected pairs leave the graph and the export. You can undo this. Approved pairs in a theme or file stay."
                          onClick={removePicked}>
                    {picked.type === 'pair' ? 'Remove' : removable.length ? `Remove ${removable.length} to review` : 'Nothing to review'}
                  </Button>
                </div>
              )}
            </Panel>
          )}
          <div className="qa-side">
          {view === 'graph' && themeHead}
          {view !== 'decide' && !focus && waiting.length > 0 && (
            <div className="qa-sweep">
              <strong>{waiting.length} to review here</strong>
              {bulkNote && <span className="qa-muted">{bulkNote}</span>}
              {held > 0 && <button className="qa-link" title="They say the same thing or disagree, so they need your choice first." onClick={() => chooseView('decide')}>{held} wait in Decide</button>}
              {flagged > 0 && <span className="qa-muted">{flagged} flagged to read</span>}
              <span className="qa-gap" />
              {sweepable.length > 0 && (
                <>
                  <Button title="Approves the pairs shown here. You can undo this." onClick={() => decideShown('approve', 'Approved')}>Approve {sweepable.length}</Button>
                  <Button title="Rejects the pairs shown here. You can undo this." onClick={() => decideShown('reject', 'Rejected')}>Reject {sweepable.length}</Button>
                </>
              )}
            </div>
          )}
          <div className="qa-pairs">
            {view === 'decide' ? (
              <Conflicts project={project} api={api} model={model} onChanged={load} onError={setError} onCount={setConflictCount} fits={fits} alsoHere={shownGroups?.length || 0}>
                {shownGroups?.map((group) => (
                  <SimilarGroup key={group.samples.map((s) => s.id).join()} group={group} model={model} language={project.language} themes={themes} api={api}
                                onChanged={load} onError={setError} onUndoable={(label, undo) => setUndoable({ label, undo })} />
                ))}
              </Conflicts>
            ) : focus && focused ? (
              <>
                <button className="qa-link qa-back" title="Return to the list of pairs." onClick={() => setFocus(null)}>Back to the list</button>
                <Pair model={model} language={project.language} key={`${focused.id}:${focused.revision}:${focused.status}`} sample={focused} themes={themes} api={api} onChanged={load} onError={setError} onUndoable={(label, undo) => setUndoable({ label, undo })} />
              </>
            ) : (
              <>
                {samples === null && <p className="qa-empty">Loading…</p>}
                {shownSamples?.length === 0 && <p className="qa-empty">Nothing here.</p>}
                {shownSamples?.map((sample) => (
                  <Pair model={model} language={project.language} key={`${sample.id}:${sample.revision}`} sample={sample} themes={themes} api={api} onChanged={load} onError={setError} onUndoable={(label, undo) => setUndoable({ label, undo })} />
                ))}
              </>
            )}
          </div>
          </div>
        </div>
      </div>
    </div>
  );
}
