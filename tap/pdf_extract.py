# Time & Attendance Processor
# Author: Isheanesu Zvikaramba
# Copyright (c) 2026 Zvicasso Technologies (Pty) Ltd. All rights reserved.
"""PDF text extraction with word coordinates.

The report is a column layout where long values (clock names, "am"/"pm")
wrap onto a second line, so plain text extraction is ambiguous. We extract
every word with its x/y position and let the parser assign words to columns.

Primary engine: pypdfium2 (fast, ~3 s for 450 pages; installed with pdfplumber).
Fallback engine: pdfplumber (slower, pure Python), used per page if pdfium
returns inconsistent text, or for the whole file if pdfium cannot open it.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Iterator

from .models import Line, Word

log = logging.getLogger(__name__)

ProgressFn = Callable[[int, int], None]

_WS = {" ", "\r", "\n", "\t", "\x00", "￾", "\xa0", "\x02"}
_LINE_TOL = 2.5  # points: words whose tops differ less than this are on one line
_WORD_GAP = 2.5  # points: horizontal gap that splits a word even without a space


class PdfExtractionError(Exception):
    """Raised with a message that is safe and useful to show to the user."""


class EncryptedPdfError(PdfExtractionError):
    pass


class ImageBasedPdfError(PdfExtractionError):
    pass


def _group_lines(words: list[Word], page_no: int) -> list[Line]:
    words = sorted(words, key=lambda w: (round(w.top, 1), w.x0))
    lines: list[Line] = []
    for w in words:
        if lines and abs(lines[-1].top - w.top) <= _LINE_TOL:
            lines[-1].words.append(w)
        else:
            lines.append(Line(page=page_no, top=w.top, words=[w]))
    for ln in lines:
        ln.words.sort(key=lambda w: w.x0)
    return lines


# --------------------------------------------------------------------------- pdfium
def _pdfium_page_words(page, page_no: int) -> list[Word] | None:
    tp = page.get_textpage()
    try:
        n = tp.count_chars()
        if n == 0:
            return []
        text = tp.get_text_range(0, n)
        if len(text) != n:
            return None  # surrogate pairs etc. -> let pdfplumber handle this page
        height = page.get_height()
        words: list[Word] = []
        buf: list[str] = []
        bx0 = bx1 = btop = 0.0
        for i, ch in enumerate(text):
            if ch in _WS:
                if buf:
                    words.append(Word("".join(buf), bx0, bx1, btop, page_no))
                    buf = []
                continue
            left, bottom, right, top = tp.get_charbox(i, loose=True)
            ctop = height - top
            if buf and (left - bx1 > _WORD_GAP or abs(ctop - btop) > _LINE_TOL):
                words.append(Word("".join(buf), bx0, bx1, btop, page_no))
                buf = []
            if not buf:
                bx0, btop = left, ctop
            buf.append(ch)
            bx1 = right
        if buf:
            words.append(Word("".join(buf), bx0, bx1, btop, page_no))
        return words
    finally:
        tp.close()


def _pdfplumber_page_words(source: Path | bytes, page_index: int) -> list[Word]:
    import io

    import pdfplumber

    src = io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source
    with pdfplumber.open(src) as pdf:
        pg = pdf.pages[page_index]
        return [
            Word(w["text"], w["x0"], w["x1"], w["top"], page_index + 1)
            for w in pg.extract_words(keep_blank_chars=False, use_text_flow=False)
        ]


def _page_has_images_pdfium(page) -> bool:
    try:
        import pypdfium2.raw as raw

        for obj in page.get_objects():
            if obj.type == raw.FPDF_PAGEOBJ_IMAGE:
                return True
    except Exception:  # pragma: no cover - defensive
        return False
    return False


def open_and_check(source: Path | bytes):
    """Open with pdfium and translate failures into user-facing errors."""
    import pypdfium2 as pdfium

    try:
        return pdfium.PdfDocument(source if isinstance(source, (bytes, bytearray)) else str(source))
    except pdfium.PdfiumError as exc:
        msg = str(exc).lower()
        if "password" in msg or "security" in msg:
            raise EncryptedPdfError(
                "This PDF is password-protected. Remove the password (re-export the report "
                "without protection) and upload it again."
            ) from exc
        raise PdfExtractionError(
            "The file could not be opened as a PDF. It may be damaged or not a real PDF "
            f"(detail: {exc})."
        ) from exc


def extract_lines(source: Path | str | bytes, progress: ProgressFn | None = None,
                  max_pages: int | None = None) -> Iterator[Line]:
    """Yield text lines (with word positions) for every page in order.

    `source` may be a file path or the PDF bytes. `max_pages` limits reading
    (used to preview the report header before full processing).
    """
    pdf_path = source if isinstance(source, (bytes, bytearray)) else Path(source)
    doc = open_and_check(pdf_path)
    try:
        n_pages = len(doc)
        if n_pages == 0:
            raise PdfExtractionError("The PDF contains no pages.")
        full_read = max_pages is None or max_pages >= n_pages
        if not full_read:
            n_pages = max_pages
        empty_pages: list[int] = []
        image_pages = 0
        for idx in range(n_pages):
            page = doc[idx]
            try:
                words = _pdfium_page_words(page, idx + 1)
                if words is None:
                    log.info("page %d: falling back to pdfplumber", idx + 1)
                    words = _pdfplumber_page_words(pdf_path, idx)
                if not words:
                    empty_pages.append(idx + 1)
                    if _page_has_images_pdfium(page):
                        image_pages += 1
                    # Early detection: first pages scanned -> whole document is probably scanned
                    if idx == min(4, n_pages - 1) and len(empty_pages) == idx + 1 and image_pages:
                        raise ImageBasedPdfError(_image_msg())
                for line in _group_lines(words, idx + 1):
                    yield line
            finally:
                page.close()
            if progress:
                progress(idx + 1, n_pages)
        if full_read and len(empty_pages) == n_pages:
            if image_pages:
                raise ImageBasedPdfError(_image_msg())
            raise PdfExtractionError("The PDF contains no readable text.")
    finally:
        doc.close()


def page_count(source: Path | str | bytes) -> int:
    doc = open_and_check(source if isinstance(source, (bytes, bytearray)) else Path(source))
    try:
        return len(doc)
    finally:
        doc.close()


def _image_msg() -> str:
    return (
        "This PDF appears to be a scanned image rather than a text report, so the "
        "attendance values cannot be read reliably. OCR is not used in this version "
        "because misread times would produce wrong late/early classifications. "
        "Please export the report directly from the access-control system "
        "(e.g. Print to PDF / Save as PDF from the report viewer) and upload that file."
    )
