"""Local source-file extraction with stable page/element references and media assets.

Supported inputs: txt, md, html, json/jsonl, csv/tsv, PDF, DOCX, PPTX,
XLSX, and common raster images. Text inside images is read by a local vision model
supplied by the caller: the model the person chose. Bytes leave this computer only when that model is an online tool.
That text is a model transcription, stored with the model name, never the original text.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import mimetypes
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path

MAX_BYTES = 50 * 1024 * 1024
MAX_PAGES = 500
MAX_ELEMENTS = 20_000
MAX_ASSETS = 500
MAX_ASSET_BYTES = 200 * 1024 * 1024
MAX_ARCHIVE_UNPACKED = 250 * 1024 * 1024
MAX_ARCHIVE_RATIO = 200
MAX_IMAGE_PIXELS = 50_000_000
MAX_OCR_IMAGES = 40
MIN_OCR_SIDE = 48
MIN_FIGURE_POINTS = 36  # half an inch on the page. Icons, logos and masks are drawn smaller; a figure someone is meant to read is not.
DECORATION_NOTE = "left out as decoration"
JOINED_NOTE = "put back together"
MIN_JOINED_POINTS = 72  # a cluster smaller than an inch is a row of icons, not a figure
FIGURE_GAP_POINTS = 24
FIGURE_LABEL_CHARS = 80
FIGURE_DPI = 200
FIGURE_CAPTION = re.compile(r"\s*(fig(ure|\.)?|tab(le|\.)?)\s*\d", re.IGNORECASE)
CHUNK_CHARS = 700

TEXT_EXTS = {".txt", ".md", ".html", ".htm", ".csv", ".tsv", ".json", ".jsonl"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif"}
SUPPORTED_EXTENSIONS = TEXT_EXTS | IMAGE_EXTS | {".pdf", ".docx", ".pptx", ".xlsx"}


class DocumentRejected(ValueError):
    """The upload is invalid, unsafe, or not a supported document."""


def _safe_name(name: str) -> str:
    base = Path((name or "upload").replace("\\", "/")).name.strip()
    return base[:240] or "upload"


def _zip_format(data: bytes) -> str | None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
            if "[Content_Types].xml" not in names:
                return None
            if "word/document.xml" in names:
                return "docx"
            if "ppt/presentation.xml" in names:
                return "pptx"
            if "xl/workbook.xml" in names:
                return "xlsx"
            return None
    except (zipfile.BadZipFile, OSError):
        return None


def detect_format(name: str, data: bytes) -> tuple[str, str, str]:
    """Validate the byte signature and return (format, mime, extension)."""
    ext = Path(_safe_name(name)).suffix.lower()
    if not data:
        raise DocumentRejected("empty file")
    if len(data) > MAX_BYTES:
        raise DocumentRejected(f"file too large; limit is {MAX_BYTES // (1024 * 1024)} MB")

    if data.startswith(b"%PDF-"):
        return "pdf", "application/pdf", ".pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image", "image/png", ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image", "image/jpeg", ".jpg"
    if data[:4] in (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"):
        return "image", "image/tiff", ".tiff"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image", "image/gif", ".gif"
    if data.startswith(b"BM"):
        return "image", "image/bmp", ".bmp"

    archive_format = _zip_format(data)
    if archive_format:
        mime_ext = {
            "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
            "pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"),
            "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
        }
        mime, detected_ext = mime_ext[archive_format]
        _validate_archive(data)
        return archive_format, mime, detected_ext

    if data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        raise DocumentRejected("legacy .doc/.ppt/.xls files are not supported yet; save as DOCX/PPTX/XLSX")

    if ext not in SUPPORTED_EXTENSIONS:
        raise DocumentRejected(f"unsupported file type {ext or '(none)'}; supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
    if ext in IMAGE_EXTS:
        raise DocumentRejected("image signature does not match the selected image file type")
    if ext in {".pdf", ".docx", ".pptx", ".xlsx"}:
        raise DocumentRejected(f"file extension {ext} does not match its contents")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DocumentRejected("text inputs must be UTF-8 encoded") from exc
    format_by_ext = {
        ".txt": ("text", "text/plain"), ".md": ("markdown", "text/markdown"),
        ".html": ("html", "text/html"), ".htm": ("html", "text/html"),
        ".csv": ("csv", "text/csv"), ".tsv": ("tsv", "text/tab-separated-values"),
        ".json": ("json", "application/json"), ".jsonl": ("jsonl", "application/x-ndjson"),
    }
    fmt, mime = format_by_ext[ext]
    if not text.strip():
        raise DocumentRejected("empty text file")
    return fmt, mime, ext


def _validate_archive(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > 10_000:
                raise DocumentRejected("Office archive contains too many entries")
            unpacked = sum(info.file_size for info in infos)
            if unpacked > MAX_ARCHIVE_UNPACKED:
                raise DocumentRejected("Office archive expands beyond the safety limit")
            for info in infos:
                if info.file_size > 50 * 1024 * 1024:
                    raise DocumentRejected("Office archive contains an oversized part")
                if info.compress_size and info.file_size / info.compress_size > MAX_ARCHIVE_RATIO:
                    raise DocumentRejected("Office archive compression ratio exceeds the safety limit")
    except zipfile.BadZipFile as exc:
        raise DocumentRejected("invalid Office Open XML archive") from exc


class _ImageReader:
    """Reads text from images with the vision model the caller supplies.

    `vision` is any object with `model` and either `read_figure(png) -> {visible_text, reading}`
    or `read_image(png) -> str`. A failure is recorded on the asset and never retried with another model.
    """

    def __init__(self, vision):
        self.vision = vision
        self.model = getattr(vision, "model", None)
        self.calls = 0

    def read(self, image_bytes: bytes) -> tuple[str, str, str, str | None]:
        if self.vision is None:
            return "", "", "not_attempted", None
        if self.calls >= MAX_OCR_IMAGES:
            return "", "", "skipped", f"figure reading limit reached ({MAX_OCR_IMAGES} images per document)"
        png, error = safe_png(image_bytes)
        if error:
            return "", "", "skipped", error
        from PIL import Image
        with Image.open(io.BytesIO(png)) as probe:
            if min(probe.size) < MIN_OCR_SIDE:
                return "", "", "skipped", f"image too small to read ({probe.size[0]}x{probe.size[1]})"
        self.calls += 1
        try:
            if hasattr(self.vision, "read_figure"):
                parsed = self.vision.read_figure(png) or {}
                text = str(parsed.get("visible_text") or "").strip()
                reading = str(parsed.get("reading") or "").strip()
            else:
                text = self.vision.read_image(png).strip()
                reading = ""
        except Exception as exc:
            return "", "", "failed", f"figure reading failed: {exc}"
        return text, reading, ("completed" if text or reading else "empty"), None


class _VisibleHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip_depth = 0
        self.images = []
        self.block_count = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1
        if self.skip_depth:
            return
        if tag in {"p", "div", "li", "h1", "h2", "h3", "h4", "tr", "section", "article", "br"}:
            self.parts.append("\n")
            self.block_count += 1
        if tag == "img" and attrs.get("alt", "").strip():
            self.images.append({"text": attrs["alt"].strip(), "locator": {"type": "html_image_alt", "index": len(self.images), "src": attrs.get("src", "")}})

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1
        elif not self.skip_depth and tag in {"p", "div", "li", "h1", "h2", "h3", "h4", "tr", "section", "article"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip_depth and data.strip():
            self.parts.append(data)


def split_spans(text: str, max_chars: int = CHUNK_CHARS) -> list[tuple[int, int]]:
    spans = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            boundary = max(text.rfind("\n", start + max_chars // 2, end), text.rfind(" ", start + max_chars // 2, end))
            if boundary > start:
                end = boundary + (text[boundary] == " ")
        if end <= start:
            end = min(len(text), start + max_chars)
        spans.append((start, end))
        start = end
    return spans


def chunk_elements(elements: list[dict]) -> list[dict]:
    chunks = []
    for element in elements:
        text = str(element.get("text", ""))
        if not text.strip():
            continue
        locator = dict(element.get("locator", {}))
        for start, end in split_spans(text):
            piece = text[start:end]
            if not piece.strip():
                continue
            chunk_locator = {**locator, "element_char_start": start, "element_char_end": end, "offset_basis": "element_text"}
            chunks.append({
                "index": len(chunks), "start": start, "end": end, "text": piece,
                "kind": element.get("kind", "text"), "asset_ref": element.get("asset_ref"),
                "locator": chunk_locator,
                "hash": hashlib.sha256(piece.encode("utf-8")).hexdigest(),
            })
            if len(chunks) >= MAX_ELEMENTS:
                return chunks
    return chunks


def extract_document(name: str, data: bytes, vision=None) -> dict:
    fmt, mime, ext = detect_format(name, data)
    ctx = {"assets": [], "elements": [], "warnings": [], "asset_bytes": 0, "ocr": _ImageReader(vision), "small_images": 0, "repeated_images": 0, "built_figures": 0, "figure_pieces": 0}
    if fmt in {"text", "markdown"}:
        text = data.decode("utf-8-sig")
        ctx["elements"].append({"text": text, "kind": "text", "locator": {"type": "text_file", "path": "/"}})
    elif fmt == "html":
        parser = _VisibleHTML()
        parser.feed(data.decode("utf-8-sig"))
        text = "".join(parser.parts)
        if text.strip():
            ctx["elements"].append({"text": text, "kind": "text", "locator": {"type": "html_document", "path": "/visible_text"}})
        for image in parser.images:
            ctx["elements"].append({**image, "kind": "image_alt"})
    elif fmt in {"csv", "tsv"}:
        _extract_delimited(data.decode("utf-8-sig"), fmt, ctx)
    elif fmt in {"json", "jsonl"}:
        _extract_json(data.decode("utf-8-sig"), fmt, ctx)
    elif fmt == "image":
        _add_image(data, mime, {"type": "image_source", "path": "/"}, "uploaded_image", ctx)
    elif fmt == "pdf":
        _extract_pdf(data, ctx)
    elif fmt == "docx":
        _extract_docx(data, ctx)
    elif fmt == "pptx":
        _extract_pptx(data, ctx)
    elif fmt == "xlsx":
        _extract_xlsx(data, ctx)
    _note_decoration(ctx)
    unread = sum(1 for a in ctx["assets"] if a["ocr_status"] == "not_attempted")
    if unread:
        ctx["warnings"].append(f"{unread} image(s) stored but not read: no vision model configured")
    if not ctx["elements"] and not ctx["assets"]:
        ctx["warnings"].append("No readable text or images were extracted")
    if len(ctx["elements"]) > MAX_ELEMENTS:
        ctx["elements"] = ctx["elements"][:MAX_ELEMENTS]
        ctx["warnings"].append(f"Extraction truncated at {MAX_ELEMENTS} elements")
    return {
        "format": fmt, "mime": mime, "extension": ext,
        "elements": ctx["elements"], "assets": ctx["assets"],
        "warnings": list(dict.fromkeys(ctx["warnings"])),
        "extractor": "amelia-local-extractors",
        "extractor_version": EXTRACTOR_VERSION,
    }


def _extract_delimited(text: str, fmt: str, ctx: dict) -> None:
    delimiter = "\t" if fmt == "tsv" else ","
    sample = text[:4096]
    if fmt == "csv":
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            pass
    rows = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    headers = None
    for row_num, row in enumerate(rows, start=1):
        if row_num > MAX_ELEMENTS:
            ctx["warnings"].append(f"Table truncated after {MAX_ELEMENTS} rows")
            break
        if headers is None:
            headers = row
            continue
        cells = [f"{headers[i] if i < len(headers) and headers[i] else f'column_{i+1}'}: {value}" for i, value in enumerate(row) if value.strip()]
        if cells:
            ctx["elements"].append({"text": " | ".join(cells), "kind": "table_row", "locator": {"type": "table_row", "row": row_num, "header_row": 1}})


def _extract_json(text: str, fmt: str, ctx: dict) -> None:
    try:
        if fmt == "json":
            obj = json.loads(text)
            entries = [("/", obj)]
            for path, value in entries:
                _flatten_json(path, value, ctx)
        else:
            for line_num, line in enumerate(text.splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    ctx["warnings"].append(f"JSONL line {line_num} is invalid: {exc.msg}")
                    continue
                _flatten_json(f"/line/{line_num}", value, ctx)
    except json.JSONDecodeError as exc:
        raise DocumentRejected(f"invalid JSON: {exc.msg} at line {exc.lineno}") from exc


def _flatten_json(path: str, value, ctx: dict, depth: int = 0) -> None:
    if len(ctx["elements"]) >= MAX_ELEMENTS:
        return
    if depth > 32:
        ctx["warnings"].append(f"JSON nesting truncated at {path}")
        return
    if isinstance(value, dict):
        for key, child in value.items():
            _flatten_json(f"{path.rstrip('/')}/{_json_pointer(str(key))}", child, ctx, depth + 1)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _flatten_json(f"{path.rstrip('/')}/{index}", child, ctx, depth + 1)
    elif value is not None:
        rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        ctx["elements"].append({"text": f"{path}: {rendered}", "kind": "json_value", "locator": {"type": "json_pointer", "pointer": path}})


def _json_pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def safe_png(data: bytes) -> tuple[bytes | None, str | None]:
    """Decode supported raster formats, enforce pixel limits, and make a safe PNG preview/OCR input."""
    from PIL import Image, ImageOps

    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.width <= 0 or image.height <= 0 or image.width * image.height > MAX_IMAGE_PIXELS:
                return None, "image skipped: pixel count exceeds the safety limit"
            image.seek(0)
            image = ImageOps.exif_transpose(image)
            image.thumbnail((1800, 1800), Image.Resampling.LANCZOS)
            if image.mode not in ("RGB", "RGBA", "L"):
                image = image.convert("RGB")
            output = io.BytesIO()
            image.save(output, format="PNG", optimize=True)
            return output.getvalue(), None
    except Exception as exc:
        return None, f"image preview/OCR unavailable for this media format: {type(exc).__name__}"


def _add_image(data: bytes, mime: str, locator: dict, kind: str, ctx: dict) -> int | None:
    if not data:
        return None
    if len(ctx["assets"]) >= MAX_ASSETS or ctx["asset_bytes"] + len(data) > MAX_ASSET_BYTES:
        ctx["warnings"].append("Image extraction limit reached; remaining media were not copied")
        return None
    digest = hashlib.sha256(data).hexdigest()
    asset_ref = len(ctx["assets"])
    asset = {
        "asset_ref": asset_ref, "bytes": data, "sha256": digest, "mime": mime,
        "size": len(data), "kind": kind, "locator": dict(locator),
        "ocr_text": "", "figure_reading": "", "ocr_status": "not_attempted", "ocr_model": None,
    }
    ctx["assets"].append(asset)
    ctx["asset_bytes"] += len(data)
    text, reading, status, error = ctx["ocr"].read(data)
    asset["ocr_text"], asset["figure_reading"], asset["ocr_status"], asset["ocr_error"] = text, reading, status, error or ""
    if status in {"completed", "empty", "failed"}:
        asset["ocr_model"] = ctx["ocr"].model
    if error:
        ctx["warnings"].append(f"{kind} at {locator}: {error}")
    base_locator = {**locator, "type": locator.get("type", "image"), "ocr_model": ctx["ocr"].model}
    if text.strip():
        ctx["elements"].append({"text": text, "kind": "ocr_text", "asset_ref": asset_ref,
                                "locator": {**base_locator, "ocr": True}})
    if reading.strip():
        ctx["elements"].append({"text": reading, "kind": "figure_reading", "asset_ref": asset_ref,
                                "locator": {**base_locator, "model_reading": True}})
    return asset_ref


# --- Reading a PDF's structure from what the file itself states ---

MAX_HEADING_CHARS = 120
MAX_HEADING_LINES = 3
LARGER_THAN_BODY = 1.15
RUNNING_HEADER_PAGES = 3
# Raise it when the extractor learns something stored chunks lack: a file read by an older one is extracted again.
EXTRACTOR_VERSION = "1.4"

CAPTION = re.compile(r"(?:figure|fig\.?|table|figura|tabela|tabla|quadro|gr[aá]fico|abbildung|tabelle|tableau)\s*\d+\s*[.:]", re.I)
_SUBCAPTION = re.compile(r"\([a-z]\)\s")
_PAGE_NUMBER = re.compile(r"\d{1,4}")
PAGE_EDGE = 0.08  # share of the page height where headers and page numbers live
_NOT_A_TITLE = re.compile(r"(?:algorithm|algoritmo|input|output|require|ensure)\b", re.I)
_LABEL = re.compile(r"[^\W\d_]+:\s")
_MATH = re.compile(r"[=←→≤≥∈∑∏√±×∼≈⇒]")
_AUTHOR_MARK = re.compile(r"[†‡§*∗]|[^\W\d_]\d(?:[,\s]|$)")
_BOLD_FONT = re.compile(r"bold|black|heavy|medi|semi|demi", re.I)


def _is_rotated(block: dict) -> bool:
    return any(tuple(round(x) for x in line.get("dir", (1, 0))) != (1, 0) for line in block.get("lines", []))


def _column_blocks(blocks: list[dict], middle: float) -> tuple[list[dict], list[dict]] | None:
    """The two columns of a page, or None when the page does not have two.

    A column has to hold real text: a short note in the right margin does not make a second column.
    """
    weight = lambda b: sum(len(s.get("text", "")) for line in b.get("lines", []) for s in line.get("spans", []))
    text = [b for b in blocks if b.get("type") == 0 and not _is_rotated(b)]
    left = [b for b in text if b["bbox"][2] <= middle + 5]
    right = [b for b in text if b["bbox"][0] >= middle - 5]
    total = sum(weight(b) for b in text)
    if not total or sum(weight(b) for b in left) < total * 0.2 or sum(weight(b) for b in right) < total * 0.2:
        return None
    return left, right


def _reading_order(blocks: list[dict], page_width: float) -> list[dict]:
    """Blocks as a person reads them. Sorting by height alone interleaves the two columns of a paper.

    A block wider than one column (title, wide table) closes the columns above it, which are read first.
    """
    top = lambda b: (b["bbox"][1], b["bbox"][0])
    middle = page_width / 2
    if _column_blocks(blocks, middle) is None:
        return sorted(blocks, key=top)
    ordered, band = [], []
    def close_band():
        ordered.extend(sorted((b for b in band if (b["bbox"][0] + b["bbox"][2]) / 2 < middle), key=top))
        ordered.extend(sorted((b for b in band if (b["bbox"][0] + b["bbox"][2]) / 2 >= middle), key=top))
        band.clear()
    for block in sorted(blocks, key=top):
        x0, _, x1, _ = block["bbox"]
        if x0 < middle - 5 and x1 > middle + 5 and not _is_rotated(block):
            close_band()
            ordered.append(block)
        else:
            band.append(block)
    close_band()
    return ordered


def _block_style(block: dict) -> tuple[float, bool]:
    """Largest font and whether all its visible text is bold."""
    spans = [s for line in block.get("lines", []) for s in line.get("spans", []) if s.get("text", "").strip()]
    if not spans:
        return 0.0, False
    bold = all(int(s.get("flags", 0)) & 16 or _BOLD_FONT.search(s.get("font", "")) for s in spans)
    return max(float(s.get("size", 0)) for s in spans), bool(bold)


def _looks_like_title(text: str, line_count: int) -> bool:
    if not text or len(text) > MAX_HEADING_CHARS or line_count > MAX_HEADING_LINES:
        return False
    first_letter = re.search(r"[^\W\d_]", text)
    if not re.search(r"[^\W\d_]{2}", text) or text[-1] in ".:;," or first_letter.group().islower():
        return False
    if CAPTION.match(text) or _NOT_A_TITLE.match(text) or _LABEL.match(text) or _MATH.search(text):
        return False
    return text.count(",") < 2 and not _AUTHOR_MARK.search(text)


def _pdf_structure(doc) -> tuple[set[tuple[int, str]], float]:
    """(page, title) of each heading and the body font size, taken from size and weight across the whole file.

    Numbering alone proves nothing, since numbered lists and algorithm lines have it too.
    Bold at body size or above counts, or a font clearly larger than the body.
    """
    sizes: dict[float, int] = {}
    found: list[tuple[int, str, float, bool, int]] = []
    for page_index, page in enumerate(doc):
        try:
            blocks = _reading_order(page.text_blocks(), page.width)
        except Exception:
            continue  # the reading pass reports this page
        for block in blocks:
            if block.get("type") != 0 or _is_rotated(block):
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    size = round(float(span.get("size", 0)), 1)
                    sizes[size] = sizes.get(size, 0) + len(span.get("text", ""))
            size, bold = _block_style(block)
            lines = ["".join(s.get("text", "") for s in line.get("spans", [])) for line in block.get("lines", [])]
            title = " ".join(" ".join(lines).split())
            found.append((page_index + 1, title, size, bold, len(lines)))
    if not sizes:
        return set(), 0.0
    body = max(sizes, key=sizes.get)
    candidates = []
    for page_no, title, size, bold, line_count in found:
        strong = (bold and size >= body - 0.5) or size >= body * LARGER_THAN_BODY
        if strong and _looks_like_title(title, line_count):
            candidates.append((page_no, title, size))
    # The same words on many pages are a running header.
    pages_of: dict[str, set[int]] = {}
    for page_no, title, _ in candidates:
        pages_of.setdefault(title, set()).add(page_no)
    candidates = [c for c in candidates if len(pages_of[c[1]]) < RUNNING_HEADER_PAGES]
    # The document's title opens the file in a font nothing else uses: it names the file, not a section.
    if len(candidates) > 1 and candidates[0][2] > max(c[2] for c in candidates[1:]):
        candidates = candidates[1:]
    return {(page_no, title) for page_no, title, _ in candidates}, body


def _block_role(block: dict, title: str, body: float, page_height: float) -> str | None:
    """What a block is when it is not running text. It stays in the file; the read plan decides what to do with it."""
    if _is_rotated(block):
        return "margin"
    if CAPTION.match(title):
        return "caption"
    if _SUBCAPTION.match(title) and len(title) < MAX_HEADING_CHARS and _block_style(block)[0] < body - 0.5:
        return "caption"
    _, y0, _, y1 = block["bbox"]
    if _PAGE_NUMBER.fullmatch(title) and (y1 < page_height * PAGE_EDGE or y0 > page_height * (1 - PAGE_EDGE)):
        return "margin"
    return None


def _extract_pdf(data: bytes, ctx: dict) -> None:
    from .pdf import open_pdf
    try:
        doc = open_pdf(data)
    except Exception as exc:
        raise DocumentRejected(f"PDF parser could not open this file: {exc}") from exc
    if doc.page_count > MAX_PAGES:
        raise DocumentRejected(f"PDF has {doc.page_count} pages; limit is {MAX_PAGES}")
    headings, body = _pdf_structure(doc)
    section = None
    seen_images: set[str] = set()
    for page_index, page in enumerate(doc):
        page_no = page_index + 1
        try:
            blocks = _reading_order(page.blocks(), page.width)
        except Exception as exc:
            ctx["warnings"].append(f"PDF page {page_no}: text layout unavailable ({exc})")
            blocks = []
        text_blocks = 0
        ocr_chars = 0
        figures = _built_figures(page, blocks)
        drawn: set[tuple] = set()
        for block_index, block in enumerate(blocks):
            locator = {"type": "pdf_block", "page": page_no, "block": block_index,
                       "bbox": [round(float(x), 2) for x in block.get("bbox", [])]}
            if block.get("type") == 0:
                lines = ["".join(span.get("text", "") for span in line.get("spans", [])) for line in block.get("lines", [])]
                block_text = "\n".join(line for line in lines if line.strip()).strip()
                if block_text:
                    text_blocks += 1
                    title = " ".join(block_text.split())
                    if (page_no, title) in headings:
                        section = title
                        locator["role"] = "heading"
                    else:
                        role = _block_role(block, title, body, page.height)
                        if not role and any(_near(r, tuple(block["bbox"]), 0) and _join(r, tuple(block["bbox"])) == r for r in figures):
                            role = "figure_label"  # the figure's reading carries it, in place
                        if role:
                            locator["role"] = role
                    if section:
                        locator["section"] = section
                    ctx["elements"].append({"text": block_text, "kind": "text", "locator": locator})
            elif block.get("type") == 1 and block.get("image"):
                region = next((r for r in figures if _near(r, tuple(block["bbox"]), 0)), None)
                if region:
                    ctx["figure_pieces"] += 1
                    if region not in drawn:
                        drawn.add(region)
                        _add_built_figure(page, region, page_no, section, ctx)
                    continue
                if _is_decoration(block, seen_images, ctx):
                    continue
                if section:
                    locator["section"] = section
                asset_ref = _add_image(block["image"], block.get("ext") and f"image/{block['ext']}" or "image/png",
                                       {**locator, "type": "pdf_image"}, "pdf_image", ctx)
                if asset_ref is not None:
                    ocr_chars += len(ctx["assets"][asset_ref].get("ocr_text", "")) + len(ctx["assets"][asset_ref].get("figure_reading", ""))
        if text_blocks == 0 and ocr_chars == 0:
            try:
                page_png = page.render_png(dpi=250)
                render = {"type": "pdf_page_render", "page": page_no}
                if section:
                    render["section"] = section
                _add_image(page_png, "image/png", render, "scanned_pdf_page", ctx)
            except Exception as exc:
                ctx["warnings"].append(f"PDF page {page_no}: OCR render unavailable ({exc})")
    doc.close()


def _near(a: tuple, b: tuple, gap: float) -> bool:
    return a[0] - gap <= b[2] and b[0] - gap <= a[2] and a[1] - gap <= b[3] and b[1] - gap <= a[3]


def _join(a: tuple, b: tuple) -> tuple:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _grow(boxes: list[tuple], gap: float) -> list[tuple]:
    """Merges each box with whatever sits within the gap, until nothing more joins."""
    merged = list(boxes)
    changed = True
    while changed:
        changed = False
        for i, box in enumerate(merged):
            for other in merged[i + 1:]:
                if _near(box, other, gap):
                    merged[i] = _join(box, other)
                    merged.remove(other)
                    changed = True
                    break
            if changed:
                break
    return merged


def _built_figures(page, blocks: list[dict]) -> list[tuple]:
    """A figure drawn from many small pictures, with its labels and lines. A picture alone stays what it is:
    it takes a piece under half an inch to call a cluster built, so ordinary figures never come here."""
    images = [tuple(b["bbox"]) for b in blocks if b.get("type") == 1 and b.get("image")]
    if not any(min(x1 - x0, y1 - y0) < MIN_FIGURE_POINTS for x0, y0, x1, y1 in images):
        return []
    clusters = []
    for box in _grow(images, FIGURE_GAP_POINTS):
        if min(box[2] - box[0], box[3] - box[1]) < MIN_JOINED_POINTS:
            continue
        if any(min(x1 - x0, y1 - y0) < MIN_FIGURE_POINTS and _near(box, (x0, y0, x1, y1), 0) for x0, y0, x1, y1 in images):
            clusters.append(box)
    if not clusters:
        return []
    labels, stops = [], []
    for block in blocks:
        if block.get("type") != 0:
            continue
        text = " ".join(span.get("text", "") for line in block.get("lines", []) for span in line.get("spans", [])).strip()
        if not text:
            continue
        (stops if FIGURE_CAPTION.match(text) or len(text) > FIGURE_LABEL_CHARS else labels).append(tuple(block["bbox"]))
    lines = []
    try:
        lines = page.drawing_regions()
    except Exception:
        pass  # without vector lines the figure is only tighter around its pictures
    usable = [r for r in lines if not any(_near(r, stop, 0) for stop in stops)]
    grown = []
    for box in clusters:
        changed = True
        while changed:
            changed = False
            for extra in images + labels + usable:
                if _near(box, extra, FIGURE_GAP_POINTS) and _join(box, extra) != box and not any(_near(_join(box, extra), stop, 0) for stop in stops):
                    box = _join(box, extra)
                    changed = True
        grown.append((max(box[0] - 4, 0.0), max(box[1] - 4, 0.0), min(box[2] + 4, page.width), min(box[3] + 4, page.height)))
    return grown


def _add_built_figure(page, region: tuple, page_no: int, section, ctx: dict) -> None:
    try:
        png = page.render_png(dpi=FIGURE_DPI, clip=region)
    except Exception as exc:
        ctx["warnings"].append(f"PDF page {page_no}: a figure could not be drawn ({exc})")
        return
    locator = {"type": "pdf_figure_render", "page": page_no, "bbox": [round(float(x), 2) for x in region]}
    if section:
        locator["section"] = section
    _add_image(png, "image/png", locator, "pdf_figure", ctx)
    ctx["built_figures"] += 1


def _is_decoration(block: dict, seen: set, ctx: dict) -> bool:
    """Judged by how the PDF draws the image, not by its pixels: an icon can be stored large. Only ever skips a copy; the file stays whole."""
    x0, y0, x1, y1 = block["bbox"]
    digest = hashlib.sha256(block["image"]).hexdigest()
    if min(x1 - x0, y1 - y0) < MIN_FIGURE_POINTS:
        ctx["small_images"] += 1
        return True
    if digest in seen:
        ctx["repeated_images"] += 1
        return True
    seen.add(digest)
    return False


def _note_decoration(ctx: dict) -> None:
    if ctx["built_figures"]:
        ctx["warnings"].append(f"{ctx['built_figures']} figure(s) {JOINED_NOTE} from {ctx['figure_pieces']} pieces")
    parts = []
    if ctx["small_images"]:
        parts.append(f"{ctx['small_images']} drawn under half an inch")
    if ctx["repeated_images"]:
        parts.append(f"{ctx['repeated_images']} repeated")
    if parts:
        ctx["warnings"].append(f"{ctx['small_images'] + ctx['repeated_images']} image(s) {DECORATION_NOTE}: {', '.join(parts)}")


def is_only_a_note(warning: str) -> bool:
    return DECORATION_NOTE in warning or JOINED_NOTE in warning


def _extract_docx(data: bytes, ctx: dict) -> None:
    from docx import Document
    from docx.oxml.ns import qn
    from docx.text.paragraph import Paragraph
    from docx.table import Table
    try:
        doc = Document(io.BytesIO(data))
    except Exception as exc:
        raise DocumentRejected(f"DOCX parser could not open this file: {exc}") from exc
    block_index = 0
    for child in doc.element.body.iterchildren():
        if child.tag.endswith("}p"):
            paragraph = Paragraph(child, doc)
            text = paragraph.text.strip()
            if text:
                ctx["elements"].append({"text": text, "kind": "text", "locator": {"type": "docx_paragraph", "paragraph": block_index}})
            for blip in child.xpath(".//a:blip"):
                rid = blip.get(qn("r:embed"))
                part = doc.part.related_parts.get(rid)
                if part is not None:
                    mime = part.content_type or "application/octet-stream"
                    _add_image(part.blob, mime, {"type": "docx_image", "paragraph": block_index, "relationship_id": rid}, "docx_image", ctx)
            block_index += 1
        elif child.tag.endswith("}tbl"):
            table = Table(child, doc)
            for row_index, row in enumerate(table.rows):
                cells = [cell.text.strip().replace("\n", " / ") for cell in row.cells]
                rendered = " | ".join(value for value in cells if value)
                if rendered:
                    ctx["elements"].append({"text": rendered, "kind": "table_row", "locator": {"type": "docx_table_row", "table": block_index, "row": row_index}})
            block_index += 1
    # Preserve any packaged media not reached through inline paragraph relationships.
    _extract_orphan_office_media(data, "word/media/", "docx_media", ctx)


def _extract_pptx(data: bytes, ctx: dict) -> None:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    try:
        prs = Presentation(io.BytesIO(data))
    except Exception as exc:
        raise DocumentRejected(f"PPTX parser could not open this file: {exc}") from exc
    if len(prs.slides) > MAX_PAGES:
        raise DocumentRejected(f"Presentation has {len(prs.slides)} slides; limit is {MAX_PAGES}")
    for slide_no, slide in enumerate(prs.slides, start=1):
        for shape_index, shape in enumerate(slide.shapes):
            locator = {"type": "pptx_shape", "slide": slide_no, "shape": shape_index,
                       "name": getattr(shape, "name", "")}
            if getattr(shape, "has_text_frame", False) and shape.text.strip():
                ctx["elements"].append({"text": shape.text.strip(), "kind": "text", "locator": locator})
            if getattr(shape, "has_table", False):
                for row_index, row in enumerate(shape.table.rows):
                    rendered = " | ".join(cell.text.strip().replace("\n", " / ") for cell in row.cells if cell.text.strip())
                    if rendered:
                        ctx["elements"].append({"text": rendered, "kind": "table_row", "locator": {**locator, "type": "pptx_table_row", "row": row_index}})
            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                image = shape.image
                _add_image(image.blob, image.content_type, {**locator, "type": "pptx_image",
                           "left": int(shape.left), "top": int(shape.top), "width": int(shape.width), "height": int(shape.height)}, "pptx_image", ctx)
    _extract_orphan_office_media(data, "ppt/media/", "pptx_media", ctx)


def _extract_xlsx(data: bytes, ctx: dict) -> None:
    from openpyxl import load_workbook
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=False, data_only=False)
    except Exception as exc:
        raise DocumentRejected(f"XLSX parser could not open this file: {exc}") from exc
    rows_seen = 0
    for sheet in workbook.worksheets:
        pending = []
        pending_start = None
        for row_index, row in enumerate(sheet.iter_rows(values_only=False), start=1):
            rows_seen += 1
            if rows_seen > MAX_ELEMENTS:
                ctx["warnings"].append(f"Workbook truncated after {MAX_ELEMENTS} rows")
                break
            cells = []
            for cell in row:
                value = cell.value
                if value is None or str(value).strip() == "":
                    continue
                cells.append(f"{cell.coordinate}: {value}")
            if not cells:
                if pending:
                    _flush_sheet_rows(sheet.title, pending_start, row_index - 1, pending, ctx)
                    pending, pending_start = [], None
                continue
            rendered = " | ".join(cells)
            if not pending:
                pending_start = row_index
            if sum(len(x) for x in pending) + len(rendered) > CHUNK_CHARS:
                _flush_sheet_rows(sheet.title, pending_start, row_index - 1, pending, ctx)
                pending, pending_start = [rendered], row_index
            else:
                pending.append(rendered)
        if pending:
            _flush_sheet_rows(sheet.title, pending_start, row_index, pending, ctx)
        for image_index, image in enumerate(getattr(sheet, "_images", [])):
            try:
                anchor = image.anchor._from
                cell = f"{chr(65 + anchor.col)}{anchor.row + 1}"
                image_bytes = image._data()
                mime = f"image/{image.format.lower()}" if image.format else "application/octet-stream"
                _add_image(image_bytes, mime, {"type": "xlsx_image", "sheet": sheet.title,
                           "cell": cell, "image": image_index}, "xlsx_image", ctx)
            except Exception as exc:
                ctx["warnings"].append(f"Workbook image in sheet {sheet.title} could not be extracted: {exc}")
    workbook.close()


def _flush_sheet_rows(sheet: str, row_start: int, row_end: int, lines: list[str], ctx: dict) -> None:
    if lines:
        ctx["elements"].append({"text": "\n".join(lines), "kind": "table_rows",
                                "locator": {"type": "xlsx_rows", "sheet": sheet, "row_start": row_start, "row_end": row_end}})


def _extract_orphan_office_media(data: bytes, prefix: str, kind: str, ctx: dict) -> None:
    """Keep packaged pictures even when a parser cannot map them to a text block."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for member in archive.namelist():
                if not member.startswith(prefix) or member.endswith("/"):
                    continue
                if len(ctx["assets"]) >= MAX_ASSETS:
                    ctx["warnings"].append("Office embedded-image limit reached")
                    return
                blob = archive.read(member)
                if not blob:
                    continue
                digest = hashlib.sha256(blob).hexdigest()
                if any(asset["sha256"] == digest for asset in ctx["assets"]):
                    continue
                mime = mimetypes.guess_type(member)[0] or "application/octet-stream"
                _add_image(blob, mime, {"type": "office_media_part", "part_path": member}, kind, ctx)
    except (zipfile.BadZipFile, OSError) as exc:
        ctx["warnings"].append(f"Embedded media inventory failed: {exc}")
