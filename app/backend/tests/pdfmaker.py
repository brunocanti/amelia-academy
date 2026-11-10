"""Small PDFs for tests, written with reportlab (BSD) and placed top-down the way a reader measures a page."""
from __future__ import annotations

import io

from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

FONTS = {"helv": "Helvetica", "hebo": "Helvetica-Bold"}
A4 = (595.0, 842.0)
LINE_HEIGHT = 1.2  # baseline to baseline, in font sizes

Rect = tuple[float, float, float, float]


class Page:
    def __init__(self, width: float, height: float):
        self.width, self.height = width, height
        self.ops: list = []

    def insert_font(self, fontname: str, fontfile: str) -> None:
        if fontname not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(fontname, fontfile))
        FONTS.setdefault(fontname, fontname)

    def insert_text(self, point: tuple[float, float], text: str, fontname: str = "helv", fontsize: float = 11, rotate: int = 0) -> None:
        """`point` is where the baseline starts; `rotate` turns the line counter-clockwise."""
        self.ops.append(("text", point, text, FONTS[fontname], fontsize, rotate))

    def insert_textbox(self, rect: Rect, text: str, fontname: str = "helv", fontsize: float = 11) -> None:
        """Wrapped to the box width; lines that do not fit in the box are left out."""
        font = FONTS[fontname]
        x0, y0, x1, y1 = rect
        y = y0 + fontsize
        for line in simpleSplit(text, font, fontsize, x1 - x0):
            if y > y1:
                break
            self.insert_text((x0, y), line, fontname, fontsize)
            y += fontsize * LINE_HEIGHT

    def insert_image(self, rect: Rect, stream: bytes) -> None:
        self.ops.append(("image", rect, stream))

    def draw_rect(self, rect: Rect, fill: tuple[float, float, float] = (0, 0, 0)) -> None:
        self.ops.append(("rect", rect, fill))

    def draw(self, c: canvas.Canvas) -> None:
        h = self.height
        for op in self.ops:
            if op[0] == "text":
                _, (x, y), text, font, size, rotate = op
                c.saveState()
                c.translate(x, h - y)
                c.rotate(rotate)
                c.setFont(font, size)
                c.drawString(0, 0, text)
                c.restoreState()
            elif op[0] == "image":
                _, (x0, y0, x1, y1), stream = op
                c.drawImage(ImageReader(io.BytesIO(stream)), x0, h - y1, x1 - x0, y1 - y0)
            else:
                _, (x0, y0, x1, y1), fill = op
                c.setFillColorRGB(*fill)
                c.rect(x0, h - y1, x1 - x0, y1 - y0, stroke=0, fill=1)


class Doc:
    def __init__(self):
        self.pages: list[Page] = []
        self.metadata: dict[str, str] = {}

    def new_page(self, width: float = A4[0], height: float = A4[1]) -> Page:
        self.pages.append(Page(width, height))
        return self.pages[-1]

    def set_metadata(self, metadata: dict[str, str]) -> None:
        self.metadata.update(metadata)

    def tobytes(self) -> bytes:
        out = io.BytesIO()
        c = canvas.Canvas(out, invariant=1)
        for key, value in self.metadata.items():
            getattr(c, "set" + key.capitalize())(value)
        for page in self.pages or [Page(*A4)]:
            c.setPageSize((page.width, page.height))
            page.draw(c)
            c.showPage()
        c.save()
        return out.getvalue()
