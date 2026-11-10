"""The challenge: what a project holds, tested against itself (ADR 016).

Each pillar is put against the others. A doubt against every file: does a passage answer it? A false claim against the
quotes nearest to it: does one confirm it? A known pair against its nearest known pairs: can both be true?
What survives needs less of a person's time; what does not becomes a conflict, the only thing that has to be read.

A conflict ends one of three ways: the doubt goes, the certainty goes, or it stays as a pair that says the two things
hold in tension. The model judges and drafts; the code only ever decides what gets compared, and nothing changes until
a person resolves it. Failures stop the run and are shown: a comparison that did not happen is never counted as passed.
"""

import json
import math
import re

from . import agents, console, db, kb, projects, qa, rules, runs, sources, workshop
from .llm import LLMError, OutputCapped, plain_error

KNOWN = ("file", "connection", "true_premise")
NEAREST = 3   # known pairs each pair is compared with; planted contradictions: 15 of 16 sit in the first three
MIN_CLOSENESS = 0.08  # skip pairs with little shared subject matter
BATCH_SIZE = 32
DOUBT_BATCH_SIZE = 8  # each doubt answer quotes evidence; 32 of them passed the 4,000-token cap

VERDICT = {"type": "object", "properties": {"verdict": {"type": "string", "enum": ["supports", "contradicts", "unrelated"]},
                                            "why": {"type": "string"}}, "required": ["verdict", "why"]}
PAIR_VERDICT = {"type": "object", "properties": {"verdict": {"type": "string", "enum": ["same", "complement", "disagree", "unrelated"]},
                                                 "why": {"type": "string"}}, "required": ["verdict", "why"]}
DRAFT = {"type": "object", "properties": {"question": {"type": "string"}, "answer": {"type": "string"}, "complex": {"type": "string"}},
         "required": ["question", "answer", "complex"]}

RESOLUTIONS = {
    "known_disagree": ("keep_first", "keep_second", "complex", "no_conflict"),
    "false_confirmed": ("keep_first", "keep_second", "complex", "no_conflict"),
    "doubt_answered": ("answer", "complex", "no_conflict"),
    "false_unsettled": ("keep_second", "no_conflict"),
}


# --- What gets compared ---

def _bag(sample: dict) -> set[str]:
    return set(kb._terms(f"{sample['question']} {sample['answer']}"))


def nearest_pairs(pool: list[dict], top: int = NEAREST) -> list[tuple[dict, dict]]:
    """Each known pair with the ones sharing its rarer words, without repeats. Words only: the model decides."""
    bags = [_bag(s) for s in pool]
    seen: dict[str, int] = {}
    for bag in bags:
        for word in bag:
            seen[word] = seen.get(word, 0) + 1
    weight = lambda word: math.log((len(pool) + 1) / seen[word])
    def closeness(a: set, b: set) -> float:
        union = sum(weight(w) for w in a | b)
        return sum(weight(w) for w in a & b) / union if union else 0.0
    pairs: dict[tuple[str, str], tuple[dict, dict]] = {}
    for i, sample in enumerate(pool):
        # Comparing different themes creates noise: the human-curated theme is the topic boundary.
        ranked = sorted(((closeness(bags[i], bags[j]), j) for j in range(len(pool))
                         if j != i and sample.get("theme_id") == pool[j].get("theme_id")), key=lambda r: -r[0])
        for score, j in ranked[:top]:
            other = pool[j]
            identical = sample.get("content_hash") and sample.get("content_hash") == other.get("content_hash")
            if score >= MIN_CLOSENESS and sample["quote"] != other["quote"] and not identical:
                first, second = sorted((sample, other), key=lambda s: s["id"])
                pairs.setdefault((first["id"], second["id"]), (first, second))
    return list(pairs.values())


def nearest_to_claim(claim: str, pool: list[dict], own_quote: str, top: int = NEAREST) -> list[dict]:
    """The known pairs closest to a false claim, whose quotes can confirm or contradict it."""
    words = set(kb._terms(claim))
    scored = ((rules.jaccard(words, _bag(s)), s) for s in pool if s["quote"] and s["quote"] != own_quote)
    return [s for score, s in sorted(scored, key=lambda r: -r[0])[:top] if score >= MIN_CLOSENESS]


# --- The prompts ---

def claim_prompt(claim: str, quote: str) -> str:
    return agents.prompt("conflict_finder", "claim", claim=claim, quote=quote)


def pair_prompt(a: dict, b: dict) -> str:
    return agents.prompt("conflict_finder", "pair", first_question=a["question"], first_answer=a["answer"], first_quote=a["quote"],
                         second_question=b["question"], second_answer=b["answer"], second_quote=b["quote"])


def draft_prompt(kind: str, language: str, first: dict, second: dict | None, quote: str, why: str) -> str:
    if kind == "doubt_answered":
        return agents.prompt("draft_writer", "doubt", question=first["question"], quote=quote, language=language, max_sentences=qa.MAX_ANSWER_SENTENCES)
    claim = first["false_claim"] if kind == "false_confirmed" else first["answer"]
    return agents.prompt("draft_writer", "disagree", why=why, claim=claim, first_quote=first["quote"], second_answer=second["answer"],
                         second_quote=second["quote"], language=language, max_sentences=qa.MAX_ANSWER_SENTENCES)


# --- The run ---

def start(conn, project_id: str, model: str) -> str:
    projects.get(conn, project_id)
    if conn.execute("SELECT 1 FROM qa_challenges WHERE project_id = ? AND status = 'running'", (project_id,)).fetchone():
        raise workshop.Conflict("a challenge is already running in this project")
    if not conn.execute("SELECT 1 FROM qa_samples WHERE project_id = ? AND status != 'rejected' AND origin != 'behavior'", (project_id,)).fetchone():
        raise ValueError("no pairs to challenge yet")
    cid = db.new_id("chl")
    conn.execute("INSERT INTO qa_challenges (id, project_id, model, status, created_at) VALUES (?,?,?, 'running', ?)",
                 (cid, project_id, model, db.now()))
    conn.commit()
    return cid


def stop_interrupted(conn) -> int:
    changed = conn.execute("UPDATE qa_challenges SET status = 'stopped', error = 'the app closed before this finished', finished_at = ?"
                           " WHERE status = 'running'", (db.now(),)).rowcount
    conn.commit()
    return changed


def _samples(conn, project_id: str) -> list[dict]:
    return db.rows(conn, "SELECT * FROM qa_samples WHERE project_id = ? AND status != 'rejected' AND origin != 'behavior'"
                         " ORDER BY created_at, id", (project_id,))


def _judged(conn, test: str, first: dict, second: dict | None) -> bool:
    return conn.execute("SELECT 1 FROM qa_comparisons WHERE test = ? AND first_id = ? AND second_id = ? AND first_hash = ? AND second_hash = ?",
                        (test, first["id"], second["id"] if second else "", first["content_hash"], second["content_hash"] if second else "")).fetchone() is not None


def _record(conn, cid: str, test: str, first: dict, second: dict | None, verdict: str, why: str = "", quote: str = "") -> None:
    conn.execute("INSERT OR REPLACE INTO qa_comparisons (test, first_id, second_id, first_hash, second_hash, verdict, why, quote, challenge_id, created_at)"
                 " VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (test, first["id"], second["id"] if second else "", first["content_hash"], second["content_hash"] if second else "",
                  verdict, rules.normalize(why), quote, cid, db.now()))


def _drafted(llm, kind: str, language: str, first: dict, second: dict | None, quote: str, why: str) -> dict:
    """A draft that breaks the rules is left out, not corrected: a person writes that one."""
    if kind == "false_unsettled":  # the only way out is to drop it or keep it: nothing to write
        return {"question": "", "answer": "", "complex": ""}
    with console.acting("draft_writer"):
        data = llm.complete_json(draft_prompt(kind, language, first, second, quote, why), DRAFT, temperature=0.2)
    evidence = " ".join(filter(None, [quote, first["quote"], first["false_claim"], first["question"], first["answer"],
                                  second["quote"] if second else "", second["answer"] if second else ""]))
    question = rules.normalize(str(data.get("question", ""))) or first["question"]
    dropped = {}
    def fit(field: str) -> str:
        text = rules.normalize(str(data.get(field, "")))
        reasons = _draft_reasons(question, text, evidence) if text else ["it wrote nothing"]
        if reasons:
            dropped[field] = "; ".join(reasons)
        return "" if reasons else text
    return {"question": question, "answer": fit("answer"), "complex": fit("complex"), "dropped": dropped}


# Words about the material or the debate, not the subject. They would be taught to the model as if they were an answer.
DRAFT_TALK = re.compile(r"\b(one|another|other|both|two|first|second) (claims?|statements?)\b|\bstatement \d|\b(provided|given|available) information\b"
                        r"|\bthe subject of\b|\b(uma|outra|duas) afirma[çc][ãa]o(ões)?\b|\binforma[çc][õo]es (fornecidas|dadas|dispon[íi]veis)\b", re.I)


def _draft_reasons(question: str, answer: str, evidence: str) -> list[str]:
    reasons = qa.text_limits(question, answer)
    if DRAFT_TALK.search(answer):
        reasons.append("talks about the material instead of the subject")
    if any(qa.SOURCE_TALK.search(t) or kb.MATERIAL_TALK.search(t) for t in (question, answer)):
        reasons.append("talks about its source instead of the subject")
    stray = sorted(qa._numbers(answer) - qa._numbers(evidence) - qa._numbers(question))
    if stray:
        reasons.append(f"states numbers the evidence does not hold: {', '.join(stray)}")
    return reasons


def _open_conflict(conn, llm, cid: str, project_id: str, language: str, kind: str, first: dict, second: dict | None, why: str,
                   quote: str = "", chunk: dict | None = None, source_id: str | None = None) -> int:
    second_id = second["id"] if second else ""
    if conn.execute("SELECT 1 FROM qa_conflicts WHERE kind = ? AND first_id = ? AND second_id = ?", (kind, first["id"], second_id)).fetchone():
        return 0
    draft = _drafted(llm, kind, language, first, second, quote, why)
    conn.execute("INSERT INTO qa_conflicts (id, project_id, challenge_id, kind, first_id, second_id, quote, chunk_id, source_id, why,"
                 " draft_question, draft_answer, draft_complex, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'open', ?)",
                 (db.new_id("cfl"), project_id, cid, kind, first["id"], second_id, quote, chunk["id"] if chunk else None, source_id,
                  rules.normalize(why), draft["question"], draft["answer"], draft["complex"], db.now()))
    return 1


def _all_chunks(conn, project_id: str) -> list[dict]:
    chunks = []
    for row in db.rows(conn, "SELECT id FROM sources WHERE project_id = ? ORDER BY created_at, id", (project_id,)):
        source = sources.get_source(conn, row["id"])
        chunks += [{**c, "source_id": row["id"]} for c in source["chunks"] if c["text"].strip()]
    return chunks


def resume(conn, project_id: str) -> dict:
    """Go on with the latest run. Every comparison already judged is kept, so only the rest costs anything."""
    last = latest(conn, project_id)
    if last and last["status"] == "running":
        raise workshop.Conflict("a challenge is already running in this project")
    if not last or last["status"] not in ("stopped", "failed"):
        raise ValueError("nothing to continue here")
    conn.execute("UPDATE qa_challenges SET status = 'running', error = NULL, finished_at = NULL WHERE id = ?", (last["id"],))
    conn.commit()
    return last


def run(conn, llm, cid: str) -> dict:
    row = db.row(conn, "SELECT project_id, done, conflicts FROM qa_challenges WHERE id = ?", (cid,))
    project_id = row["project_id"]
    project = projects.get(conn, project_id)
    language = sources.LANGUAGE_NAME.get(project["language"], project["language"])
    samples = _samples(conn, project_id)
    known = [s for s in samples if s["origin"] in KNOWN and s["quote"]]
    wrong = [s for s in samples if s["origin"] == "false_premise" and s["false_claim"] and s["quote"]]
    doubts = [s for s in samples if s["origin"] == "refusal"]
    chunks = _all_chunks(conn, project_id)

    # Everything to do is known first, so progress means something and a repeat run only pays for what changed.
    work = []
    work += [("doubt", d, None) for d in doubts if not _judged(conn, "doubt", d, None)]
    work += [("claim_own", w, None) for w in wrong if not _judged(conn, "claim_own", w, None)]
    for w in wrong:
        work += [("claim", w, k) for k in nearest_to_claim(w["false_claim"], known, w["quote"]) if not _judged(conn, "claim", w, k)]
    work += [("known", a, b) for a, b in nearest_pairs(known) if not _judged(conn, "known", a, b)]
    done, opened = row["done"] or 0, row["conflicts"] or 0  # both zero unless this run is going on from a stop
    total = done + len(work)
    conn.execute("UPDATE qa_challenges SET total = ?, done = ? WHERE id = ?", (total, done, cid))
    conn.commit()

    try:
        index = 0
        while index < len(work):
            runs.check()
            runs.progress(done, total)
            runs.say(f"Checking pair {done + 1} of {total}" if total else "Checking pairs")
            test, first, second = work[index]
            batch = work[index:index + BATCH_SIZE] if test == "known" else []
            if batch and all(item[0] == "known" for item in batch) and hasattr(llm, "complete_json_batch") and len(batch) > 1:
                results = _judge_known_batch(llm, [(a, b) for _, a, b in batch])
                for (_, a, b), result in zip(batch, results):
                    if result.get("verdict") == "disagree":
                        # A long batch calls "different topic" a disagreement; only a pair judged alone may open a conflict.
                        with console.acting("conflict_finder"):
                            result = llm.complete_json(pair_prompt(a, b), PAIR_VERDICT, temperature=0.0)
                    opened += _save_known_verdict(conn, llm, cid, project_id, language, a, b, result)
                    done += 1
                index += len(batch)
                conn.execute("UPDATE qa_challenges SET done = ? WHERE id = ?", (done, cid))
                conn.commit()
                continue
            batch = work[index:index + (DOUBT_BATCH_SIZE if test == "doubt" else BATCH_SIZE)] if test in ("doubt", "claim_own", "claim") else []
            if batch and all(item[0] == test for item in batch) and len(batch) > 1 and hasattr(llm, "complete_json_batch"):
                results = _judge_test_batch(llm, test, batch, chunks)
                for (_, a, b), result in zip(batch, results):
                    # Batched verdicts that would create a conflict must earn the same verdict alone.
                    opens = (test == "doubt" and bool(result.get("answered"))
                             or test == "claim_own" and result.get("verdict") != "contradicts"
                             or test == "claim" and result.get("verdict") == "supports")
                    if opens:
                        result = _judge_test_one(llm, test, a, b, chunks)
                    opened += _save_test_verdict(conn, llm, cid, project_id, language, test, a, b, result, chunks)
                    done += 1
                    conn.execute("UPDATE qa_challenges SET done = ? WHERE id = ?", (done, cid))
                    conn.commit()
                index += len(batch)
                continue
            opened += _one(conn, llm, cid, project_id, language, test, first, second, chunks)
            done += 1
            index += 1
            conn.execute("UPDATE qa_challenges SET done = ? WHERE id = ?", (done, cid))
            conn.commit()
    except runs.Stopped:
        conn.rollback()
        _finish(conn, cid, "stopped", None, opened)
        raise
    except LLMError as exc:
        conn.rollback()
        return _finish(conn, cid, "failed", f"model call failed after {done} of {total} comparisons: {exc}", opened)
    return _finish(conn, cid, "succeeded", None, opened)


def _test_batch_prompt(test: str, batch: list[tuple], chunks: list[dict]) -> tuple[str, dict]:
    if test in ("claim", "claim_own"):
        rows = [f"{i}. CLAIM: {a['false_claim']} | PASSAGE: {b['quote'] if b else a['quote']}" for i, (_, a, b) in enumerate(batch, 1)]
        item_schema = VERDICT
        instruction = "For each numbered claim and passage, say supports, contradicts, or unrelated. Return one result in order."
    else:
        rows = []
        for i, (_, a, _) in enumerate(batch, 1):
            excerpts = kb.nearest_passages(a["question"], chunks)
            rows.append(f"{i}. QUESTION: {a['question']}\nPASSAGES:\n" + "\n".join(f"[{n}] {x}" for n, x in enumerate(excerpts, 1)))
        item_schema = kb.ANSWER_CHECK_SCHEMA
        instruction = "For each numbered question, decide whether a passage answers it and quote the evidence. Return one result in order."
    schema = {"type": "object", "properties": {"results": {"type": "array", "items": item_schema}}, "required": ["results"]}
    return instruction + "\n" + "\n".join(rows), schema


def _judge_test_batch(llm, test: str, batch: list[tuple], chunks: list[dict]) -> list[dict]:
    prompt, schema = _test_batch_prompt(test, batch, chunks)
    try:
        with console.acting("answer_checker" if test == "doubt" else "conflict_finder"):
            result = llm.complete_json_batch(prompt, schema, temperature=0.0)
    except OutputCapped:
        # Quoted evidence makes long answers; a batch too big for the output cap is judged in halves.
        if len(batch) == 1:
            return [_judge_test_one(llm, test, a, b, chunks) for _, a, b in batch]
        half = len(batch) // 2
        return _judge_test_batch(llm, test, batch[:half], chunks) + _judge_test_batch(llm, test, batch[half:], chunks)
    values = result.get("results") if isinstance(result, dict) else None
    if isinstance(values, list) and len(values) == len(batch):
        return values
    return [_judge_test_one(llm, test, a, b, chunks) for _, a, b in batch]


def _judge_test_one(llm, test: str, first: dict, second: dict | None, chunks: list[dict]) -> dict:
    if test == "doubt":
        excerpts = kb.nearest_passages(first["question"], chunks)
        if not excerpts:
            return {"answered": False, "quote": ""}
        with console.acting("answer_checker"):
            return llm.complete_json(kb.answer_check_prompt(first["question"], excerpts), kb.ANSWER_CHECK_SCHEMA, temperature=0.0)
    with console.acting("conflict_finder"):
        quote = first["quote"] if test == "claim_own" else second["quote"]
        return llm.complete_json(claim_prompt(first["false_claim"], quote), VERDICT, temperature=0.0)


def _save_test_verdict(conn, llm, cid: str, project_id: str, language: str, test: str, first: dict, second: dict | None,
                       result: dict, chunks: list[dict]) -> int:
    if test == "doubt":
        quote = str(result.get("quote") or "").strip() if result.get("answered") else ""
        if not quote:
            _record(conn, cid, test, first, None, "open")
            return 0
        chunk, found = qa.locate_quote(quote, chunks)
        if not chunk:
            _record(conn, cid, test, first, None, "unverified", quote=quote)
            return 0
        _record(conn, cid, test, first, None, "answered", quote=found)
        return _open_conflict(conn, llm, cid, project_id, language, "doubt_answered", first, None,
                              "A passage seems to answer what was marked as not known.", found, chunk, chunk["source_id"])
    verdict, why = str(result.get("verdict")), str(result.get("why", ""))
    _record(conn, cid, test, first, second, verdict, why)
    if test == "claim_own" and verdict != "contradicts":
        return _open_conflict(conn, llm, cid, project_id, language, "false_unsettled", first, None, why)
    if test == "claim" and verdict == "supports":
        return _open_conflict(conn, llm, cid, project_id, language, "false_confirmed", first, second, why)
    return 0


def _one(conn, llm, cid: str, project_id: str, language: str, test: str, first: dict, second: dict | None, chunks: list[dict]) -> int:
    if test == "doubt":
        quote = kb.answered_in(llm, first["question"], chunks)
        if quote is None:
            _record(conn, cid, test, first, None, "open")
            return 0
        chunk, found = qa.locate_quote(quote, chunks) if quote else (None, None)
        if not chunk:  # the model says yes but cannot point at it: nothing a person could check
            _record(conn, cid, test, first, None, "unverified", quote=quote)
            return 0
        _record(conn, cid, test, first, None, "answered", quote=found)
        return _open_conflict(conn, llm, cid, project_id, language, "doubt_answered", first, None,
                              "A passage seems to answer what was marked as not known.", found, chunk, chunk["source_id"])
    if test == "claim_own":
        with console.acting("conflict_finder"):
            result = llm.complete_json(claim_prompt(first["false_claim"], first["quote"]), VERDICT, temperature=0.0)
        _record(conn, cid, test, first, None, str(result.get("verdict")), str(result.get("why", "")))
        if result.get("verdict") != "contradicts":  # a false premise exists because its quote rules it out
            return _open_conflict(conn, llm, cid, project_id, language, "false_unsettled", first, None, str(result.get("why", "")))
        return 0
    if test == "claim":
        with console.acting("conflict_finder"):
            result = llm.complete_json(claim_prompt(first["false_claim"], second["quote"]), VERDICT, temperature=0.0)
        _record(conn, cid, test, first, second, str(result.get("verdict")), str(result.get("why", "")))
        if result.get("verdict") == "supports":
            return _open_conflict(conn, llm, cid, project_id, language, "false_confirmed", first, second, str(result.get("why", "")))
        return 0
    with console.acting("conflict_finder"):
        result = llm.complete_json(pair_prompt(first, second), PAIR_VERDICT, temperature=0.0)
    return _save_known_verdict(conn, llm, cid, project_id, language, first, second, result)


def _judge_known_batch(llm, pairs: list[tuple[dict, dict]]) -> list[dict]:
    entries = "\n".join(f"{i}. A: {a['question']} | {a['answer']} | quote: {a['quote']} || B: {b['question']} | {b['answer']} | quote: {b['quote']}"
                         for i, (a, b) in enumerate(pairs, 1))
    schema = {"type": "object", "properties": {"results": {"type": "array", "items": PAIR_VERDICT}}, "required": ["results"]}
    prompt = ("For each numbered A/B pair, compare only the stated facts. Return one result in order: same, complement, disagree, unrelated. "
              "Keep each reason to a few words.\n" + entries)
    with console.acting("conflict_finder"):
        result = llm.complete_json_batch(prompt, schema, temperature=0.0)
    values = result.get("results")
    if isinstance(values, list) and len(values) == len(pairs):
        return values
    # A model that skips or adds one item breaks the order, so this batch is judged one pair at a time instead.
    singles = []
    for a, b in pairs:
        with console.acting("conflict_finder"):
            singles.append(llm.complete_json(pair_prompt(a, b), PAIR_VERDICT, temperature=0.0))
    return singles


def _save_known_verdict(conn, llm, cid: str, project_id: str, language: str, first: dict, second: dict, result: dict) -> int:
    _record(conn, cid, "known", first, second, str(result.get("verdict")), str(result.get("why", "")))
    if result.get("verdict") == "disagree":
        return _open_conflict(conn, llm, cid, project_id, language, "known_disagree", first, second, str(result.get("why", "")))
    return 0


def _finish(conn, cid: str, status: str, error: str | None, opened: int) -> dict:
    conn.execute("UPDATE qa_challenges SET status = ?, error = ?, conflicts = ?, finished_at = ? WHERE id = ?",
                 (status, error, opened, db.now(), cid))
    conn.commit()
    return db.row(conn, "SELECT * FROM qa_challenges WHERE id = ?", (cid,))


# --- What a person reads ---

def latest(conn, project_id: str) -> dict | None:
    return db.row(conn, "SELECT * FROM qa_challenges WHERE project_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1", (project_id,))


def list_conflicts(conn, project_id: str, status: str = "open") -> list[dict]:
    """A conflict whose pair a person already rejected in curation has nothing left to decide."""
    found = []
    for row in db.rows(conn, "SELECT f.*, s.name AS quote_source, c.locator_json FROM qa_conflicts f LEFT JOIN sources s ON s.id = f.source_id"
                             " LEFT JOIN source_chunks c ON c.id = f.chunk_id WHERE f.project_id = ? AND f.status = ?"
                             " ORDER BY f.created_at, f.id", (project_id, status)):
        row["quote_page"] = json.loads(row.pop("locator_json", None) or "{}").get("page")
        row["first"] = qa.get_sample(conn, row["first_id"])
        row["second"] = qa.get_sample(conn, row["second_id"]) if row["second_id"] else None
        if status == "open" and any(p and p["status"] == "rejected" for p in (row["first"], row["second"])):
            continue
        found.append(row)
    return found


def get_conflict(conn, project_id: str, conflict_id: str) -> dict:
    found = db.row(conn, "SELECT * FROM qa_conflicts WHERE id = ? AND project_id = ?", (conflict_id, project_id))
    if not found:
        raise workshop.NotFound(f"conflict {conflict_id} not found")
    return found


def _set_status(conn, sample_id: str, status: str) -> None:
    conn.execute("UPDATE qa_samples SET status = ?, decided_at = ?, review_note = '' WHERE id = ?", (status, db.now(), sample_id))


def _write_now(conn, llm, conflict: dict, resolution: str, first: dict, second: dict | None) -> dict:
    """The person chose; the model writes what that choice needs. Kept on the conflict, so Undo and choosing again cost nothing."""
    language = projects.get(conn, conflict["project_id"])["language"]
    try:
        draft = _drafted(llm, conflict["kind"], language, first, second, conflict["quote"], conflict["why"])
    except LLMError as exc:
        raise ValueError(f"The model could not write this: {plain_error(exc)}.") from exc
    field = "answer" if resolution == "answer" else "complex"
    if not draft[field]:
        raise ValueError(f"The model's text was left out: {draft['dropped'][field]}.")
    current = get_conflict(conn, conflict["project_id"], conflict["id"])  # the model took a while: someone may have decided
    if current["status"] != "open":
        raise workshop.Conflict("this conflict is already resolved")
    conn.execute(f"UPDATE qa_conflicts SET draft_question = ?, draft_{field} = ?, draft_model = ? WHERE id = ?",
                 (current["draft_question"] or draft["question"], draft[field], llm.model, conflict["id"]))
    conn.commit()
    return get_conflict(conn, conflict["project_id"], conflict["id"])


def _new_pair(conn, conflict: dict, origin: str, question: str, answer: str, parents: list[dict], author: str) -> str:
    first = parents[0]
    sid = db.new_id("qa")
    conn.execute(
        "INSERT INTO qa_samples (id, project_id, theme_id, origin, source_id, chunk_id, quote, model, question, answer, content_hash, status, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?, 'proposed', ?)",
        (sid, conflict["project_id"], first["theme_id"], origin, conflict["source_id"], conflict["chunk_id"], conflict["quote"], author,
         question, answer, rules.content_hash(question, answer), db.now()))
    if origin == "complex":
        conn.executemany("INSERT INTO qa_sample_links (sample_id, based_on_id) VALUES (?,?)", [(sid, p["id"]) for p in parents])
    return sid


def resolve(conn, project_id: str, conflict_id: str, resolution: str, *, question: str = "", answer: str = "", llm=None) -> dict:
    """The doubt goes, the certainty goes, or the tension stays as a pair. Rejected pairs stay in the database, and undo brings them back."""
    conflict = get_conflict(conn, project_id, conflict_id)
    if conflict["status"] != "open":
        raise workshop.Conflict("this conflict is already resolved")
    kind = conflict["kind"]
    if resolution not in RESOLUTIONS[kind]:
        raise ValueError(f"resolution must be one of: {', '.join(RESOLUTIONS[kind])}")
    first = qa.get_sample(conn, conflict["first_id"])
    second = qa.get_sample(conn, conflict["second_id"]) if conflict["second_id"] else None
    parents = [p for p in (first, second) if p]
    before = {p["id"]: p["status"] for p in parents}
    result_id = None
    if resolution == "keep_first":
        _set_status(conn, second["id"], "rejected")
    elif resolution == "keep_second":
        _set_status(conn, first["id"], "rejected")
    elif resolution in ("answer", "complex"):
        written = rules.normalize(answer)
        draft_field = "draft_answer" if resolution == "answer" else "draft_complex"
        evidence = " ".join(filter(None, [conflict["quote"], first["quote"], first["false_claim"], first["question"], first["answer"],
                                  second["quote"] if second else "", second["answer"] if second else ""]))
        def asked(text):
            return rules.normalize(question or conflict["draft_question"] or first["question"]), text
        stored = rules.normalize(conflict[draft_field])
        if not written and (not stored or (llm and _draft_reasons(*asked(stored), evidence))):  # a draft from before the rules changed is written again
            if not llm:
                raise ValueError("write the answer first")
            conflict = _write_now(conn, llm, conflict, resolution, first, second)
        question, answer = asked(written or rules.normalize(conflict[draft_field]))
        author = "person" if written else conflict["draft_model"] or db.row(conn, "SELECT model FROM qa_challenges WHERE id = ?", (conflict["challenge_id"],))["model"]
        reasons = _draft_reasons(question, answer, evidence)
        if reasons:
            raise ValueError("; ".join(reasons))
        result_id = _new_pair(conn, conflict, "file" if resolution == "answer" else "complex", question, answer, parents, author)
        for parent in parents:
            _set_status(conn, parent["id"], "rejected")
    conn.execute("UPDATE qa_conflicts SET status = 'resolved', resolution = ?, result_id = ?, undo = ?, decided_at = ? WHERE id = ?",
                 (resolution, result_id, json.dumps(before), db.now(), conflict_id))
    from . import curation
    for sample in parents:
        curation.event(conn, qa.get_sample(conn, sample['id']), 'resolve_conflict', {'conflict_id': conflict_id, 'resolution': resolution})
    conn.commit()
    return db.row(conn, "SELECT * FROM qa_conflicts WHERE id = ?", (conflict_id,))


def reopen(conn, project_id: str, conflict_id: str) -> dict:
    conflict = get_conflict(conn, project_id, conflict_id)
    if conflict["status"] != "resolved":
        raise workshop.Conflict("this conflict is still open")
    for sample_id, status in json.loads(conflict["undo"] or "{}").items():
        _set_status(conn, sample_id, status)
    if conflict["result_id"]:
        result = db.row(conn, "SELECT status FROM qa_samples WHERE id = ?", (conflict["result_id"],))
        if result and result["status"] == "approved":
            conn.rollback()
            raise ValueError("the pair this conflict became is already approved; reject it first")
        conn.execute("DELETE FROM qa_sample_links WHERE sample_id = ?", (conflict["result_id"],))
        conn.execute("DELETE FROM qa_samples WHERE id = ?", (conflict["result_id"],))
    conn.execute("UPDATE qa_conflicts SET status = 'open', resolution = NULL, result_id = NULL, undo = '', decided_at = NULL WHERE id = ?", (conflict_id,))
    conn.commit()
    return db.row(conn, "SELECT * FROM qa_conflicts WHERE id = ?", (conflict_id,))


def report(conn, project_id: str) -> dict:
    return {"latest": latest(conn, project_id), "open": len(list_conflicts(conn, project_id)),
            "resolved": len(list_conflicts(conn, project_id, "resolved"))}
