"""Projects: the scope boundary of every entity (spec 001).

A project is generic on purpose. Name, voice or policy of one project never become platform
fields. What separates projects is declared here and nowhere else:

- `objective`: kept for projects created before both tracks lived together. New projects use `both`.
- `language`: the language of the content the project produces.
- `max_themes`: how many topic themes the model may organize this dataset into.
- `identity`: free text a person writes about who the assistant is. The platform never reads meaning into it;
  it only hands it to behavior generation.
"""

import re

from . import db

OBJECTIVES = ("behavior", "knowledge", "both")
STATUSES = ("active", "archived")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")
LANGUAGE_RE = re.compile(r"^[a-z]{2,3}(-[A-Z]{2})?$")
LANGUAGE_NAME = {"en": "English", "pt-BR": "Brazilian Portuguese", "es": "Spanish"}
DEFAULT_MAX_THEMES = 8
MAX_THEMES_LIMIT = 50
MAX_IDENTITY = 2000
PREPARE_COUNTS = ("few", "normal", "many")
DEFAULT_TRAIN_MODEL = "mlx-community/Qwen3-4B-4bit"


class ProjectNotFound(Exception):
    pass


class ProjectInvalid(ValueError):
    pass


class ProjectExists(Exception):
    pass


class ProjectArchived(Exception):
    pass


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]


def _validated(display_name: str, language: str) -> tuple[str, str]:
    display_name = (display_name or "").strip()
    if not display_name:
        raise ProjectInvalid("display_name is required")
    if not LANGUAGE_RE.match(language or ""):
        raise ProjectInvalid("language must look like 'en' or 'pt-BR'")
    return display_name, language


def _validated_limit(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_THEMES_LIMIT:
        raise ProjectInvalid(f"the theme limit must be a whole number from 1 to {MAX_THEMES_LIMIT}")
    return value


def create(conn, *, display_name: str, objective: str | None = None, language: str,
           slug: str | None = None, description: str = "", max_themes: int = DEFAULT_MAX_THEMES) -> dict:
    display_name, language = _validated(display_name, language)
    max_themes = _validated_limit(max_themes)
    objective = objective or "both"
    if objective not in OBJECTIVES:
        raise ProjectInvalid(f"objective must be one of: {', '.join(OBJECTIVES)}")
    slug = slug or slugify(display_name)
    if not SLUG_RE.match(slug):
        raise ProjectInvalid("slug must be 2-40 characters: lowercase letters, digits and hyphens")
    if conn.execute("SELECT 1 FROM projects WHERE slug = ?", (slug,)).fetchone():
        raise ProjectExists(f"a project with slug '{slug}' already exists")
    pid, stamp = db.new_id("prj"), db.now()
    conn.execute(
        "INSERT INTO projects (id, slug, display_name, description, objective, language, status, max_themes, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?, 'active', ?, ?, ?)",
        (pid, slug, display_name, description.strip(), objective, language, max_themes, stamp, stamp),
    )
    conn.commit()
    return get(conn, pid)


def get(conn, project_id: str) -> dict:
    project = db.row(conn, "SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise ProjectNotFound(f"project {project_id} not found")
    return project


def list_projects(conn) -> list[dict]:
    return db.rows(conn, "SELECT * FROM projects ORDER BY created_at")


def update(conn, project_id: str, *, display_name: str | None = None, description: str | None = None,
           language: str | None = None, status: str | None = None, max_themes: int | None = None,
           identity: str | None = None, train_model: str | None = None, prepare_count: str | None = None,
           about_scope: str | None = None, answer_style: str | None = None, include_method: bool | None = None) -> dict:
    current = get(conn, project_id)
    if status is not None and status not in STATUSES:
        raise ProjectInvalid(f"status must be one of: {', '.join(STATUSES)}")
    name, lang = _validated(display_name if display_name is not None else current["display_name"],
                            language if language is not None else current["language"])
    limit = current["max_themes"]
    if max_themes is not None:
        limit = _validated_limit(max_themes)
        used = conn.execute("SELECT COUNT(*) FROM qa_themes WHERE project_id = ? AND kind = 'topic'", (project_id,)).fetchone()[0]
        if limit < used:
            raise ProjectInvalid(f"this dataset already has {used} themes; merge some before lowering the limit to {limit}")
    new_identity = (identity if identity is not None else current["identity"]).strip()
    if len(new_identity) > MAX_IDENTITY:
        raise ProjectInvalid(f"the identity can hold at most {MAX_IDENTITY} characters")
    if prepare_count is not None and prepare_count not in PREPARE_COUNTS:
        raise ProjectInvalid("prepare_count must be few, normal or many")
    if answer_style is not None and answer_style not in ("short", "explains"):
        raise ProjectInvalid("answer_style must be short or explains")
    if train_model is not None:
        from . import training
        if train_model not in {item["id"] for item in training.CATALOG}:
            raise ProjectInvalid("Choose a supported training model from Train.")
    conn.execute(
        "UPDATE projects SET display_name = ?, description = ?, language = ?, status = ?, max_themes = ?, identity = ?, train_model = ?, prepare_count = ?, about_scope = ?, answer_style = ?, include_method = ?, updated_at = ? WHERE id = ?",
        (name, (description if description is not None else current["description"]).strip(), lang,
         status or current["status"], limit, new_identity, train_model or current.get("train_model") or DEFAULT_TRAIN_MODEL,
         prepare_count or current.get("prepare_count") or "normal", (about_scope if about_scope is not None else current.get("about_scope", "")).strip(),
         answer_style or current.get("answer_style", "short"), int(include_method if include_method is not None else current.get("include_method", 0)), db.now(), project_id),
    )
    conn.commit()
    return get(conn, project_id)


def require_writable(conn, project_id: str) -> dict:
    """Archived projects stay readable but accept no new work (spec 001)."""
    project = get(conn, project_id)
    if project["status"] != "active":
        raise ProjectArchived(f"project {project['slug']} is {project['status']}; restore it before changing anything")
    return project


# Which project owns an entity. Children inherit scope from their root (pattern or source).
_OWNER_SQL = {
    "pattern": "SELECT project_id FROM patterns WHERE id = ?",
    "batch": "SELECT p.project_id FROM batches b JOIN patterns p ON p.id = b.pattern_id WHERE b.id = ?",
    "sample": "SELECT project_id FROM qa_samples WHERE id = ?",
    "source": "SELECT project_id FROM sources WHERE id = ?",
    "theme": "SELECT project_id FROM qa_themes WHERE id = ?",
    "dataset": "SELECT project_id FROM datasets WHERE id = ?",
}


def owner_of(conn, kind: str, entity_id: str) -> str | None:
    found = conn.execute(_OWNER_SQL[kind], (entity_id,)).fetchone()
    return found[0] if found else None


def ensure_member(conn, project_id: str, kind: str, entity_id: str) -> None:
    """Cross-project access answers 'not found', so ids never confirm what exists elsewhere."""
    if owner_of(conn, kind, entity_id) != project_id:
        raise ProjectNotFound(f"{kind} {entity_id} not found")
