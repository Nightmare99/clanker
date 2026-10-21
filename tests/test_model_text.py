"""Provider-independent reasoning separation and stream marker boundaries."""

import pytest

from clanker.ui.model_text import ModelText


@pytest.mark.parametrize("tag", ["think", "thinking"])
@pytest.mark.parametrize("closed", [False, True])
def test_thinking_tags_at_every_chunk_boundary(tag, closed):
    source = f"<{tag}>Private reasoning" + (f"</{tag}>Final answer" if closed else "")
    for index in range(len(source) + 1):
        text = ModelText()
        text.add(source[:index], {})
        text.add(source[index:], {})
        text.finish()
        assert text.thinking == "Private reasoning", index
        assert text.response == ("Final answer" if closed else ""), index
        assert text.thinking_first


def test_reasoning_and_answer_in_same_delta_are_both_preserved():
    text = ModelText()
    text.add("Final answer", {"reasoning_text": "Private reasoning"})
    text.finish()
    assert text.response == "Final answer"
    assert text.thinking == "Private reasoning"
    assert text.thinking_first


def test_encrypted_reasoning_and_signatures_never_become_display_text():
    text = ModelText()
    text.add([
        {"type": "reasoning", "encrypted_content": "secret", "summary": []},
        {"type": "redacted_thinking", "data": "redacted"},
        {"type": "thinking", "signature": "signature"},
        {"type": "text", "text": "Answer"},
    ], {"reasoning_opaque": "opaque"})
    text.finish()
    assert text.response == "Answer"
    assert not text.has_thinking


def test_reasoning_aliases_do_not_duplicate_visible_thinking():
    text = ModelText()
    text.add([{"type": "reasoning", "reasoning": "Private reasoning"}], {
        "reasoning_text": "Private reasoning", "reasoning": "Private reasoning",
    })
    text.finish()
    assert text.thinking == "Private reasoning"


def test_multiple_thinking_sections_and_literal_partial_markers():
    text = ModelText()
    for chunk in ["<think>a</th", "ink>before<thinking>b</thinking>after <th"]:
        text.add(chunk, {})
    text.finish()
    assert text.thinking == "ab"
    assert text.response == "beforeafter <th"
