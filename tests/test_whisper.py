from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tg_obsidian_bot.whisper import transcribe


def test_transcribe_returns_text(tmp_path: Path):
    audio = tmp_path / "voice.ogg"
    audio.write_bytes(b"OggS" + b"\x00" * 100)
    with patch("tg_obsidian_bot.whisper.OpenAI") as Client:
        Client.return_value.audio.transcriptions.create.return_value = SimpleNamespace(
            text="  hello there  "
        )
        out = transcribe(audio, "sk-test")
    assert out == "hello there"


def test_transcribe_returns_none_on_empty_text(tmp_path: Path):
    audio = tmp_path / "voice.ogg"
    audio.write_bytes(b"OggS" + b"\x00" * 100)
    with patch("tg_obsidian_bot.whisper.OpenAI") as Client:
        Client.return_value.audio.transcriptions.create.return_value = SimpleNamespace(text="")
        assert transcribe(audio, "sk-test") is None


def test_transcribe_returns_none_on_api_error(tmp_path: Path):
    audio = tmp_path / "voice.ogg"
    audio.write_bytes(b"OggS")
    with patch("tg_obsidian_bot.whisper.OpenAI") as Client:
        Client.return_value.audio.transcriptions.create.side_effect = RuntimeError("boom")
        assert transcribe(audio, "sk-test") is None
