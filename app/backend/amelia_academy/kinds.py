"""The kinds of pair a reading adds to the answered ones (specs 012 and 013).

Unanswered: a detail of this work the files do not give, the answer says so.
Neighbour: another subject that sounds like this one, the answer marks the limit and stays general.
False premise: the question states or assumes something the quote contradicts, the answer corrects it.
Each false premise may bring its true version, so a model does not learn to deny every confirmation.

The code only ever discards. Nothing here proves a premise false; a person decides.
"""

import hashlib
import json
import math
import re
import time

from . import agents, console, db, kb, projects, qa, rules, runs, sources, workshop

SHAPES = agents.lines("false_premise_writer", "shapes")
FALSE_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {name: {"type": "string"} for name in
                       ("fact", "false_claim", "question", "answer", "true_question", "true_answer")},
        "required": ["fact", "false_claim", "question", "answer", "true_question", "true_answer"],
    }}},
    "required": ["items"],
}
SHORT_OF_PAIRS = "not enough known pairs to start from"
MODEL_SHORT = "the model wrote fewer than asked"
TRUE_DROPPED = "its false premise was discarded"


def quotas(answered: int, unanswered_pct: int, false_premise_pct: int, neighbour_pct: int = 0) -> tuple[int, int, int]:
    """total = answered / (1 - every share); each share rounds up. No answered pair, nothing more."""
    rest = 100 - unanswered_pct - false_premise_pct - neighbour_pct
    if answered <= 0:
        return 0, 0, 0
    return (math.ceil(answered * unanswered_pct / rest), math.ceil(answered * false_premise_pct / rest),
            math.ceil(answered * neighbour_pct / rest))


def split_share(share: int) -> tuple[int, int]:
    """True versions count inside the share: 13 becomes 7 false and 6 true."""
    return math.ceil(share / 2), share // 2


def _drawn(conn, project_id: str, count: int, extraction_id: str | None) -> list[dict]:
    """Deterministic, and across themes, so the first theme does not take every false premise."""
    where = " AND extraction_id = ?" if extraction_id else ""
    rows = db.rows(
        conn,
        "SELECT id, theme_id, question, answer, quote, chunk_id, source_id FROM qa_samples q"
        f" WHERE project_id = ? AND origin = 'file' AND status != 'rejected' AND quote != ''{where}"
        " AND NOT EXISTS (SELECT 1 FROM qa_sample_links l JOIN qa_samples c ON c.id = l.sample_id"
        "                 WHERE l.based_on_id = q.id AND c.origin = 'false_premise')",
        (project_id, extraction_id) if extraction_id else (project_id,))
    return kb.round_robin(rows, lambda r: hashlib.sha256(r["id"].encode()).hexdigest())[:count]


def false_premise_prompt(project: dict, language: str, facts: list[dict]) -> str:
    listed = "\n\n".join(
        f"[P{i + 1}] Q: {f['question']}\nA: {f['answer']}\nQuote: {f['quote']}\nForm of the question: {SHAPES[i % len(SHAPES)]}"
        for i, f in enumerate(facts))
    return agents.prompt("false_premise_writer", "false_premises", project=project["display_name"], language=language,
                         states_the_claim=agents.prompt("shared", "states_the_claim"), max_sentences=qa.MAX_ANSWER_SENTENCES, facts=listed)


def _talks_about_source(*texts: str) -> bool:
    return any(qa.SOURCE_TALK.search(t) or qa.PROCESS_TALK.search(t) or kb.MATERIAL_TALK.search(t) for t in texts)


def check_false_premise(question: str, answer: str, false_claim: str, parent: dict) -> list[str]:
    reasons = qa.text_limits(question, answer)
    quote = parent["quote"]
    if not false_claim:
        reasons.append("no false claim")
    elif qa._fold(false_claim).rstrip(". ") in qa._fold(sources._norm(quote)):
        reasons.append("the false claim is in the quote")
    elif false_claim:
        # Catch an alleged error that merely rephrases a fact the evidence affirms.
        claim_words = {w for w in re.findall(r"\w+", qa._fold(false_claim)) if len(w) >= 4}
        quote_words = {w for w in re.findall(r"\w+", qa._fold(quote)) if len(w) >= 4}
        claim_numbers = qa._numbers(false_claim)
        quote_numbers = qa._numbers(quote)
        claim_fold = qa._fold(false_claim)
        quote_fold = qa._fold(quote)
        semantically_affirmed = (len(claim_words & quote_words) >= max(2, len(claim_words) - 2) and
            bool(re.search(r"\b(?:does not|doesn't|no effect|not affect|not impact|unchanged|unaffected)\b", claim_fold)) and
            bool(re.search(r"\b(?:increased|decreased|affected|impacted|changed|altered|promoted|inhibited|reduced|enhanced)\b", quote_fold)))
        if semantically_affirmed or (claim_numbers and claim_numbers <= quote_numbers and len(claim_words & quote_words) >= max(2, len(claim_words) - 2)):
            reasons.append("the quote supports the supposed false claim")
    if qa._fold(question) == qa._fold(parent.get("question", "")):
        reasons.append("same question as the pair it starts from")
    # A correction may repeat the wrong number it corrects; any other number has to be in the quote.
    stray = sorted(qa._numbers(answer) - qa._numbers(quote) - qa._numbers(false_claim))
    if stray:
        reasons.append(f"number not in the quote: {', '.join(stray)}")
    if kb.DONT_KNOW.search(qa._fold(answer)):
        reasons.append("says it does not know")
    if _talks_about_source(question, answer):
        reasons.append("talks about its source instead of the subject")
    return list(dict.fromkeys(reasons))


def states_the_claim(question: str, false_claim: str) -> list[str]:
    """A question the model wrote must hold the mistake it corrects. A person may word theirs as they like."""
    claim = {word[:5] for word in kb._long_words(false_claim)}
    asked = {word[:5] for word in kb._long_words(question)}
    # Which/What/Qual can still state the wrong detail; reject only when the claim
    # itself is mostly absent from the question.
    if len(claim & asked) < max(1, math.ceil(len(claim) * 0.45)):
        return ["question does not state the false claim"]
    return []


def check_true_version(question: str, answer: str, parent: dict, false_question: str) -> list[str]:
    reasons = qa.text_limits(question, answer)
    if qa._fold(question) in (qa._fold(parent["question"]), qa._fold(false_question)):
        reasons.append("same question as the pair it starts from")
    stray = sorted((qa._numbers(question) | qa._numbers(answer)) - qa._numbers(parent["quote"]))
    if stray:
        reasons.append(f"number not in the quote: {', '.join(stray)}")
    if _talks_about_source(question, answer):
        reasons.append("talks about its source instead of the subject")
    return reasons


def _insert(conn, llm, parent: dict, project_id: str, origin: str, question: str, answer: str, digest: str,
            false_claim: str, extraction_id: str | None) -> str:
    sid = db.new_id("qa")
    conn.execute(
        "INSERT INTO qa_samples (id, project_id, theme_id, origin, source_id, chunk_id, quote, extraction_id, model,"
        " question, answer, false_claim, content_hash, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'proposed', ?)",
        (sid, project_id, parent["theme_id"], origin, parent["source_id"], parent["chunk_id"], parent["quote"], extraction_id,
         llm.model, question, answer, false_claim, digest, db.now()))
    conn.execute("INSERT INTO qa_sample_links (sample_id, based_on_id) VALUES (?,?)", (sid, parent["id"]))
    return sid


# --- A person changes a pair's kind ---

CHANGEABLE = ("file", "refusal", "false_premise", "neighbour")


def _find_in_files(conn, project_id: str, quote: str) -> tuple[str, dict, str] | None:
    for row in db.rows(conn, "SELECT id FROM sources WHERE project_id = ? ORDER BY created_at, id", (project_id,)):
        chunk, found = qa.locate_quote(quote, sources.get_source(conn, row["id"])["chunks"])
        if chunk:
            return row["id"], chunk, found
    return None


def _proven_by(conn, sample: dict, quote: str) -> tuple[str | None, str | None, str]:
    """(source, passage, quote): a new quote has to sit in the files; without one, the pair keeps its own."""
    if quote:
        located = _find_in_files(conn, sample["project_id"], quote)
        if not located:
            raise ValueError("this quote is not in the files of this project")
        source_id, chunk, found = located
        return source_id, chunk["id"], found
    if not sample["quote"]:
        raise ValueError("this kind needs a quote from the files")
    return sample["source_id"], sample["chunk_id"], sample["quote"]


def change_kind(conn, sample_id: str, origin: str, *, question: str | None = None, answer: str | None = None, quote: str = "",
                false_claim: str = "", theme_id: str | None = None) -> dict:
    """Without what the new kind needs, the label would contradict the answer. The pair goes back to review."""
    sample = qa.get_sample(conn, sample_id)
    if origin == sample["origin"]:
        raise ValueError("the pair already has this kind")
    if origin not in CHANGEABLE or sample["origin"] not in CHANGEABLE:
        raise ValueError("only answered, unanswered, false premise and neighbouring pairs can change kind")
    resting = db.row(conn, "SELECT COUNT(*) AS n FROM qa_sample_links l JOIN qa_samples c ON c.id = l.sample_id"
                           " WHERE l.based_on_id = ? AND c.status != 'rejected'", (sample_id,))["n"]
    if resting:
        raise ValueError(f"other pairs rest on this one ({resting}); reject them before changing its kind")
    new_q = rules.normalize(question) if question is not None else sample["question"]
    new_a = rules.normalize(answer) if answer is not None else sample["answer"]
    new_claim = rules.normalize(false_claim)
    quote = rules.normalize(quote)

    if origin in ("refusal", "neighbour"):
        if qa._fold(new_a) == qa._fold(sample["answer"]):
            raise ValueError("rewrite the answer: it has to say this is not known, without naming the files" if origin == "refusal"
                             else "rewrite the answer: it has to mark the limit, then answer in general")
        # A person has judged what the files answer, so the word match that discards the model's answers does not apply.
        reasons = (kb.check_refusal if origin == "refusal" else kb.check_neighbour)(new_q, new_a, [])
        source_id, chunk_id, kept_quote, new_claim = None, None, "", ""
        target_theme = kb.limits_theme(conn, sample["project_id"])["id"]
    else:
        source_id, chunk_id, kept_quote = _proven_by(conn, sample, quote)
        target_theme = theme_id or sample["theme_id"]
        theme = qa.get_theme(conn, target_theme)
        if theme["project_id"] != sample["project_id"]:
            raise workshop.NotFound(f"theme {target_theme} not found")
        if theme["kind"] == "limits":
            raise ValueError("choose a theme for this pair: this one holds what the files do not answer")
        if origin == "false_premise":
            if not new_claim:
                raise ValueError("a false premise needs its false claim")
            reasons = check_false_premise(new_q, new_a, new_claim, {"quote": kept_quote, "question": sample["question"]})
        else:
            new_claim = ""
            reasons = qa.check_pair(new_q, new_a, kept_quote)
            if qa._fold(new_a) == qa._fold(sample["answer"]):
                reasons.append("rewrite the answer: it has to answer the question from the quote")
    if reasons:
        raise ValueError("; ".join(reasons))
    conn.execute(
        "UPDATE qa_samples SET origin = ?, source_id = ?, chunk_id = ?, quote = ?, question = ?, answer = ?, false_claim = ?,"
        " theme_id = ?, content_hash = ?, revision = revision + 1, status = 'proposed', decided_at = NULL, review_note = ''"
        " WHERE id = ?",
        (origin, source_id, chunk_id, kept_quote, new_q, new_a, new_claim, target_theme, rules.content_hash(new_q, new_a), sample_id))
    conn.execute("DELETE FROM qa_sample_links WHERE sample_id = ?", (sample_id,))
    conn.commit()
    return qa.get_sample(conn, sample_id)


def _empty_tally() -> dict:
    return {"false": 0, "true": 0, "discarded": [], "calls": 0}


def write_false_premises(conn, llm, project_id: str, count: int, *, true_versions: int | None = None,
                         extraction_id: str | None = None, tally: dict | None = None) -> dict:
    """`count` false premises and up to `true_versions` true ones. `tally` holds what is done if a batch fails."""
    project = projects.get(conn, project_id)
    tally = _empty_tally() if tally is None else tally
    true_left = count if true_versions is None else true_versions
    facts = _drawn(conn, project_id, count, extraction_id)
    if not facts and extraction_id is None and not db.row(
            conn, "SELECT 1 AS y FROM qa_samples WHERE project_id = ? AND origin = 'file' LIMIT 1", (project_id,)):
        raise ValueError("read a file first: false premises start from pairs the files answer")
    hashes = {r["content_hash"] for r in db.rows(conn, "SELECT content_hash FROM qa_samples WHERE project_id = ?", (project_id,))}
    tally["discarded"] += [{"reason": SHORT_OF_PAIRS}] * (count - len(facts))
    for start in range(0, len(facts), kb.MAX_NEW):
        batch = facts[start:start + kb.MAX_NEW]
        tally["calls"] += 1
        items = kb._ask(llm, false_premise_prompt(project, kb._language(project), batch), FALSE_SCHEMA, "writing false premises", "false_premise_writer")
        done = set()
        for item in items:
            label = re.fullmatch(r"P(\d+)", str(item.get("fact", "")).strip()) if isinstance(item, dict) else None
            index = int(label.group(1)) - 1 if label else -1
            if not 0 <= index < len(batch) or index in done:
                tally["discarded"].append({"reason": "does not name one of the facts"})
                continue
            done.add(index)
            parent = batch[index]
            question = rules.normalize(str(item.get("question", "")))
            answer = rules.normalize(str(item.get("answer", "")))
            claim = rules.normalize(str(item.get("false_claim", "")))
            digest = rules.content_hash(question, answer)
            reasons = check_false_premise(question, answer, claim, parent) + states_the_claim(question, claim)
            if digest in hashes:
                reasons.append("already in this dataset")
            if reasons:
                tally["discarded"].append({"question": question[:120], "reason": "; ".join(reasons)})
                if true_left > 0:
                    true_left -= 1
                    tally["discarded"].append({"reason": TRUE_DROPPED})
                continue
            hashes.add(digest)
            _insert(conn, llm, parent, project_id, "false_premise", question, answer, digest, claim, extraction_id)
            tally["false"] += 1
            if true_left <= 0:
                continue
            true_left -= 1
            true_q = rules.normalize(str(item.get("true_question", "")))
            true_a = rules.normalize(str(item.get("true_answer", "")))
            digest = rules.content_hash(true_q, true_a)
            reasons = check_true_version(true_q, true_a, parent, question)
            if digest in hashes:
                reasons.append("already in this dataset")
            if reasons:
                tally["discarded"].append({"question": true_q[:120], "reason": "; ".join(reasons)})
                continue
            hashes.add(digest)
            _insert(conn, llm, parent, project_id, "true_premise", true_q, true_a, digest, "", extraction_id)
            tally["true"] += 1
        conn.commit()
    return tally


def open_unanswered(conn, project_id: str, skip_extraction: str = "") -> list[dict]:
    return db.rows(conn, "SELECT id, question FROM qa_samples WHERE project_id = ? AND origin IN ('refusal', 'neighbour') AND status != 'rejected'"
                         " AND review_note = '' AND (? = '' OR extraction_id IS NOT ?)", (project_id, skip_extraction, skip_extraction))


def recheck_unanswered(conn, llm, source_id: str, skip_extraction: str = "") -> list[dict]:
    """A file may answer a question written before it. The question goes back to review, with the quote; a person decides."""
    source = sources.get_source(conn, source_id)
    returned = []
    for row in open_unanswered(conn, source["project_id"], skip_extraction):
        quote = kb.answered_in(llm, row["question"], source["chunks"])
        if quote is None:
            continue
        said = f' It says: "{quote[:300]}"' if quote else ""
        conn.execute("UPDATE qa_samples SET status = 'proposed', decided_at = NULL, review_note = ? WHERE id = ?",
                     (f"{source['name']} seems to answer this now.{said}", row["id"]))
        conn.commit()
        returned.append({"id": row["id"], "question": row["question"]})
    return returned


# --- The stage at the end of a reading ---

def _save(conn, eid: str, report: dict) -> None:
    conn.execute("UPDATE extractions SET reading = json_set(reading, '$.kinds', json(?)) WHERE id = ?",
                 (json.dumps(report, ensure_ascii=False), eid))
    conn.commit()


def _written(conn, eid: str, origin: str) -> int:
    return db.row(conn, "SELECT COUNT(*) AS n FROM qa_samples WHERE extraction_id = ? AND origin = ?", (eid, origin))["n"]


def _stage(conn, llm, eid: str, source_id: str, project_id: str, answered: int, unanswered_pct: int, false_premise_pct: int, neighbour_pct: int, returned: list) -> dict:
    """Writes only what this reading still lacks, so repeating after a failure neither re-reads nor doubles."""
    asked_unanswered, asked_share, asked_neighbours = quotas(answered, unanswered_pct, false_premise_pct, neighbour_pct)
    asked_false, asked_true = split_share(asked_share)
    tally = _empty_tally()
    refused: list[dict] = []
    outside: list[dict] = []
    began = time.monotonic()
    report = {"answered": answered, "unanswered_pct": unanswered_pct, "false_premise_pct": false_premise_pct, "neighbour_pct": neighbour_pct,
              "returned": returned, "error": "", "running": True, "calls": 0, "seconds": 0,
              "unanswered": {"asked": asked_unanswered, "written": 0, "discarded": []},
              "neighbours": {"asked": asked_neighbours, "written": 0, "discarded": []},
              "false_premises": {"asked": asked_share, "false": 0, "true": 0, "discarded": []}}

    def refresh(running: bool) -> None:
        written_u, written_n = _written(conn, eid, "refusal"), _written(conn, eid, "neighbour")
        written_f, written_t = _written(conn, eid, "false_premise"), _written(conn, eid, "true_premise")
        report["unanswered"] |= {"written": written_u, "discarded": list(refused)}
        report["neighbours"] |= {"written": written_n, "discarded": list(outside)}
        report["false_premises"] |= {"false": written_f, "true": written_t, "discarded": list(tally["discarded"])}
        report["running"] = running
        report["seconds"] = round(time.monotonic() - began)
        if not running and not report["error"] and not report.get("stopped"):
            # No retry to fill the quota: whatever is missing is shown as discarded.
            refused.extend([{"reason": MODEL_SHORT}] * (asked_unanswered - written_u - len(refused)))
            outside.extend([{"reason": MODEL_SHORT}] * (asked_neighbours - written_n - len(outside)))
            tally["discarded"].extend([{"reason": MODEL_SHORT}] * (asked_share - written_f - written_t - len(tally["discarded"])))
            report["unanswered"]["discarded"] = list(refused)
            report["neighbours"]["discarded"] = list(outside)
            report["false_premises"]["discarded"] = list(tally["discarded"])
        _save(conn, eid, report)

    refresh(True)
    calls = 0
    try:
        calls = len(open_unanswered(conn, project_id, eid))
        report["calls"] = calls
        # Keeps what an earlier try already sent back: those carry a note, so they are not asked again.
        returned.extend(recheck_unanswered(conn, llm, source_id, eid))
        refresh(True)
        for origin, asked, write, discarded in (("refusal", asked_unanswered, kb.write_refusals, refused),
                                                ("neighbour", asked_neighbours, kb.write_neighbours, outside)):
            left = asked - _written(conn, eid, origin)
            while left > 0:
                batch = min(left, kb.MAX_NEW)
                result = write(conn, llm, project_id, batch, extraction_id=eid)
                calls += 1 + result["checks"]
                report["calls"] = calls
                discarded.extend(result["rejected"])
                left -= batch
                refresh(True)
        false_left = asked_false - _written(conn, eid, "false_premise")
        true_left = asked_true - _written(conn, eid, "true_premise")
        if false_left > 0:
            write_false_premises(conn, llm, project_id, false_left, true_versions=max(true_left, 0), extraction_id=eid, tally=tally)
    except runs.Stopped:  # what was written stays; going on writes only what is still missing
        conn.rollback()
        report["stopped"] = True
        report["calls"] = calls + tally["calls"]
        refresh(False)
        raise
    except Exception as exc:  # the answered pairs stay; the person sees this and can repeat only this stage
        report["error"] = str(exc)
    report["calls"] = calls + tally["calls"]
    refresh(False)
    return report


def after_reading(conn, llm, eid: str, answered: int) -> None:
    extraction = db.row(conn, "SELECT source_id, reading FROM extractions WHERE id = ?", (eid,))
    options = json.loads(extraction["reading"] or "{}").get("options", {})
    unanswered_pct, false_premise_pct = options.get("unanswered_pct", 0), options.get("false_premise_pct", 0)
    neighbour_pct = options.get("neighbour_pct", 0)
    project_id = sources.get_source(conn, extraction["source_id"])["project_id"]
    if not (unanswered_pct or false_premise_pct or neighbour_pct or open_unanswered(conn, project_id, eid)):
        return
    earlier = json.loads(extraction["reading"] or "{}").get("kinds", {}).get("returned", [])  # going on from a stop
    _stage(conn, llm, eid, extraction["source_id"], project_id, answered, unanswered_pct, false_premise_pct, neighbour_pct, earlier)


def repeat(conn, llm, source_id: str, unanswered_pct: int, false_premise_pct: int, neighbour_pct: int = 0) -> dict:
    """The stage alone, on the latest reading of a file. The file is not read again."""
    source = sources.get_source(conn, source_id)
    latest = db.row(conn, "SELECT id, status, reading FROM extractions WHERE source_id = ? AND kind = 'qa'"
                          " ORDER BY created_at DESC, rowid DESC LIMIT 1", (source_id,))
    if not latest:
        raise ValueError("read this file first")
    if latest["status"] == "running":
        raise workshop.Conflict("this file is already generating")
    answered = _written(conn, latest["id"], "file")
    if not answered:
        raise ValueError("the latest reading of this file added no answered pair to start from")
    earlier = json.loads(latest["reading"] or "{}").get("kinds", {}).get("returned", [])
    conn.execute("UPDATE extractions SET status = 'running', reading = json_set(reading, '$.options.unanswered_pct', ?,"
                 " '$.options.false_premise_pct', ?, '$.options.neighbour_pct', ?) WHERE id = ?",
                 (unanswered_pct, false_premise_pct, neighbour_pct, latest["id"]))
    conn.commit()
    try:
        _stage(conn, llm, latest["id"], source_id, source["project_id"], answered, unanswered_pct, false_premise_pct, neighbour_pct, earlier)
    finally:
        conn.execute("UPDATE extractions SET status = ? WHERE id = ?", (latest["status"], latest["id"]))
        conn.commit()
    return sources.extraction_summary(conn, latest["id"])
