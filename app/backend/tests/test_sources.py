"""Upload and ingestion rules. Vision is a scripted stub: these tests cover rules, not model quality."""

import io
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import pytest

from amelia_academy import db, documents, projects, sources

import pdfmaker


REFERENCE = """Amelia is the first historical project, started in 2019.

Presence without demands means the assistant stays with the person and does not ask for more than they offer.

When someone says they feel heavy, acknowledge the detail they shared before offering anything else.
"""


@pytest.fixture
def conn(tmp_path: Path):
    c = db.connect(tmp_path / "t.sqlite3")
    projects.create(c, display_name="Test project", objective="behavior", language="en", slug="test")
    return c


def pid(conn):
    return conn.execute("SELECT id FROM projects WHERE slug = 'test'").fetchone()[0]


@pytest.fixture
def out(tmp_path: Path):
    return tmp_path / "sources"


def upload(conn, out, **over):
    args = dict(project_id=pid(conn), name="reference.md", content=REFERENCE, purpose="referência interna", license_basis="autoria própria")
    args.update(over)
    return sources.ingest(conn, out, **args)


def test_upload_requires_purpose_and_licence(conn, out):
    with pytest.raises(sources.SourceRejected, match="purpose and licence"):
        upload(conn, out, purpose="  ")
    with pytest.raises(sources.SourceRejected, match="purpose and licence"):
        upload(conn, out, license_basis="")


def test_upload_rejects_invalid_pdf_contents(conn, out):
    with pytest.raises(sources.SourceRejected, match="does not match its contents"):
        upload(conn, out, name="scan.pdf")


def test_upload_rejects_unknown_extension(conn, out):
    with pytest.raises(sources.SourceRejected, match="unsupported file type"):
        upload(conn, out, name="scan.exe")


def test_stored_under_hash_not_original_name(conn, out):
    s = upload(conn, out, name="minha conta bancária.txt")
    stored = list(out.iterdir())
    assert [p.name for p in stored] == [f"{s['sha256']}.txt"]


def test_same_bytes_same_source(conn, out):
    a = upload(conn, out)
    b = upload(conn, out, name="copia.md")
    assert a["id"] == b["id"]


def test_chunks_keep_exact_offsets(conn, out):
    s = upload(conn, out)
    assert len(s["chunks"]) >= 1
    for c in s["chunks"]:
        assert REFERENCE[c["start"]:c["end_pos"]] == c["text"]
        assert c["locator"]["offset_basis"] == "source_text"


def test_long_text_paragraph_splits_with_exact_offsets(conn, out):
    text = "abcdefghijklmnopqrstuvwxyz " * 100
    s = sources.ingest(conn, out, project_id=pid(conn), name="long.txt", content=text, purpose="test", license_basis="own")
    assert len(s["chunks"]) > 1
    assert all(len(c["text"]) <= sources.CHUNK_CHARS for c in s["chunks"])
    for c in s["chunks"]:
        assert text[c["start"]:c["end_pos"]] == c["text"]


def test_pdf_text_keeps_page_reference(conn, out):
    doc = pdfmaker.Doc()
    page = doc.new_page()
    page.insert_text((72, 72), "A source fact on page one.")
    raw = doc.tobytes()
    source = sources.ingest_bytes(conn, out, project_id=pid(conn), name="reference.pdf", data=raw,
                                  purpose="test", license_basis="own")
    assert source["status"] == "available"
    assert any("source fact" in c["text"] and c["locator"]["page"] == 1 for c in source["chunks"])


def test_pdf_text_preserves_scientific_symbols(conn, out):
    doc = pdfmaker.Doc()
    page = doc.new_page()
    fontfile = "/System/Library/Fonts/Supplemental/Arial.ttf"
    page.insert_font(fontname="unicode", fontfile=fontfile)
    page.insert_text((72, 72), "α β ~ ± µ Δ", fontname="unicode", fontsize=12)
    raw = doc.tobytes()
    source = sources.ingest_bytes(conn, out, project_id=pid(conn), name="symbols.pdf", data=raw,
                                  purpose="test", license_basis="own")
    extracted = " ".join(c["text"] for c in source["chunks"])
    assert all(symbol in extracted for symbol in ("α", "β", "~", "±", "µ", "Δ"))


BODY = "Graph traversal follows logical links between passages to answer a multi hop question well. "


def _paper() -> bytes:
    """Two columns, with what a real paper puts in the way: a title, authors, bold algorithm lines, a caption, a sidebar."""
    doc = pdfmaker.Doc()
    page = doc.new_page(width=612, height=792)
    page.insert_text((150, 60), "A Paper About Graphs", fontname="hebo", fontsize=16)
    page.insert_text((150, 85), "Ana Lima1, Rui Souza2, Eva Prado3", fontname="hebo", fontsize=11)
    page.insert_text((15, 500), "arXiv:2502.12442v2 [cs.IR]", fontname="helv", fontsize=20, rotate=90)
    page.insert_text((70, 120), "1 Method", fontname="hebo", fontsize=12)
    page.insert_textbox((70, 130, 295, 420), BODY * 8, fontname="helv", fontsize=10)
    page.insert_text((70, 435), "Figure 1: How the graph looks.", fontname="helv", fontsize=9)
    page.insert_text((70, 450), "12 else", fontname="hebo", fontsize=10)
    page.insert_text((70, 465), "Input: q, k", fontname="hebo", fontsize=10)
    page.insert_text((320, 120), "2 Results", fontname="hebo", fontsize=12)
    page.insert_textbox((320, 130, 545, 420), "Results improved over the baseline in every run we made. " * 8, fontname="helv", fontsize=10)
    page.insert_text((320, 435), "References", fontname="hebo", fontsize=12)
    page.insert_textbox((320, 445, 545, 600), "Smith, J. 2020. A cited work. Journal. " * 3, fontname="helv", fontsize=10)
    raw = doc.tobytes()
    return raw


def test_pdf_sections_come_from_font_weight_and_reading_follows_the_columns(conn, out):
    source = sources.ingest_bytes(conn, out, project_id=pid(conn), name="paper.pdf", data=_paper(), purpose="test", license_basis="own")
    headings = [c["locator"]["section"] for c in source["chunks"] if c["locator"].get("role") == "heading"]
    assert headings == ["1 Method", "2 Results", "References"]
    by_text = {c["text"].split("\n")[0][:12]: c["locator"] for c in source["chunks"]}
    assert by_text["Graph traver"]["section"] == "1 Method"
    assert by_text["Results impr"]["section"] == "2 Results"
    assert by_text["Figure 1: Ho"]["role"] == "caption"
    assert any(c["locator"].get("role") == "margin" and "arXiv" in c["text"] for c in source["chunks"])


def test_a_pdf_with_no_headings_has_no_sections(conn, out):
    doc = pdfmaker.Doc()
    doc.new_page().insert_textbox((72, 72, 500, 700), BODY * 10, fontname="helv", fontsize=10)
    raw = doc.tobytes()
    source = sources.ingest_bytes(conn, out, project_id=pid(conn), name="plain.pdf", data=raw, purpose="test", license_basis="own")
    assert source["chunks"] and not any(c["locator"].get("section") for c in source["chunks"])


def test_markdown_passages_do_not_cross_a_heading_and_keep_exact_offsets(conn, out):
    text = "Opening words.\n\n# One\n\nFirst part.\n\n```\n# not a heading\n```\n\n## Two ##\n\nSecond part.\n"
    source = sources.ingest_bytes(conn, out, project_id=pid(conn), name="n.md", data=text.encode(), purpose="test", license_basis="own")
    assert [c["locator"].get("section") for c in source["chunks"]] == [None, "One", "Two"]
    assert all(text[c["start"]:c["end_pos"]] == c["text"] for c in source["chunks"])
    assert "# not a heading" in source["chunks"][1]["text"]


def test_an_old_file_gains_its_sections_when_reread_and_old_pairs_keep_their_passage(conn, out):
    source = sources.ingest_bytes(conn, out, project_id=pid(conn), name="paper.pdf", data=_paper(), purpose="test", license_basis="own")
    conn.execute("UPDATE source_chunks SET locator_json = '{}' WHERE source_id = ?", (source["id"],))
    conn.commit()
    old_chunk = sources.get_source(conn, source["id"])["chunks"][0]["id"]
    reread = sources.reprocess_source(conn, out, source["id"])
    assert any(c["locator"].get("section") == "1 Method" for c in reread["chunks"])
    assert old_chunk not in {c["id"] for c in reread["chunks"]}
    assert conn.execute("SELECT 1 FROM source_chunks WHERE id = ?", (old_chunk,)).fetchone()


def test_reading_a_file_from_an_older_extractor_extracts_it_once(conn, out):
    source = sources.ingest_bytes(conn, out, project_id=pid(conn), name="paper.pdf", data=_paper(), purpose="test", license_basis="own")
    current = sources.get_source(conn, source["id"])["chunks"][0]["id"]
    sources.use_current_extractor(conn, out, source["id"])
    assert sources.get_source(conn, source["id"])["chunks"][0]["id"] == current

    conn.execute("UPDATE source_ingestions SET extractor_version = '1.0' WHERE source_id = ?", (source["id"],))
    conn.execute("UPDATE source_chunks SET locator_json = '{}' WHERE source_id = ?", (source["id"],))
    conn.commit()
    sources.use_current_extractor(conn, out, source["id"])
    chunks = sources.get_source(conn, source["id"])["chunks"]
    assert chunks[0]["id"] != current
    assert any(c["locator"].get("section") == "1 Method" for c in chunks)

    sources.use_current_extractor(conn, out, source["id"])
    assert sources.get_source(conn, source["id"])["chunks"][0]["id"] == chunks[0]["id"]


class Vision:
    """Stands in for the vision model: records what it was given and returns a scripted transcription."""

    def __init__(self, text="HELLO AMELIA 2026", error=None):
        self.model = "vision-stub"
        self.text = text
        self.error = error
        self.seen = []

    def read_image(self, png):
        self.seen.append(png)
        if self.error:
            raise RuntimeError(self.error)
        return self.text


def _png(width=1200, height=260):
    image = Image.new("RGB", (width, height), "white")
    ImageDraw.Draw(image).text((35, 80), "SCAN", fill="black", font=ImageFont.load_default(size=80))
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def test_raster_image_is_saved_and_model_text_points_back_to_asset(conn, out):
    vision = Vision()
    source = sources.ingest_bytes(conn, out, project_id=pid(conn), name="scan.png", data=_png(), purpose="test",
                                  license_basis="own", vision=vision)
    assert len(vision.seen) == 1
    asset = source["assets"][0]
    assert asset["kind"] == "uploaded_image"
    assert asset["ocr_status"] == "completed"
    assert asset["ocr_model"] == "vision-stub"
    chunk = next(c for c in source["chunks"] if c["kind"] == "ocr_text")
    assert chunk["text"] == "HELLO AMELIA 2026"
    assert chunk["asset_id"] == asset["id"]
    assert chunk["locator"]["ocr_model"] == "vision-stub"
    assert asset["url"].endswith(asset["id"])


def test_extracting_again_keeps_what_a_vision_model_read_and_calls_no_model(conn, out):
    vision = Vision("A curve falls as the rate grows.")
    source = sources.ingest_bytes(conn, out, project_id=pid(conn), name="scan.png", data=_png(), purpose="test",
                                  license_basis="own", vision=vision)
    read = source["assets"][0]
    assert read["ocr_model"] == "vision-stub"
    calls = len(vision.seen)
    conn.execute("UPDATE source_ingestions SET extractor_version = '1.0' WHERE source_id = ?", (source["id"],))
    conn.commit()
    sources.use_current_extractor(conn, out, source["id"])
    again = sources.get_source(conn, source["id"])
    asset = again["assets"][0]
    assert asset["id"] != read["id"] and asset["ocr_model"] == "vision-stub"
    assert (asset["ocr_text"], asset["figure_reading"]) == (read["ocr_text"], read["figure_reading"])
    assert {c["text"] for c in again["chunks"]} == {c["text"] for c in source["chunks"]}
    assert again["latest_ingestion"]["warnings"] == [] and again["status"] == "available"
    assert len(vision.seen) == calls


def test_a_figure_reading_is_stored_apart_from_the_visible_text(conn, out):
    class Figures(Vision):
        def read_figure(self, png):
            self.seen.append(png)
            return {"visible_text": "bits / pixel", "reading": "A curve falls as the rate grows."}

    source = sources.ingest_bytes(conn, out, project_id=pid(conn), name="scan.png", data=_png(), purpose="test",
                                  license_basis="own", vision=Figures())
    asset = source["assets"][0]
    assert asset["ocr_text"] == "bits / pixel"
    assert asset["figure_reading"] == "A curve falls as the rate grows."
    assert any(c["kind"] == "figure_reading" and c["text"].startswith("A curve") for c in source["chunks"])
    assert any(c["kind"] == "ocr_text" and c["text"] == "bits / pixel" for c in source["chunks"])


def test_pdf_embedded_scan_keeps_page_and_image_reference(conn, out):
    doc = pdfmaker.Doc()
    page = doc.new_page()
    page.insert_image((50, 50, 550, 200), stream=_png())
    raw = doc.tobytes()
    source = sources.ingest_bytes(conn, out, project_id=pid(conn), name="scan.pdf", data=raw, purpose="test",
                                  license_basis="own", vision=Vision("PAGE SCAN HELLO"))
    chunk = next(c for c in source["chunks"] if c["kind"] == "ocr_text")
    assert chunk["locator"]["page"] == 1
    assert chunk["asset_id"] is not None
    assert "PAGE SCAN" in chunk["text"]


def test_image_without_vision_model_is_stored_but_unread_and_says_so(conn, out):
    source = sources.ingest_bytes(conn, out, project_id=pid(conn), name="scan.png", data=_png(), purpose="test", license_basis="own")
    assert source["assets"][0]["ocr_status"] == "not_attempted"
    assert source["assets"][0]["ocr_model"] is None
    assert not [c for c in source["chunks"] if c["kind"] == "ocr_text"]
    assert source["status"] == "partial"
    assert any("no vision model configured" in w for w in source["latest_ingestion"]["warnings"])


def test_vision_failure_is_recorded_not_retried_elsewhere(conn, out):
    vision = Vision(error="ollama unreachable")
    source = sources.ingest_bytes(conn, out, project_id=pid(conn), name="scan.png", data=_png(), purpose="test",
                                  license_basis="own", vision=vision)
    assert len(vision.seen) == 1
    assert source["assets"][0]["ocr_status"] == "failed"
    assert source["assets"][0]["ocr_model"] == "vision-stub"
    assert source["status"] == "partial"
    assert any("figure reading failed" in w for w in source["latest_ingestion"]["warnings"])


def test_tiny_image_is_not_sent_to_the_model(conn, out):
    vision = Vision()
    source = sources.ingest_bytes(conn, out, project_id=pid(conn), name="icon.png", data=_png(20, 20), purpose="test",
                                  license_basis="own", vision=vision)
    assert vision.seen == []
    assert source["assets"][0]["ocr_status"] == "skipped"


def test_docx_paragraph_and_table_rows_keep_locators(conn, out):
    from docx import Document
    document = Document()
    document.add_paragraph("A DOCX reference paragraph.")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "category"
    table.cell(0, 1).text = "support"
    stream = io.BytesIO()
    document.save(stream)
    source = sources.ingest_bytes(conn, out, project_id=pid(conn), name="reference.docx", data=stream.getvalue(),
                                  purpose="test", license_basis="own")
    assert any(c["locator"].get("type") == "docx_paragraph" for c in source["chunks"])
    assert any(c["kind"] == "table_row" and "support" in c["text"] for c in source["chunks"])


def test_xlsx_rows_keep_sheet_and_row_references(conn, out):
    from openpyxl import Workbook
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Categories"
    sheet.append(["Category", "Guideline"])
    sheet.append(["Presence", "Offer support without pressure"])
    stream = io.BytesIO()
    workbook.save(stream)
    source = sources.ingest_bytes(conn, out, project_id=pid(conn), name="reference.xlsx", data=stream.getvalue(),
                                  purpose="test", license_basis="own")
    assert any(c["locator"].get("sheet") == "Categories" and c["locator"].get("row_start") == 1 for c in source["chunks"])
    assert any("Presence" in c["text"] for c in source["chunks"])


def _picture(color: str, side: int = 400) -> bytes:
    from io import BytesIO
    from PIL import Image
    out = BytesIO()
    Image.new("RGB", (side, side), color).save(out, format="PNG")
    return out.getvalue()


def _pdf_with_images(placed: list[tuple[bytes, float]]) -> bytes:
    doc = pdfmaker.Doc()
    page = doc.new_page()
    page.insert_text((72, 40), "A source fact beside the pictures.")
    y = 60.0
    for image, side in placed:
        page.insert_image((72, y, 72 + side, y + side), stream=image)
        y += side + 4
    raw = doc.tobytes()
    return raw


def _ingest_images(conn, out, placed):
    return sources.ingest_bytes(conn, out, project_id=pid(conn), name="figures.pdf", data=_pdf_with_images(placed),
                                purpose="test", license_basis="own")


def test_an_icon_drawn_small_is_left_out_even_when_stored_large_and_the_figure_stays(conn, out):
    doc = pdfmaker.Doc()
    page = doc.new_page()
    page.insert_text((72, 40), "A source fact beside the pictures.")
    page.insert_image((72, 60, 92, 80), stream=_picture("red", 1000))
    page.insert_image((72, 300, 272, 500), stream=_picture("blue", 100))
    raw = doc.tobytes()
    source = sources.ingest_bytes(conn, out, project_id=pid(conn), name="icon-and-figure.pdf", data=raw, purpose="test", license_basis="own")
    assert len(source["assets"]) == 1
    assert source["assets"][0]["locator"]["bbox"][2] - source["assets"][0]["locator"]["bbox"][0] > 100
    assert any("1 image(s) left out as decoration: 1 drawn under half an inch" in w for w in source["latest_ingestion"]["warnings"])


def test_the_same_figure_drawn_twice_is_kept_once(conn, out):
    picture = _picture("green")
    source = _ingest_images(conn, out, [(picture, 100), (picture, 100), (_picture("blue"), 100)])
    assert len(source["assets"]) == 2
    assert any("1 repeated" in w for w in source["latest_ingestion"]["warnings"])


def test_an_image_just_above_the_limit_is_kept(conn, out):
    source = _ingest_images(conn, out, [(_picture("red"), documents.MIN_FIGURE_POINTS + 1)])
    assert len(source["assets"]) == 1


def test_leaving_decoration_out_does_not_make_the_file_partial(conn, out):
    doc = pdfmaker.Doc()
    page = doc.new_page()
    page.insert_text((72, 72), "A source fact on page one.")
    page.insert_image((72, 90, 90, 108), stream=_picture("red"))
    raw = doc.tobytes()
    source = sources.ingest_bytes(conn, out, project_id=pid(conn), name="icon.pdf", data=raw, purpose="test", license_basis="own")
    assert source["status"] == "available"
    assert source["assets"] == []


def test_an_image_uploaded_by_itself_is_never_called_decoration(conn, out):
    source = sources.ingest_bytes(conn, out, project_id=pid(conn), name="small.png", data=_picture("red", 60), purpose="test", license_basis="own")
    assert len(source["assets"]) == 1


def _built_figure_pdf(extra_figure: bool = False) -> bytes:
    """A figure drawn from small pictures, with labels and a line, above a caption and a paragraph."""
    doc = pdfmaker.Doc()
    page = doc.new_page()
    colors = ["red", "green", "blue", "orange", "purple", "black", "gray", "pink", "brown"]
    for i, color in enumerate(colors):
        x = 100 + (i % 3) * 40
        y = 100 + (i // 3) * 40
        page.insert_image((x, y, x + 20, y + 20), stream=_picture(color))
    page.draw_rect((85, 90, 90, 205), fill=(0, 0, 0))
    page.insert_text((100, 95), "Offline")
    page.insert_textbox((72, 215, 540, 260), "Figure 1: How the pieces fit together in this method.", fontsize=10)
    page.insert_textbox((72, 270, 540, 400), BODY * 4, fontsize=10)
    page.insert_image((72, 420, 90, 438), stream=_picture("cyan"))
    if extra_figure:
        page.insert_image((150, 500, 350, 700), stream=_picture("white"))
    raw = doc.tobytes()
    return raw


def _ingest_built(conn, out, **kw):
    return sources.ingest_bytes(conn, out, project_id=pid(conn), name="built.pdf", data=_built_figure_pdf(**kw), purpose="test", license_basis="own")


def test_a_figure_made_of_small_pictures_comes_back_whole(conn, out):
    source = _ingest_built(conn, out)
    built = [a for a in source["assets"] if a["kind"] == "pdf_figure"]
    assert len(built) == 1
    x0, y0, x1, y1 = built[0]["locator"]["bbox"]
    assert x0 <= 90 and y0 <= 95 and x1 >= 200 and y1 >= 200  # the line and the label are inside
    assert y1 < 215  # the caption is not
    assert any("1 figure(s) put back together from 9 pieces" in w for w in source["latest_ingestion"]["warnings"])


def test_an_icon_far_from_the_figure_is_still_decoration(conn, out):
    source = _ingest_built(conn, out)
    assert len(source["assets"]) == 1
    assert any("1 drawn under half an inch" in w for w in source["latest_ingestion"]["warnings"])


def test_an_ordinary_figure_beside_a_built_one_keeps_its_own_bytes(conn, out):
    source = _ingest_built(conn, out, extra_figure=True)
    assert sorted(a["kind"] for a in source["assets"]) == ["pdf_figure", "pdf_image"]


def test_a_page_with_no_small_picture_is_never_rebuilt(conn, out):
    source = _ingest_images(conn, out, [(_picture("red"), 100), (_picture("blue"), 100)])
    assert {a["kind"] for a in source["assets"]} == {"pdf_image"}


def test_labels_inside_the_figure_are_not_passages_and_the_caption_keeps_its_role(conn, out):
    source = _ingest_built(conn, out)
    roles = {c["text"].split()[0]: c["locator"].get("role") for c in source["chunks"] if c["kind"] == "text"}
    assert roles["Offline"] == "figure_label"
    assert roles["Figure"] == "caption"
    assert roles["Graph"] is None


def test_cc_by_license_suggestion_reads_pdf_metadata(conn, out):
    doc = pdfmaker.Doc()
    doc.new_page().insert_text((72, 72), REFERENCE)
    doc.set_metadata({"title": "Paper", "keywords": "CC BY 4.0"})
    raw = doc.tobytes()
    source = sources.ingest_bytes(conn, out, project_id=pid(conn), name="licensed.pdf", data=raw,
                                  purpose="test", license_basis="unspecified")
    full = sources.get_source(conn, source["id"])
    suggestion = sources.license_suggestion(conn, full, out)
    assert suggestion == {"license_basis": "open-license", "label": "Open license · CC BY 4.0", "evidence": "CC BY 4.0"}


def test_cc_by_license_suggestion_reads_pdf_text_and_skips_declared_rights(conn, out):
    doc = pdfmaker.Doc()
    doc.new_page().insert_textbox((72, 72, 520, 720), "CC BY 4.0. " + REFERENCE)
    raw = doc.tobytes()
    source = sources.ingest_bytes(conn, out, project_id=pid(conn), name="licensed-text.pdf", data=raw,
                                  purpose="test", license_basis="unspecified")
    full = sources.get_source(conn, source["id"])
    assert sources.license_suggestion(conn, full, out)["license_basis"] == "open-license"
    full["license_basis"] = "own"
    assert sources.license_suggestion(conn, full, out) is None


def test_cc_by_license_suggestion_accepts_plos_attribution_wording(conn, out):
    doc = pdfmaker.Doc()
    doc.new_page().insert_textbox((72, 72, 520, 720),
        "This is an open-access article distributed under the terms of the Creative Commons Attribution License.")
    raw = doc.tobytes()
    source = sources.ingest_bytes(conn, out, project_id=pid(conn), name="plos.pdf", data=raw,
                                  purpose="test", license_basis="unspecified")
    assert sources.license_suggestion(conn, sources.get_source(conn, source["id"]), out)["license_basis"] == "open-license"
