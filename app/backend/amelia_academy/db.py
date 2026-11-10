"""SQLite store: projects, sources, themes, question/answer samples, behavior cards and datasets.

Tables of the earlier flows (samples, themes, knowledge_items, wiki_*) are no longer created.
The migration still adopts the behavior rows of an old `samples` table. Dropping those tables is a manual step.
"""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS train_runs (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, dataset_id TEXT NOT NULL,
 model TEXT NOT NULL, config TEXT NOT NULL, status TEXT NOT NULL,
 best_val_loss REAL, best_iteration INTEGER, error TEXT NOT NULL DEFAULT '',
 version INTEGER, name TEXT NOT NULL DEFAULT '', in_use INTEGER NOT NULL DEFAULT 0, deleting_at TEXT,
 created_at TEXT NOT NULL, finished_at TEXT
);
CREATE INDEX IF NOT EXISTS train_runs_project ON train_runs(project_id,created_at);
CREATE TABLE IF NOT EXISTS train_events (
 run_id TEXT NOT NULL, seq INTEGER NOT NULL, type TEXT NOT NULL, payload TEXT NOT NULL,
 created_at TEXT NOT NULL, PRIMARY KEY(run_id,seq)
);
CREATE TABLE IF NOT EXISTS train_recall (
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL, source_question TEXT NOT NULL,
 question TEXT NOT NULL, approved INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS train_comparisons (
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL, question TEXT NOT NULL, set_name TEXT NOT NULL,
 left_answer TEXT NOT NULL, right_answer TEXT NOT NULL, base_on_left INTEGER NOT NULL,
 choice TEXT, created_at TEXT NOT NULL, expected TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS training_variants (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), pair_id TEXT NOT NULL REFERENCES qa_samples(id),
 pair_version TEXT NOT NULL, kind TEXT NOT NULL, question TEXT NOT NULL, answer TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('kept','dropped_by_rule','dropped_by_person')),
 reason TEXT NOT NULL DEFAULT '', question_model TEXT NOT NULL DEFAULT '', answer_model TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS training_variants_pair ON training_variants(project_id,pair_id,pair_version);

CREATE TABLE IF NOT EXISTS curation_events (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, sample_id TEXT NOT NULL,
 input_hash TEXT NOT NULL, action TEXT NOT NULL, payload TEXT NOT NULL,
 actor TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS curation_events_sample ON curation_events(sample_id,input_hash);
CREATE TABLE IF NOT EXISTS qa_rewords (
 batch_id TEXT NOT NULL, sample_id TEXT NOT NULL, answer TEXT NOT NULL, status TEXT NOT NULL,
 decided_at TEXT, new_hash TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(batch_id, sample_id)
);
CREATE TABLE IF NOT EXISTS curation_rationales (
 id TEXT PRIMARY KEY, sample_id TEXT NOT NULL, input_hash TEXT NOT NULL,
 text TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS curation_rationales_sample ON curation_rationales(sample_id);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    objective TEXT NOT NULL,
    language TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    max_themes INTEGER NOT NULL DEFAULT 8,
    identity TEXT NOT NULL DEFAULT '',
    train_model TEXT NOT NULL DEFAULT 'mlx-community/Qwen3-4B-4bit',
    prepare_count TEXT NOT NULL DEFAULT 'normal',
    prepare_question_model TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS patterns (
    id TEXT PRIMARY KEY,
    project TEXT NOT NULL,
    title TEXT NOT NULL,
    intent TEXT NOT NULL,
    tone TEXT NOT NULL,
    guidelines TEXT NOT NULL,
    description TEXT NOT NULL,
    user_type TEXT NOT NULL DEFAULT 'others',
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS batches (
    id TEXT PRIMARY KEY,
    pattern_id TEXT NOT NULL REFERENCES patterns(id),
    runtime TEXT NOT NULL,
    model TEXT NOT NULL,
    variation_type TEXT NOT NULL,
    requested INTEGER NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    rejected_lines TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    project TEXT NOT NULL,
    name TEXT NOT NULL,
    mime TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL,
    purpose TEXT NOT NULL,
    license_basis TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    storage_path TEXT NOT NULL DEFAULT '',
    UNIQUE (project, sha256)
);
CREATE TABLE IF NOT EXISTS source_ingestions (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id),
    extractor TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    warnings TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_assets (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id),
    ingestion_id TEXT NOT NULL REFERENCES source_ingestions(id),
    idx INTEGER NOT NULL,
    kind TEXT NOT NULL,
    mime TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL,
    storage_path TEXT NOT NULL,
    locator_json TEXT NOT NULL DEFAULT '{}',
    ocr_status TEXT NOT NULL DEFAULT 'not_attempted',
    ocr_text TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_chunks (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id),
    idx INTEGER NOT NULL,
    start INTEGER NOT NULL,
    end_pos INTEGER NOT NULL,
    text TEXT NOT NULL,
    hash TEXT NOT NULL,
    ingestion_id TEXT REFERENCES source_ingestions(id),
    kind TEXT NOT NULL DEFAULT 'text',
    locator_json TEXT NOT NULL DEFAULT '{}',
    offset_basis TEXT NOT NULL DEFAULT 'source_text',
    asset_id TEXT REFERENCES source_assets(id)
);
CREATE TABLE IF NOT EXISTS extractions (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id),
    runtime TEXT NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    rejected TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS datasets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    sample_count INTEGER NOT NULL,
    manifest_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS qa_themes (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    slug TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'topic',
    pattern_id TEXT REFERENCES patterns(id),
    created_at TEXT NOT NULL,
    UNIQUE (project_id, slug)
);
CREATE TABLE IF NOT EXISTS qa_samples (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    theme_id TEXT NOT NULL REFERENCES qa_themes(id),
    origin TEXT NOT NULL,
    source_id TEXT REFERENCES sources(id),
    chunk_id TEXT,
    quote TEXT NOT NULL DEFAULT '',
    extraction_id TEXT REFERENCES extractions(id),
    pattern_id TEXT REFERENCES patterns(id),
    batch_id TEXT REFERENCES batches(id),
    model TEXT NOT NULL DEFAULT '',
    variation_type TEXT NOT NULL DEFAULT '',
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    false_claim TEXT NOT NULL DEFAULT '',
    review_note TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'proposed',
    decided_at TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS qa_sample_links (
    sample_id TEXT NOT NULL REFERENCES qa_samples(id),
    based_on_id TEXT NOT NULL REFERENCES qa_samples(id),
    PRIMARY KEY (sample_id, based_on_id)
);
CREATE INDEX IF NOT EXISTS qa_sample_links_based_on ON qa_sample_links (based_on_id);
CREATE TABLE IF NOT EXISTS qa_kept_apart (
    first_id TEXT NOT NULL REFERENCES qa_samples(id),
    second_id TEXT NOT NULL REFERENCES qa_samples(id),
    PRIMARY KEY (first_id, second_id)
);
CREATE TABLE IF NOT EXISTS qa_challenges (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    model TEXT NOT NULL,
    status TEXT NOT NULL,
    total INTEGER NOT NULL DEFAULT 0,
    done INTEGER NOT NULL DEFAULT 0,
    conflicts INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS qa_comparisons (
    test TEXT NOT NULL,
    first_id TEXT NOT NULL REFERENCES qa_samples(id) ON DELETE CASCADE,
    second_id TEXT NOT NULL DEFAULT '',
    first_hash TEXT NOT NULL,
    second_hash TEXT NOT NULL DEFAULT '',
    verdict TEXT NOT NULL,
    why TEXT NOT NULL DEFAULT '',
    quote TEXT NOT NULL DEFAULT '',
    challenge_id TEXT NOT NULL REFERENCES qa_challenges(id),
    created_at TEXT NOT NULL,
    PRIMARY KEY (test, first_id, second_id)
);
CREATE TABLE IF NOT EXISTS qa_conflicts (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    challenge_id TEXT NOT NULL REFERENCES qa_challenges(id),
    kind TEXT NOT NULL,
    first_id TEXT NOT NULL REFERENCES qa_samples(id),
    second_id TEXT NOT NULL DEFAULT '',
    quote TEXT NOT NULL DEFAULT '',
    chunk_id TEXT,
    source_id TEXT REFERENCES sources(id),
    why TEXT NOT NULL DEFAULT '',
    draft_question TEXT NOT NULL DEFAULT '',
    draft_answer TEXT NOT NULL DEFAULT '',
    draft_complex TEXT NOT NULL DEFAULT '',
    draft_model TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    resolution TEXT,
    result_id TEXT,
    undo TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    decided_at TEXT,
    UNIQUE (kind, first_id, second_id)
);
CREATE INDEX IF NOT EXISTS qa_samples_project ON qa_samples (project_id, status);
CREATE INDEX IF NOT EXISTS qa_samples_theme ON qa_samples (theme_id, status);
CREATE INDEX IF NOT EXISTS qa_samples_source ON qa_samples (source_id);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def open_db(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


def connect(path: str | Path) -> sqlite3.Connection:
    """Open the database and bring its schema up to date. Once per process; other connections use open_db."""
    conn = open_db(path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Apply additive SQLite migrations without replacing the user's database."""
    additions = {
        "train_comparisons": {"expected": "TEXT NOT NULL DEFAULT ''"},
        "sources": {
            "storage_path": "TEXT NOT NULL DEFAULT ''",
            "project_id": "TEXT REFERENCES projects(id)",
        },
        "source_chunks": {
            "ingestion_id": "TEXT REFERENCES source_ingestions(id)",
            "kind": "TEXT NOT NULL DEFAULT 'text'",
            "locator_json": "TEXT NOT NULL DEFAULT '{}'",
            "offset_basis": "TEXT NOT NULL DEFAULT 'source_text'",
            "asset_id": "TEXT REFERENCES source_assets(id)",
        },
        "source_assets": {"ocr_model": "TEXT", "figure_reading": "TEXT NOT NULL DEFAULT ''", "ocr_error": "TEXT NOT NULL DEFAULT ''"},
        "qa_conflicts": {"draft_model": "TEXT NOT NULL DEFAULT ''"},
        "projects": {"max_themes": "INTEGER NOT NULL DEFAULT 8", "identity": "TEXT NOT NULL DEFAULT ''",
                     "about_scope": "TEXT NOT NULL DEFAULT ''", "answer_style": "TEXT NOT NULL DEFAULT 'short'",
                     "include_method": "INTEGER NOT NULL DEFAULT 0",
                     "train_model": "TEXT NOT NULL DEFAULT 'mlx-community/Qwen3-4B-4bit'",
                     "prepare_count": "TEXT NOT NULL DEFAULT 'normal'", "prepare_question_model": "TEXT NOT NULL DEFAULT ''",
                     "last_read_amount": "TEXT NOT NULL DEFAULT 'normal'"},
        "train_runs": {"version": "INTEGER", "name": "TEXT NOT NULL DEFAULT ''",
                       "in_use": "INTEGER NOT NULL DEFAULT 0", "deleting_at": "TEXT"},
        "qa_samples": {"false_claim": "TEXT NOT NULL DEFAULT ''", "review_note": "TEXT NOT NULL DEFAULT ''"},
        "patterns": {"project_id": "TEXT REFERENCES projects(id)", "approved_at": "TEXT",
                     "style": "TEXT NOT NULL DEFAULT 'companion'",
                     "about_identity": "INTEGER NOT NULL DEFAULT 0"},
        "datasets": {
            "project_id": "TEXT REFERENCES projects(id)",
            "manifest_path": "TEXT NOT NULL DEFAULT ''",
            "outputs": "TEXT NOT NULL DEFAULT ''",
        },
        "extractions": {
            "passages_read": "INTEGER NOT NULL DEFAULT 0",
            "passages_total": "INTEGER NOT NULL DEFAULT 0",
            "duration_seconds": "REAL",
            "kind": "TEXT NOT NULL DEFAULT 'themes'",
            "reading": "TEXT NOT NULL DEFAULT '{}'",
        },
    }
    train_runs_columns = {row[1] for row in conn.execute("PRAGMA table_info(train_runs)").fetchall()}
    for table, columns in additions.items():
        present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, declaration in columns.items():
            if name not in present:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")
    # Existing runs receive stable per-project numbering in creation order.
    for project in conn.execute("SELECT DISTINCT project_id FROM train_runs"):
        rows = conn.execute("SELECT id FROM train_runs WHERE project_id=? AND version IS NULL ORDER BY created_at,id", (project[0],)).fetchall()
        start = conn.execute("SELECT COALESCE(MAX(version),0) FROM train_runs WHERE project_id=?", (project[0],)).fetchone()[0]
        for offset, run in enumerate(rows, 1):
            conn.execute("UPDATE train_runs SET version=? WHERE id=?", (start + offset, run[0]))
        if 'in_use' not in train_runs_columns:
            latest = conn.execute("SELECT id FROM train_runs WHERE project_id=? AND status='finished' ORDER BY version DESC LIMIT 1", (project[0],)).fetchone()
            if latest: conn.execute("UPDATE train_runs SET in_use=1 WHERE id=?", (latest[0],))
    _backfill_projects(conn)
    _adopt_behavior_samples(conn)
    conn.commit()


def _backfill_projects(conn: sqlite3.Connection) -> None:
    """Rows written before projects existed carry a free-text slug; give each slug a real project."""
    legacy = {r[0] for r in conn.execute(
        "SELECT project FROM patterns WHERE project_id IS NULL UNION SELECT project FROM sources WHERE project_id IS NULL")}
    for slug in sorted(legacy):
        if conn.execute("SELECT 1 FROM projects WHERE slug = ?", (slug,)).fetchone():
            continue
        stamp = now()
        conn.execute(
            "INSERT INTO projects (id, slug, display_name, description, objective, language, status, created_at, updated_at)"
            " VALUES (?,?,?,?, 'behavior', 'pt-BR', 'active', ?, ?)",
            (new_id("prj"), slug, slug.replace("-", " ").title(), "Migrated from the single-project prototype.", stamp, stamp),
        )
    for table in ("patterns", "sources"):
        conn.execute(
            f"UPDATE {table} SET project_id = (SELECT id FROM projects WHERE slug = {table}.project) WHERE project_id IS NULL")
    only = conn.execute("SELECT id FROM projects").fetchall()
    if len(only) == 1:  # datasets never recorded a project; with a single project the owner is unambiguous
        conn.execute("UPDATE datasets SET project_id = ? WHERE project_id IS NULL", (only[0][0],))


def _adopt_behavior_samples(conn: sqlite3.Connection) -> None:
    """Behavior conversations written before the QA flow keep their decisions in the one curation list."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'samples'").fetchone():
        return
    old = conn.execute(
        "SELECT s.*, p.project_id, p.title, b.model FROM samples s JOIN patterns p ON p.id = s.pattern_id"
        " JOIN batches b ON b.id = s.batch_id"
        " WHERE p.project_id IS NOT NULL AND s.id NOT IN (SELECT id FROM qa_samples)").fetchall()
    for s in old:
        slug = "behavior-" + s["pattern_id"].replace("_", "-")
        conn.execute(
            "INSERT OR IGNORE INTO qa_themes (id, project_id, slug, title, kind, pattern_id, created_at)"
            " VALUES (?,?,?,?, 'behavior', ?, ?)",
            (new_id("thm"), s["project_id"], slug, s["title"], s["pattern_id"], now()))
        theme = conn.execute("SELECT id FROM qa_themes WHERE project_id = ? AND slug = ?", (s["project_id"], slug)).fetchone()
        conn.execute(
            "INSERT INTO qa_samples (id, project_id, theme_id, origin, pattern_id, batch_id, model, variation_type, question,"
            " answer, content_hash, revision, status, created_at) VALUES (?,?,?, 'behavior', ?,?,?,?,?,?,?,?,?,?)",
            (s["id"], s["project_id"], theme[0], s["pattern_id"], s["batch_id"], s["model"], s["variation_type"],
             s["user_message"], s["response_text"], s["content_hash"], s["revision"], s["status"], s["created_at"]))


def row(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> dict | None:
    r = conn.execute(sql, params).fetchone()
    return dict(r) if r else None


def rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def parse_json_field(value: str):
    return json.loads(value) if value else []
