"""Tests for notify tool rendering in streaming.

Verifies that notify messages are rendered exactly once in TUI mode (via the
``_pending_notifies`` flush) and exactly once in CLI mode (via
``console.print_notify``).  Regression test for a bug where the ``on_tool_end``
handler for ``notify`` duplicated the message in the TUI chat log.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from clanker.ui.chat_log import MessageType


def _chunk(content):
    return SimpleNamespace(content=content)


def _make_astream_events_with_notify(
    *,
    message: str = "Building tests…",
    level: str = "info",
    title: str | None = "Progress",
):
    """Build an async event generator that simulates a notify tool call.

    Between the ``on_tool_start`` and ``on_tool_end`` events the generator
    invokes the registered notify callback (exactly as the real notify tool
    does), so the ``_pending_notifies`` buffer is populated before the next
    event is processed.
    """

    async def astream_events(state, config, version):
        # 1. Notify tool starts — streaming skips display-only tools.
        yield {
            "event": "on_tool_start",
            "name": "notify",
            "run_id": "notify-run-1",
            "data": {"input": {"message": message, "level": level, "title": title}},
        }

        # 2. Simulate the tool body calling the registered callback.
        from clanker.tools.notify_tools import get_notify_callback

        cb = get_notify_callback()
        if cb is not None:
            cb(message, level, title)

        # 3. Tool returns its result dict.
        yield {
            "event": "on_tool_end",
            "name": "notify",
            "run_id": "notify-run-1",
            "data": {
                "output": {
                    "ok": True,
                    "sent": True,
                    "message": message,
                    "level": level,
                    "title": title,
                }
            },
        }

        # 4. Model produces final text.
        yield {"event": "on_chat_model_start", "run_id": "model-run-1"}
        yield {
            "event": "on_chat_model_stream",
            "data": {"chunk": _chunk("Done.")},
        }

    def bound(state, config, version):
        return astream_events(state, config, version)

    return bound


# ---------------------------------------------------------------------------
# TUI mode: notify must appear in the chat log exactly once
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_rendered_once_in_tui() -> None:
    """In TUI mode, the notify message must be added to the chat log exactly
    once via the ``_pending_notifies`` flush, *not* duplicated by the
    ``on_tool_end`` handler.
    """
    from clanker.ui.streaming import stream_agent_response_async

    msg_text = "Scanning **200 files**…"
    level = "success"
    title = "Scan started"

    graph = MagicMock()
    graph.astream_events = _make_astream_events_with_notify(
        message=msg_text, level=level, title=title,
    )

    chat_log = MagicMock()
    textual_app = MagicMock()
    textual_app.get_chat_log.return_value = chat_log

    console = MagicMock()
    console._textual_app = textual_app

    settings = MagicMock()
    settings.output.show_tool_calls = True
    settings.context.max_agent_steps = 50

    with patch(
        "clanker.agent.create_agent_graph_async",
        new_callable=AsyncMock,
        return_value=(graph, None),
    ), patch(
        "clanker.ui.streaming._heal_orphaned_tool_calls",
        new_callable=AsyncMock,
    ):
        result = await stream_agent_response_async(
            settings=settings,
            checkpointer=None,
            state={"messages": []},
            config={"configurable": {"thread_id": "tui-notify-test"}},
            console=console,
        )

    # Collect all add_message calls with NOTIFY type
    notify_calls = [
        c
        for c in chat_log.add_message.call_args_list
        if len(c.args) > 1 and c.args[1] == MessageType.NOTIFY
    ]

    assert len(notify_calls) == 1, (
        f"Expected exactly 1 NOTIFY add_message call, got {len(notify_calls)}: "
        f"{notify_calls}"
    )
    assert notify_calls[0].args[0] == msg_text
    assert notify_calls[0].kwargs.get("level", notify_calls[0].args[3] if len(notify_calls[0].args) > 3 else None) or level == level

    # console.print_notify is still called for CLI-layer rendering
    console.print_notify.assert_called_once_with(msg_text, level, title)

    assert result.response == "Done."


# ---------------------------------------------------------------------------
# CLI mode: notify renders via console.print_notify only, no chat log
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_rendered_once_in_cli() -> None:
    """In CLI mode (no textual_app), the notify message renders only via
    ``console.print_notify()`` — no chat log interaction at all.
    """
    from clanker.ui.streaming import stream_agent_response_async

    msg_text = "Running tests…"
    level = "info"
    title = None

    graph = MagicMock()
    graph.astream_events = _make_astream_events_with_notify(
        message=msg_text, level=level, title=title,
    )

    console = MagicMock(spec=["print_notify", "print_assistant_message",
                              "print_thinking_start", "print_thinking",
                              "print_info", "get_loading_message",
                              "_console"])
    # No _textual_app attribute → CLI mode
    assert not hasattr(console, "_textual_app")

    settings = MagicMock()
    settings.output.show_tool_calls = True
    settings.context.max_agent_steps = 50

    with patch(
        "clanker.agent.create_agent_graph_async",
        new_callable=AsyncMock,
        return_value=(graph, None),
    ), patch(
        "clanker.ui.streaming._heal_orphaned_tool_calls",
        new_callable=AsyncMock,
    ):
        result = await stream_agent_response_async(
            settings=settings,
            checkpointer=None,
            state={"messages": []},
            config={"configurable": {"thread_id": "cli-notify-test"}},
            console=console,
        )

    console.print_notify.assert_called_once_with(msg_text, level, title)
    assert result.response == "Done."


# ---------------------------------------------------------------------------
# Multiple notify calls in one turn should each appear exactly once
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multiple_notifies_each_rendered_once() -> None:
    """When the agent fires multiple notify calls in a single turn, each
    should appear in the TUI chat log exactly once.
    """
    from clanker.tools.notify_tools import get_notify_callback
    from clanker.ui.streaming import stream_agent_response_async

    notifications = [
        ("Step 1: reading files…", "info", None),
        ("Step 2: writing output…", "success", "Progress"),
        ("Step 3: done!", "success", "Complete"),
    ]

    async def astream_events(state, config, version):
        for i, (msg, level, title) in enumerate(notifications):
            yield {
                "event": "on_tool_start",
                "name": "notify",
                "run_id": f"n{i}",
                "data": {"input": {"message": msg, "level": level, "title": title}},
            }
            # Simulate tool body calling callback
            cb = get_notify_callback()
            if cb is not None:
                cb(msg, level, title)
            yield {
                "event": "on_tool_end",
                "name": "notify",
                "run_id": f"n{i}",
                "data": {
                    "output": {
                        "ok": True,
                        "sent": True,
                        "message": msg,
                        "level": level,
                        "title": title,
                    }
                },
            }

        yield {"event": "on_chat_model_start", "run_id": "m1"}
        yield {"event": "on_chat_model_stream", "data": {"chunk": _chunk("All done.")}}

    graph = MagicMock()
    graph.astream_events = lambda s, config, version: astream_events(s, config, version)

    chat_log = MagicMock()
    textual_app = MagicMock()
    textual_app.get_chat_log.return_value = chat_log

    console = MagicMock()
    console._textual_app = textual_app

    settings = MagicMock()
    settings.output.show_tool_calls = True
    settings.context.max_agent_steps = 50

    with patch(
        "clanker.agent.create_agent_graph_async",
        new_callable=AsyncMock,
        return_value=(graph, None),
    ), patch(
        "clanker.ui.streaming._heal_orphaned_tool_calls",
        new_callable=AsyncMock,
    ):
        result = await stream_agent_response_async(
            settings=settings,
            checkpointer=None,
            state={"messages": []},
            config={"configurable": {"thread_id": "multi-notify-test"}},
            console=console,
        )

    notify_calls = [
        c
        for c in chat_log.add_message.call_args_list
        if len(c.args) > 1 and c.args[1] == MessageType.NOTIFY
    ]

    assert len(notify_calls) == len(notifications), (
        f"Expected {len(notifications)} NOTIFY calls, got {len(notify_calls)}"
    )
    for (expected_msg, _, _), actual_call in zip(notifications, notify_calls, strict=True):
        assert actual_call.args[0] == expected_msg

    # console.print_notify should also have been called exactly once per notification
    assert console.print_notify.call_count == len(notifications)

    assert result.response == "All done."


# ---------------------------------------------------------------------------
# Subagent isolation: child notify must NOT appear in parent chat log
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subagent_notify_does_not_leak_to_parent_chat_log() -> None:
    """Notify events from a child subagent (propagated via parent_ids) must
    not appear in the parent TUI chat log.
    """
    from clanker.ui.streaming import stream_agent_response_async

    async def astream_events(state, config, version):
        # spawn_subagent starts
        yield {
            "event": "on_tool_start",
            "name": "spawn_subagent",
            "run_id": "spawn-1",
            "data": {"input": {}},
        }
        # Child notify event (propagated via parent_ids) — should be filtered
        yield {
            "event": "on_tool_end",
            "name": "notify",
            "parent_ids": ["spawn-1"],
            "run_id": "child-notify-1",
            "data": {
                "output": {
                    "ok": True,
                    "sent": True,
                    "message": "CHILD PRIVATE NOTIFY",
                    "level": "info",
                    "title": None,
                }
            },
        }
        # spawn_subagent ends
        yield {
            "event": "on_tool_end",
            "name": "spawn_subagent",
            "run_id": "spawn-1",
            "data": {
                "output": {
                    "task_id": "t1",
                    "status": "success",
                    "response": "child done",
                }
            },
        }
        # Parent model response
        yield {"event": "on_chat_model_start", "run_id": "parent-m1"}
        yield {
            "event": "on_chat_model_stream",
            "data": {"chunk": _chunk("Parent answer.")},
        }

    graph = MagicMock()
    graph.astream_events = lambda s, config, version: astream_events(s, config, version)

    chat_log = MagicMock()
    textual_app = MagicMock()
    textual_app.get_chat_log.return_value = chat_log

    console = MagicMock()
    console._textual_app = textual_app

    settings = MagicMock()
    settings.output.show_tool_calls = True
    settings.context.max_agent_steps = 50

    with patch(
        "clanker.agent.create_agent_graph_async",
        new_callable=AsyncMock,
        return_value=(graph, None),
    ), patch(
        "clanker.ui.streaming._heal_orphaned_tool_calls",
        new_callable=AsyncMock,
    ):
        await stream_agent_response_async(
            settings=settings,
            checkpointer=None,
            state={"messages": []},
            config={"configurable": {"thread_id": "subagent-notify-test"}},
            console=console,
        )

    # No NOTIFY messages should have been added from the child
    notify_calls = [
        c
        for c in chat_log.add_message.call_args_list
        if len(c.args) > 1 and c.args[1] == MessageType.NOTIFY
    ]
    for nc in notify_calls:
        assert "CHILD PRIVATE NOTIFY" not in nc.args[0], (
            "Child subagent notify leaked to parent chat log"
        )
