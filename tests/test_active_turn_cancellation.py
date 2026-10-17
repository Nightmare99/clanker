"""Interrupt a real tool node, repair its checkpoint, then run another turn."""

import asyncio
import json
import os
import shlex
import signal
import sys
import threading
from contextlib import suppress
from pathlib import Path
from typing import Annotated
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict

from clanker.config.settings import Settings
from clanker.context import find_orphaned_tool_call_ids
from clanker.execution import check_cancelled, turn_cancellation
from clanker.ui import streaming
from clanker.ui.console import Console


class State(TypedDict):
    messages: Annotated[list, add_messages]


def make_graph(selected_tool, args):
    async def model(state):
        last = state["messages"][-1]
        if isinstance(last, HumanMessage) and last.content == "start":
            message = AIMessage(content="", tool_calls=[{
                "name": selected_tool.name, "args": args, "id": "interrupted-call",
            }])
        else:
            check_cancelled()  # The next turn must have a fresh, unset flag.
            message = AIMessage(content="Resumed successfully")
        return {"messages": [message]}

    graph = StateGraph(State)
    graph.add_node("model", model)
    graph.add_node("tools", ToolNode([selected_tool]))
    graph.add_edge(START, "model")
    graph.add_conditional_edges(
        "model", lambda state: "tools" if state["messages"][-1].tool_calls else END,
    )
    graph.add_edge("tools", "model")
    return graph.compile(checkpointer=MemorySaver())


async def run_turn(graph, monkeypatch, text):
    monkeypatch.setattr(
        "clanker.agent.create_agent_graph_async", AsyncMock(return_value=(graph, None)),
    )
    settings = Settings()
    settings.output.show_tool_calls = False
    return await streaming.stream_agent_response_async(
        settings, None, {"messages": [HumanMessage(content=text)]},
        {"configurable": {"thread_id": "interrupt-and-resume"}}, Console(),
    )


async def assert_resumable(graph, monkeypatch):
    config = {"configurable": {"thread_id": "interrupt-and-resume"}}
    snapshot = await graph.aget_state(config)
    messages = snapshot.values["messages"]
    assert not find_orphaned_tool_call_ids(messages)
    assert any(
        isinstance(message, ToolMessage)
        and message.tool_call_id == "interrupted-call"
        and "interrupted" in message.content.lower()
        for message in messages
    )
    result = await asyncio.wait_for(run_turn(graph, monkeypatch, "continue"), 3)
    assert result.status == "success"
    snapshot = await graph.aget_state(config)
    assert snapshot.values["messages"][-1].content == "Resumed successfully"
    assert turn_cancellation.get() is None
    assert streaming._current_streaming_task is None


async def test_interrupt_cancels_idle_async_tool_and_resumes(monkeypatch):
    started = asyncio.Event()
    cancelled = asyncio.Event()
    calls = []

    @tool
    async def slow_tool() -> str:
        """A tool that produces no events while it waits."""
        calls.append("start")
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        return "unreachable"

    graph = make_graph(slow_tool, {})
    turn = asyncio.create_task(run_turn(graph, monkeypatch, "start"))
    await asyncio.wait_for(started.wait(), 3)
    streaming._cancel_streaming_task()
    # Repeated Ctrl+C must not cancel checkpoint repair.
    streaming._cancel_streaming_task()
    result = await asyncio.wait_for(turn, 2)
    assert result.status == "cancelled"
    assert cancelled.is_set()
    await assert_resumable(graph, monkeypatch)
    assert calls == ["start"]


@pytest.mark.skipif(os.name != "posix", reason="POSIX process group integration")
@pytest.mark.parametrize("promote_after,parent_exits", [(0, False), (10, False), (10, True)])
async def test_interrupt_kills_shell_and_descendants_then_resumes(
    monkeypatch, tmp_path, promote_after, parent_exits,
):
    from clanker.tools import bash_tools

    settings = Settings()
    settings.safety.foreground_promote_after_seconds = promote_after
    monkeypatch.setattr(bash_tools, "get_settings", lambda: settings)
    monkeypatch.setattr(bash_tools, "run_safety_checks", lambda _: None)
    marker = tmp_path / "started.json"
    script = (
        "import json, os, pathlib, subprocess, sys, time; "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        f"marker = pathlib.Path({str(marker)!r}); temporary = marker.with_suffix('.tmp'); "
        "temporary.write_text(json.dumps([os.getpid(), child.pid, os.getpgrp()])); "
        "temporary.replace(marker); "
        f"time.sleep({0 if parent_exits else 30})"
    )
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}"
    graph = make_graph(bash_tools.execute_shell, {"command": command})
    turn = asyncio.create_task(run_turn(graph, monkeypatch, "start"))
    deadline = asyncio.get_running_loop().time() + 5
    try:
        while not marker.exists():
            assert asyncio.get_running_loop().time() < deadline
            await asyncio.sleep(0.01)
        pids = json.loads(marker.read_text())
        streaming._cancel_streaming_task()
        result = await asyncio.wait_for(turn, 2)
        assert result.status == "cancelled"
        for pid in pids[:2]:
            deadline = asyncio.get_running_loop().time() + 2
            while True:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                # Linux CI may retain a dead orphan as a zombie until init reaps it.
                status = Path(f"/proc/{pid}/stat")
                if status.exists() and status.read_text().split()[2] == "Z":
                    break
                assert asyncio.get_running_loop().time() < deadline, f"Child {pid} still running"
                await asyncio.sleep(0.01)
        await assert_resumable(graph, monkeypatch)
    finally:
        if not turn.done():
            streaming._cancel_streaming_task()
            await asyncio.wait_for(turn, 3)
        if marker.exists():
            group = json.loads(marker.read_text())[2]
            with suppress(ProcessLookupError):
                os.killpg(group, signal.SIGKILL)


async def test_interrupt_during_graph_setup_is_also_resumable(monkeypatch):
    started = asyncio.Event()

    async def build(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("clanker.agent.create_agent_graph_async", build)
    turn = asyncio.create_task(streaming.stream_agent_response_async(
        Settings(), None, {"messages": []}, {}, Console(),
    ))
    await asyncio.wait_for(started.wait(), 2)
    streaming._cancel_streaming_task()
    assert (await asyncio.wait_for(turn, 2)).status == "cancelled"
    assert turn_cancellation.get() is None
    assert streaming._current_streaming_task is None


async def test_cancelled_sync_worker_cannot_write_after_the_next_turn(monkeypatch, tmp_path):
    from clanker.tools.file_tools import write_file

    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    writes = []
    destination = tmp_path / "must-not-exist.txt"

    @tool
    def blocking_python_tool() -> str:
        """Simulate blocking Python code that cannot itself be force-killed."""
        started.set()
        try:
            release.wait(5)
            writes.append(write_file.invoke({"file_path": str(destination), "content": "late write"}))
            return "late result"
        finally:
            finished.set()

    graph = make_graph(blocking_python_tool, {})
    turn = asyncio.create_task(run_turn(graph, monkeypatch, "start"))
    try:
        assert await asyncio.to_thread(started.wait, 3)
        streaming._cancel_streaming_task()
        assert (await asyncio.wait_for(turn, 2)).status == "cancelled"
        await assert_resumable(graph, monkeypatch)
        release.set()
        assert await asyncio.to_thread(finished.wait, 2)
        assert writes and not writes[0]["ok"]
        assert not destination.exists()
    finally:
        release.set()
        if not turn.done():
            streaming._cancel_streaming_task()
            await asyncio.wait_for(turn, 3)


async def test_tui_ctrl_c_stops_tool_and_accepts_next_prompt(monkeypatch, tmp_path):
    from unittest.mock import MagicMock

    from clanker.ui.app import ClankerApp

    started = asyncio.Event()
    stopped = asyncio.Event()

    @tool
    async def waiting_tool() -> str:
        """Wait until the user interrupts."""
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
        return "unreachable"

    graph = make_graph(waiting_tool, {})
    monkeypatch.setattr("clanker.agent.create_agent_graph_async", AsyncMock(return_value=(graph, None)))
    monkeypatch.setattr(ClankerApp, "_load_history", lambda self: [])
    monkeypatch.setattr(ClankerApp, "_save_history", lambda self: None)
    app = ClankerApp(Console())
    app._play_hero = AsyncMock()
    app._refresh_selected_model = lambda: None
    app._settings = Settings()
    app._working_dir = str(tmp_path)
    manager = MagicMock()
    manager.checkpointer = graph.checkpointer
    manager.model_name = None
    manager.session_id = "interrupt-and-resume"
    manager.get_config.return_value = {"configurable": {"thread_id": "interrupt-and-resume"}}
    app._session_manager = manager
    async with app.run_test(size=(100, 30)) as pilot:
        app.get_prompt_input().value = "start"
        await pilot.press("enter")
        await asyncio.wait_for(started.wait(), 3)
        assert app._processing
        await pilot.pause(0.25)  # Let the normal debounced tool indicator mount.
        entries = [
            entry for entry in app.get_chat_log()._tool_entries.values()
            if entry.tool_name == "waiting_tool"
        ]
        assert entries and entries[0].status == "running"
        await pilot.press("ctrl+c")
        await asyncio.wait_for(app.workers.wait_for_complete(), 2)
        assert stopped.is_set()
        assert not app._processing
        assert entries[0].status != "running"
        assert "Interrupted" in entries[0].result
        app.get_prompt_input().value = "continue"
        await pilot.press("enter")
        await asyncio.wait_for(app.workers.wait_for_complete(), 3)
        assert not app._processing
        snapshot = await graph.aget_state(manager.get_config())
        assert snapshot.values["messages"][-1].content == "Resumed successfully"
        assert not find_orphaned_tool_call_ids(snapshot.values["messages"])


@pytest.mark.skipif(os.name != "posix", reason="POSIX background job integration")
@pytest.mark.parametrize("promoted", [False, True])
async def test_only_current_turn_background_jobs_stop(monkeypatch, tmp_path, promoted):
    from clanker.execution import TurnCancellation
    from clanker.tools import background, bash_tools

    monkeypatch.setattr(background, "_JOB_LOG_DIR", tmp_path / "logs")
    manager = background.JobManager()
    monkeypatch.setattr(background, "_manager", manager)
    settings = Settings()
    settings.safety.foreground_promote_after_seconds = 1
    monkeypatch.setattr(bash_tools, "get_settings", lambda: settings)
    monkeypatch.setattr(bash_tools, "run_safety_checks", lambda _: None)
    old_job = await manager.launch("sleep 30", None, "previous turn")
    turn = TurnCancellation()
    token = turn_cancellation.set(turn)
    try:
        if promoted:
            output = await asyncio.to_thread(bash_tools.execute_shell.invoke, {"command": "sleep 30"})
            assert "promoted" in output
            job = next(item for item in manager.all() if item.id != old_job.id)
        else:
            job = await manager.launch("sleep 30", None, "current turn")
        turn.stop.set()
        await asyncio.wait_for(turn.settle(), 2)
        await manager.wait(job.id, 2)
        assert job.state == "killed"
        assert old_job.state == "running"
    finally:
        turn_cancellation.reset(token)
        await manager.shutdown()
        await asyncio.to_thread(manager.close)
