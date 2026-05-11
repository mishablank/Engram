from __future__ import annotations

import base64
import logging
from pathlib import Path

from anthropic import Anthropic

from .config import VISION_MODEL

log = logging.getLogger(__name__)

OCR_PROMPT = (
    "Extract all human-readable text visible in this image. "
    "If it is a screenshot of a tweet, article, message, or document, transcribe the text faithfully and preserve order. "
    "If it is a screenshot of a UI, transcribe visible labels and text content. "
    "If it is a photo with no meaningful text, respond with the single word: NONE. "
    "Do NOT add commentary, headings, descriptions, or quotation marks — only the extracted text."
)


def ocr_image(image_path: Path, client: Anthropic) -> str | None:
    try:
        data = base64.b64encode(image_path.read_bytes()).decode()
    except OSError as e:
        log.warning("Could not read image %s: %s", image_path, e)
        return None

    media_type = "image/jpeg"
    suffix = image_path.suffix.lower()
    if suffix == ".png":
        media_type = "image/png"
    elif suffix in (".gif",):
        media_type = "image/gif"
    elif suffix in (".webp",):
        media_type = "image/webp"

    try:
        resp = client.messages.create(
            model=VISION_MODEL,
            max_tokens=2000,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": data,
                            },
                        },
                        {"type": "text", "text": OCR_PROMPT},
                    ],
                }
            ],
        )
    except Exception as e:
        log.warning("OCR failed for %s: %s", image_path, e)
        return None

    text = "".join(
        block.text for block in resp.content if getattr(block, "type", None) == "text"
    ).strip()
    if not text or text.upper() == "NONE":
        return None
    log.info("OCR extracted %d chars from %s", len(text), image_path.name)
    return text
