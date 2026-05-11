from __future__ import annotations

from pathlib import Path

import pytest

from engram.pdf import extract_pdf_text


def _make_pdf(tmp_path: Path, text: str) -> Path:
    pypdf = pytest.importorskip("pypdf")
    from pypdf import PdfWriter
    from pypdf.generic import (
        ArrayObject,
        DecodedStreamObject,
        DictionaryObject,
        FloatObject,
        NameObject,
        NumberObject,
    )

    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    # Build a minimal content stream that draws the text via Tj.
    safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream_data = f"BT\n/F1 12 Tf\n72 720 Td\n({safe}) Tj\nET\n".encode("latin-1")
    content = DecodedStreamObject()
    content.set_data(stream_data)
    page[NameObject("/Contents")] = writer._add_object(content)

    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    resources = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
    )
    page[NameObject("/Resources")] = resources
    page[NameObject("/MediaBox")] = ArrayObject(
        [NumberObject(0), NumberObject(0), FloatObject(612), FloatObject(792)]
    )

    pdf_path = tmp_path / "x.pdf"
    with pdf_path.open("wb") as f:
        writer.write(f)
    return pdf_path


def test_extract_pdf_text_reads_text(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path, "Hello PDF World")
    out = extract_pdf_text(pdf)
    assert "Hello" in out and "World" in out


def test_extract_pdf_text_returns_empty_on_corrupt(tmp_path: Path) -> None:
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"this is not a pdf")
    assert extract_pdf_text(bad) == ""
