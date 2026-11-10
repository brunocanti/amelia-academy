"""HTTP API. Every resource lives under /projects/{project_id} (spec 001); there is no implicit scope."""

import json
import os
import re
import threading
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from . import challenge, console, datasets, db, documents, expander, kb, kinds, projects, qa, runs, sources, workshop
from . import cli_tools
from .llm import LLMError, OllamaClient, installed_models

DATA_DIR = Path(os.environ.get("AMELIA_ACADEMY_DATA", Path(__file__).resolve().parents[2] / "var"))
DB_PATH = DATA_DIR / "academy.sqlite3"
DEFAULT_MODEL = os.environ.get("AMELIA_ACADEMY_MODEL", "qwen3:14b")
OLLAMA_URL = os.environ.get("AMELIA_ACADEMY_OLLAMA_URL", "http://localhost:11434")

app = FastAPI(title="Amelia Academy")
_first_open = threading.Lock()
_conn = None  # set once the database is ready; a new value also retires every thread's connection
_local = threading.local()


def conn():
    """One connection per worker thread: a route that polls must never read through another route's statement."""
    global _conn
    with _first_open:
        if _conn is None:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            _conn = db.connect(DB_PATH)
            qa.stop_interrupted(_conn)
            challenge.stop_interrupted(_conn)
            from . import training
            training.recover(_conn)
            training.cleanup_deletions(_conn, DATA_DIR)
    if getattr(_local, "opened_with", None) is not _conn:
        _local.conn = db.open_db(DB_PATH)
        _local.opened_with = _conn
    return _local.conn


def client_for(model: str):
    """The name of a model says who runs it."""
    if cli_tools.tool_of(model):
        return cli_tools.CliClient(model)
    return OllamaClient(model=model, base_url=OLLAMA_URL)


def vision_client(model: str | None):
    """The selected model reads figures only when it can see. No second model is loaded."""
    name = (model or "").strip()
    if not name:
        return None
    tool = cli_tools.tool_of(name)
    if tool:
        return cli_tools.CliClient(name) if tool.sees else None
    match = next((item for item in installed_models(OLLAMA_URL) if item["name"] == name), None)
    if not match or not match.get("vision"):
        return None
    return OllamaClient(model=name, base_url=OLLAMA_URL)


@app.exception_handler(LLMError)
def model_unavailable(_request, exc: LLMError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


def _errors(fn):
    try:
        return fn()
    except (workshop.NotFound, projects.ProjectNotFound) as exc:
        raise HTTPException(404, str(exc))
    except (workshop.PatternNotApproved, workshop.Conflict, projects.ProjectExists, projects.ProjectArchived, runs.Busy) as exc:
        raise HTTPException(409, str(exc))
    except (sources.SourceRejected, ValueError) as exc:  # ProjectInvalid is a ValueError
        raise HTTPException(422, str(exc))


def _scoped(project_id: str, fn, *, kind: str | None = None, entity_id: str | None = None, write: bool = False):
    """Run `fn` inside a project: it must exist, be writable for writes, and own the entity it names."""
    def go():
        c = conn()
        (projects.require_writable if write else projects.get)(c, project_id)
        if kind:
            projects.ensure_member(c, project_id, kind, entity_id)
        return fn()
    return _errors(go)


# --- Work that goes on without the page ---

REFUSED_AT_ONCE = (workshop.NotFound, projects.ProjectNotFound, workshop.PatternNotApproved, workshop.Conflict,
                   projects.ProjectArchived, sources.SourceRejected, ValueError)
REFUSAL_WAIT = 0.25  # seconds: work that cannot start says so before any model call


def _begin(project_id: str, kind: str, subject: str, title: str, where: dict, work, *, note=None, again=None) -> dict:
    """Answer the click now and go on in the background. A refusal still answers the click that caused it."""
    def go():
        try:
            return work(conn())
        except BaseException:
            conn().rollback()  # a stop or a failure between commits leaves no half of a step behind
            raise

    entry = runs.launch(project_id, kind, subject, title, where, go, note=note, again=again)
    runs.settle(entry, REFUSAL_WAIT)
    if isinstance(entry["raised"], REFUSED_AT_ONCE):
        runs.forget(entry)
        raise entry["raised"]
    return runs.public(entry)


FILES = lambda source_id: {"view": "files", "params": {"source": source_id}}  # noqa: E731
CONFLICTS = {"view": "curate", "params": {"view": "conflicts"}}
CURATE = {"view": "curate", "params": {}}


def _begin_reading(project_id: str, source: dict, eid: str, llm, vision) -> dict:
    def work(c):
        done = qa.run(c, llm, eid, out_dir=DATA_DIR / "sources", vision=vision)
        if done["status"] == "failed":
            raise RuntimeError(done["error"])
        return done
    return _begin(project_id, "reading", source["id"], f"Reading {source['name']}", FILES(source["id"]), work,
                  note=lambda _: "Finished. The pairs are ready to review.")


def _begin_challenge(project_id: str, cid: str, llm) -> dict:
    def work(c):
        done = challenge.run(c, llm, cid)
        if done["status"] == "failed":
            raise RuntimeError(done["error"])
        return done
    return _begin(project_id, "challenge", project_id, "Challenge", CONFLICTS, work,
                  note=lambda done: f"{done['total']} comparison(s), {done['conflicts']} new to decide.")


def _wrote(result: dict) -> str:
    why = "; ".join(sorted({r["reason"] for r in result["rejected"]}))
    return f"{result['kept']} new pair(s) to review" + (f", {len(result['rejected'])} discarded: {why}." if why else ".")


def _project_runs(project_id: str) -> list[dict]:
    """What is going on in a project, and what stopped and can go on, even after the app closed."""
    c = conn()
    named = {s["id"]: s["name"] for s in db.rows(c, "SELECT id, name FROM sources WHERE project_id = ?", (project_id,))}
    listed = {e["key"]: runs.public(e) for e in runs.in_project(project_id)
              if e["kind"] not in ("reading", "figures", "kinds") or e["subject"] in named}

    def stored(kind: str, subject: str, title: str, where: dict, created_at: str) -> dict:
        return {"key": runs.key(kind, subject), "project_id": project_id, "kind": kind, "subject": subject, "title": title, "where": where,
                "status": "stopped", "stopping": False, "error": "", "message": "", "started_at": created_at, "finished_at": None}

    for source_id, name in named.items():
        run = sources.extraction_progress(c, source_id)
        key = runs.key("reading", source_id)
        if run and run["status"] == "stopped" and key not in listed:
            listed[key] = stored("reading", source_id, f"Reading {name}", FILES(source_id), run["created_at"])
        if run and key in listed and run["status"] != "running":
            figures = (run.get("reading") or {}).get("figures") or {}
            figures_done = sum(figures.get(name, 0) for name in ("read", "failed", "skipped"))
            listed[key].update(done=(run["passages_read"] or 0) + figures_done,
                               total=run["passages_total"] or 0, can_continue=run["can_continue"])
            if run["status"] == "stopped":
                listed[key]["message"] = run["error"] or ""
    last = challenge.latest(c, project_id)
    key = runs.key("challenge", project_id)
    if last and last["status"] == "stopped" and key not in listed:
        listed[key] = stored("challenge", project_id, "Challenge", CONFLICTS, last["created_at"])
    if last and key in listed:
        listed[key].update(done=last["done"] or 0, total=last["total"] or 0, can_continue=last["status"] in ("stopped", "failed"))
        if last["status"] == "stopped":
            listed[key]["message"] = last["error"] or ""
    return list(listed.values())


# --- Projects ---

class ProjectIn(BaseModel):
    display_name: str
    objective: str | None = None
    language: str = "en"
    slug: str | None = None
    description: str = ""
    max_themes: int = projects.DEFAULT_MAX_THEMES


class ProjectPatch(BaseModel):
    model_config = {"extra": "forbid"}

    display_name: str | None = None
    description: str | None = None
    language: str | None = None
    status: str | None = None
    max_themes: int | None = None
    identity: str | None = None
    train_model: str | None = None
    prepare_count: str | None = None
    about_scope: str | None = None
    answer_style: Literal["short", "explains"] | None = None
    include_method: bool | None = None


@app.get("/projects")
def list_projects():
    return projects.list_projects(conn())


@app.post("/projects")
def create_project(body: ProjectIn):
    return _errors(lambda: projects.create(conn(), **body.model_dump()))


@app.get("/projects/{project_id}")
def get_project(project_id: str):
    return _errors(lambda: projects.get(conn(), project_id))


@app.patch("/projects/{project_id}")
def patch_project(project_id: str, body: ProjectPatch):
    return _errors(lambda: projects.update(conn(), project_id, **body.model_dump(exclude_unset=True)))


@app.get("/console")
def read_console(after: int = 0):
    """What the agents are doing and how it went, since the server started."""
    return console.snapshot(after)


@app.get("/console/lines/{seq}")
def read_console_line(seq: int):
    found = console.line(seq)
    if found is None:
        raise HTTPException(404, "that line is no longer kept")
    return found


@app.get("/models")
def list_models():
    """What can be chosen: Ollama's models, then those of each tool that is signed in. The default stays on this computer."""
    online, problems = cli_tools.available_models()
    try:
        local = [{**item, "label": item["name"], "group": "", "online": False, "notice": ""} for item in installed_models(OLLAMA_URL)]
    except LLMError as exc:
        if not online:
            raise HTTPException(503, str(exc)) from exc
        local, problems = [], ["Ollama is not running, so models on this computer are not listed.", *problems]
    names = [item["name"] for item in local]
    default = DEFAULT_MODEL if DEFAULT_MODEL in names else (names[0] if names else ("" if online else DEFAULT_MODEL))
    return {"default": default, "models": local + online, "problems": problems}


# --- Files ---

class SourceIn(BaseModel):
    name: str
    content: str
    purpose: str
    license_basis: str
    model: str = ""


class VisionIn(BaseModel):
    model: str = ""


class ReadingMix(BaseModel):
    model_config = {"extra": "forbid"}

    false: int = Field(15, ge=0, le=30)
    doubts: int = Field(15, ge=0, le=30)
    neighbour: int = Field(5, ge=0, le=30)


class GenerateIn(BaseModel):
    model: str = DEFAULT_MODEL
    amount: Literal["quick", "normal", "everything"] | None = None
    care: Literal["direct", "balanced", "careful"] | None = None
    mix: ReadingMix | None = None
    pairs_per_section: int | None = Field(None, ge=qa.PAIRS_PER_WINDOW_LIMITS[0], le=qa.PAIRS_PER_WINDOW_LIMITS[1])
    section_chars: int = Field(qa.WINDOW_CHARS, ge=qa.WINDOW_CHARS_LIMITS[0], le=qa.WINDOW_CHARS_LIMITS[1])
    images: bool = False
    false_per_section: int | None = Field(None, ge=0, le=4)
    doubts_per_section: int | None = Field(None, ge=0, le=4)
    unanswered_pct: int | None = Field(None, ge=qa.KIND_PCT_LIMITS[0], le=qa.KIND_PCT_LIMITS[1])
    false_premise_pct: int | None = Field(None, ge=qa.KIND_PCT_LIMITS[0], le=qa.KIND_PCT_LIMITS[1])
    neighbour_pct: int | None = Field(None, ge=qa.KIND_PCT_LIMITS[0], le=qa.KIND_PCT_LIMITS[1])


class KindsIn(BaseModel):
    model: str = DEFAULT_MODEL
    unanswered_pct: int = Field(0, ge=qa.KIND_PCT_LIMITS[0], le=qa.KIND_PCT_LIMITS[1])
    false_premise_pct: int = Field(0, ge=qa.KIND_PCT_LIMITS[0], le=qa.KIND_PCT_LIMITS[1])
    neighbour_pct: int = Field(0, ge=qa.KIND_PCT_LIMITS[0], le=qa.KIND_PCT_LIMITS[1])


@app.get("/projects/{project_id}/sources")
def list_sources(project_id: str):
    return _scoped(project_id, lambda: sources.list_sources(conn(), project_id, DATA_DIR / "sources"))


@app.post("/projects/{project_id}/about-scope/draft")
def draft_about_scope(project_id: str, body: VisionIn):
    def draft(c):
        project = projects.get(c, project_id)
        files = c.execute("SELECT s.id,s.name,c.text FROM sources s JOIN source_chunks c ON c.source_id=s.id WHERE s.project_id=? AND c.kind='text' ORDER BY s.created_at,c.idx", (project_id,)).fetchall()
        if not files:
            raise ValueError("Add a file first.")
        summaries = []
        for row in files:
            text = str(row[2] or '')
            summaries.append(f"File: {row[1]}\nThemes and short summary: {text[:1800]}")
        schema = {"type":"object","properties":{"about":{"type":"string"}},"required":["about"]}
        result = client_for(body.model).complete_json("Read every file summary below. Write one plain sentence in " + project["language"] + " describing the subject common to all files and what this model should know across them. Cover all files; do not focus on only one. Do not mention files or sources.\n\n" + "\n\n".join(summaries), schema, temperature=0.1)
        return {"about_scope": str(result.get("about", "")).strip()}
    return _scoped(project_id, lambda: draft(conn()))


@app.post("/projects/{project_id}/sources")
def upload_source(project_id: str, body: SourceIn):
    return _scoped(project_id, lambda: sources.ingest(
        conn(), DATA_DIR / "sources", project_id=project_id, name=body.name, content=body.content,
        purpose=body.purpose, license_basis=body.license_basis, vision=vision_client(body.model)), write=True)


@app.post("/projects/{project_id}/sources/upload")
async def upload_source_file(
    project_id: str,
    file: UploadFile = File(...),
    purpose: str = Form("qa-dataset"),
    license_basis: str = Form("unspecified"),
    model: str = Form(""),
):
    _scoped(project_id, lambda: None, write=True)  # fail before reading the body of an unusable project
    data = await file.read(documents.MAX_BYTES + 1)
    await file.close()
    if len(data) > documents.MAX_BYTES:
        raise HTTPException(413, f"file too large; limit is {documents.MAX_BYTES // (1024 * 1024)} MB")
    # Reading figures takes minutes, and on the event loop it would stop every other request.
    return await run_in_threadpool(lambda: _scoped(project_id, lambda: sources.ingest_bytes(
        conn(), DATA_DIR / "sources", project_id=project_id, name=file.filename or "upload", data=data,
        purpose=purpose, license_basis=license_basis, vision=vision_client(model)), write=True))


@app.get("/projects/{project_id}/sources/{source_id}")
def get_source(project_id: str, source_id: str):
    return _scoped(project_id, lambda: sources.get_source(conn(), source_id), kind="source", entity_id=source_id)


@app.get("/projects/{project_id}/sources/{source_id}/assets/{asset_id}")
def source_asset_preview(project_id: str, source_id: str, asset_id: str):
    asset = _scoped(project_id, lambda: sources.get_asset(conn(), source_id, asset_id), kind="source", entity_id=source_id)
    root = (DATA_DIR / "sources").resolve()
    path = (root / asset["storage_path"]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(404, "source asset file not found")
    preview, error = documents.safe_png(path.read_bytes())
    if preview is None:
        raise HTTPException(415, error or "no safe raster preview is available")
    return Response(preview, media_type="image/png", headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=300"})


@app.post("/projects/{project_id}/sources/{source_id}/reprocess")
def reprocess_source(project_id: str, source_id: str, body: VisionIn | None = None):
    return _scoped(project_id, lambda: sources.reprocess_source(
        conn(), DATA_DIR / "sources", source_id, vision=vision_client(body.model if body else "")),
                   kind="source", entity_id=source_id, write=True)


@app.post("/projects/{project_id}/sources/{source_id}/figures/read")
def read_figures(project_id: str, source_id: str, body: VisionIn):
    """Read the figures not read yet with the selected model, when that model can see. Document text stays."""
    client = vision_client(body.model)
    if client is None:
        raise HTTPException(422, "this model does not see images")

    def work(c):
        counts = sources.read_figures(c, DATA_DIR / "sources", source_id, client,
                                      on_progress=lambda n: runs.progress(n["read"] + n["failed"], n["total"]))
        if counts["failed"]:
            raise RuntimeError(f"{counts['failed']} figure(s) could not be read: {counts.get('error', '')}")
        return counts

    def start():
        if conn().execute("SELECT 1 FROM extractions WHERE source_id = ? AND status = 'running'", (source_id,)).fetchone():
            raise workshop.Conflict("this file is being read")
        name = sources.get_source(conn(), source_id)["name"]
        return _begin(project_id, "figures", source_id, f"Reading the figures of {name}", FILES(source_id), work,
                      note=lambda counts: f"{counts['read']} figure(s) read.", again=start)
    return _scoped(project_id, start, kind="source", entity_id=source_id, write=True)


@app.get("/projects/{project_id}/sources/{source_id}/extraction")
def extraction_progress(project_id: str, source_id: str):
    return _scoped(project_id, lambda: sources.extraction_progress(conn(), source_id), kind="source", entity_id=source_id)


@app.post("/projects/{project_id}/sources/{source_id}/generate")
def generate(project_id: str, source_id: str, body: GenerateIn):
    """Propose themes and write the pairs. Answers at once and goes on; `extraction` and `runs` tell how far it got."""
    llm = client_for(body.model)
    def read():
        source_for_vision = sources.get_source(conn(), source_id)
        has_unread_images = bool(sources.unread_figures(source_for_vision))
        selected_vision = vision_client(body.model) if has_unread_images else None
        vision_models = [m for m in installed_models(OLLAMA_URL) if m.get("vision")] if has_unread_images and selected_vision is None else []
        vision = selected_vision or (OllamaClient(model=vision_models[0]["name"], base_url=OLLAMA_URL) if vision_models else None)
        images = body.images or (has_unread_images and vision is not None)
        if not body.images and has_unread_images and vision is not None:
            images = True
        if vision is None:
            images = False
        if runs.is_running("figures", source_id):
            raise workshop.Conflict("the figures of this file are being read")
        sources.use_current_extractor(conn(), DATA_DIR / "sources", source_id)
        fields = body.model_fields_set
        legacy_pairs = body.pairs_per_section
        amount = body.amount or ("quick" if legacy_pairs is not None and legacy_pairs <= 4 else "everything" if legacy_pairs is not None and legacy_pairs >= 9 else "normal")
        legacy_mix = any(key in fields for key in ("false_per_section", "doubts_per_section", "false_premise_pct", "unanswered_pct", "neighbour_pct"))
        legacy_strength = (body.false_per_section or 0) + (body.doubts_per_section or 0) + (body.false_premise_pct or 0) + (body.unanswered_pct or 0)
        care = body.care or ("direct" if not legacy_mix or legacy_strength == 0 else "careful" if legacy_strength >= 40 else "balanced")
        legacy_false = body.false_per_section if body.false_per_section is not None else (0 if legacy_mix else None)
        legacy_doubts = body.doubts_per_section if body.doubts_per_section is not None else (0 if legacy_mix else None)
        eid = qa.start(conn(), source_id, body.model, pairs_per_section=body.pairs_per_section or qa.MAX_PER_WINDOW,
                       section_chars=body.section_chars, images=images,
                       false_per_section=legacy_false, doubts_per_section=legacy_doubts,
                       unanswered_pct=body.unanswered_pct, false_premise_pct=body.false_premise_pct,
                       neighbour_pct=body.neighbour_pct, amount=amount, care=care,
                       mix=body.mix.model_dump() if body.mix else ({"false": 7, "doubts": 8} if body.care == "direct" and not legacy_mix else None))
        return _begin_reading(project_id, sources.get_source(conn(), source_id), eid, llm, vision)
    return _scoped(project_id, read, kind="source", entity_id=source_id, write=True)


def _reading_calibration(c, measured, amount: str) -> dict:
    """What earlier readings with this model really gave: pairs per planned window and clock seconds per window."""
    from datetime import datetime, timedelta
    plans: dict[str, int] = {}

    def planned(source_id: str) -> int:
        if source_id not in plans:
            file = sources.get_source(c, source_id)
            plan = qa.read_plan(file["chunks"], window_chars=qa.WINDOW_CHARS, images=False) if file else {"windows": []}
            plans[source_id] = sum(1 for w in plan["windows"][:qa.MAX_WINDOWS] if qa.density_limit(w, amount))
        return plans[source_id]

    def mix_of(row) -> float:
        try:
            mix = (json.loads(row["reading"] or "{}").get("options") or {}).get("mix") or {}
        except (TypeError, ValueError):
            mix = {}
        return 100 / max(1, 100 - int(mix.get("false") or 0) - int(mix.get("doubts") or 0))

    rows = [row for row in measured if planned(row["source_id"])]
    if not rows:
        return {"pairs_per_window": None, "mix_scale": 1.0, "wall_per_window": None}
    windows = sum(planned(row["source_id"]) for row in rows)
    mix_scale = sum(mix_of(row) * planned(row["source_id"]) for row in rows) / windows
    # Files started together (within a minute, same project) are one "Read all": its clock time is first start to last end.
    batches: list[list] = []
    for row in sorted(rows, key=lambda r: (r["project_id"], r["created_at"])):
        start = datetime.fromisoformat(row["created_at"])
        last = batches[-1] if batches else None
        if last and last[0]["project_id"] == row["project_id"] and start - datetime.fromisoformat(last[0]["created_at"]) <= timedelta(minutes=1):
            last.append(row)
        else:
            batches.append([row])
    wall = 0.0
    for b in batches:
        begin = min(datetime.fromisoformat(r["created_at"]) for r in b)
        end = max(datetime.fromisoformat(r["created_at"]) + timedelta(seconds=r["duration_seconds"]) for r in b)
        wall += (end - begin).total_seconds()
    return {"pairs_per_window": sum(row["pairs"] for row in rows) / windows, "mix_scale": mix_scale,
            "wall_per_window": wall / windows}


@app.get("/projects/{project_id}/reading-estimate")
def reading_estimate(project_id: str, amount: str = "normal", care: str = "balanced", model: str = DEFAULT_MODEL,
                     false_pct: int | None = None, doubt_pct: int | None = None):
    def estimate(c):
        files = [sources.get_source(c, row["id"]) for row in c.execute("SELECT id FROM sources WHERE project_id = ?", (project_id,))]
        windows, pairs, file_work = 0, 0, []
        for file in files:
            plan = qa.read_plan(file["chunks"], window_chars=qa.WINDOW_CHARS, images=False)
            this_file = 0
            for window in plan["windows"][:qa.MAX_WINDOWS]:
                limit = qa.density_limit(window, amount)
                if limit:
                    windows += 1
                    pairs += limit
                    this_file += 1
            figure_count = len(sources.unread_figures(file))
            file_work.append((this_file, figure_count))
        history = c.execute(
            "SELECT e.id, e.source_id, s.project_id, e.created_at, e.passages_read, e.duration_seconds, e.reading,"
            " (SELECT COUNT(*) FROM qa_samples x WHERE x.extraction_id = e.id AND x.origin != 'refusal') AS pairs"
            " FROM extractions e JOIN sources s ON s.id = e.source_id"
            " WHERE e.model = ? AND e.kind = 'qa' AND e.status = 'succeeded'",
            (model,),
        ).fetchall()
        measured = [row for row in history if row["passages_read"] and row["duration_seconds"] is not None]
        calibrated = _reading_calibration(c, measured, amount)
        # Duration per passage is calibrated across projects for the exact selected model.
        # Unknown models get a cautious size-based estimate; bigger models are slower.
        size = re.search(r"(?:^|[-_:])(\d+(?:\.\d+)?)\s*[bB](?:$|[-_:])", model)
        billions = float(size.group(1)) if size else 14.0
        fallback_seconds = max(35.0, min(150.0, 18.0 + billions * 4.5))
        seconds = (sum(row["duration_seconds"] / row["passages_read"] for row in measured) / len(measured)
                   if measured else fallback_seconds)
        default_mix = qa.READ_CARE.get(care, qa.READ_CARE["balanced"])
        false_share = max(0, min(30, default_mix[0] if false_pct is None else false_pct))
        doubt_share = max(0, min(30, default_mix[1] if doubt_pct is None else doubt_pct))
        mix_scale = 100 / max(1, 100 - false_share - doubt_share)
        pairs_per_window = calibrated["pairs_per_window"]
        if pairs_per_window is not None:
            # Past readings already hold the mix they were read with; rescale to the mix asked now.
            pairs = round(windows * pairs_per_window * mix_scale / calibrated["mix_scale"])
        else:
            # The density limit is a ceiling; readings keep about two thirds of it after the checks.
            pairs = round(pairs * mix_scale * 0.65)
        figure_seconds = max(30.0, min(90.0, seconds * 0.75))
        if calibrated["wall_per_window"] is not None:
            # Measured clock time of earlier "Read all" batches already holds parallel reading and figures.
            clock_seconds = windows * calibrated["wall_per_window"]
        else:
            # Files are read concurrently, so clock time follows the slowest file and its own figures.
            per_file_figures = 0 if measured else figure_seconds
            clock_seconds = max((count * seconds + figures * per_file_figures for count, figures in file_work), default=0)
        return {"pairs": pairs, "minutes": max(1, round(clock_seconds / 60)), "windows": windows,
                "seconds_per_window": round(seconds, 1),
                "pairs_per_window": None if pairs_per_window is None else round(pairs_per_window, 2),
                "figures": sum(figures for _, figures in file_work)}
    return _scoped(project_id, lambda: estimate(conn()))


@app.post("/projects/{project_id}/sources/{source_id}/kinds")
def write_kinds(project_id: str, source_id: str, body: KindsIn):
    """The added kinds of pair for the latest reading of a file. The file is not read again."""
    llm = client_for(body.model)

    def start():
        name = sources.get_source(conn(), source_id)["name"]
        return _begin(project_id, "kinds", source_id, f"Writing the other kinds for {name}", FILES(source_id),
                      lambda c: kinds.repeat(c, llm, source_id, body.unanswered_pct, body.false_premise_pct, body.neighbour_pct),
                      note=lambda _: "Finished.", again=start)
    return _scoped(project_id, start, kind="source", entity_id=source_id, write=True)


# --- Themes ---

class ThemeIn(BaseModel):
    title: str
    description: str = ""


class ThemePatch(BaseModel):
    model_config = {"extra": "forbid"}

    title: str | None = None
    description: str | None = None


class MergeIn(BaseModel):
    into: str


class ThemeOperationUndo(BaseModel):
    snapshot: dict


class ThemeSplitIn(BaseModel):
    model: str = Field(min_length=1)


class ThemeSplitConfirmIn(BaseModel):
    proposal: dict


@app.get("/projects/{project_id}/themes")
def list_themes(project_id: str):
    return _scoped(project_id, lambda: qa.list_themes(conn(), project_id))


@app.post("/projects/{project_id}/themes")
def create_theme(project_id: str, body: ThemeIn):
    return _scoped(project_id, lambda: qa.create_theme(conn(), project_id, body.title, body.description), write=True)


@app.patch("/projects/{project_id}/themes/{theme_id}")
def edit_theme(project_id: str, theme_id: str, body: ThemePatch):
    return _scoped(project_id, lambda: qa.edit_theme(conn(), theme_id, **body.model_dump(exclude_unset=True)),
                   kind="theme", entity_id=theme_id, write=True)


@app.post("/projects/{project_id}/themes/{theme_id}/merge")
def merge_theme(project_id: str, theme_id: str, body: MergeIn):
    return _scoped(project_id, lambda: qa.merge_theme(conn(), theme_id, body.into),
                   kind="theme", entity_id=theme_id, write=True)


@app.post("/projects/{project_id}/themes/{theme_id}/split")
def split_theme(project_id: str, theme_id: str, body: ThemeSplitIn):
    llm = client_for(body.model)
    return _scoped(project_id, lambda: qa.split_theme(conn(), theme_id, llm),
                   kind="theme", entity_id=theme_id, write=True)


@app.post("/projects/{project_id}/themes/{theme_id}/split/confirm")
def confirm_theme_split(project_id: str, theme_id: str, body: ThemeSplitConfirmIn):
    return _scoped(project_id, lambda: qa.confirm_theme_split(conn(), theme_id, body.proposal),
                   kind="theme", entity_id=theme_id, write=True)


@app.post("/projects/{project_id}/themes/undo")
def undo_theme_operation(project_id: str, body: ThemeOperationUndo):
    return _scoped(project_id, lambda: qa.undo_theme_operation(conn(), project_id, body.snapshot), write=True)


# --- Curation ---

class SampleEdit(BaseModel):
    model_config = {"extra": "forbid"}

    question: str | None = None
    answer: str | None = None
    false_claim: str | None = None
    theme_id: str | None = None


@app.get("/projects/{project_id}/samples")
def list_samples(project_id: str, theme: str = "", source: str = "", status: str = "", origin: str = ""):
    return _scoped(project_id, lambda: qa.list_samples(conn(), project_id, theme_id=theme, source_id=source, status=status, origin=origin))


class SimilarDecision(BaseModel):
    model_config = {"extra": "forbid"}

    sample_ids: list[str]
    keep_id: str | None = None
    undo: bool = False


@app.get("/projects/{project_id}/pillars")
def pillars(project_id: str):
    return _scoped(project_id, lambda: qa.pillar_counts(conn(), project_id))


class ChallengeIn(BaseModel):
    model: str = Field(min_length=1)


class ConflictDecision(BaseModel):
    resolution: str
    question: str = Field(default="", max_length=qa.MAX_QUESTION_CHARS)
    answer: str = Field(default="", max_length=qa.MAX_ANSWER_CHARS)
    model: str = ""  # writes the new pair when the person chose and nothing is written yet


@app.post("/projects/{project_id}/challenge")
def run_challenge(project_id: str, body: ChallengeIn):
    """Every pillar against the others. Answers at once and goes on; the GET tells how far it got."""
    llm = client_for(body.model)
    return _scoped(project_id, lambda: _begin_challenge(project_id, challenge.start(conn(), project_id, body.model), llm), write=True)


@app.get("/projects/{project_id}/runs")
def project_runs(project_id: str):
    return _scoped(project_id, lambda: _project_runs(project_id))


@app.post("/projects/{project_id}/runs/{kind}/{subject}/stop")
def stop_run(project_id: str, kind: str, subject: str):
    """Takes effect at the next word the model writes. What was kept stays."""
    def stop():
        entry = runs.find(kind, subject)
        if not entry or entry["project_id"] != project_id:
            raise workshop.NotFound("no such run")
        if not runs.stop(kind, subject):
            raise workshop.Conflict("this is not running any more")
        return runs.public(entry)
    return _scoped(project_id, stop, write=True)


@app.post("/projects/{project_id}/runs/{kind}/{subject}/continue")
def continue_run(project_id: str, kind: str, subject: str):
    def go_on():
        c = conn()
        if kind == "reading":
            projects.ensure_member(c, project_id, "source", subject)
            if runs.is_running("figures", subject) or runs.is_running("reading", subject):
                raise workshop.Conflict("this file is being read")
            before = sources.extraction_progress(c, subject) or {}
            # Asked before the run is marked as going on: Ollama being away must not leave it marked.
            vision = vision_client(before["model"]) if before.get("reading", {}).get("options", {}).get("images") else None
            last = qa.resume(c, subject)
            return _begin_reading(project_id, sources.get_source(c, subject), last["id"], client_for(last["model"]), vision)
        if kind == "challenge":
            if subject != project_id:
                raise workshop.NotFound("no such run")
            if runs.is_running("challenge", project_id):
                raise workshop.Conflict("a challenge is already running in this project")
            last = challenge.resume(c, project_id)
            return _begin_challenge(project_id, last["id"], client_for(last["model"]))
        entry = runs.find(kind, subject)
        if not entry or entry["project_id"] != project_id:
            raise workshop.NotFound("no such run")
        if not entry["again"] or entry["status"] not in ("stopped", "failed"):
            raise ValueError("nothing to continue here")
        return entry["again"]()
    return _scoped(project_id, go_on, write=True)


@app.get("/projects/{project_id}/challenge")
def challenge_report(project_id: str):
    return _scoped(project_id, lambda: challenge.report(conn(), project_id))


@app.get("/projects/{project_id}/conflicts")
def conflicts(project_id: str, status: str = "open"):
    return _scoped(project_id, lambda: challenge.list_conflicts(conn(), project_id, status))


@app.post("/projects/{project_id}/conflicts/{conflict_id}/resolve")
def resolve_conflict(project_id: str, conflict_id: str, body: ConflictDecision):
    return _scoped(project_id, lambda: challenge.resolve(conn(), project_id, conflict_id, body.resolution, question=body.question, answer=body.answer,
                                                       llm=client_for(body.model) if body.model else None), write=True)


@app.post("/projects/{project_id}/conflicts/{conflict_id}/reopen")
def reopen_conflict(project_id: str, conflict_id: str):
    return _scoped(project_id, lambda: challenge.reopen(conn(), project_id, conflict_id), write=True)


@app.get("/projects/{project_id}/similar")
def similar(project_id: str):
    return _scoped(project_id, lambda: qa.similar_groups(conn(), project_id))


@app.post("/projects/{project_id}/similar/keep-one")
def keep_one(project_id: str, body: SimilarDecision):
    return _scoped(project_id, lambda: qa.keep_one(conn(), project_id, body.keep_id or "", body.sample_ids), write=True)


@app.post("/projects/{project_id}/similar/keep-apart")
def keep_apart(project_id: str, body: SimilarDecision):
    return _scoped(project_id, lambda: qa.keep_apart(conn(), project_id, body.sample_ids, undo=body.undo), write=True)


class ManyDecision(BaseModel):
    model_config = {"extra": "forbid"}

    sample_ids: list[str]
    decision: str


@app.post("/projects/{project_id}/samples/decide")
def decide_many(project_id: str, body: ManyDecision):
    return _scoped(project_id, lambda: qa.decide_many(conn(), project_id, body.sample_ids, body.decision), write=True)


@app.post("/projects/{project_id}/samples/{sample_id}/approve")
def approve(project_id: str, sample_id: str):
    return _scoped(project_id, lambda: qa.decide(conn(), sample_id, "approve"), kind="sample", entity_id=sample_id, write=True)


@app.post("/projects/{project_id}/samples/{sample_id}/reject")
def reject(project_id: str, sample_id: str):
    return _scoped(project_id, lambda: qa.decide(conn(), sample_id, "reject"), kind="sample", entity_id=sample_id, write=True)


@app.post("/projects/{project_id}/samples/{sample_id}/reset")
def reset(project_id: str, sample_id: str):
    return _scoped(project_id, lambda: qa.decide(conn(), sample_id, "reset"), kind="sample", entity_id=sample_id, write=True)


class CurationChecks(BaseModel):
    model_config = {"extra": "forbid"}
    input_hash: str
    checks: dict[str, bool]


class RewordIn(BaseModel):
    model: str
    sample_ids: list[str] = Field(min_length=1, max_length=2000)


@app.get("/projects/{project_id}/samples/repeated-answers")
def repeated_answers(project_id: str):
    return _scoped(project_id, lambda: kb.repeated_answers(qa.list_samples(conn(), project_id, status="approved")))


@app.post("/projects/{project_id}/samples/reword")
def reword_refusals(project_id: str, body: RewordIn):
    """The model names what each bare "I don't know" does not know. The pairs go back to review."""
    llm = client_for(body.model)

    def start():
        batch = db.new_id("rwd")  # known before the work ends, so Undo can name it
        entry = _begin(project_id, "reword", project_id, "Rewording answers", CURATE,
                       lambda c: kb.reword_refusals(c, llm, project_id, body.sample_ids, batch),
                       note=lambda done: f"{done['reworded']} answer(s) reworded. They are back in Curate to read.", again=start)
        return {**entry, "batch_id": batch}
    return _scoped(project_id, start, write=True)


@app.post("/projects/{project_id}/samples/reword/{batch_id}/undo")
def undo_reword(project_id: str, batch_id: str):
    return _scoped(project_id, lambda: kb.undo_reword(conn(), project_id, batch_id), write=True)


class DraftRationaleIn(BaseModel):
    model: str


@app.post("/projects/{project_id}/samples/{sample_id}/rationale/draft")
def draft_rationale(project_id: str, sample_id: str, body: DraftRationaleIn):
    from . import curation
    llm = client_for(body.model)
    return _scoped(project_id, lambda: curation.draft(conn(), qa.get_sample(conn(), sample_id), llm),
                   kind="sample", entity_id=sample_id, write=True)


class RationaleIn(BaseModel):
    model_config = {"extra": "forbid"}
    input_hash: str
    text: str
    approve: bool = False


@app.post("/projects/{project_id}/samples/{sample_id}/checks")
def confirm_checks(project_id: str, sample_id: str, body: CurationChecks):
    from . import curation
    return _scoped(project_id, lambda: curation.check(conn(), qa.get_sample(conn(), sample_id), body.input_hash, body.checks),
                   kind="sample", entity_id=sample_id, write=True)


@app.post("/projects/{project_id}/samples/{sample_id}/rationale")
def save_rationale(project_id: str, sample_id: str, body: RationaleIn):
    from . import curation
    return _scoped(project_id, lambda: curation.write_rationale(conn(), qa.get_sample(conn(), sample_id), body.input_hash, body.text, body.approve),
                   kind="sample", entity_id=sample_id, write=True)


@app.post("/projects/{project_id}/samples/{sample_id}/rationale/{rationale_id}/reset")
def reset_rationale(project_id: str, sample_id: str, rationale_id: str):
    from . import curation
    return _scoped(project_id, lambda: curation.reset_rationale(conn(), qa.get_sample(conn(), sample_id), rationale_id),
                   kind="sample", entity_id=sample_id, write=True)


class KindChange(BaseModel):
    model_config = {"extra": "forbid"}

    origin: str
    question: str | None = None
    answer: str | None = None
    quote: str = ""
    false_claim: str = ""
    theme_id: str | None = None


@app.post("/projects/{project_id}/samples/{sample_id}/kind")
def change_kind(project_id: str, sample_id: str, body: KindChange):
    values = body.model_dump()
    origin = values.pop("origin")
    return _scoped(project_id, lambda: kinds.change_kind(conn(), sample_id, origin, **values),
                   kind="sample", entity_id=sample_id, write=True)


@app.put("/projects/{project_id}/samples/{sample_id}")
def edit(project_id: str, sample_id: str, body: SampleEdit):
    return _scoped(project_id, lambda: qa.edit(conn(), sample_id, **body.model_dump(exclude_unset=True)),
                   kind="sample", entity_id=sample_id, write=True)


# --- Behaviors: cards a person writes, conversations written from scratch ---

class PatternIn(BaseModel):
    title: str
    intent: str
    tone: str
    guidelines: str
    description: str
    user_type: str = "others"
    style: str = "companion"
    about_identity: bool = False


class PatternStatusIn(BaseModel):
    status: str


class BatchIn(BaseModel):
    count: int = Field(default=5, ge=1, le=20)
    variation_type: str = "positive"
    model: str = DEFAULT_MODEL


@app.get("/projects/{project_id}/patterns")
def list_patterns(project_id: str):
    return _scoped(project_id, lambda: workshop.list_patterns(conn(), project_id))


@app.post("/projects/{project_id}/patterns")
def create_pattern(project_id: str, body: PatternIn):
    return _scoped(project_id, lambda: workshop.create_pattern(conn(), project_id=project_id, **body.model_dump()), write=True)


@app.get("/projects/{project_id}/patterns/{pattern_id}")
def get_pattern(project_id: str, pattern_id: str):
    return _scoped(project_id, lambda: workshop.get_pattern(conn(), pattern_id), kind="pattern", entity_id=pattern_id)


@app.post("/projects/{project_id}/patterns/{pattern_id}/status")
def set_pattern_status(project_id: str, pattern_id: str, body: PatternStatusIn):
    return _scoped(project_id, lambda: workshop.set_pattern_status(conn(), pattern_id, body.status),
                   kind="pattern", entity_id=pattern_id, write=True)


@app.post("/projects/{project_id}/patterns/{pattern_id}/batches")
def create_batch(project_id: str, pattern_id: str, body: BatchIn):
    llm = client_for(body.model)

    def work(c):
        batch = workshop.generate_batch(c, llm, pattern_id, count=body.count, variation_type=body.variation_type)
        if batch["status"] == "failed":
            raise RuntimeError(batch["error"])
        return batch

    def wrote(batch: dict) -> str:
        counts = batch["denominator"]
        return f"{counts['proposed']} of {counts['requested']} written, {counts['rejected']} discarded."

    def start():
        title = workshop.get_pattern(conn(), pattern_id)["title"]
        return _begin(project_id, "behavior", pattern_id, f"Writing conversations for {title}", CURATE, work, note=wrote)
    return _scoped(project_id, start, kind="pattern", entity_id=pattern_id, write=True)


@app.get("/projects/{project_id}/batches/{batch_id}")
def get_batch(project_id: str, batch_id: str):
    return _scoped(project_id, lambda: workshop.batch_summary(conn(), batch_id), kind="batch", entity_id=batch_id)


# --- The knowledge base: the same pairs seen as a graph ---

class ModelIn(BaseModel):
    model: str = DEFAULT_MODEL


class RefusalsIn(ModelIn):
    count: int = Field(default=kb.MAX_NEW, ge=1, le=kb.MAX_NEW)


class LicenseIn(BaseModel):
    license_basis: str


@app.get("/projects/{project_id}/kb/graph")
def kb_graph(project_id: str):
    return _scoped(project_id, lambda: kb.graph(conn(), project_id))


@app.post("/projects/{project_id}/themes/{theme_id}/connect")
def connect_theme(project_id: str, theme_id: str, body: ModelIn):
    llm = client_for(body.model)
    return _scoped(project_id, lambda: _begin(project_id, "connect", theme_id, "Connecting pairs", CURATE, lambda c: kb.connect(c, llm, theme_id), note=_wrote),
                   kind="theme", entity_id=theme_id, write=True)


@app.post("/projects/{project_id}/refusals")
def write_refusals(project_id: str, body: RefusalsIn):
    llm = client_for(body.model)
    return _scoped(project_id, lambda: _begin(project_id, "refusals", project_id, "Writing what is not known", CURATE,
                                              lambda c: kb.write_refusals(c, llm, project_id, body.count), note=_wrote), write=True)


@app.post("/projects/{project_id}/neighbours")
def write_neighbours(project_id: str, body: RefusalsIn):
    llm = client_for(body.model)
    return _scoped(project_id, lambda: _begin(project_id, "neighbours", project_id, "Writing neighbouring subjects", CURATE,
                                              lambda c: kb.write_neighbours(c, llm, project_id, body.count), note=_wrote), write=True)


@app.post("/projects/{project_id}/false-premises")
def write_false_premises(project_id: str, body: RefusalsIn):
    llm = client_for(body.model)

    def work(c):
        done = kinds.write_false_premises(c, llm, project_id, body.count)
        return {"kept": done["false"] + done["true"], "rejected": done["discarded"]}
    return _scoped(project_id, lambda: _begin(project_id, "premises", project_id, "Writing false premises", CURATE, work, note=_wrote), write=True)


@app.patch("/projects/{project_id}/sources/{source_id}")
def set_source_license(project_id: str, source_id: str, body: LicenseIn):
    return _scoped(project_id, lambda: kb.set_license(conn(), source_id, body.license_basis),
                   kind="source", entity_id=source_id, write=True)


# --- Export ---

class ExpandIn(BaseModel):
    field: str
    text: str = Field(max_length=expander.MAX_CHARS)
    model: str
    language: str = "en"
    context: str = Field(default="", max_length=6000)


@app.post("/expand")
def expand(body: ExpandIn):
    llm = client_for(body.model)
    return _errors(lambda: {"text": expander.expand(llm, body.field, body.text, body.language, body.context)})


class DatasetIn(BaseModel):
    profile: str = 'direct'
    confidence_levels: list[str] | None = None
    sample_ids: list[str] | None = None
    name: str = "dataset"
    theme_ids: list[str] | None = None  # none: every theme
    outputs: list[str] | None = None  # none: all of them


@app.get("/projects/{project_id}/datasets")
def list_datasets(project_id: str):
    return _scoped(project_id, lambda: datasets.list_datasets(conn(), project_id))


@app.post("/projects/{project_id}/datasets")
def export(project_id: str, body: DatasetIn):
    return _scoped(project_id, lambda: datasets.export_dataset(
        conn(), DATA_DIR / "datasets", body.name, project_id, body.theme_ids, body.outputs, profile=body.profile, confidence_levels=body.confidence_levels, sample_ids=body.sample_ids), write=True)


@app.get('/projects/{project_id}/training-variants')
def training_variants(project_id: str):
    from . import prepare
    return _scoped(project_id, lambda: prepare.summary(conn(), project_id))


class PrepareIn(BaseModel):
    model: str
    train_model: str | None = None
    prepare_count: str | None = None


@app.post('/projects/{project_id}/training-variants/prepare')
def prepare_training_variants(project_id: str, body: PrepareIn):
    from . import prepare
    llm = client_for(body.model)
    def start():
        return _begin(project_id, 'prepare_training', project_id, 'Preparing examples', {'view':'export'},
            lambda c: prepare.generate(c, project_id, llm, DATA_DIR, OLLAMA_URL, conn,
                train_model=body.train_model, prepare_count=body.prepare_count),
            note=lambda result: 'Examples are ready to review: {} kept, {} dropped.'.format(
                *(sum(c.get(k, 0) for c in (result or {}).get('counts', {}).values()) for k in ('kept', 'dropped'))), again=start)
    return _scoped(project_id, start, write=True)


@app.post('/projects/{project_id}/training-variants/{variant_id}/drop')
def drop_training_variant(project_id: str, variant_id: str):
    from . import prepare
    return _scoped(project_id, lambda: prepare.drop(conn(), project_id, variant_id), write=True)


@app.post('/projects/{project_id}/training-variants/{variant_id}/undo')
def undo_training_variant(project_id: str, variant_id: str):
    from . import prepare
    return _scoped(project_id, lambda: prepare.undo_drop(conn(), project_id, variant_id), write=True)


@app.get("/projects/{project_id}/datasets/{dataset_id}/download")
def download_dataset(project_id: str, dataset_id: str):
    name, data = _scoped(project_id, lambda: datasets.zip_export(conn(), dataset_id, DATA_DIR / "datasets"),
                         kind="dataset", entity_id=dataset_id)
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"'})


# --- Local training (small models, isolated ML worker) ---
class TrainIn(BaseModel):
    model_config = {'extra': 'forbid'}
    dataset_id: str | None = None
    model: str
    profile: str = 'direct'
    epochs: float = Field(default=3, gt=0, le=10)
    batch_size: int = Field(default=4, ge=1, le=8)
    learning_rate: float = Field(default=1e-5, gt=0, le=0.001)
    iters: int | None = Field(default=None, ge=2, le=10000)


class CompareIn(BaseModel):
    model_config = {'extra': 'forbid'}
    questions: list[str] | None = None
    model: str | None = None


class TryIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class CompareChoice(BaseModel):
    choice: str | None = None


class VersionPatch(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    in_use: bool | None = None


@app.get('/projects/{project_id}/train/models')
def training_models(project_id: str):
    from . import training
    return _scoped(project_id, training.models)


@app.get('/projects/{project_id}/train/resources')
def training_resources(project_id: str):
    from . import gpu
    return _scoped(project_id, gpu.status)


@app.post('/projects/{project_id}/train/preflight')
def training_preflight(project_id: str, body: TrainIn):
    from . import training
    return _scoped(project_id, lambda: training.preflight(conn(), DATA_DIR, project_id, body.model_dump()))


@app.post('/projects/{project_id}/train/runs')
def start_training(project_id: str, body: TrainIn):
    from . import training
    return _scoped(project_id, lambda: training.launch(conn(), DATA_DIR, project_id, body.model_dump(), OLLAMA_URL, conn), write=True)


@app.get('/projects/{project_id}/train/runs')
def training_runs(project_id: str):
    from . import training
    return _scoped(project_id, lambda: training.list_runs(conn(), project_id, DATA_DIR))


@app.get('/projects/{project_id}/train/changes')
def training_changes(project_id: str):
    from . import training
    return _scoped(project_id, lambda: training.changes(conn(), project_id))


@app.delete('/projects/{project_id}/train/runs')
def delete_training_versions(project_id: str, keep: str = ''):
    from . import training
    if keep != 'in_use': raise HTTPException(status_code=422, detail="Use keep=in_use.")
    return _scoped(project_id, lambda: training.delete_others(conn(), DATA_DIR, project_id), write=True)


@app.patch('/projects/{project_id}/train/runs/{run_id}')
def update_training_version(project_id: str, run_id: str, body: VersionPatch):
    from . import training
    return _scoped(project_id, lambda: training.update_version(conn(), project_id, run_id, **body.model_dump(exclude_unset=True)), write=True)


@app.delete('/projects/{project_id}/train/runs/{run_id}')
def delete_training_version(project_id: str, run_id: str):
    from . import training
    return _scoped(project_id, lambda: training.delete_version(conn(), DATA_DIR, project_id, run_id), write=True)


@app.post('/projects/{project_id}/train/runs/{run_id}/undo-delete')
def undo_delete_training_version(project_id: str, run_id: str):
    from . import training
    return _scoped(project_id, lambda: training.undo_delete(conn(), project_id, run_id), write=True)


@app.get('/projects/{project_id}/train/runs/{run_id}')
def training_run(project_id: str, run_id: str):
    from . import training
    return _scoped(project_id, lambda: training.get(conn(), project_id, run_id, DATA_DIR))


@app.get('/projects/{project_id}/train/runs/{run_id}/events')
def training_events(project_id: str, run_id: str, after: int = 0):
    from . import training
    return _scoped(project_id, lambda: [e for e in training.events(conn(), project_id, run_id, after) if e['type'] != 'answer'])


@app.post('/projects/{project_id}/train/runs/{run_id}/stop')
def stop_training(project_id: str, run_id: str):
    from . import training
    return _scoped(project_id, lambda: training.stop(conn(), project_id, run_id), write=True)


@app.post('/projects/{project_id}/train/runs/{run_id}/continue')
def continue_training(project_id: str, run_id: str):
    from . import training
    return _scoped(project_id, lambda: training.continue_run(conn(), DATA_DIR, project_id, run_id, OLLAMA_URL, conn), write=True)


@app.get('/projects/{project_id}/train/runs/{run_id}/download')
def download_training(project_id: str, run_id: str):
    from . import training
    content = _scoped(project_id, lambda: training.download(conn(), DATA_DIR, project_id, run_id))
    return Response(content, media_type='application/zip', headers={'Content-Disposition': f'attachment; filename="{run_id}-adapter.zip"'})


def _question_client(project_id: str, model: str | None):
    """Rewording uses the question model (never the model being trained, which Ollama does not run)."""
    chosen = model or projects.get(conn(), project_id).get('prepare_question_model')
    return client_for(chosen) if chosen else None


@app.post('/projects/{project_id}/train/runs/{run_id}/compare')
def compare_training(project_id: str, run_id: str, body: CompareIn):
    from . import training
    return _scoped(project_id, lambda: training.start_compare(conn(), DATA_DIR, project_id, run_id, body.model_dump(), OLLAMA_URL, conn,
                                                               llm=_question_client(project_id, body.model)), write=True)


@app.get('/projects/{project_id}/train/runs/{run_id}/comparison')
def training_comparison(project_id: str, run_id: str):
    from . import training
    return _scoped(project_id, lambda: training.comparison(conn(), project_id, run_id))


@app.post('/projects/{project_id}/train/runs/{run_id}/comparison/{item_id}/choice')
def training_choice(project_id: str, run_id: str, item_id: str, body: CompareChoice):
    from . import training
    return _scoped(project_id, lambda: training.choose(conn(), project_id, run_id, item_id, body.choice), write=True)


@app.post('/projects/{project_id}/train/runs/{run_id}/try')
def try_training(project_id: str, run_id: str, body: TryIn):
    from . import training
    return _scoped(project_id, lambda: training.start_compare(conn(), DATA_DIR, project_id, run_id, body.model_dump(), OLLAMA_URL, conn, try_only=True), write=True)



class RecallReview(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    approved: bool


@app.post('/projects/{project_id}/train/runs/{run_id}/recall/draft')
def draft_recall_questions(project_id: str, run_id: str):
    from . import training
    return _scoped(project_id, lambda: training.draft_recall(conn(), DATA_DIR, project_id, run_id, OLLAMA_URL, conn), write=True)


@app.post('/projects/{project_id}/train/runs/{run_id}/recall/{item_id}/review')
def review_recall_question(project_id: str, run_id: str, item_id: str, body: RecallReview):
    from . import training
    return _scoped(project_id, lambda: training.review_recall(conn(), project_id, run_id, item_id, body.question, body.approved), write=True)
