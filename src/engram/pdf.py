from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

MAX_PAGES = 50


def extract_pdf_text(path: Path, max_pages: int = MAX_PAGES) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        log.warning("pypdf not installed; cannot extract PDF text")
        return ""
    try:
        reader = PdfReader(str(path))
    except Exception as e:
        log.warning("Could not open PDF %s: %s", path, e)
        return ""
    chunks: list[str] = []
    for i, page in enumerate(reader.pages):
        if i >= max_pages:
            chunks.append(f"[truncated after {max_pages} pages]")
            break
        try:
            chunks.append(page.extract_text() or "")
        except Exception as e:
            log.warning("Page %d extraction failed for %s: %s", i, path, e)
    text = "\n\n".join(c.strip() for c in chunks if c and c.strip())
    if text:
        log.info("Extracted %d chars from %s", len(text), path.name)
    return text
