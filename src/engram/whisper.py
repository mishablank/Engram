from __future__ import annotations

import logging
from pathlib import Path

from openai import OpenAI

log = logging.getLogger(__name__)

MODEL = "whisper-1"


def transcribe(audio_path: Path, api_key: str) -> str | None:
    try:
        client = OpenAI(api_key=api_key)
        with open(audio_path, "rb") as f:
            resp = client.audio.transcriptions.create(model=MODEL, file=f)
        text = (resp.text or "").strip()
        if not text:
            return None
        log.info("Transcribed %s (%d chars)", audio_path.name, len(text))
        return text
    except Exception as e:
        log.warning("Whisper transcription failed for %s: %s", audio_path, e)
        return None
