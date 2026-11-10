"""The project's knowledge base: one view over the same pairs, never a second thing to review.

The graph holds only real relations: a pair belongs to a theme, comes from a file, shares a passage with
another pair, or combines other pairs. Nothing here guesses a link between concepts.

Two model steps a person asks for, both ending in `proposed` pairs like any other:
- connect: pairs of one theme combined across passages, with the pairs they rest on recorded;
- refusals: details of this work that the files do not give, answered by saying so;
- neighbours: questions on another subject that sounds like this one, answered by marking the limit, then in general.
False premises are in `kinds.py`.

`memory.jsonl` is the same approved knowledge as the dataset, shaped to be looked up instead of trained on.
"""

import json
import re

from . import agents, console, db, projects, qa, rules, sources, workshop
from .llm import LLMError

MAX_FACTS = 24
MAX_NEW = 5
MAX_REFUSAL_QUESTIONS = 40
MAX_REFUSAL_SENTENCES = 2
MAX_NEIGHBOUR_SENTENCES = 3
MAX_LIMIT_WORDS = 30  # the sentence that marks the limit
DONT_KNOW = re.compile(r"\b(i don'?t know|i do not know|i'?m not sure|nao sei|nao tenho (certeza|informac)|no lo se)\b")
# A trained model has no documents to point at, so a refusal that names them would teach it to invent some.
# "the dataset" counts, "the HotpotQA dataset" does not: a question may well ask about a benchmark.
MATERIAL_TALK = re.compile(
    r"\b(the|this|these|those|o|a|os|as|este|esta|estes|estas|esses|essas)\s+(datasets?|documents?|files|texts?|sources?|material|documentos?|arquivos|textos?|fontes?|materiais)\b",
    re.IGNORECASE)
# A doubt about where something is printed is not a doubt about the subject.
DOCUMENT_PART = re.compile(
    r"\b(appendix|appendices|chapter|table|ap[êe]ndice|cap[íi]tulo|tabela)\s+([A-Z]\b|\d)|\b[A-Z]\.\d+\b|\b(section|se[çc][ãa]o)\s+\d", re.IGNORECASE)
ANSWER_CHECK_PASSAGES = 8  # passages shown to the model, each with its two neighbours
ANSWERED_SHARE = 0.8     # share of a question's long words found in one passage that makes it look answered
LIMITS_SLUG = "fora-do-escopo"
LIMITS_TITLE = {"pt-BR": "Fora do escopo", "pt": "Fora do escopo", "es": "Fuera de alcance"}
LICENSES = ("unspecified", "own", "permission", "open-license", "public-domain")

CONNECT_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {"question": {"type": "string"}, "answer": {"type": "string"},
                       "facts": {"type": "array", "items": {"type": "string"}}},
        "required": ["question", "answer", "facts"],
    }}},
    "required": ["items"],
}
REFUSAL_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {"question": {"type": "string"}, "answer": {"type": "string"}},
        "required": ["question", "answer"],
    }}},
    "required": ["items"],
}


ANSWER_CHECK_SCHEMA = {
    "type": "object",
    "properties": {"answered": {"type": "boolean"}, "quote": {"type": "string"}},
    "required": ["answered", "quote"],
}


def round_robin(rows: list[dict], order) -> list[dict]:
    """One from each theme in turn, so the first themes do not take everything."""
    themes: dict[str, list[dict]] = {}
    for row in sorted(rows, key=order):
        themes.setdefault(row["theme_id"], []).append(row)
    queues, out = list(themes.values()), []
    while queues:
        out += [q.pop(0) for q in queues]
        queues = [q for q in queues if q]
    return out


def _language(project: dict) -> str:
    return projects.LANGUAGE_NAME.get(project["language"], project["language"])


def _seen(conn, project_id: str) -> tuple[set, list]:
    earlier = db.rows(conn, "SELECT question, content_hash FROM qa_samples WHERE project_id = ?", (project_id,))
    return {e["content_hash"] for e in earlier}, [rules.word_shingles(e["question"]) for e in earlier]


def _duplicate(question: str, digest: str, hashes: set, shingles: list) -> bool:
    mine = rules.word_shingles(question)
    return digest in hashes or any(rules.jaccard(mine, s) >= qa.NEAR_DUPLICATE for s in shingles)


def _ask(llm, prompt: str, schema: dict, what: str, agent: str) -> list:
    try:
        with console.acting(agent):
            items = llm.complete_json(prompt, schema, temperature=0.3).get("items")
    except LLMError as exc:
        raise workshop.Conflict(f"model call failed while {what}: {exc}") from exc
    if not isinstance(items, list):
        raise workshop.Conflict(f"model output unparseable while {what}: missing 'items' list")
    return items


# --- Connect: pairs that rest on more than one passage ---

def _facts(conn, theme_id: str) -> list[dict]:
    """Approved pairs first, so a connection tends to rest on what a person already accepted."""
    rows = db.rows(
        conn,
        "SELECT id, question, answer, quote, chunk_id, source_id FROM qa_samples"
        " WHERE theme_id = ? AND origin = 'file' AND status != 'rejected'"
        " ORDER BY status = 'approved' DESC, created_at, id", (theme_id,))
    return rows[:MAX_FACTS]


def connect_prompt(project: dict, language: str, theme: dict, facts: list[dict]) -> str:
    listed = "\n".join(f"[F{i + 1}] Q: {f['question']}\nA: {f['answer']}" for i, f in enumerate(facts))
    return agents.prompt("connection_writer", "connect", project=project["display_name"], theme=theme["title"], most=MAX_NEW,
                         language=language, max_sentences=qa.MAX_ANSWER_SENTENCES, facts=listed)


def connect(conn, llm, theme_id: str) -> dict:
    theme = qa.get_theme(conn, theme_id)
    project = projects.get(conn, theme["project_id"])
    facts = _facts(conn, theme_id)
    if len({f["chunk_id"] for f in facts}) < 2:
        raise ValueError("this theme needs pairs from at least two passages before they can be connected")
    items = _ask(llm, connect_prompt(project, _language(project), theme, facts), CONNECT_SCHEMA, "connecting pairs", "connection_writer")
    hashes, shingles = _seen(conn, project["id"])
    kept, rejected = [], []
    for item in items[:MAX_NEW]:
        if not isinstance(item, dict):
            rejected.append({"reason": "not an object"})
            continue
        question = rules.normalize(str(item.get("question", "")))
        answer = rules.normalize(str(item.get("answer", "")))
        labels = item.get("facts") if isinstance(item.get("facts"), list) else []
        picked = {}
        for label in labels:
            found = re.fullmatch(r"F(\d+)", str(label).strip())
            if found and 1 <= int(found.group(1)) <= len(facts):
                picked[int(found.group(1))] = facts[int(found.group(1)) - 1]
        used = list(picked.values())
        evidence = " ".join(f"{f['question']} {f['answer']} {f['quote']}" for f in used)
        reasons = qa.check_pair(question, answer, evidence)
        if len({f["chunk_id"] for f in used}) < 2:
            reasons.append("does not rest on two different passages")
        digest = rules.content_hash(question, answer)
        if _duplicate(question, digest, hashes, shingles):
            reasons.append("too close to a question already asked")
        if reasons:
            rejected.append({"question": question[:120], "reason": "; ".join(reasons)})
            continue
        hashes.add(digest)
        shingles.append(rules.word_shingles(question))
        sid = db.new_id("qa")
        conn.execute(
            "INSERT INTO qa_samples (id, project_id, theme_id, origin, model, question, answer, content_hash, status, created_at)"
            " VALUES (?,?,?, 'connection', ?,?,?,?, 'proposed', ?)",
            (sid, project["id"], theme_id, llm.model, question, answer, digest, db.now()))
        conn.executemany("INSERT INTO qa_sample_links (sample_id, based_on_id) VALUES (?,?)",
                         [(sid, f["id"]) for f in used])
        kept.append(sid)
    conn.commit()
    return {"kept": len(kept), "rejected": rejected}


# --- Refusals: what the model should say it does not know ---

def limits_theme(conn, project_id: str) -> dict:
    """Like "Other", this theme does not count against the limit."""
    found = db.row(conn, "SELECT * FROM qa_themes WHERE project_id = ? AND kind = 'limits'", (project_id,))
    if found:
        return found
    language = projects.get(conn, project_id)["language"]
    tid = db.new_id("thm")
    conn.execute(
        "INSERT INTO qa_themes (id, project_id, slug, title, description, kind, created_at) VALUES (?,?,?,?,?, 'limits', ?)",
        (tid, project_id, LIMITS_SLUG, LIMITS_TITLE.get(language, "Out of scope"),
         "Questions the files do not answer.", db.now()))
    return db.row(conn, "SELECT * FROM qa_themes WHERE id = ?", (tid,))


def refusal_prompt(project: dict, language: str, themes: list[dict], questions: list[str], count: int,
                   already: list[str] | None = None) -> str:
    covered = "\n".join(f"- {t['title']}" + (f": {t['description']}" if t.get("description") else "") for t in themes)
    asked = "\n".join(f"- {q}" for q in questions)
    written = "\n\n" + agents.prompt("shared", "already_written", questions="\n".join(f"- {q}" for q in already)) if already else ""
    written += "\nNever ask about publication or acceptance dates, editors, journal details, instruments, or equipment/model configuration settings. Ask only details of the scientific work."
    return agents.prompt("doubt_writer", "doubts", project=project["display_name"], count=count, plain_doubt=agents.prompt("shared", "plain_doubt"),
                         language=language, max_sentences=MAX_REFUSAL_SENTENCES, themes=covered, known=asked, written=written)


def neighbour_prompt(project: dict, language: str, themes: list[dict], questions: list[str], count: int,
                     already: list[str] | None = None) -> str:
    covered = "\n".join(f"- {t['title']}" + (f": {t['description']}" if t.get("description") else "") for t in themes)
    asked = "\n".join(f"- {q}" for q in questions)
    written = "\n\n" + agents.prompt("shared", "already_written", questions="\n".join(f"- {q}" for q in already)) if already else ""
    return agents.prompt("neighbour_writer", "neighbours", count=count, language=language, themes=covered, known=asked, written=written)


def _terms(text: str) -> list[str]:
    words = (w[:-1] if len(w) > 3 and w.endswith("s") else w for w in re.findall(r"\w+", qa._fold(text)))
    return [w for w in words if len(w) >= 3]


def nearest_passages(question: str, chunks: list[dict], top: int = ANSWER_CHECK_PASSAGES) -> list[str]:
    """The passages sharing the question's rarer words, each with its neighbours, in file order. Words only: the model decides."""
    bags = [set(_terms(c["text"])) for c in chunks]
    wanted = set(_terms(question))
    frequency = {w: sum(w in bag for bag in bags) for w in wanted}
    score = lambda bag: sum(1 / frequency[w] for w in wanted & bag)
    ranked = sorted((i for i, bag in enumerate(bags) if wanted & bag), key=lambda i: -score(bags[i]))[:top]
    picked = sorted({j for i in ranked for j in (i - 1, i, i + 1) if 0 <= j < len(chunks)})
    return [chunks[j]["text"] for j in picked]


def answer_check_prompt(question: str, excerpts: list[str]) -> str:
    listed = "\n\n".join(f"[{i}] {text}" for i, text in enumerate(excerpts, 1))
    return agents.prompt("answer_checker", "check", question=question, excerpts=listed)


def answered_in(llm, question: str, chunks: list[dict]) -> str | None:
    """Asks the model whether the text answers the question. Returns the quote it points at, or None. A model failure raises."""
    excerpts = nearest_passages(question, chunks)
    if not excerpts:
        return None
    with console.acting("answer_checker"):
        found = llm.complete_json(answer_check_prompt(question, excerpts), ANSWER_CHECK_SCHEMA, temperature=0.0)
    if not isinstance(found, dict) or not isinstance(found.get("answered"), bool):
        raise LLMError(f"model {llm.model} broke the structured-output contract while checking a question against the files")
    # A yes without a real quote still counts: a question wrongly dropped costs less than teaching "I don't know" about something the files say.
    return str(found.get("quote") or "").strip() if found["answered"] else None


def _long_words(text: str) -> set[str]:
    return {w for w in re.findall(r"\w+", qa._fold(text)) if len(w) >= 5}


def looks_answered(question: str, passages: list[set[str]]) -> bool:
    """Cheap and language-free: nearly all the question's long words sitting in one passage. Only ever discards."""
    words = _long_words(question)
    if len(words) < 3:
        return False
    return any(len(words & passage) >= ANSWERED_SHARE * len(words) for passage in passages)


def _sentences(answer: str) -> int:
    return len(rules.sentences(answer))


def _beyond_the_files(question: str, answer: str, passages: list[set[str]], what: str) -> list[str]:
    """What holds for an answer that no file proves."""
    reasons = qa.text_limits(question, answer)
    if any(qa.SOURCE_TALK.search(text) or MATERIAL_TALK.search(text) or DOCUMENT_PART.search(text) for text in (question, answer)):
        reasons.append("talks about its source instead of the subject")
    if qa._numbers(answer) - qa._numbers(question):
        reasons.append(f"{what} must not state numbers of its own")
    if looks_answered(question, passages):
        reasons.append("the files seem to answer this question")
    return reasons


def check_refusal(question: str, answer: str, passages: list[set[str]]) -> list[str]:
    reasons = _beyond_the_files(question, answer, passages, "a refusal")
    if _sentences(answer) > MAX_REFUSAL_SENTENCES:
        reasons.append(f"longer than {MAX_REFUSAL_SENTENCES} sentences")
    return reasons


# A model that leans on one word teaches the student to refuse by the look of a question.
FILLER = re.compile(r"\b(?:specific|specifically|exact|exactly|precise|precisely|particular|especific[oa]s?|exat[oa]s?)\b")


def check_written_refusal(question: str, answer: str, passages: list[set[str]]) -> list[str]:
    """A refusal the model wrote. A person may word theirs as they like."""
    reasons = check_refusal(question, answer, passages)
    if re.search(r"\b(editor|publication|published|accepted for publication|acceptance date|journal|instrument|flow cytometry|encoder settings|settings used|configuration|parameter settings)\b", qa._fold(question)):
        reasons.append("asks about publication details or technical settings")
    if FILLER.search(qa._fold(question)):
        reasons.append("the question is vague")
    if bare_refusal(question, answer):
        reasons.append("says only that it does not know, without naming what")
    return list(dict.fromkeys(reasons))


def bare_refusal(question: str, answer: str) -> bool:
    """"I don't know." alone, many times over, teaches a student to say it to everything, sums included.
    Naming what is not known ties the refusal to the question."""
    return not _long_words(answer) & _long_words(question)


# --- One answer for many questions ---

REPEAT_MIN = 5        # pairs with the same answer before it is worth saying
REPEAT_SHARE = 0.05   # of the pairs going out
REWORD_BATCH = 8
REWORD_SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": {
    "type": "object", "properties": {"id": {"type": "string"}, "answer": {"type": "string"}}, "required": ["id", "answer"]}}},
    "required": ["items"]}


def repeated_answers(samples: list[dict]) -> list[dict]:
    """The same words answering many questions: a student learns the words, not when to say them."""
    groups: dict[str, list[dict]] = {}
    for s in samples:
        groups.setdefault(qa._fold(s["answer"]).strip(" .!"), []).append(s)
    found = []
    for members in groups.values():
        if len(members) >= REPEAT_MIN and len(members) >= REPEAT_SHARE * len(samples):
            rewordable = [m["id"] for m in members if m["origin"] == "refusal" and bare_refusal(m["question"], m["answer"])]
            found.append({"answer": members[0]["answer"], "count": len(members), "rewordable": rewordable,
                          "message": f'{len(members)} pairs answer only "{members[0]["answer"]}". '
                                     "A model trained on them tends to say it to every question."})
    return sorted(found, key=lambda f: -f["count"])


def reword_refusals(conn, llm, project_id: str, sample_ids: list[str], batch: str) -> dict:
    """The model names what is not known; each pair goes back to review, and the old words are kept for Undo."""
    project = projects.get(conn, project_id)
    marks = ",".join("?" * len(sample_ids))
    todo = db.rows(conn, f"SELECT id, question, answer, status, decided_at, content_hash FROM qa_samples WHERE project_id = ?"
                         f" AND origin = 'refusal' AND id IN ({marks}) ORDER BY id", (project_id, *sample_ids))
    todo = [t for t in todo if bare_refusal(t["question"], t["answer"])]
    done, kept = 0, []
    from . import curation, runs
    for start in range(0, len(todo), REWORD_BATCH):
        runs.check()
        runs.progress(done, len(todo))
        part = todo[start:start + REWORD_BATCH]
        listed = "\n".join(f"- id {t['id']}: {t['question']}" for t in part)
        prompt = agents.prompt("doubt_writer", "reword", language=_language(project), max_sentences=MAX_REFUSAL_SENTENCES, questions=listed)
        written = {str(i.get("id")): rules.normalize(str(i.get("answer", ""))) for i in _ask(llm, prompt, REWORD_SCHEMA, "rewording refusals", "doubt_writer")
                   if isinstance(i, dict)}
        for t in part:
            answer = written.get(t["id"], "")
            # The question was already approved by a person; only the new answer is checked.
            if not answer or check_refusal(t["question"], answer, []) or bare_refusal(t["question"], answer) \
                    or DONT_KNOW.search(qa._fold(answer)) is None:
                continue
            new_hash = rules.content_hash(t["question"], answer)
            conn.execute("INSERT INTO qa_rewords(batch_id, sample_id, answer, status, decided_at, new_hash, created_at) VALUES (?,?,?,?,?,?,?)",
                         (batch, t["id"], t["answer"], t["status"], t["decided_at"], new_hash, db.now()))
            conn.execute("UPDATE qa_samples SET answer = ?, content_hash = ?, revision = revision + 1, status = 'proposed',"
                         " decided_at = NULL, review_note = '' WHERE id = ?", (answer, new_hash, t["id"]))
            curation.event(conn, qa.get_sample(conn, t["id"]), "edit", {"by": "reword"})
            kept.append(t["id"])
        conn.commit()
        done += len(part)
    runs.progress(done, len(todo))
    return {"batch_id": batch, "reworded": len(kept), "left": len(todo) - len(kept)}


def undo_reword(conn, project_id: str, batch_id: str) -> dict:
    """Puts the old words and decision back on every pair nobody changed since."""
    from . import curation
    rows = db.rows(conn, "SELECT r.* FROM qa_rewords r JOIN qa_samples s ON s.id = r.sample_id"
                         " WHERE r.batch_id = ? AND s.project_id = ? AND s.content_hash = r.new_hash", (batch_id, project_id))
    for r in rows:
        question = qa.get_sample(conn, r["sample_id"])["question"]
        conn.execute("UPDATE qa_samples SET answer = ?, content_hash = ?, revision = revision + 1, status = ?, decided_at = ? WHERE id = ?",
                     (r["answer"], rules.content_hash(question, r["answer"]), r["status"], r["decided_at"], r["sample_id"]))
        curation.event(conn, qa.get_sample(conn, r["sample_id"]), "edit", {"by": "undo_reword"})
    conn.execute("DELETE FROM qa_rewords WHERE batch_id = ?", (batch_id,))
    conn.commit()
    return {"restored": len(rows)}


def check_neighbour(question: str, answer: str, passages: list[set[str]]) -> list[str]:
    """The limit and the general answer can only be told apart by reading: a person checks that part."""
    reasons = _beyond_the_files(question, answer, passages, "a neighbouring answer")
    count = _sentences(answer)
    if count > MAX_NEIGHBOUR_SENTENCES:
        reasons.append(f"longer than {MAX_NEIGHBOUR_SENTENCES} sentences")
    if count < 2:
        reasons.append("needs the limit and a general answer")
    if DONT_KNOW.search(qa._fold(answer)):
        reasons.append("says it does not know instead of answering in general")
    if len(re.split(r"(?<=[.!?])\s", answer.strip())[0].split()) > MAX_LIMIT_WORDS:
        reasons.append("recites what was studied instead of naming it briefly")
    return list(dict.fromkeys(reasons))


def _known_questions(known: list[dict], already: int) -> list[str]:
    """A sample across themes that moves on with each batch, so later batches see other questions."""
    ordered = [k["question"] for k in round_robin(known, lambda k: (k["status"] != "approved", k["created_at"], k["id"]))]
    start = already * MAX_REFUSAL_QUESTIONS // MAX_NEW % len(ordered)
    return (ordered[start:] + ordered[:start])[:MAX_REFUSAL_QUESTIONS]


def _write_beyond_the_files(conn, llm, project_id: str, origin: str, prompt_for, check, what: str, count: int,
                            extraction_id: str | None) -> dict:
    project = projects.get(conn, project_id)
    known = db.rows(conn, "SELECT question, theme_id, status, created_at, id FROM qa_samples"
                          " WHERE project_id = ? AND origin = 'file' AND status != 'rejected'", (project_id,))
    if not known:
        raise ValueError(f"read a file first: {what} are written against what the files already answer")
    themes = qa._topics(conn, project_id)
    already = [r["question"] for r in db.rows(conn, "SELECT question FROM qa_samples WHERE project_id = ? AND origin = ?"
                                                    " AND status != 'rejected' ORDER BY created_at, id", (project_id, origin))]
    prompt = prompt_for(project, _language(project), themes, _known_questions(known, len(already)), count, already)
    agent = "doubt_writer" if origin == "refusal" else "neighbour_writer"
    items = _ask(llm, prompt, REFUSAL_SCHEMA, f"writing {what}", agent)
    chunks = db.rows(conn, "SELECT c.text FROM source_chunks c JOIN sources s ON s.id = c.source_id"
                           " WHERE s.project_id = ? ORDER BY s.created_at, s.id, c.idx", (project_id,))
    passages = [_long_words(c["text"]) for c in chunks]
    hashes, shingles = _seen(conn, project_id)
    kept, rejected, checks = 0, [], 0
    for item in items[:count]:
        if not isinstance(item, dict):
            rejected.append({"reason": "not an object"})
            continue
        question = rules.normalize(str(item.get("question", "")))
        answer = rules.normalize(str(item.get("answer", "")))
        reasons = check(question, answer, passages)
        digest = rules.content_hash(question, answer)
        if _duplicate(question, digest, hashes, shingles):
            reasons.append("near-duplicate of a question already in this dataset")
        if reasons:
            rejected.append({"question": question[:120], "reason": "; ".join(dict.fromkeys(reasons))})
            continue
        checks += 1
        quote = answered_in(llm, question, chunks)
        if quote is not None:
            rejected.append({"question": question[:120], "reason": "the files answer this question", "quote": quote[:300]})
            continue
        hashes.add(digest)
        shingles.append(rules.word_shingles(question))
        theme = limits_theme(conn, project_id)
        conn.execute(
            "INSERT INTO qa_samples (id, project_id, theme_id, origin, extraction_id, model, question, answer, content_hash, status, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?, 'proposed', ?)",
            (db.new_id("qa"), project_id, theme["id"], origin, extraction_id, llm.model, question, answer, digest, db.now()))
        kept += 1
    conn.commit()
    console.outcome(agent, what, kept, [r["reason"] for r in rejected])
    return {"kept": kept, "rejected": rejected, "checks": checks}


def write_refusals(conn, llm, project_id: str, count: int = MAX_NEW, *, extraction_id: str | None = None) -> dict:
    return _write_beyond_the_files(conn, llm, project_id, "refusal", refusal_prompt, check_written_refusal, "refusals", count, extraction_id)


def write_neighbours(conn, llm, project_id: str, count: int = MAX_NEW, *, extraction_id: str | None = None) -> dict:
    return _write_beyond_the_files(conn, llm, project_id, "neighbour", neighbour_prompt, check_neighbour, "neighbouring questions", count, extraction_id)


# --- The graph ---

def graph(conn, project_id: str) -> dict:
    """Project -> themes -> pairs, with files and shared passages. A rejected pair is not part of the knowledge."""
    project = projects.get(conn, project_id)
    themes = qa.list_themes(conn, project_id)
    samples = [s for s in qa.list_samples(conn, project_id) if s["status"] != "rejected"]
    root = f"project:{project_id}"
    nodes = [{"id": root, "type": "project", "label": project["display_name"]}]
    links = []
    for t in themes:
        if t["proposed"] or t["approved"] or t["kind"] == "topic":
            nodes.append({"id": t["id"], "type": "theme", "label": t["title"], "kind": t["kind"],
                          "proposed": t["proposed"], "approved": t["approved"]})
            links.append({"source": root, "target": t["id"], "kind": "theme"})
    shown = {n["id"] for n in nodes}
    by_chunk: dict[str, list[str]] = {}
    files = {}
    for s in samples:
        if s["theme_id"] not in shown:
            continue
        nodes.append({"id": s["id"], "type": "pair", "label": s["question"], "status": s["status"],
                      "origin": s["origin"], "pillar": s["pillar"], "theme_id": s["theme_id"], "confidence": s["curation"]["level"], "confidence_reasons": s["curation"]["reasons"]})
        links.append({"source": s["theme_id"], "target": s["id"], "kind": "member"})
        if s["source_id"]:
            files.setdefault(s["source_id"], s["source_name"])
            links.append({"source": f"file:{s['source_id']}", "target": s["id"], "kind": "file"})
        if s["chunk_id"]:
            by_chunk.setdefault(s["chunk_id"], []).append(s["id"])
        for parent in s.get("based_on") or []:
            check = 'positions' if s['origin'] == 'complex' else 'combination' if s['origin'] == 'connection' else 'correction' if s['origin'] == 'false_premise' else 'evidence'
            confirmed = s['curation']['level'] != 'low' and s['curation']['checks'].get(check, False)
            links.append({"source": parent["id"], "target": s["id"], "kind": "combines",
                          "review_state": "confirmed" if confirmed else "proposed"})
    nodes += [{"id": f"file:{sid}", "type": "file", "label": name} for sid, name in files.items()]
    # A chain, not a clique: it says the same thing with far fewer lines.
    for members in by_chunk.values():
        links += [{"source": a, "target": b, "kind": "passage"} for a, b in zip(members, members[1:])]
    # An open conflict is an edge like any other: both ends are recorded, and resolving it removes the line.
    links += [{"source": c["first_id"], "target": c["second_id"], "kind": "tension", "review_state": "proposed"} for c in db.rows(
        conn, "SELECT first_id, second_id FROM qa_conflicts WHERE project_id = ? AND status = 'open' AND second_id != ''", (project_id,))]
    present = {n["id"] for n in nodes}
    links = [l for l in links if l["source"] in present and l["target"] in present]
    return {"nodes": nodes, "links": links, "approved": sum(s["status"] == "approved" for s in samples),
            "proposed": sum(s["status"] == "proposed" for s in samples)}


# --- Long-term memory export ---

def memory_records(conn, project_id: str, sample_ids: set[str], canonical_id) -> list[dict]:
    """One lookup record per pair, its kind on it. A false claim or an open question is knowledge only with its label.
    Behavior conversations are not knowledge, a true version repeats the pair it comes from, and a neighbouring
    answer is the LLM's own general knowledge: looked up, the module returns nothing and the LLM answers alone."""
    checked = [{"source": r["name"], "sha256": r["sha256"]} for r in db.rows(
        conn, "SELECT name, sha256 FROM sources WHERE project_id = ? ORDER BY name", (project_id,))]
    records = []
    for s in qa.list_samples(conn, project_id, status="approved"):
        if s["id"] not in sample_ids or s["origin"] in ("behavior", "true_premise", "neighbour"):
            continue
        base = {"id": canonical_id(s["id"]), "revision": s["revision"], "question": s["question"], "theme": s["theme_title"],
                "tags": [s["theme_slug"]], "approved_at": s["decided_at"], "pillar": s["pillar"]}
        if s["origin"] == "refusal":
            # No answer: "I don't know" in the first person is training text, and the kind already says it.
            records.append(base | {"kind": "unanswered", "checked_against": checked})
            continue
        evidence = s["based_on"] if s["origin"] == "connection" else [s]
        if s["origin"] == "complex":
            evidence = [e for e in [s, *s["based_on"]] if e.get("quote")]
        base |= {"answer": s["answer"], "kind": s["origin"], "evidence": [
            {"source": e.get("source_name"), "page": e.get("page"), "quote": e.get("quote")} for e in evidence]}
        if s["origin"] == "false_premise":
            # Written in the reading that found it, a false premise rests on its own quote and corrects no pair.
            base |= {"false_claim": s["false_claim"]} | ({"corrects": canonical_id(s["based_on"][0]["id"])} if s["based_on"] else {})
        records.append(base)
    return sorted(records, key=lambda r: r["id"])


def set_license(conn, source_id: str, license_basis: str) -> dict:
    if license_basis not in LICENSES:
        raise ValueError(f"license must be one of: {', '.join(LICENSES)}")
    sources.get_source(conn, source_id)
    conn.execute("UPDATE sources SET license_basis = ? WHERE id = ?", (license_basis, source_id))
    conn.commit()
    return {"id": source_id, "license_basis": license_basis}


def source_rights(conn, project_id: str, sample_ids: set[str]) -> list[dict]:
    """The files behind an export, connected pairs' files included, and what was declared about each."""
    rows = db.rows(conn, "SELECT DISTINCT s.name, s.sha256, s.license_basis, q.id AS sample_id FROM qa_samples q"
                         " LEFT JOIN qa_sample_links l ON l.sample_id = q.id"
                         " LEFT JOIN qa_samples p ON p.id = l.based_on_id"
                         " JOIN sources s ON s.id = COALESCE(q.source_id, p.source_id) WHERE q.project_id = ?", (project_id,))
    seen = {}
    for row in rows:
        if row["sample_id"] in sample_ids:
            seen[row["sha256"]] = {"name": row["name"], "sha256": row["sha256"], "license_basis": row["license_basis"]}
    return sorted(seen.values(), key=lambda r: r["name"])
