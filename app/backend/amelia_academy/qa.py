"""File -> themes -> question/answer pairs -> curation -> OKF wiki. `kb.py` adds what spans pairs.

The model writes every pair; a source passage is only its proof. Cutting source text into a
question and an answer stays forbidden (docs/erros-da-primeira-implementacao.md).

Invariants:
- a project holds at most `max_themes` topic themes; "Other" and behavior themes do not count;
- a pair may only use a theme from the closed list, otherwise it lands in "Other";
- a pair is kept only when its quote appears verbatim in one passage of the section it was written from;
- pairs are born `proposed`; only `approved` pairs reach an export or the wiki;
- a model failure fails the run visibly and never falls back to another model.
"""

import json
import math
import re
import threading
import time
import unicodedata

from . import agents, console, db, okf, projects, rules, runs, sources, workshop
from .cli_tools import provider_of
from .llm import LLMError, OutputCapped

WINDOW_CHARS = 4500      # a window never crosses a section unless that section is under MIN_SECTION_CHARS
_theme_proposal_guard = threading.Lock()
_theme_proposal_locks: dict[str, threading.Lock] = {}
_READ_STARTED: dict[str, float] = {}
MIN_WINDOW_CHARS = 120   # shorter windows are headings or fragments
MIN_SECTION_CHARS = 1500 # a shorter section joins the next one
MAX_WINDOWS = 120        # windows read per run; the run reports read vs total
MAX_PER_WINDOW = 6       # default; each read may choose between the two limits below
PAIRS_PER_WINDOW_LIMITS = (1, 12)
WINDOW_CHARS_LIMITS = (2000, 8000)
KIND_PCT_LIMITS = (0, 30)  # share of each added kind (unanswered, false premise, neighbour) in what a reading writes
MAX_QUESTION_CHARS = 500
MAX_ANSWER_CHARS = 900
MAX_ANSWER_SENTENCES = 4
NEAR_DUPLICATE = 0.95    # only almost identical questions are filtered; closer ideas go to curation
REPEAT_PENALTY = 1.3  # only on the retry of a window where the model ran away
SIMILAR_QUESTION = 0.6   # content-word Jaccard: above this, two questions are shown together in curation
SIMILAR_LOOSE = (0.4, 0.6)  # or: a question this close whose answer is this close
OUTLINE_WINDOWS = 40
OUTLINE_CHARS = 300
RESERVE_FOR_LATER = 0.6  # share of the free theme slots one file may take, so later files still fit
READ_AMOUNTS = {"quick": 0.45, "normal": 0.75, "everything": 1.0}
READ_CARE = {"direct": (7, 8), "balanced": (15, 15), "careful": (25, 25)}


def read_preferences(amount="normal", care="balanced", mix=None, *, windows=1):
    """Translate plain choices into bounded legacy settings, keeping old API values useful."""
    pairs = {"quick": 3, "normal": 6, "everything": 10}.get(amount, MAX_PER_WINDOW)
    false_pct, doubt_pct = READ_CARE.get(care, READ_CARE["balanced"])
    if mix:
        false_pct = max(0, min(30, int(mix.get("false", false_pct))))
        doubt_pct = max(0, min(30, int(mix.get("doubts", doubt_pct))))
    return {"pairs_per_section": pairs, "false_per_section": min(4, math.ceil(false_pct * pairs / 70)),
            "doubts_per_section": min(4, math.ceil(doubt_pct * pairs / 70)),
            "false_premise_pct": false_pct, "unanswered_pct": doubt_pct}


def factual_density(text: str) -> int:
    """Conservative count of sentence-sized, factual claims suitable for a pair."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    count = 0
    for sentence in sentences:
        words = re.findall(r"\b[\w-]+\b", sentence)
        if len(words) < 4:
            continue
        has_number = bool(re.search(r"\b\d+(?:[.,]\d+)?\b", sentence))
        has_name = bool(re.search(r"\b[A-Z][a-z]{2,}\b", sentence))
        has_cause = bool(re.search(r"\b(?:caused|leads? to|results? in|increases?|decreases?|because|therefore|causa|aumenta|diminui|resulta)\b", sentence, re.I))
        has_assertion = bool(re.search(r"\b(?:is|are|was|were|has|have|show|found|measured|contains|produces|is associated|é|são|foi|foram|tem|mostra|encontrou|contém)\b", sentence, re.I))
        count += bool(has_number or has_name or has_cause or has_assertion)
    return int(count)


def density_limit(window: list[dict], amount="normal") -> int:
    facts = sum(factual_density(c["text"]) for c in window)
    return min(MAX_PER_WINDOW if amount == "normal" else PAIRS_PER_WINDOW_LIMITS[1],
               max(0, math.ceil(facts * READ_AMOUNTS.get(amount, READ_AMOUNTS["normal"]))))


def mix_targets(known: int, false_pct: int, doubt_pct: int) -> tuple[int, int]:
    """Project-wide target counts for each added kind, relative to known pairs."""
    known_pct = max(1, 100 - false_pct - doubt_pct)
    return round(known * false_pct / known_pct), round(known * doubt_pct / known_pct)
OTHER_SLUG = "outros"
OTHER_TITLE = {"pt-BR": "Outros", "pt": "Outros", "es": "Otros"}
SOURCE_TALK = re.compile(
    r"\b(according to|in|from) (the|this) (text|passage|section|document|article)\b"
    r"|\b(the|this) (passage|section)\b"
    r"|\b(segundo|de acordo com|conforme|no|neste|na|nesta) (o |a |este |esta )?(texto|trecho|passagem|seção|documento|artigo)\b"
    # The reader does not see the picture, and [P12] is the number this program gives a passage.
    r"|\b(the|this) (diagram|figure(?!\s+of\b)|picture|illustration|chart)\b"
    r"|\b(the|this) image (shows|illustrates|depicts|compares|displays)\b"
    r"|\b(o|este|esse) diagrama\b|\b(a|esta|essa) (figura|ilustração)\b|\b(a|esta|essa) imagem (mostra|ilustra|compara)\b"
    r"|\b(figure|figura|fig\.?|diagram|diagrama)\s*\d"
    r"|\[P\d+\]|\b(section|passage|seção|trecho|passagem)\s+P\d+\b",
    re.IGNORECASE)
PROCESS_TALK = re.compile(r"\b(?:original statement|corrected information|the corrected version|wrong detail|false premise|the source pair)\b", re.I)

THEME_SCHEMA = {
    "type": "object",
    "properties": {
        "themes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"title": {"type": "string"}, "description": {"type": "string"}},
                "required": ["title", "description"],
            },
        }
    },
    "required": ["themes"],
}


def pair_schema(slugs: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "answer": {"type": "string"},
                        "quote": {"type": "string"},
                        "theme": {"type": "string", "enum": slugs},
                    },
                    "required": ["question", "answer", "quote", "theme"],
                },
            }
        },
        "required": ["items"],
    }


# --- Themes ---

def other_theme(conn, project_id: str) -> dict:
    found = db.row(conn, "SELECT * FROM qa_themes WHERE project_id = ? AND kind = 'other'", (project_id,))
    if found:
        return found
    language = projects.get(conn, project_id)["language"]
    tid = db.new_id("thm")
    conn.execute(
        "INSERT INTO qa_themes (id, project_id, slug, title, description, kind, created_at) VALUES (?,?,?,?,?, 'other', ?)",
        (tid, project_id, OTHER_SLUG, OTHER_TITLE.get(language, "Other"), "", db.now()))
    conn.commit()
    return db.row(conn, "SELECT * FROM qa_themes WHERE id = ?", (tid,))


def _topics(conn, project_id: str) -> list[dict]:
    return db.rows(conn, "SELECT * FROM qa_themes WHERE project_id = ? AND kind = 'topic' ORDER BY created_at, id", (project_id,))


def list_themes(conn, project_id: str) -> list[dict]:
    other_theme(conn, project_id)
    themes = db.rows(
        conn,
        "SELECT t.*,"
        " SUM(s.status = 'proposed') AS proposed, SUM(s.status = 'approved') AS approved,"
        " SUM(s.status = 'rejected') AS rejected"
        " FROM qa_themes t LEFT JOIN qa_samples s ON s.theme_id = t.id WHERE t.project_id = ?"
        " GROUP BY t.id ORDER BY CASE t.kind WHEN 'topic' THEN 0 WHEN 'behavior' THEN 1 ELSE 2 END, t.created_at, t.id",
        (project_id,))
    for theme in themes:
        for key in ("proposed", "approved", "rejected"):
            theme[key] = theme[key] or 0
        theme["pillars"] = {pillar: {"proposed": 0, "approved": 0} for pillar in PILLARS}
    by_id = {t["id"]: t for t in themes}
    for row in db.rows(conn, "SELECT theme_id, origin, status, COUNT(*) AS n FROM qa_samples WHERE project_id = ? AND status != 'rejected'"
                             " GROUP BY theme_id, origin, status", (project_id,)):
        if row["theme_id"] in by_id:
            by_id[row["theme_id"]]["pillars"][PILLAR.get(row["origin"], "known")][row["status"]] += row["n"]
    topics = [t for t in themes if t["kind"] == "topic"]
    from . import kb
    bags = {}
    for t in topics:
        bags[t["id"]] = set(kb._terms(t["title"]))
        for row in db.rows(conn, "SELECT question, answer FROM qa_samples WHERE theme_id=? AND status!='rejected' LIMIT 100", (t["id"],)):
            bags[t["id"]].update(kb._terms(row["question"] + " " + row["answer"]))
    for theme in topics:
        a = bags[theme["id"]]
        choices = []
        for other in topics:
            if other["id"] == theme["id"]: continue
            b = bags[other["id"]]
            score = len(a & b) / len(a | b) if a | b else 0
            if score >= 0.42: choices.append((score, other["id"]))
        theme["merge_suggestion"] = max(choices)[1] if choices else ""
    return themes


def get_theme(conn, theme_id: str) -> dict:
    theme = db.row(conn, "SELECT * FROM qa_themes WHERE id = ?", (theme_id,))
    if not theme:
        raise workshop.NotFound(f"theme {theme_id} not found")
    return theme


def _free_slug(conn, project_id: str, title: str) -> str | None:
    slug = okf.slugify(title)
    taken = conn.execute("SELECT 1 FROM qa_themes WHERE project_id = ? AND slug = ?", (project_id, slug)).fetchone()
    return None if taken or slug == OTHER_SLUG else slug


def _insert_topic(conn, project_id: str, slug: str, title: str, description: str) -> dict:
    tid = db.new_id("thm")
    conn.execute(
        "INSERT INTO qa_themes (id, project_id, slug, title, description, kind, created_at) VALUES (?,?,?,?,?, 'topic', ?)",
        (tid, project_id, slug, title, description, db.now()))
    return db.row(conn, "SELECT * FROM qa_themes WHERE id = ?", (tid,))


def create_theme(conn, project_id: str, title: str, description: str = "") -> dict:
    title = rules.normalize(title)
    if not title:
        raise ValueError("a theme needs a title")
    passages = conn.execute("SELECT COUNT(*) FROM source_chunks c JOIN sources s ON s.id=c.source_id WHERE s.project_id=? AND c.kind='text'", (project_id,)).fetchone()[0]
    limit = theme_limit(passages)
    if len(_topics(conn, project_id)) >= limit:
        raise workshop.Conflict(f"this dataset is at its limit of {limit} themes; raise the limit or merge two themes")
    slug = _free_slug(conn, project_id, title)
    if not slug:
        raise workshop.Conflict(f"a theme named '{title}' already exists")
    theme = _insert_topic(conn, project_id, slug, title, rules.normalize(description))
    conn.commit()
    return theme


def edit_theme(conn, theme_id: str, title: str | None = None, description: str | None = None) -> dict:
    """The slug stays: earlier exports keep pointing at the same theme."""
    theme = get_theme(conn, theme_id)
    new_title = rules.normalize(title) if title is not None else theme["title"]
    if not new_title:
        raise ValueError("a theme needs a title")
    new_description = rules.normalize(description) if description is not None else theme["description"]
    conn.execute("UPDATE qa_themes SET title = ?, description = ? WHERE id = ?", (new_title, new_description, theme_id))
    conn.commit()
    return get_theme(conn, theme_id)


def merge_theme(conn, theme_id: str, into_id: str) -> dict:
    """Move every pair into another theme of the same project and free the slot."""
    theme, into = get_theme(conn, theme_id), get_theme(conn, into_id)
    if theme_id == into_id:
        raise ValueError("a theme cannot be merged into itself")
    if theme["project_id"] != into["project_id"]:
        raise workshop.NotFound(f"theme {into_id} not found")
    if theme["kind"] != "topic":
        raise workshop.Conflict("only a topic theme can be merged away")
    operation = {"theme": dict(theme), "created": [],
                 "pairs": [{"id": r[0], "theme_id": theme_id} for r in conn.execute("SELECT id FROM qa_samples WHERE theme_id = ?", (theme_id,))]}
    ids = [item["id"] for item in operation["pairs"]]
    for sample_id in ids:
        conn.execute("DELETE FROM qa_comparisons WHERE first_id=? OR second_id=?", (sample_id, sample_id))
    conn.execute("UPDATE qa_samples SET theme_id = ? WHERE theme_id = ?", (into_id, theme_id))
    conn.execute("DELETE FROM qa_themes WHERE id = ?", (theme_id,))
    conn.commit()
    return {"theme": dict(into), "undo": operation}


def split_theme(conn, theme_id: str, llm) -> dict:
    """Ask the selected model to name two groups and assign every pair; nothing is written until valid."""
    theme = get_theme(conn, theme_id)
    if theme["kind"] != "topic":
        raise workshop.Conflict("only a topic theme can be split")
    pairs = db.rows(conn, "SELECT id, question, answer FROM qa_samples WHERE theme_id=? ORDER BY id", (theme_id,))
    if len(pairs) < 2:
        raise ValueError("this theme needs at least two pairs to split")
    schema = {
        "type": "object",
        "properties": {
            "themes": {"type": "array", "items": {"type": "object", "properties": {
                "title": {"type": "string"}, "description": {"type": "string"}}, "required": ["title", "description"]}, "minItems": 2, "maxItems": 2},
            "groups": {"type": "array", "items": {"type": "object", "properties": {
                "pair_id": {"type": "string"}, "group": {"type": "integer", "enum": [0, 1]}}, "required": ["pair_id", "group"]}},
        }, "required": ["themes", "groups"]}
    project = projects.get(conn, theme["project_id"])
    prompt = agents.prompt("theme_splitter", "split", theme=theme["title"], language=project["language"],
                           pairs=json.dumps(pairs, ensure_ascii=False))
    from . import console
    with console.acting("theme_splitter"):
        draft = llm.complete_json(prompt, schema, temperature=0.1)
    proposed = draft.get("themes") or []
    assignment = {x.get("pair_id"): x.get("group") for x in draft.get("groups", [])}
    ids = {p["id"] for p in pairs}
    if len(proposed) != 2 or set(assignment) != ids or any(v not in (0,1) for v in assignment.values()):
        raise ValueError("the model did not assign every pair to two themes")
    titles = [rules.normalize(t.get("title", "")) for t in proposed]
    if not all(titles) or titles[0].casefold() == titles[1].casefold():
        raise ValueError("the model did not suggest two different theme names")
    slugs = [_free_slug(conn, theme["project_id"], title) for title in titles]
    if not all(slugs) or slugs[0] == slugs[1]:
        raise workshop.Conflict("a suggested theme name already exists")
    return {"theme_id": theme_id, "theme_title": theme["title"],
            "themes": [{"title": titles[i], "description": rules.normalize(proposed[i].get("description", "")), "count": sum(v == i for v in assignment.values())} for i in range(2)],
            "groups": assignment}


def confirm_theme_split(conn, theme_id: str, proposal: dict) -> dict:
    theme = get_theme(conn, theme_id)
    if theme["kind"] != "topic" or proposal.get("theme_id") != theme_id:
        raise workshop.Conflict("this theme changed before the split was confirmed")
    pairs = db.rows(conn, "SELECT id FROM qa_samples WHERE theme_id=? ORDER BY id", (theme_id,))
    assignment = proposal.get("groups") or {}
    if len(pairs) < 2 or set(assignment) != {p["id"] for p in pairs} or any(v not in (0, 1) for v in assignment.values()):
        raise workshop.Conflict("the pairs changed before the split was confirmed")
    proposed = proposal.get("themes") or []
    if len(proposed) != 2:
        raise ValueError("choose two suggested themes")
    titles = [rules.normalize(t.get("title", "")) for t in proposed]
    if not all(titles) or titles[0].casefold() == titles[1].casefold():
        raise ValueError("choose two different theme names")
    slugs = [_free_slug(conn, theme["project_id"], title) for title in titles]
    if not all(slugs) or slugs[0] == slugs[1]:
        raise workshop.Conflict("a suggested theme name already exists")
    themes = [_insert_topic(conn, theme["project_id"], slugs[i], titles[i], rules.normalize(proposed[i].get("description", ""))) for i in range(2)]
    snapshot = {"theme":dict(theme),"created":[t["id"] for t in themes],"pairs":[{"id":p["id"],"theme_id":theme_id} for p in pairs]}
    for pair in pairs:
        conn.execute("DELETE FROM qa_comparisons WHERE first_id=? OR second_id=?", (pair["id"], pair["id"]))
    for pid, group in assignment.items():
        conn.execute("UPDATE qa_samples SET theme_id=? WHERE id=?", (themes[group]["id"], pid))
    conn.execute("DELETE FROM qa_themes WHERE id=?", (theme_id,))
    conn.commit()
    return {"themes":themes,"undo":snapshot}


def undo_theme_operation(conn, project_id: str, snapshot: dict) -> dict:
    old = snapshot.get("theme") or {}
    if old.get("project_id") != project_id or conn.execute("SELECT 1 FROM qa_themes WHERE id=?",(old.get("id"),)).fetchone():
        raise workshop.Conflict("this theme change can no longer be undone")
    conn.execute("INSERT INTO qa_themes (id,project_id,slug,title,description,kind,pattern_id,created_at) VALUES (?,?,?,?,?,?,?,?)",
                 tuple(old.get(k) for k in ("id","project_id","slug","title","description","kind","pattern_id","created_at")))
    for item in snapshot.get("pairs",[]):
        conn.execute("UPDATE qa_samples SET theme_id=? WHERE id=? AND project_id=?", (item["theme_id"],item["id"],project_id))
        conn.execute("DELETE FROM qa_comparisons WHERE first_id=? OR second_id=?", (item["id"], item["id"]))
    for tid in snapshot.get("created",[]):
        conn.execute("DELETE FROM qa_themes WHERE id=? AND project_id=?",(tid,project_id))
    conn.commit()
    return {"ok":True}


def new_theme_slots(limit: int, used: int) -> int:
    """How many new themes one file may open. Part of the free slots stays for later files."""
    return math.ceil(max(0, limit - used) * RESERVE_FOR_LATER)

def theme_limit(passages: int) -> int:
    return max(3, min(20, passages // 40))


def _outline(windows: list[list[dict]]) -> str:
    step = max(1, len(windows) // OUTLINE_WINDOWS)
    return "\n".join(f"- {sources._norm(' '.join(c['text'] for c in w))[:OUTLINE_CHARS]}"
                     for w in windows[::step][:OUTLINE_WINDOWS])


def theme_prompt(project: dict, language: str, existing: list[dict], slots: int, windows: list[list[dict]]) -> str:
    known = "\n".join(f"- {t['title']}" for t in existing) or "(none yet)"
    return agents.prompt("theme_proposer", "themes", project=project["display_name"], slots=slots, existing=known, language=language,
                         outline=_outline(windows))


def propose_themes(conn, llm, project: dict, language: str, windows: list[list[dict]]) -> list[dict]:
    """Fill free slots from an outline of the whole file, before any pair is written. Raises LLMError on failure."""
    existing = _topics(conn, project["id"])
    passages = conn.execute("SELECT COUNT(*) FROM source_chunks c JOIN sources s ON s.id=c.source_id WHERE s.project_id=? AND c.kind='text'", (project["id"],)).fetchone()[0]
    slots = new_theme_slots(theme_limit(passages), len(existing))
    if not slots:
        return []
    with console.acting("theme_proposer"):
        proposed = llm.complete_json(theme_prompt(project, language, existing, slots, windows), THEME_SCHEMA, temperature=0.1)
    # Model calls can overlap, but two files must not reserve the same theme slug.
    with _theme_proposal_guard:
        guard = _theme_proposal_locks.setdefault(project["id"], threading.Lock())
    with guard:
        room = min(slots, project["max_themes"] - len(_topics(conn, project["id"])))
        created = []
        for item in (proposed.get("themes") or []):
            if len(created) >= room:
                break
            title = rules.normalize(str(item.get("title", ""))) if isinstance(item, dict) else ""
            slug = _free_slug(conn, project["id"], title) if title else None
            if slug:
                created.append(_insert_topic(conn, project["id"], slug, title, rules.normalize(str(item.get("description", "")))))
        conn.commit()
        return created


# --- Windows ---

SECTIONS_LEFT_OUT = {
    "bibliography": {"references", "reference", "bibliography", "works cited", "literature", "referencias",
                     "referencias bibliograficas", "bibliografia", "references cited", "literatur", "literaturverzeichnis",
                     "references bibliographiques", "bibliographie"},
    "acknowledgements": {"acknowledgements", "acknowledgments", "acknowledgement", "acknowledgment", "agradecimentos",
                         "agradecimientos", "remerciements", "danksagung"},
    "table of contents": {"contents", "table of contents", "sumario", "indice", "table des matieres", "inhaltsverzeichnis"},
    "affiliations": {"affiliations", "author affiliations", "author information", "institutional affiliations"},
    "metadata": {"funding", "funding information", "author contributions", "conflict of interest", "conflicts of interest",
                 "data availability", "ethics statement", "supplementary information", "accepted manuscript details"},
}
ROLES_LEFT_OUT = {"caption": "figure or table caption", "margin": "text in the page margin", "figure_label": "label inside a figure"}


def _page_of(chunk: dict):
    page = (chunk.get("locator") or {}).get("page")
    return page if isinstance(page, int) else None


def _folded_title(section: str) -> str:
    """A heading without its number, case or accents, to compare against the lists below."""
    plain = re.sub(r"^(?:[A-Z]|\d+)(?:\.\d+)*[.)]?\s+", "", section.strip())
    return re.sub(r"[^a-z ]", "", _fold(plain)).strip()


def _left_out_section(section: str) -> str | None:
    title = _folded_title(section)
    for reason, names in SECTIONS_LEFT_OUT.items():
        if title in names:
            return reason
    return None


def _sum_chars(chunks: list[dict]) -> int:
    return sum(len(c["text"].strip()) for c in chunks)


def _windows_by_page(chunks: list[dict], window_chars: int = WINDOW_CHARS) -> list[list[dict]]:
    """A file with no detected headings: consecutive passages, inside one page and under the window size."""
    windows, current, size, page = [], [], 0, None
    for chunk in chunks:
        text = chunk["text"].strip()
        this_page = _page_of(chunk)
        crosses_page = page is not None and this_page is not None and this_page != page
        if current and (crosses_page or size + len(text) > window_chars):
            windows.append(current)
            current, size = [], 0
        current.append(chunk)
        size += len(text)
        if this_page is not None:
            page = this_page
    if current:
        windows.append(current)
    return windows


def _opens_paragraph(chunk: dict) -> bool:
    return not (chunk.get("locator") or {}).get("element_char_start")


def _split_at_paragraphs(chunks: list[dict], window_chars: int = WINDOW_CHARS) -> list[list[dict]]:
    """Cut under the window size at the last paragraph start. Only one huge paragraph gets cut inside."""
    windows, current, size = [], [], 0
    for chunk in chunks:
        length = len(chunk["text"].strip())
        if current and size + length > window_chars:
            cut = next((i for i in range(len(current) - 1, 0, -1) if _opens_paragraph(current[i])), len(current))
            windows.append(current[:cut])
            current = current[cut:]
            size = _sum_chars(current)
        current.append(chunk)
        size += length
    if current:
        windows.append(current)
    return windows


IMAGE_KINDS = {"ocr_text", "figure_reading"}  # what a vision model wrote about a figure


def read_plan(chunks: list[dict], *, window_chars: int = WINDOW_CHARS, images: bool = True) -> dict:
    """What a run will read and what it will leave out, and why. Decided by code, before any model call.

    Sections stay whole when they fit. One too short to stand alone joins the next.
    """
    usable = [c for c in chunks if c["text"].strip()]
    left_out: dict[str, dict] = {}

    def leave(reason: str, group: list[dict]):
        entry = left_out.setdefault(reason, {"reason": reason, "passages": 0, "chars": 0})
        entry["passages"] += len(group)
        entry["chars"] += _sum_chars(group)

    kept = []
    for chunk in usable:
        role = (chunk.get("locator") or {}).get("role")
        if not images and chunk.get("kind") in IMAGE_KINDS:
            leave("image reading, with images off", [chunk])
        elif role in ROLES_LEFT_OUT:
            leave(ROLES_LEFT_OUT[role], [chunk])
        else:
            kept.append(chunk)

    groups: list[tuple[str | None, list[dict]]] = []
    for chunk in kept:
        section = (chunk.get("locator") or {}).get("section")
        if groups and groups[-1][0] == section:
            groups[-1][1].append(chunk)
        else:
            groups.append((section, [chunk]))

    if not any(section for section, _ in groups):
        windows = _windows_by_page(kept, window_chars)
        by_section = False
        sections = 0
    else:
        by_section = True
        reading = []
        for at, (section, group) in enumerate(groups):
            reason = _left_out_section(section) if section else None
            # Title and authors sit before the first heading. A real opening text is long enough to stay.
            if not section and at == 0 and _sum_chars(group) < MIN_SECTION_CHARS:
                reason = "before the first heading"
            if reason:
                leave(reason, group)
            else:
                reading.append(group)
        sections = len(reading)
        merged: list[list[dict]] = []
        pending: list[dict] = []
        for group in reading:
            pending = pending + group
            if _sum_chars(pending) >= MIN_SECTION_CHARS:
                merged.append(pending)
                pending = []
        if pending:
            if merged and _sum_chars(merged[-1]) + _sum_chars(pending) <= window_chars:
                merged[-1] = merged[-1] + pending
            else:
                merged.append(pending)
        windows = [w for group in merged for w in _split_at_paragraphs(group, window_chars)]

    short = [w for w in windows if _sum_chars(w) < MIN_WINDOW_CHARS]
    for window in short:
        leave("too short to read", window)
    windows = [w for w in windows if _sum_chars(w) >= MIN_WINDOW_CHARS]
    return {"windows": windows, "by_section": by_section, "sections": sections,
            "left_out": sorted(left_out.values(), key=lambda e: -e["passages"])}


def make_windows(chunks: list[dict]) -> list[list[dict]]:
    return read_plan(chunks)["windows"]


# --- Generation ---

def locate_quote(quote: str, window: list[dict]) -> tuple[dict | None, str | None]:
    """The passage a quote proves from, and the quote as the source has it.

    A paragraph longer than one passage is cut, so a true quote can run into the next passage.
    """
    for chunk in window:
        found = sources.find_quote(quote, chunk["text"])
        if found:
            return chunk, _citation_sentence(chunk["text"], found)
    for chunk, following in zip(window, window[1:]):
        if following["index"] == chunk["index"] + 1:
            found = sources.find_quote(quote, sources.join_passages(chunk["text"], following["text"]))
            if found:
                return chunk, _citation_sentence(sources.join_passages(chunk["text"], following["text"]), found)
    return None, None


def _citation_sentence(text: str, quote: str) -> str:
    """Expand a matched span to the complete sentence that carries the evidence."""
    at = text.find(quote)
    if at < 0:
        return quote
    boundaries = list(re.finditer(r"(?<=[.!?])\s+(?=[A-ZΑ-Ω0-9])|\n+", text))
    start = max((m.end() for m in boundaries if m.end() <= at), default=0)
    end = min((m.start() for m in boundaries if m.start() >= at + len(quote)), default=len(text))
    return text[start:end].strip()


# With method details disabled, omit implementation and experimental procedure,
# including materials and conditions. Keep outcome questions (e.g. growth
# comparisons) eligible even when the passage also describes an experiment.
METHOD_WORDS = re.compile(
    r"\b(?:protocol\w*|instrument\w*|equipment|reagent\w*|supplier\w*|vendor\w*|"
    r"software|version|encoder|architecture\s+of\s+(?:the\s+)?encoder|"
    r"configuration\w*|centrifug\w*|rpm|incubat\w*|cultiv\w*|culture\w*|"
    r"growth\s+medium|media|ypd|dntp|buffer\w*|kit\b|plasmids?\s+(?:were|was)\s+(?:obtained|verified|constructed|received)|how\s+(?:were|was)\b[^?]{0,60}\b(?:verified|obtained|constructed|cloned)\b|inserts?\s+for\s+the\s+plasmids?|"
    r"fund(?:ing|er|ers)|grant\w*|donat\w*|gift\w*|received\s+as\s+(?:a\s+)?gift|"
    r"study\s+design|experimental\s+design|method\s+(?:was|were)\s+used|what\s+(?:was\s+)?the\s+(?:specific\s+)?method|"
    r"protocollo|instrumento|reagente|fornecedor|vers[aã]o\s+do\s+software|configura[cç][aã]o)\b",
    re.I,
)
# An answer may name a medium or a method as context; only protocol detail in it is a method pair.
METHOD_ANSWER_WORDS = re.compile(
    r"\b(?:centrifug\w*|rpm|incubat\w*|reagent\w*|kit\b|dntp|encoder|supplier\w*|vendor\w*|protocol\w*|ypd)\b", re.I)


def answer_sentences(project: dict) -> int:
    return 3 if project.get("answer_style", "short") == "short" else 5


def pair_prompt(project: dict, language: str, themes: list[dict], window: list[dict], most: int = MAX_PER_WINDOW) -> str:
    def marked(chunk: dict) -> str:
        mark = f" · {agents.prompt('shared', 'figure_mark')}" if chunk.get("kind") == "figure_reading" else ""
        return f"[P{chunk['index']}{mark}] {chunk['text'].strip()}"

    listed = "\n".join(f"- {t['slug']}: {t['title']}" + (f" ({t['description']})" if t.get("description") else "")
                       for t in themes)
    passages = "\n\n".join(marked(c) for c in window)
    return agents.prompt("passage_reader", "pairs", project=project["display_name"], most=most, language=language, max_sentences=answer_sentences(project),
                         other_theme=OTHER_SLUG, themes=listed, passages=passages) + _scope_rules(project)


def _scope_rules(project):
    scope = (project.get("about_scope") or "").strip()
    text = f"\nProject scope: {scope}. Write knowledge pairs only about this scope. If a passage is outside it, return no pairs from it." if scope else ""
    if not project.get("include_method", 0):
        text += (" Do not write questions about protocols, instrument configuration, reagents, suppliers, or software/version details. "
                 "Do not include methods or implementation details in either questions or answers: omit protocols, experimental procedures, "
                 "study design, instrument settings, centrifugation, incubation or culture conditions, media, reagents, buffers, kits, "
                 "plasmids or other gifted materials, funding or funder roles, software and encoder architecture (including layer counts). "
                 "Questions about findings and results remain welcome, including comparisons of outcomes such as growth versus a control.")
    return text


def pillars_schema(slugs: list[str]) -> dict:
    text = {"type": "string"}
    def group(**fields):
        return {"type": "array", "items": {"type": "object", "properties": fields, "required": list(fields)}}
    theme = {"type": "string", "enum": slugs}
    return {"type": "object",
            "properties": {"known": group(question=text, answer=text, quote=text, theme=theme),
                           "false_premise": group(false_claim=text, question=text, answer=text, quote=text, theme=theme),
                           "not_known": group(question=text, answer=text, theme=theme)},
            "required": ["known", "false_premise", "not_known"]}


def pillars_prompt(project: dict, language: str, themes: list[dict], window: list[dict], most: int, falses: int, doubts: int) -> str:
    """One reading, three groups: what the section establishes, what it rules out, and where it stops."""
    def marked(chunk: dict) -> str:
        mark = f" · {agents.prompt('shared', 'figure_mark')}" if chunk.get("kind") == "figure_reading" else ""
        return f"[P{chunk['index']}{mark}] {chunk['text'].strip()}"

    listed = "\n".join(f"- {t['slug']}: {t['title']}" + (f" ({t['description']})" if t.get("description") else "") for t in themes)
    passages = "\n\n".join(marked(c) for c in window)
    false_group = agents.prompt("passage_reader", "false_premise_group", most=falses, language=language, max_sentences=MAX_ANSWER_SENTENCES,
                                states_the_claim=agents.prompt("shared", "states_the_claim")) if falses else agents.prompt("passage_reader", "false_premise_none")
    doubt_group = agents.prompt("passage_reader", "not_known_group", most=doubts, language=language,
                                plain_doubt=agents.prompt("shared", "plain_doubt")) if doubts else agents.prompt("passage_reader", "not_known_none")
    return agents.prompt("passage_reader", "pillars", project=project["display_name"], most=most, language=language, max_sentences=answer_sentences(project),
                         other_theme=OTHER_SLUG, themes=listed, false_premise_group=false_group, not_known_group=doubt_group, passages=passages) + _scope_rules(project)


def _numbers(text: str) -> set[str]:
    return {n.replace(",", ".").rstrip(".") for n in re.findall(r"\d+(?:[.,]\d+)*", text)}


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode("ascii")


def text_limits(question: str, answer: str, project: dict | None = None) -> list[str]:
    """What holds for any pair, whoever wrote it."""
    reasons = []
    if not question:
        reasons.append("empty question")
    if not answer:
        reasons.append("empty answer")
    if len(question) > MAX_QUESTION_CHARS:
        reasons.append(f"question longer than {MAX_QUESTION_CHARS} characters")
    if len(answer) > MAX_ANSWER_CHARS:
        reasons.append(f"answer longer than {MAX_ANSWER_CHARS} characters")
    limit = answer_sentences(project or {})
    if len(rules.sentences(answer)) > limit:
        reasons.append(f"answer longer than {limit} sentences")
    return reasons + rules.forbidden_fragments(f"{question} {answer}")


# "the system" means one thing beside its section and nothing in a dataset drawn from many files.
UNNAMED_SUBJECT = re.compile(
    r"(?:\b(?:the|this|these|that|those)\s+(?:proposed\s+|new\s+|novel\s+)?(?:system|framework|study|model|method|approach|paper|research|authors?|technique|algorithm)\b"
    r"|\b(?:o|a|os|as|este|esta|esse|essa)\s+(?:sistema|estudo|modelo|m[ée]todo|abordagem|artigo|pesquisa|autor(?:es)?|t[ée]cnica|algoritmo)\b)"
    r"(?!\s+(?:of|for|by|called|named|de|do|da|chamad[oa]))", re.IGNORECASE)


def check_pair(question: str, answer: str, section: str, project: dict | None = None) -> list[str]:
    """Why a pair the model wrote cannot be proposed. Empty means it can."""
    reasons = text_limits(question, answer, project)
    if project and not project.get("include_method", 0) and (METHOD_WORDS.search(question) or METHOD_ANSWER_WORDS.search(answer)):
        reasons.append("asks about method details")
    if SOURCE_TALK.search(question) or SOURCE_TALK.search(answer):
        reasons.append("talks about its source instead of the subject")
    if PROCESS_TALK.search(question) or PROCESS_TALK.search(answer):
        reasons.append("talks about the process instead of the subject")
    if UNNAMED_SUBJECT.search(question):
        reasons.append("question does not name its subject")
    if re.search(r"\b(?:accepted|acceptance) date|\bdate\b.{0,40}\baccepted\b|\b(?:funding|grant number|plasmid donor|who provided|author affiliation|email address|postal address|corresponding author|acknowledg|reference title)\b", question, re.I):
        reasons.append("asks about publication or author details")
    if len(question) >= 25 and _fold(question) in _fold(sources._norm(section)):
        reasons.append("question copied from the source")
    # A PDF table may split a thousands comma: "86, 864" in the source is the 86,864 of the answer.
    glued = re.sub(r"(\d),\s+(\d{3})\b", r"\1,\2", section)
    stray = sorted(_numbers(answer) - _numbers(section) - _numbers(glued) - _numbers(question))
    if stray:
        reasons.append(f"answer states numbers the section does not hold: {', '.join(stray)}")
    for sentence in rules.sentences(answer):
        def stemmed(text):
            terms = {re.sub(r"(?:ation|ions|ing|ed|es|s)$", "", w.casefold()) for w in re.findall(r"\b[\w-]+\b", text)}
            aliases = {"osmoprotective": "protect", "osmoprotection": "protect", "proliferation": "grow", "viability": "surviv", "anhydrobiosis": "desiccat"}
            return terms | {aliases[t] for t in terms if t in aliases} | {t for t, root in aliases.items() if root in terms}
        passage_terms = stemmed(section)
        rare = [w for w in re.findall(r"\b[\w-]+\b", sentence) if len(w) >= 13 and
                re.sub(r"(?:ation|ions|ing|ed|es|s)$", "", w.casefold()) not in passage_terms]
        if rare:
            reasons.append("the answer uses a rare technical word the passage does not support")
            break
    return list(dict.fromkeys(reasons))


def _plan_summary(plan: dict, options: dict, figures: dict | None = None) -> str:
    summary = {k: plan[k] for k in ("by_section", "sections", "left_out")} | {"options": options}
    if figures:
        summary["figures"] = figures
    return json.dumps(summary, ensure_ascii=False)


def start(conn, source_id: str, model: str, *, pairs_per_section: int = MAX_PER_WINDOW,
          section_chars: int = WINDOW_CHARS, images: bool = False, unanswered_pct: int | None = None, false_premise_pct: int | None = None,
          neighbour_pct: int | None = None, false_per_section: int | None = None, doubts_per_section: int | None = None,
          amount: str = "normal", care: str = "direct", mix: dict | None = None) -> str:
    """Record the run so it can be polled. Fails before any model call when the file cannot run."""
    source = sources.get_source(conn, source_id)
    derived = read_preferences(amount, care, mix)
    # Calls using the old numeric API with no named mix keep their old direct-only behavior.
    # The Files UI always sends the explicit 7/8 mix for the named Direct choice.
    if mix is None and care == "direct":
        derived.update(false_per_section=0, doubts_per_section=0)
        if unanswered_pct is None and false_premise_pct is None:
            derived.update(false_premise_pct=0, unanswered_pct=0)
    pairs_per_section = pairs_per_section if pairs_per_section != MAX_PER_WINDOW else derived["pairs_per_section"]
    false_per_section = false_per_section if false_per_section is not None else derived["false_per_section"]
    doubts_per_section = doubts_per_section if doubts_per_section is not None else derived["doubts_per_section"]
    false_premise_pct = false_premise_pct if false_premise_pct is not None else derived["false_premise_pct"]
    unanswered_pct = unanswered_pct if unanswered_pct is not None else derived["unanswered_pct"]
    neighbour_pct = neighbour_pct if neighbour_pct is not None else int((mix or {}).get("neighbour", 0))
    options = {"amount": amount, "care": care, "mix": mix, "pairs_per_section": pairs_per_section, "section_chars": section_chars, "images": images,
               "unanswered_pct": unanswered_pct, "false_premise_pct": false_premise_pct, "neighbour_pct": neighbour_pct,
               "false_per_section": false_per_section, "doubts_per_section": doubts_per_section}
    conn.execute("UPDATE projects SET last_read_amount=? WHERE id=(SELECT project_id FROM sources WHERE id=?)", (amount, source_id))
    conn.commit()
    plan = read_plan(source["chunks"], window_chars=section_chars, images=images)
    windows = plan["windows"]
    if not windows and not (images and sources.unread_figures(source)):
        hint = " Turn on Read images to read its pictures." if source["assets"] and not images else ""
        raise sources.SourceRejected(f"the file has no section with at least {MIN_WINDOW_CHARS} characters to read.{hint}")
    if conn.execute("SELECT 1 FROM extractions WHERE source_id = ? AND status = 'running'", (source_id,)).fetchone():
        raise workshop.Conflict("this file is already generating")
    eid = db.new_id("ext")
    conn.execute(
        "INSERT INTO extractions (id, source_id, runtime, model, status, rejected, reading, passages_total, kind, created_at)"
        " VALUES (?,?, ?, ?, 'running', '[]', ?, ?, 'qa', ?)",
        (eid, source_id, provider_of(model), model, _plan_summary(plan, options),
         min(len(windows), MAX_WINDOWS) + (len(sources.unread_figures(source)) if images else 0), db.now()))
    conn.commit()
    return eid


def stop_interrupted(conn) -> int:
    """A run still `running` when the API starts went away with the previous process. Nothing kept is lost: it can go on."""
    changed = conn.execute("UPDATE extractions SET status = 'stopped', error = 'the app closed before this finished',"
                           " reading = CASE WHEN json_type(reading, '$.kinds') IS NULL THEN reading"
                           " ELSE json_set(reading, '$.kinds.running', json('false'), '$.kinds.stopped', json('true')) END"
                           " WHERE status = 'running'").rowcount
    conn.commit()
    return changed


def resume(conn, source_id: str) -> dict:
    """Pick up the latest reading of a file where it stopped. The run itself skips the sections already read."""
    sources.get_source(conn, source_id)
    latest = db.row(conn, "SELECT id, model, reading, status, passages_read, passages_total FROM extractions"
                          " WHERE source_id = ? AND kind = 'qa' ORDER BY created_at DESC, id DESC LIMIT 1", (source_id,))
    if latest and latest["status"] == "running":
        raise workshop.Conflict("this file is already generating")
    if not latest or not sources.can_continue(latest["status"], latest["passages_read"], latest["passages_total"]):
        raise ValueError("nothing to continue here; read the file again")
    conn.execute("UPDATE extractions SET status = 'running', error = NULL WHERE id = ?", (latest["id"],))
    conn.commit()
    return latest


def _read_window(llm, prompt: str, schema: dict) -> dict:
    """A model that starts repeating itself gets one more try, told not to repeat. A second cut-off reaches the caller."""
    with console.acting("passage_reader"):
        try:
            return llm.complete_json(prompt, schema, temperature=0.2)
        except OutputCapped:
            return llm.complete_json(prompt, schema, temperature=0.2, options={"repeat_penalty": REPEAT_PENALTY})


def _finish(conn, eid: str, status: str, error: str | None, rejected: list, read: int) -> dict:
    started = _READ_STARTED.pop(eid, None)
    elapsed = max(0, round(time.monotonic() - started, 2)) if started is not None else None
    conn.execute("UPDATE extractions SET status = ?, error = ?, rejected = ?, passages_read = ?, duration_seconds = ? WHERE id = ?",
                 (status, error, json.dumps(rejected, ensure_ascii=False), read, elapsed, eid))
    conn.commit()
    return sources.extraction_summary(conn, eid)


def run(conn, llm, eid: str, *, out_dir=None, vision=None) -> dict:
    """Read the figures when asked, propose themes, then write pairs one section at a time.
    Pairs already kept stay when a later section fails or a person stops the run, and it can go on from there."""
    _READ_STARTED[eid] = time.monotonic()
    try:
        return _run(conn, llm, eid, out_dir, vision)
    except runs.Stopped:
        conn.rollback()
        started = _READ_STARTED.pop(eid, None)
        elapsed = max(0, round(time.monotonic() - started, 2)) if started is not None else None
        conn.execute("UPDATE extractions SET status = 'stopped', error = NULL, duration_seconds = ? WHERE id = ?", (elapsed, eid))
        conn.commit()
        raise
    except Exception as exc:
        conn.rollback()
        started = _READ_STARTED.pop(eid, None)
        elapsed = max(0, round(time.monotonic() - started, 2)) if started is not None else None
        conn.execute("UPDATE extractions SET status = 'failed', error = ?, duration_seconds = ? WHERE id = ?", (f"internal error: {exc}", elapsed, eid))
        conn.commit()
        raise


def _read_figures_first(conn, eid: str, source_id: str, out_dir, vision, options: dict) -> dict:
    """Unread figures only. A figure that fails is counted and shown; the text of the file is still read."""
    source_before = sources.get_source(conn, source_id)
    passage_hint = min(len(read_plan(source_before["chunks"], window_chars=options["section_chars"], images=True)["windows"]), MAX_WINDOWS)
    def report(figures: dict):
        conn.execute("UPDATE extractions SET reading = json_set(reading, '$.figures', json(?)) WHERE id = ?",
                     (json.dumps(figures), eid))
        conn.commit()

        total = figures.get("total", 0)
        done = figures.get("read", 0) + figures.get("failed", 0) + figures.get("skipped", 0)
        runs.progress(done, total + passage_hint)
        if total and done < total:
            runs.say(f"Reading figure {done + 1} of {total}")
        elif total:
            runs.say("")

    report(sources.read_figures(conn, out_dir, source_id, vision, on_progress=report))
    source = sources.get_source(conn, source_id)
    plan = read_plan(source["chunks"], window_chars=options["section_chars"], images=True)
    figures = json.loads(db.row(conn, "SELECT reading FROM extractions WHERE id = ?", (eid,))["reading"]).get("figures")
    figure_count = (figures or {}).get("read", 0) + (figures or {}).get("failed", 0) + (figures or {}).get("skipped", 0)
    runs.progress(figure_count, figure_count + min(len(plan["windows"]), MAX_WINDOWS))
    conn.execute("UPDATE extractions SET reading = ?, passages_total = ? WHERE id = ?",
                 (_plan_summary(plan, options, figures), figure_count + min(len(plan["windows"]), MAX_WINDOWS), eid))
    conn.commit()
    return source


def _listed(found: dict, key: str) -> list[dict]:
    """A group the model got wrong is that group's loss, not the reading's."""
    items = found.get(key)
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


_DOUBT_STOPWORDS = set("how many what which who whom where when why does do did is are was were the a an in of for to and with from on as by according about other besides".split())


def _doubt_terms(text: str) -> set[str]:
    """Keep technical names intact (CAHS, phrA) while dropping question scaffolding."""
    return {word for word in re.findall(r"\w+", _fold(text)) if len(word) >= 3 and word not in _DOUBT_STOPWORDS}


def _run(conn, llm, eid: str, out_dir=None, vision=None) -> dict:
    extraction = db.row(conn, "SELECT source_id, reading, rejected, passages_read FROM extractions WHERE id = ?", (eid,))
    options = {"pairs_per_section": MAX_PER_WINDOW, "section_chars": WINDOW_CHARS, "images": False,
               **json.loads(extraction["reading"] or "{}").get("options", {})}
    source = sources.get_source(conn, extraction["source_id"])
    # Going on from a stop: figures and themes came before the first section, and what was read stays read.
    read = extraction["passages_read"] or 0
    pending_figures = len(sources.unread_figures(source)) if options["images"] and vision is not None and not read else 0
    runs.progress(read, pending_figures + min(len(read_plan(source["chunks"], window_chars=options["section_chars"], images=options["images"])["windows"]), MAX_WINDOWS))
    if options["images"] and vision is not None and not read:
        source = _read_figures_first(conn, eid, source["id"], out_dir, vision, options)
    project = projects.get(conn, source["project_id"])
    language = sources.LANGUAGE_NAME.get(project["language"], project["language"])
    windows = read_plan(source["chunks"], window_chars=options["section_chars"], images=options["images"])["windows"]
    # A reading can run alongside other files. Not known checks must use the
    # project's complete, current corpus, not whichever source finished first.
    project_chunks = []
    for row in db.rows(conn, "SELECT id FROM sources WHERE project_id = ? ORDER BY created_at, id", (project["id"],)):
        project_chunks.extend(sources.get_source(conn, row["id"])["chunks"])
    figure_count = pending_figures
    runs.progress(figure_count + read, figure_count + min(len(windows), MAX_WINDOWS))
    other = other_theme(conn, project["id"])
    rejected = db.parse_json_field(extraction["rejected"]) or []
    kept = db.row(conn, "SELECT COUNT(*) AS n FROM qa_samples WHERE extraction_id = ? AND origin = 'file'", (eid,))["n"]
    if not windows:
        return _finish(conn, eid, "failed", "nothing to read: no text in the file, and no figure gave enough", rejected, read)
    if not read:
        try:
            propose_themes(conn, llm, project, language, windows)
        except LLMError as exc:
            return _finish(conn, eid, "failed", f"model call failed while proposing themes: {exc}", rejected, read)

    # A false premise looks like the true question on purpose; it must not keep a real one out.
    earlier = db.rows(conn, "SELECT question, content_hash FROM qa_samples WHERE project_id = ?"
                            " AND origin NOT IN ('false_premise', 'true_premise')", (project["id"],))
    hashes = {e["content_hash"] for e in earlier}
    shingles = [rules.word_shingles(e["question"]) for e in earlier]

    falses, doubts = options.get("false_per_section", 0), options.get("doubts_per_section", 0)
    three = bool(falses or doubts)
    window_limits = [min(options["pairs_per_section"], density_limit(w, options.get("amount", "normal"))) for w in windows[:MAX_WINDOWS]]
    false_quotas, doubt_quotas = [falses] * len(window_limits), [doubts] * len(window_limits)
    if options.get("mix"):
        mix = options["mix"]
        previous = dict(conn.execute("SELECT origin, COUNT(*) FROM qa_samples WHERE project_id = ? AND origin IN ('file', 'false_premise', 'refusal') GROUP BY origin", (project["id"],)).fetchall())
        known_before = previous.get("file", 0)
        total_known = known_before + sum(window_limits)
        false_target, doubt_target = mix_targets(total_known, int(mix.get("false", 0)), int(mix.get("doubts", 0)))
        false_target = max(0, false_target - previous.get("false_premise", 0))
        doubt_target = max(0, doubt_target - previous.get("refusal", 0))
        def spread(target):
            result, allocated, cumulative_known = [], 0, 0
            for known in window_limits:
                cumulative_known += known
                cumulative_target = round(target * cumulative_known / total_known) if total_known else 0
                result.append(min(4, max(0, cumulative_target - allocated)))
                allocated = cumulative_target
            return result
        false_quotas, doubt_quotas = spread(false_target), spread(doubt_target)
    if three:
        from . import kb, kinds  # imported here: they build on this module
        passages_words = [kb._long_words(c["text"]) for c in project_chunks]
        written_false = db.rows(conn, "SELECT question, false_claim, content_hash FROM qa_samples WHERE project_id = ? AND origin = 'false_premise'", (project["id"],))
        false_hashes = {r["content_hash"] for r in written_false}
        false_shingles = [rules.word_shingles(r[key]) for r in written_false for key in ("question", "false_claim")]

    for window_index, window in enumerate(windows[read:MAX_WINDOWS], start=read):
        runs.check()
        # Read every time: a person may rename or merge themes while a long file runs.
        themes = _topics(conn, project["id"]) + [other]
        by_slug = {t["slug"]: t for t in themes}
        where = f"passages {window[0]['index']}-{window[-1]['index']}"
        turned_down = len(rejected)
        window_false, window_doubts = false_quotas[window_index], doubt_quotas[window_index]
        try:
            window_limit = min(options["pairs_per_section"], density_limit(window, options.get("amount", "normal")))
            if window_limit == 0:
                read += 1
                conn.execute("UPDATE extractions SET passages_read = ? WHERE id = ?", (read, eid))
                conn.commit()
                continue
            if three:
                found = _read_window(llm, pillars_prompt(project, language, themes, window, window_limit, window_false, window_doubts),
                                     pillars_schema(list(by_slug)))
                items = found.get("known")
            else:
                found = {}
                items = _read_window(llm, pair_prompt(project, language, themes, window, window_limit),
                                     pair_schema(list(by_slug))).get("items")
        except OutputCapped:
            # One stuck window must not cost the rest of the file. It stays visible, among what was turned down.
            read += 1
            rejected.append({"index": window[0]["index"], "reason": f"the model kept repeating itself on {where}, so they were skipped"})
            console.outcome("passage_reader", where, 0, [rejected[-1]["reason"]])
            conn.execute("UPDATE extractions SET passages_read = ?, rejected = ? WHERE id = ?",
                         (read, json.dumps(rejected, ensure_ascii=False), eid))
            conn.commit()
            continue
        except LLMError as exc:
            return _finish(conn, eid, "failed", f"model call failed at {where}: {exc}", rejected, read)
        if not isinstance(items, list):
            return _finish(conn, eid, "failed", f"model output unparseable at {where}: missing 'items' list", rejected, read)
        read += 1
        runs.progress(figure_count + read, figure_count + min(len(windows), MAX_WINDOWS))
        section = " ".join(c["text"] for c in window)
        for item in items[:window_limit]:
            if not isinstance(item, dict):
                rejected.append({"index": window[0]["index"], "reason": "not an object"})
                continue
            question = rules.normalize(str(item.get("question", "")))
            answer = rules.normalize(str(item.get("answer", "")))
            chunk, quote = locate_quote(str(item.get("quote", "")), window)
            reasons = check_pair(question, answer, section, project)
            if quote:
                quote_reasons = check_pair(question, answer, quote)
                if _numbers(answer) - _numbers(quote) - _numbers(question):
                    reasons.append("answer assigns a number not supported by its complete citation")
            if chunk is None:
                reasons.append("quote not found in the passages")
            digest = rules.content_hash(question, answer)
            mine = rules.word_shingles(question)
            if digest in hashes or any(rules.jaccard(mine, s) >= NEAR_DUPLICATE for s in shingles):
                reasons.append("too close to a question already asked")
            if reasons:
                rejected.append({"index": window[0]["index"], "question": question[:120], "reason": "; ".join(dict.fromkeys(reasons))})
                continue
            hashes.add(digest)
            shingles.append(mine)
            theme = by_slug.get(str(item.get("theme", "")).strip(), other)
            conn.execute(
                "INSERT INTO qa_samples (id, project_id, theme_id, origin, source_id, chunk_id, quote, extraction_id, model,"
                " question, answer, content_hash, status, created_at) VALUES (?,?,?, 'file', ?,?,?,?,?,?,?,?, 'proposed', ?)",
                (db.new_id("qa"), project["id"], theme["id"], source["id"], chunk["id"], quote, eid, llm.model,
                 question, answer, digest, db.now()))
            kept += 1
        if three:
            section_id = window[0]["index"]
            for item in _listed(found, "false_premise")[:window_false]:
                question, answer = rules.normalize(str(item.get("question", ""))), rules.normalize(str(item.get("answer", "")))
                claim = rules.normalize(str(item.get("false_claim", "")))
                chunk, quote = locate_quote(str(item.get("quote", "")), window)
                reasons = kinds.check_false_premise(question, answer, claim, {"quote": quote or "", "question": ""}) + kinds.states_the_claim(question, claim)
                if chunk is None:
                    reasons.append("quote not found in the passages")
                digest = rules.content_hash(question, answer)
                mine = [rules.word_shingles(question), rules.word_shingles(claim)]
                if digest in false_hashes or any(rules.jaccard(new, old) >= NEAR_DUPLICATE for new in mine for old in false_shingles):
                    reasons.append("too close to a false premise already written")
                if reasons:
                    rejected.append({"index": section_id, "question": question[:120], "reason": "; ".join(dict.fromkeys(reasons))})
                    continue
                false_hashes.add(digest)
                false_shingles.extend(mine)
                theme = by_slug.get(str(item.get("theme", "")).strip(), other)
                conn.execute(
                    "INSERT INTO qa_samples (id, project_id, theme_id, origin, source_id, chunk_id, quote, extraction_id, model,"
                    " question, answer, false_claim, content_hash, status, created_at) VALUES (?,?,?, 'false_premise', ?,?,?,?,?,?,?,?,?, 'proposed', ?)",
                    (db.new_id("qa"), project["id"], theme["id"], source["id"], chunk["id"], quote, eid, llm.model,
                     question, answer, claim, digest, db.now()))
            for item in _listed(found, "not_known")[:window_doubts]:
                question, answer = rules.normalize(str(item.get("question", ""))), rules.normalize(str(item.get("answer", "")))
                reasons = kb.check_written_refusal(question, answer, passages_words)
                # Match Challenge's doubt retrieval: rank all project passages
                # by the question's rarer words, then inspect the nearest set.
                nearest = kb.nearest_passages(question, project_chunks)
                nearest_words = [kb._long_words(text) for text in nearest]
                retrieval_terms = _doubt_terms(question)
                lexical_match = bool(retrieval_terms) and any(
                    len(retrieval_terms & _doubt_terms(text)) >= kb.ANSWERED_SHARE * len(retrieval_terms)
                    for text in nearest
                )
                full_file_question = question.casefold().startswith(("how many", "which", "quantos", "quantas", "quais"))
                if full_file_question and not lexical_match:
                    lexical_match = any(
                        len(retrieval_terms & _doubt_terms(chunk["text"])) >= kb.ANSWERED_SHARE * len(retrieval_terms)
                        for chunk in project_chunks
                    )
                if nearest and (kb.looks_answered(question, nearest_words) or lexical_match):
                    reasons.append("a nearby passage in this project answers the question")
                else:
                    # Use Challenge's answer checker on the same project-wide
                    # retrieval set. None means unanswered; any other result
                    # means the checker found an answer, even without a quote.
                    try:
                        answered = kb.answered_in(llm, question, project_chunks) is not None
                    except LLMError:
                        answered = True  # fail closed: do not teach a refusal we could not check
                    if answered:
                        reasons.append("a nearby passage in this project answers the question")
                digest = rules.content_hash(question, answer)
                mine = rules.word_shingles(question)
                if digest in hashes or any(rules.jaccard(mine, s) >= NEAR_DUPLICATE for s in shingles):
                    reasons.append("near-duplicate of a question already in this dataset")
                if reasons:
                    rejected.append({"index": section_id, "question": question[:120], "reason": "; ".join(reasons)})
                    continue
                hashes.add(digest)
                shingles.append(mine)
                # A doubt belongs to what it is about: themes and pillars cross, so a theme shows what it knows and where it stops.
                theme = by_slug.get(str(item.get("theme", "")).strip(), other)
                conn.execute(
                    "INSERT INTO qa_samples (id, project_id, theme_id, origin, extraction_id, model, question, answer, content_hash, status, created_at)"
                    " VALUES (?,?,?, 'refusal', ?,?,?,?,?, 'proposed', ?)",
                    (db.new_id("qa"), project["id"], theme["id"], eid, llm.model, question, answer, digest, db.now()))
        wrote = len(items[:window_limit])
        if three:
            wrote += len(_listed(found, "false_premise")[:window_false]) + len(_listed(found, "not_known")[:window_doubts])
        reasons = [r["reason"] for r in rejected[turned_down:]]
        console.outcome("passage_reader", where, wrote - len(reasons), reasons)
        conn.execute("UPDATE extractions SET passages_read = ?, rejected = ? WHERE id = ?",
                     (read, json.dumps(rejected, ensure_ascii=False), eid))
        conn.commit()
    if three:
        written = dict(conn.execute("SELECT origin, COUNT(*) FROM qa_samples WHERE extraction_id = ? AND origin IN ('false_premise', 'refusal') GROUP BY origin", (eid,)).fetchall())
        conn.execute("UPDATE extractions SET reading = json_set(reading, '$.groups', json(?)) WHERE id = ?",
                     (json.dumps({"false_premise": written.get("false_premise", 0), "not_known": written.get("refusal", 0)}), eid))
        conn.commit()
    # A second run that only finds duplicates did not fail; the file already has its pairs.
    if kept or conn.execute("SELECT 1 FROM qa_samples WHERE source_id = ? LIMIT 1", (source["id"],)).fetchone():
        from . import kinds  # imported here: kinds builds on this module
        # The three-pillar prompt already handled the requested kinds. Running the
        # legacy post-read stage as well duplicated model work on the same extraction.
        if not three:
            kinds.after_reading(conn, llm, eid, kept)
        return _finish(conn, eid, "succeeded", None, rejected, read)
    return _finish(conn, eid, "failed", f"no usable pair in the {read} section(s) read", rejected, read)


# --- Curation ---

_SELECT = (
    "SELECT q.*, t.title AS theme_title, t.slug AS theme_slug, s.name AS source_name, c.locator_json"
    " FROM qa_samples q JOIN qa_themes t ON t.id = q.theme_id"
    " LEFT JOIN sources s ON s.id = q.source_id LEFT JOIN source_chunks c ON c.id = q.chunk_id")


def _view(row: dict) -> dict:
    row["page"] = json.loads(row.pop("locator_json", None) or "{}").get("page")
    row["pillar"] = PILLAR.get(row["origin"], "known")
    return row


LINKED_ORIGINS = ("connection", "false_premise", "true_premise", "complex")

# Every kind of pair teaches one of three things about the subject. Behavior is about the model itself, so it stands apart.
PILLAR = {"file": "known", "connection": "known", "true_premise": "known", "complex": "known",
          "false_premise": "false_premise",
          "refusal": "not_known", "neighbour": "not_known",
          "behavior": "behavior"}
PILLARS = ("known", "false_premise", "not_known", "behavior")


def _with_basis(conn, samples: list[dict]) -> list[dict]:
    """A connected pair carries the pairs it rests on: their words, and the quotes that prove them."""
    wanted = [s["id"] for s in samples if s["origin"] in LINKED_ORIGINS]
    parents: dict[str, list[dict]] = {}
    if wanted:
        marks = ",".join("?" * len(wanted))
        for row in db.rows(conn, f"SELECT l.sample_id AS child_id, q.*, t.title AS theme_title, t.slug AS theme_slug,"
                                 f" s.name AS source_name, c.locator_json FROM qa_sample_links l"
                                 f" JOIN qa_samples q ON q.id = l.based_on_id JOIN qa_themes t ON t.id = q.theme_id"
                                 f" LEFT JOIN sources s ON s.id = q.source_id LEFT JOIN source_chunks c ON c.id = q.chunk_id"
                                 f" WHERE l.sample_id IN ({marks}) ORDER BY q.created_at, q.id", tuple(wanted)):
            parents.setdefault(row.pop("child_id"), []).append(_view(row))
    for sample in samples:
        sample["based_on"] = parents.get(sample["id"], [])
    from . import curation
    for sample in samples:
        sample['curation'] = curation.state(conn, sample)
    return samples


def list_samples(conn, project_id: str, *, theme_id: str = "", status: str = "", source_id: str = "", origin: str = "") -> list[dict]:
    where, params = ["q.project_id = ?"], [project_id]
    for column, value in (("q.theme_id", theme_id), ("q.status", status), ("q.source_id", source_id), ("q.origin", origin)):
        if value:
            where.append(f"{column} = ?")
            params.append(value)
    return _with_basis(conn, [_view(r) for r in db.rows(
        conn, f"{_SELECT} WHERE {' AND '.join(where)} ORDER BY q.created_at, q.id", tuple(params))])


def pillar_counts(conn, project_id: str) -> dict:
    """How many pairs each pillar holds, by status, and how they stand in what is approved."""
    counts = {pillar: {"proposed": 0, "approved": 0, "rejected": 0} for pillar in PILLARS}
    for row in db.rows(conn, "SELECT origin, status, COUNT(*) AS n FROM qa_samples WHERE project_id = ? GROUP BY origin, status", (project_id,)):
        counts[PILLAR.get(row["origin"], "known")][row["status"]] += row["n"]
    return counts


def get_sample(conn, sample_id: str) -> dict:
    found = db.row(conn, f"{_SELECT} WHERE q.id = ?", (sample_id,))
    if not found:
        raise workshop.NotFound(f"sample {sample_id} not found")
    return _with_basis(conn, [_view(found)])[0]


DECISIONS = {"approve": "approved", "reject": "rejected", "reset": "proposed"}


def decide(conn, sample_id: str, decision: str) -> dict:
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of: {', '.join(DECISIONS)}")
    sample = get_sample(conn, sample_id)
    from . import curation
    curation.event(conn, sample, decision)
    conn.execute("UPDATE qa_samples SET status = ?, decided_at = ?, review_note = '' WHERE id = ?", (DECISIONS[decision], db.now(), sample_id))
    conn.commit()
    return get_sample(conn, sample_id)


def _kept_apart(conn, project_id: str) -> set[tuple[str, str]]:
    return {(r["first_id"], r["second_id"]) for r in db.rows(
        conn, "SELECT k.first_id, k.second_id FROM qa_kept_apart k JOIN qa_samples q ON q.id = k.first_id WHERE q.project_id = ?", (project_id,))}


def similar_groups(conn, project_id: str) -> list[dict]:
    """Pairs that may say the same thing, grouped for a person to decide. Only pairs of one kind are compared:
    a false premise and its true version are alike on purpose. Nothing here changes a pair."""
    samples = [s for s in list_samples(conn, project_id) if s["status"] != "rejected"]
    apart = _kept_apart(conn, project_id)
    words = {s["id"]: (rules.content_words(s["question"]), rules.content_words(s["answer"])) for s in samples}
    parent = {s["id"]: s["id"] for s in samples}

    def root(sample_id: str) -> str:
        while parent[sample_id] != sample_id:
            parent[sample_id] = parent[parent[sample_id]]
            sample_id = parent[sample_id]
        return sample_id

    for index, first in enumerate(samples):
        for second in samples[index + 1:]:
            if first["origin"] != second["origin"] or tuple(sorted((first["id"], second["id"]))) in apart:
                continue
            asked = rules.jaccard(words[first["id"]][0], words[second["id"]][0])
            if asked >= SIMILAR_QUESTION or (asked >= SIMILAR_LOOSE[0] and rules.jaccard(words[first["id"]][1], words[second["id"]][1]) >= SIMILAR_LOOSE[1]):
                parent[root(first["id"])] = root(second["id"])

    # The challenge read these two and found one fact, often in words that share little.
    shown = {s["id"]: s for s in samples}
    for row in db.rows(conn, "SELECT c.first_id, c.second_id, c.first_hash, c.second_hash FROM qa_comparisons c JOIN qa_samples q ON q.id = c.first_id"
                             " WHERE q.project_id = ? AND c.test = 'known' AND c.verdict = 'same'", (project_id,)):
        first, second = shown.get(row["first_id"]), shown.get(row["second_id"])
        if (first and second and first["origin"] == second["origin"] and tuple(sorted((first["id"], second["id"]))) not in apart
                and first["content_hash"] == row["first_hash"] and second["content_hash"] == row["second_hash"]):
            parent[root(first["id"])] = root(second["id"])

    groups: dict[str, list[dict]] = {}
    for sample in samples:
        groups.setdefault(root(sample["id"]), []).append(sample)
    return [{"samples": members} for members in groups.values() if len(members) > 1]


def questions_similar(first: str, second: str, first_answer: str = "", second_answer: str = "") -> bool:
    """Use Curate's question and answer thresholds for near-duplicate questions."""
    asked = rules.jaccard(rules.content_words(first), rules.content_words(second))
    answered = rules.jaccard(rules.content_words(first_answer), rules.content_words(second_answer))
    return asked >= SIMILAR_QUESTION or (asked >= SIMILAR_LOOSE[0] and answered >= SIMILAR_LOOSE[1])


def _members(conn, project_id: str, sample_ids: list[str]) -> None:
    marks = ",".join("?" * len(sample_ids))
    found = db.rows(conn, f"SELECT id FROM qa_samples WHERE project_id = ? AND id IN ({marks})", (project_id, *sample_ids))
    if len(found) != len(set(sample_ids)):
        raise workshop.NotFound("a pair of this group is not in this project")


def keep_one(conn, project_id: str, keep_id: str, sample_ids: list[str]) -> dict:
    """Reject the others of a group. The kept pair keeps its status: keeping is not approving."""
    if keep_id not in sample_ids or len(set(sample_ids)) < 2:
        raise ValueError("keep one of at least two pairs")
    _members(conn, project_id, sample_ids)
    others = [s for s in set(sample_ids) if s != keep_id]
    conn.executemany("UPDATE qa_samples SET status = 'rejected', decided_at = ?, review_note = '' WHERE id = ?",
                     [(db.now(), s) for s in others])
    conn.commit()
    return {"rejected": len(others)}


def keep_apart(conn, project_id: str, sample_ids: list[str], *, undo: bool = False) -> dict:
    """These pairs ask different things: stop showing them together. Decisions on the pairs stay as they are."""
    unique = sorted(set(sample_ids))
    if len(unique) < 2:
        raise ValueError("keep apart needs at least two pairs")
    _members(conn, project_id, unique)
    combos = [(a, b) for index, a in enumerate(unique) for b in unique[index + 1:]]
    conn.executemany("DELETE FROM qa_kept_apart WHERE first_id = ? AND second_id = ?" if undo
                     else "INSERT OR IGNORE INTO qa_kept_apart (first_id, second_id) VALUES (?, ?)", combos)
    conn.commit()
    return {"pairs": len(unique)}


def decide_many(conn, project_id: str, sample_ids: list[str], decision: str) -> dict:
    """One decision over the pairs a person sees. Approving or rejecting touches only pairs still to review with nothing
    flagged on them: those need a look. Going back to review undoes it. An id from another project changes nothing."""
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of: {', '.join(DECISIONS)}")
    only_open = "" if decision == "reset" else " AND status = 'proposed' AND review_note = ''"
    changed = [sample_id for sample_id in sample_ids if conn.execute(
        f"UPDATE qa_samples SET status = ?, decided_at = ?, review_note = '' WHERE id = ? AND project_id = ?{only_open}",
        (DECISIONS[decision], db.now(), sample_id, project_id)).rowcount]
    from . import curation
    for sample_id in changed:
        curation.event(conn, get_sample(conn, sample_id), decision, {'bulk': True})
    conn.commit()
    return {"changed": changed}


def behavior_reasons(conn, sample: dict, question: str, answer: str) -> list[str]:
    pattern = workshop.get_pattern(conn, sample["pattern_id"])
    return rules.check_sample(question, answer, " ".join(
        [pattern["intent"], pattern["tone"], pattern["guidelines"], pattern["description"]]),
        max_sentences=workshop.max_sentences(pattern))


def edit(conn, sample_id: str, *, question: str | None = None, answer: str | None = None, theme_id: str | None = None,
         false_claim: str | None = None) -> dict:
    """A rewrite is checked and returns to pending until approved. Moving to another theme keeps the decision."""
    sample = get_sample(conn, sample_id)
    new_q = rules.normalize(question) if question is not None else sample["question"]
    new_a = rules.normalize(answer) if answer is not None else sample["answer"]
    new_claim = rules.normalize(false_claim) if false_claim is not None else sample["false_claim"]
    if false_claim is not None and sample["origin"] != "false_premise":
        raise ValueError("only a false premise has a false claim")
    if sample["origin"] == "false_premise" and not new_claim:
        raise ValueError("a false premise needs its false claim")
    rewritten = (new_q, new_a, new_claim) != (sample["question"], sample["answer"], sample["false_claim"])
    if theme_id is not None and get_theme(conn, theme_id)["project_id"] != sample["project_id"]:
        raise workshop.NotFound(f"theme {theme_id} not found")
    if rewritten:
        reasons = behavior_reasons(conn, sample, new_q, new_a) if sample["origin"] == "behavior" else text_limits(new_q, new_a)
        if reasons:
            raise ValueError("; ".join(reasons))
        conn.execute(
            "UPDATE qa_samples SET question = ?, answer = ?, false_claim = ?, content_hash = ?, revision = revision + 1,"
            " status = 'proposed', decided_at = NULL, review_note = '' WHERE id = ?",
            (new_q, new_a, new_claim, rules.content_hash(new_q, new_a), sample_id))
        # A pair resting on these words has to be looked at again.
        conn.execute("UPDATE qa_samples SET status = 'proposed', decided_at = NULL WHERE id IN"
                     " (SELECT sample_id FROM qa_sample_links WHERE based_on_id = ?)", (sample_id,))
    if theme_id is not None:
        conn.execute("UPDATE qa_samples SET theme_id = ? WHERE id = ?", (theme_id, sample_id))
    from . import curation
    curation.event(conn, get_sample(conn, sample_id), 'edit' if rewritten else 'move_theme')
    conn.commit()
    return get_sample(conn, sample_id)


# --- OKF wiki: generated from approved pairs, never reviewed on its own ---

def _proof(sample: dict) -> str:
    if not sample.get("quote"):
        lines = [f"> {p['quote']}\n>\n> {p.get('source_name') or 'source'}" + (f", p. {p['page']}" if p.get("page") else "")
                 for p in sample.get("based_on") or [] if p.get("quote")]
        return "".join(f"\n\n{line}" for line in lines)
    where = sample.get("source_name") or "source"
    if sample.get("page"):
        where += f", p. {sample['page']}"
    return f"\n\n> {sample['quote']}\n>\n> {where}"


def _theme_body(pairs: list[dict]) -> str:
    """Right and wrong stay apart, so nobody reads a false claim as a fact of the theme."""
    mistakes = [p for p in pairs if p["origin"] == "false_premise"]
    open_questions = [p for p in pairs if p["origin"] == "refusal"]
    parts = [f"## {p['question']}\n\n{p['answer']}{_proof(p)}" for p in pairs if p["origin"] not in ("false_premise", "refusal")]
    if mistakes:
        parts.append("## Possible mistakes\n\n" + "\n\n".join(
            f"### Wrong: {p['false_claim']}\nCorrect: {p['answer']}{_proof(p)}" for p in mistakes))
    if open_questions:
        parts.append("## Not answered here\n\nThe files read do not answer these. Another source might.\n\n"
                     + "\n".join(f"- {p['question']}" for p in open_questions))
    return "\n\n".join(parts)


def wiki_files(conn, project_id: str, sample_ids: set[str]) -> dict[str, str]:
    """{bundle path: text}. One page per theme, holding exactly the pairs being exported."""
    project = projects.get(conn, project_id)
    entries, files = [], {}
    for theme in list_themes(conn, project_id):
        # A true version repeats what its pair already says; a neighbouring answer and a behavior are not knowledge of these files.
        pairs = [p for p in list_samples(conn, project_id, theme_id=theme["id"], status="approved")
                 if p["id"] in sample_ids and p["origin"] not in ("true_premise", "neighbour", "behavior")]
        if not pairs:
            continue
        body = _theme_body(pairs)
        names = sorted({p["source_name"] for p in pairs if p.get("source_name")})
        meta = {"type": "Theme", "title": theme["title"], "description": theme["description"], "status": "stable",
                "sources": names, "generated": True}
        path = f"themes/{theme['slug']}.md"
        files[path] = okf.concept(meta, body)
        entries.append((theme["title"], path, theme["description"]))
    files["index.md"] = okf.index([(project["display_name"], entries)], root=True)
    files["log.md"] = okf.log([(db.now()[:10], "Export", f"Generated from {len(sample_ids)} approved pair(s) in {len(entries)} theme(s).")])
    problems = okf.validate(files)
    if problems:
        raise ValueError("wiki export is not valid OKF: " + "; ".join(problems))
    return files
