"""Tests for building/persisting multimodal (image-attached) user messages.

Two things under test:
1. app.py's _build_user_message_content -- turns pasted images + text into
   the multimodal HumanMessage content LangChain/the model providers expect,
   matching the same content-block shape MultimodalToolResultsMiddleware
   already produces for read_file's image results.
2. checkpointer.py's message_content_to_text -- shared by the session-
   snapshot writer AND the F3 history popup (clanker.ui.history_modal).
   Both must NOT dump raw base64 image data (str(content) on a multimodal
   block list would): the snapshot would bloat its JSON file forever, and
   the popup would show a wall of base64 instead of a readable transcript.
"""

from __future__ import annotations

import base64
import json

from clanker.memory.checkpointer import SessionManager, message_content_to_text
from clanker.ui.app import _build_user_message_content
from clanker.ui.clipboard_image import ClipboardImage


def test_build_user_message_content_no_images_is_plain_string() -> None:
    content = _build_user_message_content("hello there", [])
    assert content == "hello there"


def test_build_user_message_content_with_one_image() -> None:
    image = ClipboardImage(data=b"fakepngbytes", mime_type="image/png")
    content = _build_user_message_content("check this out [Image #1]", [image])

    assert isinstance(content, list)
    assert content[0] == {"type": "text", "text": "check this out [Image #1]"}
    assert content[1]["type"] == "image_url"
    expected_b64 = base64.b64encode(b"fakepngbytes").decode("utf-8")
    assert content[1]["image_url"]["url"] == f"data:image/png;base64,{expected_b64}"


def test_build_user_message_content_multiple_images_in_order() -> None:
    images = [
        ClipboardImage(data=b"first", mime_type="image/png"),
        ClipboardImage(data=b"second", mime_type="image/jpeg"),
    ]
    content = _build_user_message_content("two images", images)

    assert len(content) == 3  # text + 2 images
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert content[2]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_message_content_to_text_plain_string_passthrough() -> None:
    assert message_content_to_text("just text") == "just text"


def test_message_content_to_text_strips_image_blocks_to_placeholder() -> None:
    content = [
        {"type": "text", "text": "look at this"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + "A" * 500_000}},
    ]
    result = message_content_to_text(content)

    assert "look at this" in result
    assert "[image omitted]" in result
    assert "base64" not in result
    assert "A" * 100 not in result  # no chunk of the actual image data leaked through
    assert len(result) < 1000  # nowhere near the ~500KB of base64 that went in


def test_message_content_to_text_multiple_images() -> None:
    content = [
        {"type": "text", "text": "two shots"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,BBBB"}},
    ]
    result = message_content_to_text(content)
    assert result.count("[image omitted]") == 2


def test_session_snapshot_does_not_bloat_with_base64_image_data(tmp_path, monkeypatch) -> None:
    """End-to-end: saving a multimodal HumanMessage must not write megabytes
    of base64 into the session JSON file."""
    from langchain_core.messages import HumanMessage

    monkeypatch.chdir(tmp_path)
    sm = SessionManager(workspace_path=str(tmp_path))

    huge_b64 = base64.b64encode(b"x" * 2_000_000).decode("utf-8")  # ~2MB of image data
    msg = HumanMessage(content=[
        {"type": "text", "text": "check this screenshot"},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{huge_b64}"}},
    ])

    sm.save_conversation_snapshot([msg])

    conv_path = tmp_path / ".clanker" / "conversations" / f"{sm.session_id}.json"
    assert conv_path.exists()

    raw = conv_path.read_text()
    assert len(raw) < 10_000  # nowhere near the ~2.7MB the base64 blob alone would be
    data = json.loads(raw)
    assert data["messages"][0]["content"] == "check this screenshot\n[image omitted]"
