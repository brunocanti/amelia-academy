"""Behavior cards: a card written by a person -> proposed conversations in the curation list.

Invariants enforced here:
- only an approved card generates a batch;
- generated conversations are born `proposed` and are curated with every other pair (qa.py);
- a batch records the runtime and model that wrote it;
- a model failure fails the batch visibly, never falls back to another model.
"""

import json

from . import agents, console, db, projects, rules, runs
from .cli_tools import provider_of
from .llm import LLMError

VARIATION_INSTRUCTIONS = agents.table("behavior_writer", "variations")


NEAR_DUPLICATE = 0.6  # word 3-gram Jaccard between user messages of the same card


class PatternNotApproved(Exception):
    pass


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


def create_pattern(conn, *, project_id: str, title: str, intent: str, tone: str,
                   guidelines: str, description: str, user_type: str = "others", style: str = "companion",
                   about_identity: bool = False) -> dict:
    if style not in STYLES:
        raise ValueError(f"style must be one of: {', '.join(STYLES)}")
    project = projects.get(conn, project_id)
    pid = db.new_id("pat")
    conn.execute(
        "INSERT INTO patterns (id, project, project_id, title, intent, tone, guidelines, description, user_type,"
        " status, created_at, style, about_identity) VALUES (?,?,?,?,?,?,?,?,?, 'draft', ?, ?, ?)",
        (pid, project["slug"], project_id, title, intent, tone, guidelines, description, user_type, db.now(), style,
         int(about_identity)),
    )
    conn.commit()
    return get_pattern(conn, pid)


def list_patterns(conn, project_id: str) -> list[dict]:
    return db.rows(conn, "SELECT * FROM patterns WHERE project_id = ? ORDER BY created_at DESC", (project_id,))


def get_pattern(conn, pattern_id: str) -> dict:
    p = db.row(conn, "SELECT * FROM patterns WHERE id = ?", (pattern_id,))
    if not p:
        raise NotFound(f"pattern {pattern_id} not found")
    return p


def set_pattern_status(conn, pattern_id: str, status: str) -> dict:
    if status not in ("draft", "in_review", "approved"):
        raise ValueError(f"invalid pattern status: {status}")
    pattern = get_pattern(conn, pattern_id)
    if pattern["status"] == status:
        return pattern
    if pattern["status"] == "approved" and conn.execute(
            "SELECT 1 FROM batches WHERE pattern_id = ? LIMIT 1", (pattern_id,)).fetchone():
        # Samples were generated against the approved text; reopening it would leave them without a basis.
        raise Conflict(f"pattern {pattern_id} already generated samples; it stays approved")
    conn.execute("UPDATE patterns SET status = ?, approved_at = ? WHERE id = ?",
                 (status, db.now() if status == "approved" else None, pattern_id))
    conn.commit()
    return get_pattern(conn, pattern_id)


STYLES = {"companion": 2, "task": 4}  # kind of conversation -> sentences a reply may hold


def max_sentences(pattern: dict) -> int:
    return STYLES.get(pattern.get("style") or "companion", 2)


def _identity_block(identity: str) -> str:
    if not identity:
        return ""
    return agents.prompt("behavior_writer", "identity", identity=identity) + "\n\n"


def _task_prompt(pattern: dict, variation_type: str, count: int, language: str | None, identity: str = "") -> str:
    return agents.prompt("behavior_writer", "task", count=count, identity_block=_identity_block(identity), intent=pattern["intent"], tone=pattern["tone"],
                         guidelines=pattern["guidelines"], description=pattern["description"], variation=variation_type,
                         variation_instruction=VARIATION_INSTRUCTIONS[variation_type], max_sentences=STYLES["task"],
                         write_in=agents.prompt("behavior_writer", "in_language", language=language) if language else agents.prompt("behavior_writer", "same_language_card"))


def build_prompt(pattern: dict, variation_type: str, count: int, language: str | None = None, identity: str = "") -> str:
    if pattern.get("style") == "task":
        return _task_prompt(pattern, variation_type, count, language, identity)
    # The charter example line is deliberately not included: it is an evaluation
    # reference, not an answer to copy (spec 004).
    return agents.prompt("behavior_writer", "companion", count=count, identity_block=_identity_block(identity), intent=pattern["intent"], tone=pattern["tone"],
                         guidelines=pattern["guidelines"], description=pattern["description"], variation=variation_type,
                         variation_instruction=VARIATION_INSTRUCTIONS[variation_type],
                         write_in=agents.prompt("behavior_writer", "in_language", language=language) if language else agents.prompt("behavior_writer", "same_language_pattern"))


SAMPLE_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"user_message": {"type": "string"}, "response_text": {"type": "string"}},
                "required": ["user_message", "response_text"],
            },
        }
    },
    "required": ["items"],
}


def behavior_theme(conn, pattern: dict) -> dict:
    """Conversations of a card are curated under the card's own theme, which does not count against the limit."""
    slug = "behavior-" + pattern["id"].replace("_", "-")
    found = db.row(conn, "SELECT * FROM qa_themes WHERE project_id = ? AND slug = ?", (pattern["project_id"], slug))
    if found:
        return found
    tid = db.new_id("thm")
    conn.execute(
        "INSERT INTO qa_themes (id, project_id, slug, title, description, kind, pattern_id, created_at)"
        " VALUES (?,?,?,?,?, 'behavior', ?, ?)",
        (tid, pattern["project_id"], slug, pattern["title"], pattern["intent"], pattern["id"], db.now()))
    return db.row(conn, "SELECT * FROM qa_themes WHERE id = ?", (tid,))


def generate_batch(conn, llm, pattern_id: str, *, count: int, variation_type: str = "positive") -> dict:
    if variation_type not in VARIATION_INSTRUCTIONS:
        raise ValueError(f"unknown variation_type: {variation_type}")
    pattern = get_pattern(conn, pattern_id)
    if pattern["status"] != "approved":
        raise PatternNotApproved(f"pattern {pattern_id} is {pattern['status']}; only approved patterns generate batches")
    project = projects.get(conn, pattern["project_id"])
    if pattern["about_identity"] and not project["identity"].strip():
        raise Conflict("this card is about who the model is, and the project does not say it yet")

    bid = db.new_id("bat")
    conn.execute(
        "INSERT INTO batches (id, pattern_id, runtime, model, variation_type, requested, status, created_at)"
        " VALUES (?,?,?,?,?,?, 'generating', ?)",
        (bid, pattern_id, provider_of(llm.model), llm.model, variation_type, count, db.now()),
    )
    conn.commit()

    prompt = build_prompt(pattern, variation_type, count, projects.LANGUAGE_NAME.get(project["language"], project["language"]),
                          project["identity"])
    pattern_text = " ".join([pattern["intent"], pattern["tone"], pattern["guidelines"], pattern["description"]])

    try:
        with console.acting("behavior_writer"):
            items = llm.complete_json(prompt, SAMPLE_SCHEMA).get("items")
    except runs.Stopped:
        _fail_batch(conn, bid, "stopped by you")
        raise
    except LLMError as exc:
        return _fail_batch(conn, bid, f"model call failed: {exc}")
    if not isinstance(items, list):
        return _fail_batch(conn, bid, "model output unparseable: missing 'items' list")

    accepted, rejected = [], []
    earlier = db.rows(conn, "SELECT question, content_hash FROM qa_samples WHERE pattern_id = ?", (pattern_id,))
    seen = {e["content_hash"] for e in earlier}
    seen_users = [rules.word_shingles(e["question"]) for e in earlier]
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            rejected.append({"index": index, "reason": "not an object"})
            continue
        user = rules.normalize(str(item.get("user_message", "")))
        resp = rules.normalize(str(item.get("response_text", "")))
        reasons = rules.check_sample(user, resp, pattern_text, max_sentences=max_sentences(pattern))
        digest = rules.content_hash(user, resp)
        shingles = rules.word_shingles(user)
        if digest in seen:
            reasons.append("duplicate of an existing sample")
        elif any(rules.jaccard(shingles, s) >= NEAR_DUPLICATE for s in seen_users):
            reasons.append("near-duplicate of an existing situation")
        if reasons:
            rejected.append({"index": index, "reason": "; ".join(reasons)})
            continue
        seen.add(digest)
        seen_users.append(shingles)
        accepted.append((user, resp, digest))

    if not accepted:
        return _fail_batch(conn, bid, f"no valid line out of {len(items)} returned", rejected)

    theme = behavior_theme(conn, pattern)
    for user, resp, digest in accepted:
        conn.execute(
            "INSERT INTO qa_samples (id, project_id, theme_id, origin, pattern_id, batch_id, model, variation_type, question,"
            " answer, content_hash, status, created_at) VALUES (?,?,?, 'behavior', ?,?,?,?,?,?,?, 'proposed', ?)",
            (db.new_id("qa"), pattern["project_id"], theme["id"], pattern_id, bid, llm.model, variation_type,
             user, resp, digest, db.now()),
        )
    conn.execute(
        "UPDATE batches SET status = 'reviewable', rejected_lines = ? WHERE id = ?",
        (json.dumps(rejected, ensure_ascii=False), bid),
    )
    conn.commit()
    return batch_summary(conn, bid)


def _fail_batch(conn, batch_id: str, error: str, rejected: list | None = None) -> dict:
    conn.execute(
        "UPDATE batches SET status = 'failed', error = ?, rejected_lines = ? WHERE id = ?",
        (error, json.dumps(rejected or [], ensure_ascii=False), batch_id),
    )
    conn.commit()
    return batch_summary(conn, batch_id)


def batch_summary(conn, batch_id: str) -> dict:
    b = db.row(conn, "SELECT * FROM batches WHERE id = ?", (batch_id,))
    if not b:
        raise NotFound(f"batch {batch_id} not found")
    b["rejected_lines"] = db.parse_json_field(b["rejected_lines"])
    b["proposed"] = db.rows(conn, "SELECT * FROM qa_samples WHERE batch_id = ? ORDER BY created_at", (batch_id,))
    b["denominator"] = {"requested": b["requested"], "proposed": len(b["proposed"]), "rejected": len(b["rejected_lines"])}
    return b
