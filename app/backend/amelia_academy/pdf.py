"""Reading a PDF on permissive licenses: pdfplumber (MIT, on pdfminer.six) for text and vector drawings,
pypdfium2 (Apache-2.0 / BSD-3) for embedded pictures and renders.

Pages hand back text and pictures as blocks shaped like PyMuPDF's `get_text("dict")`, so the structure
reading in documents.py stays the same: a block holds lines, a line holds spans of one font and size.
Coordinates are points from the top-left corner of the visible page (the crop box).
"""
from __future__ import annotations

import io
import math
import re

_SUBSET = re.compile(r"^[A-Z]{6}\+")
_CID = re.compile(r"\(cid:\d+\)")
# Fonts whose name or descriptor say bold; TeX's bold faces name it only in the family code.
_TEX_BOLD = re.compile(r"^(?:CMBX|CMMIB|CMBSY|CMSSBX|CMB\d|CMTTB|LMRomanDemi|SFBX)", re.I)
BOLD_FLAG = 16  # the bit PyMuPDF sets on bold spans

# A character joins the line when it sits this close to the baseline and to the previous character (in font sizes).
BASELINE_SHIFT = 0.6
SPACE_GAP = 0.15
LINE_BREAK_GAP = 1.0
BACKSTEP = 0.5
# A line joins the block above when the baselines are this close, in font sizes.
BLOCK_LINE_STEP = 1.55
SIZE_CHANGE = 0.5
PARAGRAPH_INDENT = 0.5
SHORT_LINE = 1.0
FAMILY_CHANGE_STEP = 1.3  # wider than the line gap of tight text, narrower than a heading break
DRAWING_TOLERANCE = 3


class PdfRejected(Exception):
    pass


def open_pdf(data: bytes) -> "PdfFile":
    return PdfFile(data)


class PdfFile:
    def __init__(self, data: bytes):
        import pdfplumber
        import pypdfium2
        try:
            self._plumber = pdfplumber.open(io.BytesIO(data))
            self._pdfium = pypdfium2.PdfDocument(data)
            self.page_count = len(self._pdfium)
        except Exception as exc:
            raise PdfRejected(str(exc) or type(exc).__name__) from exc

    @property
    def metadata(self) -> dict:
        try:
            return {k: v for k, v in self._pdfium.get_metadata_dict(skip_empty=True).items()}
        except Exception:
            return {}

    def __iter__(self):
        for index in range(self.page_count):
            yield PdfPage(self, index)

    def close(self) -> None:
        for closer in (self._plumber.close, self._pdfium.close):
            try:
                closer()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class PdfPage:
    def __init__(self, parent: PdfFile, index: int):
        self.index = index
        self._plumber = parent._plumber.pages[index]
        self._pdfium = parent._pdfium[index]
        x0, top, x1, bottom = self._plumber.bbox
        self._offset = (x0, top)
        self.width, self.height = x1 - x0, bottom - top
        self.rect = (0.0, 0.0, self.width, self.height)

    # --- text ---

    def text_blocks(self) -> list[dict]:
        bold = _bold_fonts(self._plumber)
        lines = _lines(self._chars(), bold)
        return [_block(group) for group in _group_lines(lines)]

    def _chars(self) -> list[dict]:
        ox, oy = self._offset
        chars = []
        for c in self._plumber.chars:
            x0, x1, top, bottom = c["x0"] - ox, c["x1"] - ox, c["top"] - oy, c["bottom"] - oy
            if (x0 + x1) / 2 < 0 or (x0 + x1) / 2 > self.width or (top + bottom) / 2 < 0 or (top + bottom) / 2 > self.height:
                continue  # drawn outside the visible page
            a, b, _, _, e, f = c.get("matrix") or (1, 0, 0, 1, x0, c["y0"])
            norm = math.hypot(a, b) or 1.0
            direction = (a / norm, -b / norm)
            origin = (e - ox, bottom + (c["y0"] - f) - oy)
            text = _CID.sub("", c["text"])  # a glyph the file gives no letter for
            if not text:
                continue
            advance = float(c["adv"]) * norm if c.get("adv") is not None else None
            chars.append({"text": text, "advance": advance, "font": _SUBSET.sub("", c.get("fontname") or ""),
                          "size": float(c.get("size") or 0), "bbox": (x0, top, x1, bottom),
                          "origin": origin, "dir": direction})
        return chars

    # --- pictures ---

    def image_blocks(self) -> list[dict]:
        import pypdfium2.raw as raw
        blocks = []
        for obj, matrix in _walk(self._pdfium, raw):
            try:
                bbox = self._top_down(_transform_bounds(obj.get_bounds(), matrix))
                data, ext = _image_bytes(obj)
            except Exception:
                continue
            if not data or bbox[2] - bbox[0] <= 0 or bbox[3] - bbox[1] <= 0:
                continue
            blocks.append({"type": 1, "bbox": bbox, "image": data, "ext": ext})
        return blocks

    def blocks(self) -> list[dict]:
        return self.text_blocks() + self.image_blocks()

    def drawing_regions(self, tolerance: float = DRAWING_TOLERANCE) -> list[tuple]:
        """Rectangles around vector drawings that touch each other, as PyMuPDF's cluster_drawings joins them."""
        ox, oy = self._offset
        p = self._plumber
        rects = []
        for item in list(p.rects) + list(p.lines) + list(p.curves):
            box = (item["x0"] - ox, item["top"] - oy, item["x1"] - ox, item["bottom"] - oy)
            if box[0] >= 0 and box[1] >= 0 and box[2] <= self.width and box[3] <= self.height:
                rects.append(box)
        return _cluster(rects, tolerance)

    def render_png(self, dpi: float, clip: tuple | None = None) -> bytes:
        scale = dpi / 72
        crop = (0, 0, 0, 0)
        if clip:
            x0, y0, x1, y1 = (max(0.0, clip[0]), max(0.0, clip[1]), min(self.width, clip[2]), min(self.height, clip[3]))
            crop = (x0, self.height - y1, self.width - x1, y0)
        image = self._pdfium.render(scale=scale, crop=crop).to_pil().convert("RGB")
        out = io.BytesIO()
        image.save(out, "PNG")
        return out.getvalue()

    def _top_down(self, box: tuple) -> tuple:
        left, bottom, right, top = box
        cx0, cy0, cx1, cy1 = self._pdfium.get_cropbox()
        return (left - cx0, cy1 - top, right - cx0, cy1 - bottom)


# --- characters into lines, lines into blocks ---

def _bold_fonts(page) -> set[str]:
    """Font names the page's font descriptors mark bold (weight or ForceBold)."""
    from pdfminer.pdftypes import resolve1
    names = set()
    try:
        fonts = resolve1(resolve1(page.page_obj.resources or {}).get("Font")) or {}
        for ref in fonts.values():
            font = resolve1(ref) or {}
            descriptor = resolve1(font.get("FontDescriptor"))
            if descriptor is None and font.get("DescendantFonts"):
                descendant = resolve1(resolve1(font["DescendantFonts"])[0]) or {}
                descriptor = resolve1(descendant.get("FontDescriptor"))
            descriptor = descriptor or {}
            weight = resolve1(descriptor.get("FontWeight")) or 0
            flags = resolve1(descriptor.get("Flags")) or 0
            if (isinstance(weight, (int, float)) and weight >= 600) or (isinstance(flags, int) and flags & (1 << 18)):
                base = resolve1(font.get("BaseFont"))
                name = getattr(base, "name", base)
                if isinstance(name, bytes):
                    name = name.decode("latin-1")
                if name:
                    names.add(_SUBSET.sub("", str(name)))
    except Exception:
        pass
    return names


def _flags(font: str, bold: set[str]) -> int:
    return BOLD_FLAG if font in bold or _TEX_BOLD.match(font) else 0


def _lines(chars: list[dict], bold: set[str]) -> list[dict]:
    """Characters in the order the file draws them, joined into lines the way a reader would see them."""
    lines: list[dict] = []
    line = None
    pen = None
    prev_size = 0.0
    for c in chars:
        blank = not c["text"].strip()
        if line is not None and c["dir"] == line["dir"]:
            size = max(c["size"], line["size"]) or 1.0
            d = line["dir"]
            dx, dy = c["origin"][0] - pen[0], c["origin"][1] - pen[1]
            along = dx * d[0] + dy * d[1]
            bx, by = c["origin"][0] - line["base"][0], c["origin"][1] - line["base"][1]
            across = by * d[0] - bx * d[1]  # off the line's baseline: superscripts stay, the next line does not
            if abs(across) < size * BASELINE_SHIFT and -size * BACKSTEP < along < size * LINE_BREAK_GAP:
                if blank:
                    _add_space(line)
                else:
                    if along > min(c["size"], prev_size or c["size"]) * SPACE_GAP:  # the letters either side, not an odd large glyph
                        _add_space(line)
                    _add_char(line, c, bold)
                pen = _pen_after(c)
                prev_size = c["size"] if not blank else prev_size
                continue
        if blank:
            continue
        line = {"dir": c["dir"], "size": 0.0, "spans": [], "origin": c["origin"], "base": c["origin"]}
        lines.append(line)
        _add_char(line, c, bold)
        pen = _pen_after(c)
        prev_size = c["size"]
    for line in lines:
        for span in line["spans"]:
            span["bbox"] = tuple(span["bbox"])
        line["spans"] = [s for s in line["spans"] if s["text"]]
        line["bbox"] = _union(s["bbox"] for s in line["spans"])
    return [l for l in lines if l["spans"]]


def _pen_after(c: dict) -> tuple:
    width = c["advance"]
    if width is None:
        x0, top, x1, bottom = c["bbox"]
        width = abs((x1 - x0) * c["dir"][0]) + abs((bottom - top) * c["dir"][1])
    return (c["origin"][0] + width * c["dir"][0], c["origin"][1] + width * c["dir"][1])


def _add_space(line: dict) -> None:
    if line["spans"] and not line["spans"][-1]["text"].endswith(" "):
        line["spans"][-1]["text"] += " "


def _add_char(line: dict, c: dict, bold: set[str]) -> None:
    spans = line["spans"]
    if not spans or spans[-1]["font"] != c["font"] or abs(spans[-1]["size"] - c["size"]) > 0.01:
        spans.append({"text": "", "font": c["font"], "size": c["size"], "flags": _flags(c["font"], bold),
                      "origin": c["origin"], "bbox": list(c["bbox"])})
    span = spans[-1]
    span["text"] += c["text"]
    b = span["bbox"]
    x0, top, x1, bottom = c["bbox"]
    span["bbox"] = [min(b[0], x0), min(b[1], top), max(b[2], x1), max(b[3], bottom)]
    if c["text"].strip() and c["size"] > line["size"]:
        if line["size"] and c["size"] > line["size"] + SIZE_CHANGE:
            line["base"] = c["origin"]  # the larger letters carry the baseline
        line["size"] = c["size"]


def _line_style(line: dict) -> tuple[float, str, str]:
    visible = [s for s in line["spans"] if s["text"].strip()] or line["spans"]
    return max(s["size"] for s in visible), visible[0]["font"], visible[-1]["font"]


def _group_lines(lines: list[dict]) -> list[list[dict]]:
    groups: list[list[dict]] = []
    for line in lines:
        if groups and _continues(groups[-1], line):
            groups[-1].append(line)
        else:
            groups.append([line])
    return groups


def _continues(group: list[dict], line: dict) -> bool:
    prev = group[-1]
    if prev["dir"] != line["dir"]:
        return False
    d = line["dir"]
    size = max(prev["size"], line["size"]) or 1.0
    dx, dy = line["origin"][0] - prev["origin"][0], line["origin"][1] - prev["origin"][1]
    step = (dy * d[0] - dx * d[1]) / size  # how far below the previous baseline, in font sizes
    if abs(step) <= 0.3:
        return True  # the same baseline, split by a wide gap
    if step < 0 or step > BLOCK_LINE_STEP:
        return False
    if prev["size"] - line["size"] > SIZE_CHANGE:
        return False  # running text under a heading; a kicker line over a title stays with it
    if step > FAMILY_CHANGE_STEP and _family(prev) != _family(line):
        return False  # a heading set in another typeface over the next heading or text
    box, other = _union(l["bbox"] for l in group), line["bbox"]
    if d != (1.0, 0.0):
        return other[1] <= box[3] and box[1] <= other[3]
    if not (other[0] <= box[2] and box[0] <= other[2]):
        return False
    # An indented line after a short one opens a paragraph.
    return not (other[0] > box[0] + size * PARAGRAPH_INDENT and prev["bbox"][2] < box[2] - size * SHORT_LINE)


def _family(line: dict) -> str:
    fonts = [s["font"] for s in line["spans"] if s["text"].strip()]
    return fonts[0].split("-")[0].split(",")[0] if fonts else ""


def _block(lines: list[dict]) -> dict:
    out = []
    for line in lines:
        out.append({"bbox": line["bbox"], "dir": line["dir"], "wmode": 0,
                    "spans": [{k: s[k] for k in ("text", "font", "size", "flags", "origin", "bbox")} for s in line["spans"]]})
    return {"type": 0, "bbox": _union(l["bbox"] for l in lines), "lines": out}


def _union(boxes) -> tuple:
    boxes = list(boxes)
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


# --- pictures and drawings ---

def _walk(page, raw, form=None, matrix=(1, 0, 0, 1, 0, 0), depth=0):
    """Image objects on the page, with forms opened and their placement carried down."""
    for obj in page.get_objects(max_depth=0, form=form) if form is not None else page.get_objects(max_depth=0):
        if obj.type == raw.FPDF_PAGEOBJ_IMAGE:
            yield obj, matrix
        elif obj.type == raw.FPDF_PAGEOBJ_FORM and depth < 15:
            m = obj.get_matrix()
            yield from _walk(page, raw, obj, _compose((m.a, m.b, m.c, m.d, m.e, m.f), matrix), depth + 1)


def _compose(inner: tuple, outer: tuple) -> tuple:
    a, b, c, d, e, f = inner
    A, B, C, D, E, F = outer
    return (a * A + b * C, a * B + b * D, c * A + d * C, c * B + d * D, e * A + f * C + E, e * B + f * D + F)


def _transform_bounds(bounds: tuple, m: tuple) -> tuple:
    if m == (1, 0, 0, 1, 0, 0):
        return tuple(bounds)
    left, bottom, right, top = bounds
    points = [(x * m[0] + y * m[2] + m[4], x * m[1] + y * m[3] + m[5]) for x in (left, right) for y in (bottom, top)]
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _image_bytes(image) -> tuple[bytes, str]:
    """A JPEG stays as stored; anything else comes out as PNG."""
    filters = list(image.get_filters())
    if filters and filters[-1] in ("DCTDecode", "DCT") and all(f in image.SIMPLE_FILTERS for f in filters[:-1]):
        return bytes(image.get_data(decode_simple=True)), "jpeg"
    try:
        pil = image.get_bitmap(render=False).to_pil()
    except Exception:
        pil = image.get_bitmap(render=True).to_pil()
    if pil.mode not in ("RGB", "RGBA", "L", "LA", "1", "P"):
        pil = pil.convert("RGB")
    out = io.BytesIO()
    pil.save(out, "PNG")
    return out.getvalue(), "png"


def _cluster(rects: list[tuple], delta: float) -> list[tuple]:
    def neighbors(r1, r2):
        return not (r1[2] < r2[0] - delta or r1[0] > r2[2] + delta or r1[3] < r2[1] - delta or r1[1] > r2[3] + delta)

    pending = sorted(set(rects), key=lambda r: (r[3], r[0]))
    joined = []
    while pending:
        r = pending[0]
        repeat = True
        while repeat:
            repeat = False
            for i in range(len(pending) - 1, 0, -1):
                if neighbors(pending[i], r):
                    r = _union([r, pending[i]])
                    del pending[i]
                    repeat = True
        joined.append(r)
        del pending[0]
        pending = sorted(set(pending), key=lambda r: (r[3], r[0]))
    joined = sorted(set(joined), key=lambda r: (r[3], r[0]))
    return [r for r in joined if r[2] - r[0] > delta and r[3] - r[1] > delta]
