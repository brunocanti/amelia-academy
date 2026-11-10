# ADR 020: PDFs are read with pdfplumber and pypdfium2, not PyMuPDF

- **Status:** Accepted
- **Date:** 2026-11-10
- **Scope:** PDF extraction in Amelia Academy (`app/backend`)

## Context

Amelia Academy is to be published under MIT. PyMuPDF is AGPL-3.0, and shipping it would put the whole app under AGPL terms. The backend used it for five things: text blocks with font, size and boxes (reading order and block roles); full-page renders; clusters of vector drawings (built figures); clipped figure renders; and PDF metadata (license suggestion).

## Decision

`amelia_academy/pdf.py` wraps two permissive libraries behind the small interface `documents.py` needs:

- **pdfplumber 0.11.10** (MIT, on pdfminer.six) for characters with font, size, matrix and advance, and for vector drawings. `pdf.py` joins characters into lines and blocks shaped like PyMuPDF's `get_text("dict")`, so `_reading_order` and `_block_role` did not change. Fonts are marked bold from their font descriptor (FontWeight ≥ 600 or ForceBold) or a TeX bold font name (CMBX and similar).
- **pypdfium2 5.15.2** (Apache-2.0 / BSD-3) for image objects (placement and bytes, with forms opened), page renders and clipped renders, and metadata.
- The drawing clusters follow MuPDF's `cluster_drawings` algorithm: neighbours within 3 pt, sorted by `(y1, x0)`, with clusters of width or height of 3 pt or less dropped.
- Test PDFs are written with **reportlab 5.1.0** (BSD) through `tests/pdfmaker.py`. It is a test-only dependency.
- `EXTRACTOR_VERSION` is 1.4, so stored sources show as due for re-extraction.

## Before / after on the four PLOS tardigrade papers (`app/var/sources/`)

The order ratio is difflib's ratio over the word sequence of all elements in reading order. Headings, captions and figures are compared element by element.

| PDF | Blocks old→new | Words old→new | Order ratio | Headings | Captions | Figures |
|---|---|---|---|---|---|---|
| 7204e26d, heat-soluble protein families | 90→91 | 5017→5016 | 0.9999 | same (1) | 4/4 | same (4) |
| 8e4bbaf3, cell stiffening (Discovery Report) | 299→309 | 15256→15255 | 1.0000 | 30 vs 29: see below | 4/4 | same (4) |
| ba4de382, proteins in yeast | 230→225 | 8001→8001 | 0.9885 | same (18) | 7/7 | same (6) |
| dfdc950e, DNA repair in *R. varieornatus* | 133→138 | 6952→6953 | 0.9994 | same (0) | 7/7 | same (6); 2 boxes differ by ≤0.13 pt |

Known differences:

- **8e4bbaf3:** PyMuPDF gave one heading, "Materials and methods Animals". The new reader gives "Materials and methods" and "Animals" as two headings, since they are a section and its first subsection. Every other heading matches.
- **ba4de382:** MuPDF reports line-end soft hyphens as U+00AD, and pdfminer reports them as "-". Quote matching (`sources._quote_key`) treats both the same at a line break. One display equation's pieces come out in a different order, and two short passages ("or solvents…", "New England Biolabs") sit one block earlier or later.
- **Block counts** differ by a few blocks because paragraphs split slightly differently. Roles and sections are unaffected on these files.
- **Non-PLOS PDFs** in `app/var/sources/` (arXiv/ICLR papers) have larger block-count differences: the new reader keeps more lines of a paragraph together. Order ratios are 0.955 to 0.996. Those files were not part of the acceptance check.
