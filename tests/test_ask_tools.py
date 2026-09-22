"""Tests for ask_user tool and interactive option selection fallback."""

from __future__ import annotations

import builtins
from typing import Any, Callable, Sequence, cast

import pytest


# ----------------------------------------------------------------------
# select_options fallback (non-TTY) parsing
# ----------------------------------------------------------------------
def _force_non_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make _stdin_is_interactive() return False so the numbered path runs."""
    from clanker.ui import prompts

    monkeypatch.setattr(prompts, "_stdin_is_interactive", lambda: False)


def _feed_inputs(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> None:
    """Feed a queue of input() responses."""
    it = iter(answers)
    monkeypatch.setattr(builtins, "input", lambda *a, **k: next(it))


class TestSelectFallback:
    def test_single_select(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        from clanker.ui.prompts import select_options

        _force_non_tty(monkeypatch)
        _feed_inputs(monkeypatch, ["2"])
        result = select_options("Env?", ["staging", "production", "both"])
        assert result == {"selected": ["production"], "cancelled": False}

    def test_multi_select(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from clanker.ui.prompts import select_options

        _force_non_tty(monkeypatch)
        _feed_inputs(monkeypatch, ["1,3"])
        result = select_options("Svcs?", ["auth", "billing", "search"], multi_select=True)
        assert result == {"selected": ["auth", "search"], "cancelled": False}

    def test_cancel_with_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from clanker.ui.prompts import select_options

        _force_non_tty(monkeypatch)
        _feed_inputs(monkeypatch, ["0"])
        assert select_options("Q", ["a", "b"]) == {"selected": [], "cancelled": True}

    def test_cancel_with_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from clanker.ui.prompts import select_options

        _force_non_tty(monkeypatch)
        _feed_inputs(monkeypatch, [""])
        assert select_options("Q", ["a", "b"])["cancelled"] is True

    def test_other_via_letter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from clanker.ui.prompts import select_options

        _force_non_tty(monkeypatch)
        _feed_inputs(monkeypatch, ["o", "my custom answer"])
        result = select_options("Q", ["a", "b"])
        assert result == {"selected": ["my custom answer"], "cancelled": False}

    def test_other_via_number(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from clanker.ui.prompts import select_options

        _force_non_tty(monkeypatch)
        # options a,b -> "Other" is number 3
        _feed_inputs(monkeypatch, ["3", "typed value"])
        result = select_options("Q", ["a", "b"])
        assert result == {"selected": ["typed value"], "cancelled": False}

    def test_out_of_range_is_cancelled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from clanker.ui.prompts import select_options

        _force_non_tty(monkeypatch)
        _feed_inputs(monkeypatch, ["9"])
        assert select_options("Q", ["a", "b"], allow_other=False)["cancelled"] is True

    def test_eof_is_cancel(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from clanker.ui.prompts import select_options

        _force_non_tty(monkeypatch)

        def raise_eof(*a: object, **k: object) -> str:
            raise EOFError

        monkeypatch.setattr(builtins, "input", raise_eof)
        assert select_options("Q", ["a", "b"])["cancelled"] is True


# ----------------------------------------------------------------------
# ask_user tool
# ----------------------------------------------------------------------
def _langchain_available() -> bool:
    try:
        import langchain_core  # noqa: F401

        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(not _langchain_available(), reason="langchain not installed")


class TestAskUserValidation:
    def test_empty_options(self) -> None:
        from clanker.tools.ask_tools import ask_user

        out = ask_user.invoke({"question": "Q", "options": []})
        assert out["ok"] is False
        assert "options" in out["error"]

    def test_blank_question(self) -> None:
        from clanker.tools.ask_tools import ask_user

        out = ask_user.invoke({"question": "   ", "options": ["a"]})
        assert out["ok"] is False
        assert "question" in out["error"]

    def test_too_many_options(self) -> None:
        from clanker.tools.ask_tools import ask_user

        out = ask_user.invoke({"question": "Q", "options": [str(i) for i in range(11)]})
        assert out["ok"] is False
        assert "too many" in out["error"]

    def test_options_stringified(self) -> None:
        from clanker.tools import ask_tools

        captured: dict[str, list[str]] = {}

        def fake(question: str, options: list[str], **kw: Any) -> dict[str, Any]:
            captured["options"] = options
            return {"selected": [options[0]], "cancelled": False}

        ask_tools.set_ask_callback(fake)
        try:
            out = ask_tools.ask_user.invoke({"question": "Q", "options": ["10", "20"]})
        finally:
            ask_tools.set_ask_callback(None)
        assert out["ok"] is True
        assert captured["options"] == ["10", "20"]


class TestAskUserCallback:
    def test_uses_registered_callback(self) -> None:
        from clanker.tools import ask_tools

        def fake(
            question: str,
            options: list[str],
            *,
            multi_select: bool = False,
            allow_other: bool = False,
            allow_cancel: bool = True,
        ) -> dict[str, Any]:
            return {"selected": [options[1]], "cancelled": False}

        ask_tools.set_ask_callback(fake)
        try:
            out = ask_tools.ask_user.invoke({"question": "Env?", "options": ["staging", "prod"]})
        finally:
            ask_tools.set_ask_callback(None)
        assert out == {"ok": True, "selected": ["prod"], "cancelled": False}

    def test_cancel_result(self) -> None:
        from clanker.tools import ask_tools

        ask_tools.set_ask_callback(lambda *a, **k: {"selected": [], "cancelled": True})
        try:
            out = ask_tools.ask_user.invoke({"question": "Q", "options": ["a", "b"]})
        finally:
            ask_tools.set_ask_callback(None)
        assert out == {"ok": True, "selected": [], "cancelled": True}

    def test_empty_selection_counts_as_cancelled(self) -> None:
        from clanker.tools import ask_tools

        # A callback returning nothing selected -> treated as cancelled.
        ask_tools.set_ask_callback(lambda *a, **k: {"selected": [], "cancelled": False})
        try:
            out = ask_tools.ask_user.invoke({"question": "Q", "options": ["a"]})
        finally:
            ask_tools.set_ask_callback(None)
        assert out["cancelled"] is True

    def test_callback_exception_returns_error(self) -> None:
        from clanker.tools import ask_tools

        def boom(*a: object, **k: object) -> dict[str, Any]:
            raise RuntimeError("ui exploded")

        ask_tools.set_ask_callback(boom)
        try:
            out = ask_tools.ask_user.invoke({"question": "Q", "options": ["a"]})
        finally:
            ask_tools.set_ask_callback(None)
        assert out["ok"] is False
        assert "could not collect" in out["error"]

    def test_falls_back_when_no_callback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from clanker.tools import ask_tools
        from clanker.ui import prompts

        ask_tools.set_ask_callback(None)
        monkeypatch.setattr(prompts, "_stdin_is_interactive", lambda: False)
        monkeypatch.setattr(builtins, "input", lambda *a, **k: "1")
        out = ask_tools.ask_user.invoke({"question": "Q", "options": ["x", "y"]})
        assert out == {"ok": True, "selected": ["x"], "cancelled": False}


class TestAskUserRegistration:
    def test_registered_in_tool_registry(self) -> None:
        from clanker.tools import get_tools

        assert "ask_user" in [t.name for t in get_tools()]


class TestTaskPromptModal:
    @pytest.mark.asyncio
    async def test_single_select_enforces_one_choice(self) -> None:
        import asyncio

        from textual.app import App
        from textual.widgets import SelectionList

        from clanker.ui.task_prompt import TaskPromptScreen, show_prompt_modal

        app: App[object] = App()
        async with app.run_test(size=(80, 28)) as pilot:
            pending = asyncio.create_task(
                asyncio.to_thread(
                    show_prompt_modal,
                    app,
                    "clanker",
                    "Choose an option",
                    ["Option A", "Option B"],
                    multi_select=False,
                    allow_other=False,
                    allow_cancel=True,
                )
            )
            for _ in range(50):
                await pilot.pause(0.02)
                if isinstance(app.screen, TaskPromptScreen):
                    break

            selection_list = app.screen.query_one(SelectionList)
            # Toggle option 0, then toggle option 1
            selection_list.toggle(0)
            await pilot.pause(0.02)
            assert selection_list.selected == [0]

            selection_list.toggle(1)
            await pilot.pause(0.02)
            assert selection_list.selected == [1]

            await pilot.click("#question-submit")
            result = await pending
            assert result == {"selected": ["Option B"], "cancelled": False}

    @pytest.mark.asyncio
    async def test_allow_cancel_false_hides_cancel_button(self) -> None:
        import asyncio

        from textual.app import App
        from textual.widgets import Button

        from clanker.ui.task_prompt import TaskPromptScreen, show_prompt_modal

        app: App[object] = App()
        async with app.run_test(size=(80, 28)) as pilot:
            pending = asyncio.create_task(
                asyncio.to_thread(
                    show_prompt_modal,
                    app,
                    "clanker",
                    "Must choose",
                    ["Yes", "No"],
                    allow_cancel=False,
                )
            )
            for _ in range(50):
                await pilot.pause(0.02)
                if isinstance(app.screen, TaskPromptScreen):
                    break

            cancel_buttons = [b for b in app.screen.query(Button) if b.id == "question-cancel"]
            assert len(cancel_buttons) == 0

            # Force cancel externally to complete the thread task
            cast(TaskPromptScreen, app.screen).force_cancel()
            result = await pending
            assert result == {"selected": [], "cancelled": True}

    @pytest.mark.asyncio
    async def test_modal_custom_input(self) -> None:
        import asyncio

        from textual.app import App
        from textual.widgets import Input

        from clanker.ui.task_prompt import TaskPromptScreen, show_prompt_modal

        app: App[object] = App()
        async with app.run_test(size=(80, 28)) as pilot:
            pending = asyncio.create_task(
                asyncio.to_thread(
                    show_prompt_modal,
                    app,
                    "clanker",
                    "Custom choice?",
                    ["Option 1"],
                    allow_other=True,
                )
            )
            for _ in range(50):
                await pilot.pause(0.02)
                if isinstance(app.screen, TaskPromptScreen):
                    break

            custom_input = app.screen.query_one("#question-other", Input)
            custom_input.value = "My custom value"
            await pilot.click("#question-submit")
            result = await pending
            assert result == {"selected": ["My custom value"], "cancelled": False}

    @pytest.mark.asyncio
    async def test_modal_check_cancelled(self) -> None:
        import asyncio

        from textual.app import App

        from clanker.ui.task_prompt import TaskPromptScreen, show_prompt_modal

        app: App[object] = App()
        is_cancelled = False

        async with app.run_test(size=(80, 28)) as pilot:
            pending = asyncio.create_task(
                asyncio.to_thread(
                    show_prompt_modal,
                    app,
                    "clanker",
                    "Will cancel?",
                    ["Option 1"],
                    check_cancelled=lambda: is_cancelled,
                )
            )
            for _ in range(50):
                await pilot.pause(0.02)
                if isinstance(app.screen, TaskPromptScreen):
                    break

            # Trigger cancellation flag
            is_cancelled = True
            result = await pending
            assert result == {"selected": [], "cancelled": True}

    @pytest.mark.asyncio
    async def test_modal_preface_display(self) -> None:
        import asyncio

        from textual.app import App
        from textual.widgets import Static

        from clanker.ui.task_prompt import TaskPromptScreen, show_prompt_modal

        app: App[object] = App()
        async with app.run_test(size=(80, 28)) as pilot:
            pending = asyncio.create_task(
                asyncio.to_thread(
                    show_prompt_modal,
                    app,
                    "clanker",
                    "Approve this?",
                    ["Yes", "No"],
                    preface="Dangerous command: rm -rf /",
                    allow_other=False,
                    allow_cancel=False,
                )
            )
            for _ in range(50):
                await pilot.pause(0.02)
                if isinstance(app.screen, TaskPromptScreen):
                    break

            preface_statics = [
                s for s in app.screen.query(Static)
                if "Dangerous command" in str(s.render())
            ]
            assert len(preface_statics) == 1

            cast(TaskPromptScreen, app.screen).force_cancel()
            result = await pending
            assert result == {"selected": [], "cancelled": True}

    @pytest.mark.asyncio
    async def test_single_select_enter_key_submits(self) -> None:
        import asyncio

        from textual.app import App

        from clanker.ui.task_prompt import TaskPromptScreen, show_prompt_modal

        app: App[object] = App()
        async with app.run_test(size=(80, 28)) as pilot:
            pending = asyncio.create_task(
                asyncio.to_thread(
                    show_prompt_modal,
                    app,
                    "clanker",
                    "Pick an option",
                    ["Alpha", "Beta", "Gamma"],
                    multi_select=False,
                    allow_other=False,
                    allow_cancel=True,
                )
            )
            for _ in range(50):
                await pilot.pause(0.02)
                if isinstance(app.screen, TaskPromptScreen):
                    break

            # Navigate down to "Beta" and press enter
            await pilot.press("down")
            await pilot.press("enter")
            result = await pending
            assert result == {"selected": ["Beta"], "cancelled": False}


class TestContextVarPropagation:
    @pytest.mark.asyncio
    async def test_ask_callback_propagates_across_to_thread(self) -> None:
        import asyncio

        from clanker.tools import ask_tools

        called: list[tuple[str, list[str]]] = []

        def dummy_cb(question: str, options: list[str], **kwargs: Any) -> dict[str, Any]:
            called.append((question, options))
            return {"selected": ["Option 1"], "cancelled": False}

        ask_tools.set_ask_callback(dummy_cb)
        try:
            # invoke ask_user inside an asyncio.to_thread worker
            res = await asyncio.to_thread(
                ask_tools.ask_user.invoke,
                {"question": "What to do?", "options": ["Option 1", "Option 2"]},
            )
            assert res == {"ok": True, "selected": ["Option 1"], "cancelled": False}
            assert len(called) == 1
            assert called[0][0] == "What to do?"
        finally:
            ask_tools.set_ask_callback(None)

    @pytest.mark.asyncio
    async def test_bash_approval_callback_propagates_across_to_thread(self) -> None:
        import asyncio

        from clanker.tools import bash_tools

        called: list[tuple[str, str | None]] = []

        def dummy_approval(question: str, options: list[str], *, preface: str | None = None) -> dict[str, Any]:
            called.append((question, preface))
            return {"selected": [bash_tools._APPROVE_YES], "cancelled": False}

        bash_tools.set_approval_callback(dummy_approval)
        try:
            res = await asyncio.to_thread(
                bash_tools.prompt_for_approval,
                "rm -rf /tmp/foo",
            )
            assert res is True
            assert len(called) == 1
            assert "rm -rf /tmp/foo" in (called[0][1] or "")
        finally:
            bash_tools.set_approval_callback(None)

    @pytest.mark.asyncio
    async def test_notify_callback_propagates_across_to_thread(self) -> None:
        import asyncio

        from clanker.tools import notify_tools

        called: list[tuple[str, str, str | None]] = []

        def dummy_notify(message: str, level: str, title: str | None) -> None:
            called.append((message, level, title))

        notify_tools.set_notify_callback(dummy_notify)
        try:
            res = await asyncio.to_thread(
                notify_tools.notify.invoke,
                {"message": "Deploying...", "level": "info", "title": "Deploy"},
            )
            assert res["ok"] is True
            assert len(called) == 1
            assert called[0] == ("Deploying...", "info", "Deploy")
        finally:
            notify_tools.set_notify_callback(None)

    @pytest.mark.asyncio
    async def test_todo_store_propagates_across_to_thread(self) -> None:
        import asyncio

        from clanker.tools import todo_tools

        store = todo_tools.get_todo_store()
        store.clear()
        try:
            # write todos from worker thread
            await asyncio.to_thread(
                todo_tools.todo_write.invoke,
                {"todos": [{"content": "Task 1", "status": "in_progress"}]},
            )
            # read back from main thread
            items = store.read()
            assert len(items) == 1
            assert items[0].content == "Task 1"
            assert items[0].status == "in_progress"
        finally:
            store.clear()

    @pytest.mark.asyncio
    async def test_langchain_agent_thread_propagation(self) -> None:
        from langchain_core.callbacks.manager import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
        from langchain_core.language_models.chat_models import BaseChatModel
        from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
        from langchain_core.outputs import ChatGeneration, ChatResult
        from langchain_core.runnables import Runnable
        from langgraph.prebuilt import create_react_agent

        from clanker.tools import ask_tools

        class CustomFakeChatModel(BaseChatModel):
            responses: list[AIMessage]
            _idx: int = 0

            @property
            def _llm_type(self) -> str:
                return "custom_fake_chat_model"

            def bind_tools(
                self,
                tools: Sequence[dict[str, Any] | type | Callable[..., Any] | Any],
                **kwargs: Any,
            ) -> Runnable[Any, Any]:
                return self

            def _generate(
                self,
                messages: list[BaseMessage],
                stop: list[str] | None = None,
                run_manager: CallbackManagerForLLMRun | None = None,
                **kwargs: Any,
            ) -> ChatResult:
                msg = self.responses[self._idx]
                self._idx += 1
                return ChatResult(generations=[ChatGeneration(message=msg)])

            async def _agenerate(
                self,
                messages: list[BaseMessage],
                stop: list[str] | None = None,
                run_manager: AsyncCallbackManagerForLLMRun | None = None,
                **kwargs: Any,
            ) -> ChatResult:
                msg = self.responses[self._idx]
                self._idx += 1
                return ChatResult(generations=[ChatGeneration(message=msg)])

        call_records: list[dict[str, Any]] = []

        def modal_ask_callback(question: str, options: list[str], **kwargs: Any) -> dict[str, Any]:
            call_records.append({"question": question, "options": options})
            return {"selected": [options[0]], "cancelled": False}

        tool_call_msg = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "ask_user",
                    "args": {"question": "Select target:", "options": ["staging", "prod"]},
                    "id": "call_123",
                }
            ],
        )
        final_ai_msg = AIMessage(content="You selected staging.")
        llm = CustomFakeChatModel(responses=[tool_call_msg, final_ai_msg])
        agent = create_react_agent(llm, [ask_tools.ask_user])

        ask_tools.set_ask_callback(modal_ask_callback)
        try:
            events = []
            async for ev in agent.astream_events(
                {"messages": [HumanMessage(content="Where should I deploy?")]},
                version="v2",
            ):
                events.append(ev)

            assert len(call_records) == 1
            assert call_records[0]["question"] == "Select target:"
            assert call_records[0]["options"] == ["staging", "prod"]

            tool_end_events = [e for e in events if e.get("event") == "on_tool_end"]
            assert len(tool_end_events) == 1
            output = tool_end_events[0]["data"]["output"]
            if hasattr(output, "content"):
                import json

                assert json.loads(output.content) == {"ok": True, "selected": ["staging"], "cancelled": False}
            else:
                assert output == {"ok": True, "selected": ["staging"], "cancelled": False}
        finally:
            ask_tools.set_ask_callback(None)
