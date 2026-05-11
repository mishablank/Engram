from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from tg_obsidian_bot.vision import ocr_image


def _fake_response(text: str):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


def test_ocr_returns_extracted_text(tmp_path: Path):
    img = tmp_path / "screenshot.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    client = MagicMock()
    client.messages.create.return_value = _fake_response("Hello world\nLine two")
    out = ocr_image(img, client)
    assert out == "Hello world\nLine two"
    sent = client.messages.create.call_args.kwargs
    assert sent["messages"][0]["content"][0]["source"]["media_type"] == "image/png"


def test_ocr_returns_none_when_model_says_none(tmp_path: Path):
    img = tmp_path / "blank.jpg"
    img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)
    client = MagicMock()
    client.messages.create.return_value = _fake_response("NONE")
    assert ocr_image(img, client) is None


def test_ocr_returns_none_on_api_error(tmp_path: Path):
    img = tmp_path / "x.jpg"
    img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 50)
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("boom")
    assert ocr_image(img, client) is None
