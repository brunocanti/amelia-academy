"""Sources -> chunks (spec 002). What is written from a source lives in qa.py.

Invariants enforced here:
- an upload declares purpose and licence basis; missing either fails before anything is derived;
- original bytes are stored under their SHA-256, never under the uploaded name;
- a chunk resolves to one exact source version and offset.
"""

import hashlib
import json
import mimetypes
import re
from pathlib import Path

from . import db, documents, projects, workshop

CHUNK_CHARS = documents.CHUNK_CHARS
UNREAD_FIGURE = {"not_attempted", "failed"}
LANGUAGE_NAME = projects.LANGUAGE_NAME


class SourceRejected(Exception):
    pass


Conflict = workshop.Conflict


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


_LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}
_HYPHENS = "-\u00ad\u2010\u2011"


def _quote_key(text: str) -> tuple[str, list[int]]:
    """Text as a quote is compared, and where each of its characters came from.

    PDF extraction leaves line-end hyphens and ligatures that a model does not copy. A hyphen between two
    letters is dropped on both sides, because `multi-\\nhop` and `multi-hop` must both match.
    """
    out: list[str] = []
    origin: list[int] = []
    i, size = 0, len(text)
    while i < size:
        char = text[i]
        if char.isspace():
            if out and out[-1] != " ":
                out.append(" ")
                origin.append(i)
        elif char in _HYPHENS:
            after = i + 1
            while after < size and text[after].isspace():
                after += 1
            if out and out[-1].isalnum() and after < size and text[after].isalnum():
                i = after
                continue
            if char != "\u00ad":
                out.append("-")
                origin.append(i)
        else:
            for piece in _LIGATURES.get(char, char):
                out.append(piece)
                origin.append(i)
        i += 1
    if out and out[-1] == " ":
        out.pop()
        origin.pop()
    return "".join(out), origin


MIN_QUOTE_PART = 12   # shorter pieces around an ellipsis prove nothing
MAX_LOOSE_SPAN = 900  # an ellipsis may skip a little of a passage, not join two distant ideas


def find_quote(quote: str, text: str) -> str | None:
    """The span of `text` that `quote` copies, exactly as the source has it, or None."""
    wanted, _ = _quote_key(quote)
    if not wanted:
        return None
    key, origin = _quote_key(text)
    at = key.find(wanted)
    if at >= 0:
        return text[origin[at]:origin[at + len(wanted) - 1] + 1]
    return _find_loosely(quote, key, origin, text)


def _loose(key: str, origin: list[int]) -> tuple[str, list[int]]:
    """Without spaces or capitals: PDF extraction glues math to words, and a model lowers the first letter of a span."""
    pairs = [(c.lower() if len(c.lower()) == 1 else c, at) for c, at in zip(key, origin) if c != " "]
    return "".join(c for c, _ in pairs), [at for _, at in pairs]


def _find_loosely(quote: str, key: str, origin: list[int], text: str) -> str | None:
    """The span a quote copies with only its spaces or capitals changed, or with its middle skipped by an ellipsis.

    What comes back is always the source's own span, from the first part to the last, so the citation stays verifiable.
    """
    loose_key, loose_origin = _loose(key, origin)
    at, end = 0, None
    begin = None
    for part in re.split(r"\.\.\.|\u2026", quote):
        wanted = _loose(*_quote_key(part))[0].strip(".,;: ")
        if len(wanted) < MIN_QUOTE_PART:
            continue
        found = loose_key.find(wanted, at)
        if found < 0:
            return None
        if begin is None:
            begin = found
        at = end = found + len(wanted)
    if begin is None:
        return None
    span = text[loose_origin[begin]:loose_origin[end - 1] + 1]
    return span if len(span) <= MAX_LOOSE_SPAN else None


def quote_holds(conn, chunk_id: str, quote: str) -> bool:
    """A long paragraph is cut into passages, and a quote may run over the cut into the next one."""
    chunk = db.row(conn, "SELECT source_id, idx, ingestion_id, text FROM source_chunks WHERE id = ?", (chunk_id,))
    if not chunk:
        return False
    following = db.row(conn, "SELECT text FROM source_chunks WHERE source_id = ? AND idx = ? AND ingestion_id IS ?",
                       (chunk["source_id"], chunk["idx"] + 1, chunk["ingestion_id"]))
    return find_quote(quote, join_passages(chunk["text"], following["text"] if following else "")) is not None


def join_passages(first: str, second: str) -> str:
    return f"{first}\n{second}" if second else first


_MD_HEADING = re.compile(r"^ {0,3}#{1,6}[ \t]+(.+?)[ \t#]*$", re.M)
_MD_FENCE = re.compile(r"^ {0,3}(?:```|~~~).*?^ {0,3}(?:```|~~~)[ \t]*$", re.M | re.S)


def chunk_markdown(text: str) -> list[dict]:
    """Passages that never cross a `#` heading, each knowing the heading it sits under."""
    fences = [m.span() for m in _MD_FENCE.finditer(text)]
    heads = [m for m in _MD_HEADING.finditer(text) if not any(a <= m.start() < b for a, b in fences)]
    cuts = [(0, None)] + [(m.start(), m.group(1).strip()) for m in heads]
    chunks = []
    for at, (begin, title) in enumerate(cuts):
        end = cuts[at + 1][0] if at + 1 < len(cuts) else len(text)
        for chunk in chunk_text(text[begin:end]):
            chunk.update(index=len(chunks), start=chunk["start"] + begin, end=chunk["end"] + begin, section=title)
            chunks.append(chunk)
    return chunks


def chunk_text(text: str) -> list[dict]:
    """Pack paragraphs into bounded chunks while retaining exact source offsets."""
    spans, buf_start, buf_end = [], None, None

    def flush():
        nonlocal buf_start, buf_end
        if buf_start is not None:
            length = buf_end - buf_start
            if length <= CHUNK_CHARS:
                spans.append((buf_start, buf_end))
            else:
                spans.extend((buf_start + s, buf_start + e)
                             for s, e in documents.split_spans(text[buf_start:buf_end], CHUNK_CHARS))
        buf_start = buf_end = None

    for match in re.finditer(r"[^\n]+(?:\n(?!\s*\n)[^\n]+)*", text):
        para_start, para_end = match.start(), match.end()
        if para_end - para_start > CHUNK_CHARS:
            flush()
            spans.extend((para_start + s, para_start + e)
                         for s, e in documents.split_spans(text[para_start:para_end], CHUNK_CHARS))
        elif buf_start is None:
            buf_start, buf_end = para_start, para_end
        elif para_end - buf_start <= CHUNK_CHARS:
            buf_end = para_end
        else:
            flush()
            buf_start, buf_end = para_start, para_end
    flush()
    return [
        {"index": i, "start": start, "end": end, "text": text[start:end],
         "hash": hashlib.sha256(text[start:end].encode("utf-8")).hexdigest()}
        for i, (start, end) in enumerate(spans)
    ]


def ingest(conn, out_dir: Path, *, project_id: str, name: str, content: str, purpose: str,
           license_basis: str, vision=None) -> dict:
    """Compatibility path for direct text callers; file uploads use ingest_bytes."""
    if not isinstance(content, str):
        raise SourceRejected("text content must be a string")
    return ingest_bytes(conn, out_dir, name=name, data=content.encode("utf-8"),
                        purpose=purpose, license_basis=license_basis, project_id=project_id, vision=vision)


def ingest_bytes(conn, out_dir: Path, *, project_id: str, name: str, data: bytes, purpose: str,
                 license_basis: str, vision=None) -> dict:
    project = projects.get(conn, project_id)
    if not purpose.strip() or not license_basis.strip():
        raise SourceRejected("purpose and licence basis are required before any derivation")
    name = _safe_source_name(name)
    try:
        _, mime, extension = documents.detect_format(name, data)
    except documents.DocumentRejected as exc:
        raise SourceRejected(str(exc)) from exc
    digest = hashlib.sha256(data).hexdigest()
    existing = db.row(conn, "SELECT id FROM sources WHERE project_id = ? AND sha256 = ?", (project_id, digest))
    if existing:
        return get_source(conn, existing["id"])

    out_dir.mkdir(parents=True, exist_ok=True)
    storage_path = f"{digest}{extension}"
    _write_content_addressed(out_dir, storage_path, data, digest)
    sid = db.new_id("src")
    conn.execute(
        "INSERT INTO sources (id, project, project_id, name, mime, sha256, size, purpose, license_basis, status, created_at, storage_path)"
        " VALUES (?,?,?,?,?,?,?,?,?, 'processing', ?, ?)",
        (sid, project["slug"], project_id, name, mime, digest, len(data), purpose.strip(), license_basis.strip(), db.now(), storage_path),
    )
    conn.commit()
    return _run_ingestion(conn, out_dir, sid, name, data, vision)


def _safe_source_name(name: str) -> str:
    return Path((name or "upload").replace("\\", "/")).name.strip()[:240] or "upload"


def _write_content_addressed(root: Path, relative: str, data: bytes, digest: str) -> None:
    root = root.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise SourceRejected("unsafe storage path")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise SourceRejected("content-addressed storage integrity check failed")
    else:
        path.write_bytes(data)


def _asset_extension(mime: str) -> str:
    aliases = {"image/jpg": ".jpg", "image/jpeg": ".jpg", "image/tif": ".tiff", "image/tiff": ".tiff"}
    return aliases.get(mime.lower()) or mimetypes.guess_extension(mime.split(";")[0]) or ".bin"


def _run_ingestion(conn, out_dir: Path, source_id: str, name: str, data: bytes, vision=None) -> dict:
    ingestion_id = db.new_id("ing")
    conn.execute(
        "INSERT INTO source_ingestions (id, source_id, extractor, extractor_version, status, warnings, created_at)"
        " VALUES (?,?, 'amelia-local-extractors', ?, 'running', '[]', ?)",
        (ingestion_id, source_id, documents.EXTRACTOR_VERSION, db.now()),
    )
    conn.execute("UPDATE sources SET status = 'processing' WHERE id = ?", (source_id,))
    conn.commit()

    try:
        extracted = documents.extract_document(name, data, vision)
        if extracted["format"] in {"text", "markdown"}:
            source_text = data.decode("utf-8-sig")
            chunks = chunk_markdown(source_text) if extracted["format"] == "markdown" else chunk_text(source_text)
            for chunk in chunks:
                locator = {"type": "text_file", "path": "/", "char_start": chunk["start"], "char_end": chunk["end"], "offset_basis": "source_text"}
                if chunk.get("section"):
                    locator["section"] = chunk["section"]
                chunk.update({"kind": "text", "asset_ref": None, "offset_basis": "source_text", "locator": locator})
        else:
            chunks = documents.chunk_elements(extracted["elements"])
            for chunk in chunks:
                chunk["offset_basis"] = "element_text"

        asset_ids = {}
        assets_root = out_dir / "assets"
        for asset in extracted["assets"]:
            asset_path = f"assets/{asset['sha256']}{_asset_extension(asset['mime'])}"
            _write_content_addressed(out_dir, asset_path, asset["bytes"], asset["sha256"])
            asset_id = db.new_id("ast")
            asset_ids[asset["asset_ref"]] = asset_id
            conn.execute(
                "INSERT INTO source_assets (id, source_id, ingestion_id, idx, kind, mime, sha256, size, storage_path, locator_json, ocr_status, ocr_text, figure_reading, ocr_error, ocr_model, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (asset_id, source_id, ingestion_id, asset["asset_ref"], asset["kind"], asset["mime"],
                 asset["sha256"], asset["size"], asset_path, json.dumps(asset["locator"], ensure_ascii=False),
                 asset["ocr_status"], asset["ocr_text"], asset.get("figure_reading") or "", asset.get("ocr_error") or "", asset.get("ocr_model"), db.now()),
            )

        for chunk in chunks:
            asset_id = asset_ids.get(chunk.get("asset_ref"))
            conn.execute(
                "INSERT INTO source_chunks (id, source_id, idx, start, end_pos, text, hash, ingestion_id, kind, locator_json, offset_basis, asset_id)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (db.new_id("chk"), source_id, chunk["index"], chunk["start"], chunk["end"], chunk["text"],
                 chunk["hash"], ingestion_id, chunk.get("kind", "text"),
                 json.dumps(chunk.get("locator", {}), ensure_ascii=False), chunk.get("offset_basis", "element_text"), asset_id),
            )

        warnings = extracted["warnings"]
        if chunks and all(documents.is_only_a_note(w) for w in warnings):
            source_status, ingestion_status = "available", "succeeded"
        elif chunks or extracted["assets"]:
            source_status, ingestion_status = "partial", "partial"
        else:
            source_status, ingestion_status = "failed", "failed"
        error = None if chunks or extracted["assets"] else "no readable text or media extracted"
        conn.execute("UPDATE source_ingestions SET status = ?, error = ?, warnings = ? WHERE id = ?",
                     (ingestion_status, error, json.dumps(warnings, ensure_ascii=False), ingestion_id))
        conn.execute("UPDATE sources SET status = ? WHERE id = ?", (source_status, source_id))
        conn.commit()
    except Exception as exc:
        conn.rollback()
        error = f"{type(exc).__name__}: {exc}"
        conn.execute("UPDATE source_ingestions SET status = 'failed', error = ? WHERE id = ?", (error, ingestion_id))
        conn.execute("UPDATE sources SET status = 'failed' WHERE id = ?", (source_id,))
        conn.commit()
    return get_source(conn, source_id)


def reprocess_source(conn, out_dir: Path, source_id: str, vision=None) -> dict:
    source = db.row(conn, "SELECT * FROM sources WHERE id = ?", (source_id,))
    if not source:
        raise workshop.NotFound(f"source {source_id} not found")
    if not source.get("storage_path"):
        raise SourceRejected("legacy source has no stored original to reprocess")
    root = out_dir.resolve()
    original = (root / source["storage_path"]).resolve()
    if not original.is_relative_to(root) or not original.is_file():
        raise SourceRejected("stored source file is missing or outside source storage")
    return _run_ingestion(conn, out_dir, source_id, source["name"], original.read_bytes(), vision)


def use_current_extractor(conn, out_dir: Path, source_id: str) -> None:
    """A file read by an older extractor has no sections or roles: reading it again must extract it first.
    Pairs already written keep the passages they cite."""
    source = db.row(conn, "SELECT storage_path FROM sources WHERE id = ?", (source_id,))
    if not source:
        raise workshop.NotFound(f"source {source_id} not found")
    latest = db.row(conn, "SELECT id, extractor_version FROM source_ingestions WHERE source_id = ? ORDER BY created_at DESC, id DESC LIMIT 1", (source_id,))
    current = latest and latest["extractor_version"] == documents.EXTRACTOR_VERSION
    running = conn.execute("SELECT 1 FROM extractions WHERE source_id = ? AND status = 'running'", (source_id,)).fetchone()
    if current or running or not source["storage_path"]:
        return
    ingestion = reprocess_source(conn, out_dir, source_id)["latest_ingestion"]
    if ingestion["status"] == "failed":
        raise SourceRejected(ingestion["error"] or "the file could not be read")
    if latest:
        _keep_figure_readings(conn, source_id, latest["id"], ingestion)


def _store_figure_chunks(conn, source_id: str, ingestion_id: str, asset: dict, text: str, reading: str, model, next_idx: int) -> int:
    locator = json.loads(asset["locator_json"] or "{}")
    for kind, body, extra in (("ocr_text", text, {"ocr": True}), ("figure_reading", reading, {"model_reading": True})):
        if not body.strip():
            continue
        conn.execute(
            "INSERT INTO source_chunks (id, source_id, idx, start, end_pos, text, hash, ingestion_id, kind, locator_json, offset_basis, asset_id)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (db.new_id("chk"), source_id, next_idx, 0, len(body), body,
             hashlib.sha256(body.encode("utf-8")).hexdigest(), ingestion_id, kind,
             json.dumps({**locator, **extra, "ocr_model": model}, ensure_ascii=False), "element_text", asset["id"]))
        next_idx += 1
    return next_idx


def _keep_figure_readings(conn, source_id: str, previous_id: str, ingestion: dict) -> None:
    """Extracting again calls no model, so what a vision model already read of the same image carries over."""
    new_id = ingestion["id"]
    read = {a["sha256"]: a for a in db.rows(conn, "SELECT * FROM source_assets WHERE ingestion_id = ? AND ocr_model IS NOT NULL", (previous_id,))}
    next_idx = conn.execute("SELECT COALESCE(MAX(idx), -1) + 1 FROM source_chunks WHERE ingestion_id = ?", (new_id,)).fetchone()[0]
    assets = db.rows(conn, "SELECT * FROM source_assets WHERE ingestion_id = ? ORDER BY idx", (new_id,))
    unread = 0
    for asset in assets:
        old = read.get(asset["sha256"])
        if not old:
            unread += asset["ocr_status"] == "not_attempted"
            continue
        conn.execute("UPDATE source_assets SET ocr_text = ?, figure_reading = ?, ocr_status = ?, ocr_error = ?, ocr_model = ? WHERE id = ?",
                     (old["ocr_text"], old["figure_reading"], old["ocr_status"], old["ocr_error"], old["ocr_model"], asset["id"]))
        next_idx = _store_figure_chunks(conn, source_id, new_id, asset, old["ocr_text"] or "", old["figure_reading"] or "", old["ocr_model"], next_idx)
    _settle_image_warning(conn, source_id, new_id, ingestion["warnings"], ingestion["status"], unread)
    conn.commit()


def _settle_image_warning(conn, source_id: str, ingestion_id: str, warnings: list, status: str, unread: int) -> None:
    warnings = [w for w in warnings if "stored but not read" not in w]
    if unread:
        warnings.append(f"{unread} image(s) stored but not read: no vision model configured")
    conn.execute("UPDATE source_ingestions SET warnings = ? WHERE id = ?", (json.dumps(warnings, ensure_ascii=False), ingestion_id))
    if all(documents.is_only_a_note(w) for w in warnings) and status == "partial":
        conn.execute("UPDATE source_ingestions SET status = 'succeeded' WHERE id = ?", (ingestion_id,))
        conn.execute("UPDATE sources SET status = 'available' WHERE id = ?", (source_id,))


def unread_figures(source: dict) -> list[dict]:
    return [a for a in source["assets"] if a["ocr_status"] in UNREAD_FIGURE]


def read_figures(conn, out_dir: Path, source_id: str, vision, on_progress=None) -> dict:
    """Ask the vision model what each figure not read yet shows. Document text stays.
    A figure already read keeps its reading, because pairs may cite it. Returns the counts."""
    source = get_source(conn, source_id)
    if not source.get("latest_ingestion"):
        raise SourceRejected("this source has no stored ingestion to attach a figure reading to")
    ingestion_id = source["latest_ingestion"]["id"]
    reader = documents._ImageReader(vision)
    root = out_dir.resolve()
    pending = {a["id"] for a in unread_figures(source)}
    stored = [a for a in db.rows(conn, "SELECT * FROM source_assets WHERE source_id = ? AND ingestion_id = ? ORDER BY idx",
                                 (source_id, ingestion_id)) if a["id"] in pending]
    next_idx = conn.execute("SELECT COALESCE(MAX(idx), -1) + 1 FROM source_chunks WHERE source_id = ? AND ingestion_id = ?",
                            (source_id, ingestion_id)).fetchone()[0]
    counts = {"read": 0, "total": len(stored), "failed": 0, "skipped": 0}
    if on_progress:
        on_progress(dict(counts))
    for asset in stored:
        path = (root / asset["storage_path"]).resolve()
        if path.is_relative_to(root) and path.is_file():
            text, reading, status, why = reader.read(path.read_bytes())
        else:
            text, reading, status, why = "", "", "failed", "the stored image file is missing"
        model = reader.model if status in {"completed", "empty", "failed"} else None
        conn.execute("UPDATE source_assets SET ocr_text = ?, figure_reading = ?, ocr_status = ?, ocr_error = ?, ocr_model = ? WHERE id = ?",
                     (text, reading, status, why or "", model, asset["id"]))
        next_idx = _store_figure_chunks(conn, source_id, ingestion_id, asset, text, reading, model, next_idx)
        counts["read"] += 1
        counts["failed"] += status == "failed"
        counts["skipped"] += status == "skipped"
        if status == "failed":
            counts["error"] = why
        conn.commit()
        if on_progress:
            on_progress(dict(counts))
    fresh = get_source(conn, source_id)
    _settle_image_warning(conn, source_id, ingestion_id, fresh["latest_ingestion"]["warnings"], fresh["latest_ingestion"]["status"],
                          sum(a["ocr_status"] == "not_attempted" for a in fresh["assets"]))
    conn.commit()
    return counts


def get_asset(conn, source_id: str, asset_id: str) -> dict:
    asset = db.row(conn, "SELECT * FROM source_assets WHERE id = ? AND source_id = ?", (asset_id, source_id))
    if not asset:
        raise workshop.NotFound(f"source asset {asset_id} not found")
    asset["locator"] = json.loads(asset.pop("locator_json") or "{}")
    return asset


def get_source(conn, source_id: str) -> dict:
    s = db.row(conn, "SELECT * FROM sources WHERE id = ?", (source_id,))
    if not s:
        raise workshop.NotFound(f"source {source_id} not found")
    latest = db.row(conn, "SELECT * FROM source_ingestions WHERE source_id = ? ORDER BY created_at DESC, id DESC LIMIT 1", (source_id,))
    if latest:
        latest["warnings"] = db.parse_json_field(latest["warnings"])
        ingestion_id = latest["id"]
        chunks = db.rows(conn, 'SELECT id, idx AS "index", start, end_pos, text, hash, kind, locator_json, offset_basis, asset_id FROM source_chunks WHERE source_id = ? AND ingestion_id = ? ORDER BY idx', (source_id, ingestion_id))
        assets = db.rows(conn, "SELECT id, idx, kind, mime, sha256, size, locator_json, ocr_status, ocr_text, figure_reading, ocr_error, ocr_model FROM source_assets WHERE source_id = ? AND ingestion_id = ? ORDER BY idx", (source_id, ingestion_id))
    else:
        latest = None
        chunks = db.rows(conn, 'SELECT id, idx AS "index", start, end_pos, text, hash, kind, locator_json, offset_basis, asset_id FROM source_chunks WHERE source_id = ? AND ingestion_id IS NULL ORDER BY idx', (source_id,))
        assets = []
    for chunk in chunks:
        chunk["locator"] = json.loads(chunk.pop("locator_json") or "{}")
    preview_mimes = {"image/png", "image/jpeg", "image/jpg", "image/tiff", "image/tif", "image/bmp", "image/gif", "image/webp"}
    for asset in assets:
        asset["locator"] = json.loads(asset.pop("locator_json") or "{}")
        asset["preview_available"] = asset["mime"].lower() in preview_mimes
        if asset["preview_available"]:
            asset["url"] = f"/api/projects/{s['project_id']}/sources/{source_id}/assets/{asset['id']}"
    s["chunks"] = chunks
    s["assets"] = assets
    s["latest_ingestion"] = latest
    s["extractions"] = db.rows(conn, "SELECT * FROM extractions WHERE source_id = ? ORDER BY created_at DESC", (source_id,))
    for extraction in s["extractions"]:
        extraction["rejected"] = db.parse_json_field(extraction["rejected"])
    s.pop("storage_path", None)
    return s


def _totals(source: dict) -> dict:
    """What was extracted from the file, whether or not a run has read it."""
    pages = {c["locator"].get("page") for c in source["chunks"]} - {None}
    text = [c for c in source["chunks"] if c["kind"] not in {"ocr_text", "figure_reading"}]
    return {"pages": len(pages), "passages": len(text), "chars": sum(len(c["text"]) for c in text),
            "figures": len(source["assets"]), "figures_read": sum(a["ocr_status"] in {"completed", "empty"} for a in source["assets"])}


def license_suggestion(conn, source: dict, out_dir: Path | None = None) -> dict | None:
    """Suggest a CC BY basis only when the PDF itself states it in metadata or extracted text."""
    if source.get("license_basis") != "unspecified" or source.get("mime") != "application/pdf":
        return None
    texts = " ".join(row["text"] for row in db.rows(conn,
        "SELECT text FROM source_chunks WHERE source_id = ? ORDER BY idx", (source["id"],)))
    metadata = ""
    stored = db.row(conn, "SELECT storage_path FROM sources WHERE id = ?", (source["id"],)) if out_dir is not None else None
    storage_path = source.get("storage_path") or (stored or {}).get("storage_path")
    if out_dir is not None and storage_path:
        try:
            from .pdf import open_pdf
            with open_pdf((out_dir / storage_path).read_bytes()) as pdf:
                metadata = " ".join(str(v) for v in pdf.metadata.values())
        except Exception:
            pass
    evidence = _norm(f"{metadata} {texts}")
    match = re.search(r"(?:creativecommons\.org/licenses/by/4\.0|CC\s*BY(?:\s*4\.0)?|Creative Commons Attribution(?:\s+License)?(?:\s+4\.0)?|open-access article distributed under the terms of the Creative Commons Attribution License)", evidence, re.I)
    if not match and re.search(r"\bPLOS\s+ONE\b", evidence, re.I) and re.search(r"\bdoi\s*:\s*10\.1371/journal\.pone\.", evidence, re.I):
        return {"license_basis": "open-license", "label": "Open license · CC BY 4.0", "evidence": "PLOS ONE open-access article"}
    if match:
        return {"license_basis": "open-license", "label": "Open license · CC BY 4.0", "evidence": match.group(0)}
    return None


def list_sources(conn, project_id: str, out_dir: Path | None = None) -> list[dict]:
    rows = db.rows(conn, "SELECT id FROM sources WHERE project_id = ? ORDER BY created_at DESC", (project_id,))
    result = []
    for row in rows:
        source = get_source(conn, row["id"])
        result.append({key: source.get(key) for key in (
            "id", "name", "mime", "sha256", "size", "purpose", "license_basis", "status", "created_at"
        )} | {"chunk_count": len(source["chunks"]), "asset_count": len(source["assets"]), "totals": _totals(source),
             "license_suggestion": license_suggestion(conn, source, out_dir),
             "assets": [{key: asset.get(key) for key in (
                 "id", "kind", "locator", "ocr_status", "ocr_text", "figure_reading", "ocr_error", "ocr_model", "preview_available", "url",
             )} for asset in source["assets"]],
             "latest_ingestion": source["latest_ingestion"], "run": extraction_progress(conn, row["id"]),
             "pairs": db.row(conn, "SELECT COUNT(*) AS n FROM qa_samples WHERE source_id = ? AND status != 'rejected'", (row["id"],))["n"],
             "rejected_pairs": db.row(conn, "SELECT COUNT(*) AS n FROM qa_samples WHERE source_id = ? AND status = 'rejected'", (row["id"],))["n"]})
    return result


def can_continue(status: str, read: int | None, total: int | None) -> bool:
    """A stopped reading can go on. So can one that failed with sections left; one that read everything has nothing to go on with."""
    return status == "stopped" or (status == "failed" and (read or 0) < (total or 0))


def extraction_progress(conn, source_id: str) -> dict | None:
    """Latest question run for a source, light enough to poll while it is still writing."""
    e = db.row(
        conn,
        "SELECT id, kind, model, status, error, rejected, reading, passages_read, passages_total, created_at, duration_seconds"
        " FROM extractions WHERE source_id = ? AND kind = 'qa' ORDER BY created_at DESC, id DESC LIMIT 1",
        (source_id,),
    )
    if not e:
        return None
    rejected = db.parse_json_field(e["rejected"])
    e["rejected"] = len(rejected)
    e["reading"] = json.loads(e["reading"] or "{}")
    e["reasons"] = [item["reason"] for item in rejected]
    e["can_continue"] = can_continue(e["status"], e["passages_read"], e["passages_total"])
    e["duration_minutes"] = round((e["duration_seconds"] or 0) / 60, 1)
    e["kept"] = db.row(conn, "SELECT COUNT(*) AS n FROM qa_samples WHERE extraction_id = ? AND origin = 'file'", (e["id"],))["n"]
    return e


def extraction_summary(conn, eid: str) -> dict:
    e = db.row(conn, "SELECT * FROM extractions WHERE id = ?", (eid,))
    if not e:
        raise workshop.NotFound(f"extraction {eid} not found")
    e["rejected"] = db.parse_json_field(e["rejected"])
    e["reading"] = json.loads(e["reading"] or "{}")
    e["kept"] = db.row(conn, "SELECT COUNT(*) AS n FROM qa_samples WHERE extraction_id = ? AND origin = 'file'", (eid,))["n"]
    return e
