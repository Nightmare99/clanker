"""Managed task lifecycle tests use deterministic streams and real local tools."""

import asyncio
import subprocess
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage
from textual.app import App
from textual.widgets import Input

from clanker.changes import ChangeJournal, active_journal
from clanker.config.settings import Settings
from clanker.execution import task_directory, task_stop, working_directory
from clanker.tools import subagent as module
from clanker.tools.bash_tools import _run_managed_command
from clanker.tools.file_tools import write_file
from clanker.ui.streaming import StreamResult
from clanker.ui.subagent_history import SubagentHistoryScreen, SubagentRun
from clanker.utils.validators import validate_file_path


@pytest.fixture
def managed(tmp_path):
    settings = Settings()
    settings.subagents.max_concurrent = 1
    agent = SimpleNamespace(
        name="test", system_prompt="Test agent", tools=["read_file", "write_file"], model=None
    )
    console = SimpleNamespace(_textual_app=None)
    directory = task_directory.set(str(tmp_path))
    journal = active_journal.set(ChangeJournal())
    with (
        patch.object(module, "get_settings", return_value=settings),
        patch.object(module, "load_agent_config", return_value=agent),
        patch("clanker.ui.streaming.get_active_console", return_value=console),
    ):
        yield settings
    module._stop_all()
    for task in list(module._tasks.values()):
        if task.thread:
            task.thread.join(timeout=3)
    module._tasks.clear()
    task_directory.reset(directory)
    active_journal.reset(journal)


async def start(**kwargs):
    return await module.spawn_subagent.ainvoke(
        {"agent_name": "test", "prompt": "Do the task", "background": True, **kwargs}
    )


async def wait(task_id):
    return await module.subagent_wait.ainvoke({"task_id": task_id, "timeout_seconds": 3})


@pytest.mark.asyncio
async def test_background_message_and_stop(managed):
    received = threading.Event()

    async def stream(**kwargs):
        while kwargs["input_queue"].empty():
            await asyncio.sleep(0.01)
        assert kwargs["input_queue"].get_nowait() == "Focus on the parser"
        received.set()
        await asyncio.sleep(100)

    with patch("clanker.ui.streaming.stream_agent_response_async", side_effect=stream):
        result = await start()
        task_id = result["task_id"]
        assert module.send_task_message(task_id, "Focus on the parser") == "Follow-up queued"
        assert await asyncio.to_thread(received.wait, 2)
        assert module.stop_task(task_id)
        result = await wait(task_id)
        assert result["status"] == "cancelled"
        assert not result["success"]
        assert "ended" in module.send_task_message(task_id, "Too late")


@pytest.mark.asyncio
async def test_concurrency_and_queued_cancellation(managed):
    started = threading.Event()

    async def stream(**kwargs):
        started.set()
        await asyncio.sleep(100)

    with patch("clanker.ui.streaming.stream_agent_response_async", side_effect=stream):
        one = await start()
        assert await asyncio.to_thread(started.wait, 2)
        two = await start()
        assert module._tasks[two["task_id"]].run.status == "queued"
        module.stop_task(two["task_id"])
        assert (await wait(two["task_id"]))["status"] == "cancelled"
        module.stop_task(one["task_id"])
        await wait(one["task_id"])


@pytest.mark.asyncio
async def test_timeout(managed):
    async def stream(**kwargs):
        await asyncio.sleep(100)

    with patch("clanker.ui.streaming.stream_agent_response_async", side_effect=stream):
        result = await start(timeout_seconds=1)
        assert (await wait(result["task_id"]))["status"] == "timed_out"


@pytest.mark.asyncio
async def test_token_budget_and_cancelled_status(managed):
    async def stream(**kwargs):
        kwargs["event_callback"](
            {
                "event": "on_chat_model_end",
                "data": {
                    "output": AIMessage(
                        content="",
                        usage_metadata={"input_tokens": 5, "output_tokens": 5, "total_tokens": 10},
                    )
                },
            }
        )
        return StreamResult(response="Should not finish")

    with patch("clanker.ui.streaming.stream_agent_response_async", side_effect=stream):
        result = await start(max_tokens=10)
        result = await wait(result["task_id"])
        assert result["status"] == "budget_exceeded"
        assert result["input_tokens"] == 5
        assert not result["success"]


@pytest.mark.asyncio
async def test_task_local_writes_have_attribution(managed, tmp_path):
    async def stream(**kwargs):
        assert working_directory() == str(tmp_path)
        result = await write_file.ainvoke({"file_path": "task.txt", "content": "done"})
        assert result["ok"]
        return StreamResult(response="Done")

    with patch("clanker.ui.streaming.stream_agent_response_async", side_effect=stream):
        result = await start()
        result = await wait(result["task_id"])
        assert result["changed_files"] == [str(tmp_path / "task.txt")]
        assert active_journal.get().changes[0].actor == result["task_id"]


def test_repeat_failure_detection_uses_run_ids():
    task = module.ManagedTask(SubagentRun("test", "test"))
    event = module._event_handler(task, 2)
    for i in range(2):
        event(
            {
                "event": "on_tool_start",
                "name": "read_file",
                "run_id": str(i),
                "data": {"input": {"file_path": "missing"}},
            }
        )
        end = {
            "event": "on_tool_end",
            "name": "read_file",
            "run_id": str(i),
            "data": {"output": {"ok": False, "error": "File not found"}},
        }
        if i:
            with pytest.raises(asyncio.CancelledError):
                event(end)
        else:
            event(end)
    assert task.reason == "stalled"
    assert all(c.status == "error" for c in task.run.tool_calls)


def test_managed_shell_cancellation_and_directory(tmp_path):
    stop = threading.Event()
    stop_token = task_stop.set(stop)
    directory = task_directory.set(str(tmp_path))
    timer = threading.Timer(0.2, stop.set)
    timer.start()
    try:
        assert validate_file_path("a") == tmp_path / "a"
        output = _run_managed_command("sleep 30", 30)
        assert "cancelled" in output
    finally:
        timer.cancel()
        task_stop.reset(stop_token)
        task_directory.reset(directory)


def test_worktree_snapshots_dirty_and_untracked_files(tmp_path):
    def git(*args):
        return subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init")
    (tmp_path / "tracked").write_text("base")
    git("add", "tracked")
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "fixture")
    (tmp_path / "tracked").write_text("user changes")
    (tmp_path / "untracked").write_text("new user file")
    from pathlib import Path

    destination = Path(module._create_worktree(str(tmp_path)))
    assert (destination / "tracked").read_text() == "user changes"
    assert (destination / "untracked").read_text() == "new user file"
    (destination / "tracked").write_text("agent changes")
    assert (tmp_path / "tracked").read_text() == "user changes"


@pytest.mark.asyncio
async def test_tasks_panel_messages_and_stop(managed):
    run = SubagentRun("test", "Inspect parser")
    task = module.ManagedTask(run)
    module._tasks[run.task_id] = task
    app = App()
    async with app.run_test(size=(100, 35)) as pilot:
        screen = SubagentHistoryScreen([run])
        app.push_screen(screen)
        await pilot.pause()
        screen.query_one("#task-message", Input).value = "Check error paths"
        await pilot.click("#task-send")
        assert task.inbox.get_nowait() == "Check error paths"
        await pilot.click("#task-stop")
        assert task.stop.is_set()
        await pilot.press("escape")
        assert app.screen is not screen


@pytest.mark.asyncio
async def test_in_app_approval_response_and_cancellation(managed):
    from clanker.ui.task_prompt import TaskPromptScreen

    run = SubagentRun("test", "Run checks")
    task = module.ManagedTask(run)
    app = App()
    async with app.run_test(size=(80, 28)) as pilot:
        handler = module._interaction_handler(task, app)
        pending = asyncio.create_task(
            asyncio.to_thread(handler, "Run tests?", ["Yes", "No"], allow_other=False)
        )
        for _ in range(50):
            await pilot.pause(0.02)
            if isinstance(app.screen, TaskPromptScreen):
                break
        from textual.widgets import SelectionList

        app.screen.query_one(SelectionList).select(0)
        await pilot.click("#question-submit")
        assert await pending == {"selected": ["Yes"], "cancelled": False}
        assert run.status == "running"
        pending = asyncio.create_task(asyncio.to_thread(handler, "Run more?", ["Yes", "No"]))
        for _ in range(50):
            await pilot.pause(0.02)
            if isinstance(app.screen, TaskPromptScreen):
                break
        task.cancel()
        assert (await pending)["cancelled"]
        await pilot.pause()
        assert not isinstance(app.screen, TaskPromptScreen)


@pytest.mark.asyncio
async def test_shell_approval_context_survives_tool_executor(managed):
    from clanker.execution import task_interaction
    from clanker.tools.bash_tools import prompt_for_approval

    calls = []

    def ask(question, options, **kwargs):
        calls.append((question, kwargs))
        return {"selected": [options[0]], "cancelled": False}

    token = task_interaction.set(ask)
    try:
        assert await asyncio.to_thread(prompt_for_approval, "echo test")
        assert calls[0][1]["allow_other"] is False
    finally:
        task_interaction.reset(token)


@pytest.mark.asyncio
async def test_result_reports_stream_failure(managed):
    async def stream(**kwargs):
        return StreamResult(response="Partial work", status="step_limit")

    with patch("clanker.ui.streaming.stream_agent_response_async", side_effect=stream):
        result = await start()
        result = await wait(result["task_id"])
        assert result["status"] == "step_limit"
        assert not result["success"]


def test_task_tools_respect_feature_flag():
    from clanker.tools import get_tools

    settings = Settings()
    settings.tools.subagents = False
    with patch("clanker.config.settings.get_settings", return_value=settings):
        names = {tool.name for tool in get_tools()}
    assert not names.intersection(
        {"spawn_subagent", "subagent_status", "subagent_message", "subagent_stop", "subagent_wait"}
    )


def test_task_status_rendering_preserves_pending_state():
    from clanker.ui.tool_display import normalize_tool_output
    from clanker.ui.tool_summary import compact_result_summary, is_failed_tool_result

    payload = {
        "task_id": "abc",
        "agent": "reviewer",
        "status": "queued",
        "success": False,
        "error": "",
    }
    rendered = normalize_tool_output(payload)
    assert "reviewer · queued" in compact_result_summary(rendered, "spawn_subagent", {})
    assert not is_failed_tool_result(rendered, "spawn_subagent", {})
    payload["status"] = "budget_exceeded"
    assert is_failed_tool_result(normalize_tool_output(payload), "subagent_wait", {})


@pytest.mark.parametrize("status", ["success", "error", "cancelled", "timed_out", "budget_exceeded"])
async def test_main_tui_shows_task_lifecycle_without_child_output(status):
    from clanker.ui.app import ClankerApp
    from clanker.ui.console import Console

    app = ClankerApp(Console())

    async def no_hero(*args):
        pass

    app._play_hero = no_hero
    run = SubagentRun(agent_name="reviewer", prompt="Review code", status="queued")
    async with app.run_test(size=(100, 30)) as pilot:
        app.register_subagent_run(run)
        chat = app.get_chat_log()
        entry, = chat._tool_entries.values()
        assert entry.tool_name == "spawn_subagent"
        for phase in ("queued", "running", "waiting", "stopping"):
            run.status = phase
            await pilot.pause(0.15)
            assert phase in entry.args
            assert entry.status == "running"
            assert entry.spinner_timer is not None
        run.response = "PRIVATE CHILD TRANSCRIPT"
        run.error = "PRIVATE CHILD ERROR"
        run.status = status
        await pilot.pause(0.15)
        assert status in entry.args
        assert entry.status == ("success" if status == "success" else "error")
        assert entry.spinner_timer is None
        assert entry.result == ""
        assert entry.output_widget is None
        screen = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
        assert "spawn_subagent" in screen
        assert "PRIVATE CHILD" not in screen
        assert app._subagent_runs[0].response == "PRIVATE CHILD TRANSCRIPT"


@pytest.mark.parametrize("tool", ["spawn_subagent", "subagent_wait", "subagent_status", "subagent_message"])
@pytest.mark.parametrize("payload", ['PRIVATE CHILD OUTPUT', '{"message":"PRIVATE CHILD OUTPUT"}', '{"response":"PRIVATE CHILD OUTPUT"}'])
def test_subagent_summary_never_falls_back_to_transcript(tool, payload):
    from clanker.ui.tool_summary import compact_result_summary

    assert "PRIVATE CHILD" not in compact_result_summary(payload, tool, {})


@pytest.mark.asyncio
async def test_budget_includes_worktree_preparation(managed):
    def prepare(root):
        # Model execution must not start after preparation exhausts the budget.
        assert task_stop.get().wait(2)
        return root

    with (
        patch.object(module, "_create_worktree", side_effect=prepare),
        patch("clanker.ui.streaming.stream_agent_response_async") as stream,
    ):
        result = await start(isolation="worktree", timeout_seconds=1)
        result = await wait(result["task_id"])
        assert result["status"] == "timed_out"
        stream.assert_not_called()


def test_cancelled_task_cannot_start_shell():
    stop = threading.Event()
    stop.set()
    token = task_stop.set(stop)
    try:
        with patch("clanker.tools.bash_tools.subprocess.Popen") as popen:
            with pytest.raises(ValueError, match="stopped"):
                _run_managed_command("echo should-not-run", 30)
            popen.assert_not_called()
    finally:
        task_stop.reset(token)
