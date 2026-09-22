"""In-app questions and command approvals from managed task threads."""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from typing import Any

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, SelectionList, Static

from clanker.logging import get_logger

logger = get_logger("ui.task_prompt")


class TaskPromptScreen(ModalScreen[dict[str, Any]]):
    BINDINGS = [("escape", "cancel", "Cancel task question")]
    DEFAULT_CSS = """
    TaskPromptScreen { align: center middle; }
    TaskPromptScreen #task-question {
        width: 85%; max-height: 90%; height: auto;
        border: round rgb(0,240,240); background: black; padding: 1 2;
    }
    TaskPromptScreen Static { height: auto; }
    TaskPromptScreen SelectionList { height: auto; max-height: 12; }
    TaskPromptScreen #question-actions { height: auto; }
    """

    def __init__(
        self,
        agent: str,
        question: str,
        options: list[str],
        *,
        multi_select: bool = False,
        allow_other: bool = True,
        allow_cancel: bool = True,
        preface: str | None = None,
    ) -> None:
        super().__init__()
        self.agent = agent
        self.question = question
        self.options = options
        self.multi_select = multi_select
        self.allow_other = allow_other
        self.allow_cancel = allow_cancel
        self.preface = preface
        self._cancel_pending = False

    def compose(self) -> ComposeResult:
        with Vertical(id="task-question"):
            agent_title = f"{self.agent.capitalize()} needs your input" if self.agent else "Input required"
            yield Static(Text(agent_title, style="bold cyan"))
            if self.preface:
                yield Static(Text(self.preface))
            yield Static(Text(self.question))
            yield SelectionList(
                *[(Text(option), i) for i, option in enumerate(self.options)], id="question-options"
            )
            if self.allow_other:
                yield Input(placeholder="Or enter your answer", id="question-other")
            if self.multi_select:
                hint = "Space toggles · Tab to navigate · Enter on Respond to confirm · Esc to cancel"
            elif self.allow_other:
                hint = "↑/↓ to move · Enter to select · Tab for custom answer · Esc to cancel"
            else:
                hint = "↑/↓ to move · Enter to select · Esc to cancel"
            yield Static(hint, id="question-help")
            with Horizontal(id="question-actions"):
                yield Button("Respond", id="question-submit", variant="primary")
                if self.allow_cancel:
                    yield Button("Cancel", id="question-cancel")

    def on_key(self, event: events.Key) -> None:
        if event.key == "enter" and not self.multi_select and isinstance(self.focused, SelectionList):
            sl = self.focused
            if sl.highlighted is not None:
                event.prevent_default()
                event.stop()
                val = sl.get_option_at_index(sl.highlighted).value
                for other in list(sl.selected):
                    if other != val:
                        sl.deselect(other)
                sl.select(val)
                self._respond()
            elif sl.selected:
                event.prevent_default()
                event.stop()
                self._respond()

    def on_selection_list_selection_toggled(
        self, event: SelectionList.SelectionToggled[Any]
    ) -> None:
        if not self.multi_select:
            sl = event.selection_list
            toggled_val = sl.get_option_at_index(event.selection_index).value
            if toggled_val in sl.selected:
                for val in list(sl.selected):
                    if val != toggled_val:
                        sl.deselect(val)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "question-cancel":
            self.action_cancel()
            return
        self._respond()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._respond()

    def _respond(self) -> None:
        selected = self.query_one(SelectionList).selected
        other = self.query_one("#question-other", Input).value.strip() if self.allow_other else ""
        answers = [other] if other else [self.options[i] for i in selected]
        if not answers or (not self.multi_select and len(answers) != 1):
            self.query_one("#question-help", Static).update(
                "Choose one answer." if not self.multi_select else "Choose at least one answer."
            )
            return
        self.dismiss({"selected": answers, "cancelled": False})

    def action_cancel(self) -> None:
        if not self.allow_cancel:
            return
        if self.is_current:
            self.dismiss({"selected": [], "cancelled": True})
        else:
            self._cancel_pending = True

    def force_cancel(self) -> None:
        if self.is_current:
            self.dismiss({"selected": [], "cancelled": True})
        else:
            self._cancel_pending = True

    def on_screen_resume(self) -> None:
        if self._cancel_pending:
            self.force_cancel()


def show_prompt_modal(
    app: Any,
    agent: str,
    question: str,
    options: list[str],
    *,
    multi_select: bool = False,
    allow_other: bool = True,
    allow_cancel: bool = True,
    preface: str | None = None,
    check_cancelled: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Display a modal question/selection dialog on a running Textual app.

    Pushes TaskPromptScreen from a background worker thread and blocks until
    the user responds, the dialog is cancelled, or check_cancelled() returns True.
    """
    screen = TaskPromptScreen(
        agent,
        question,
        options,
        multi_select=multi_select,
        allow_other=allow_other,
        allow_cancel=allow_cancel,
        preface=preface,
    )
    response: list[dict[str, Any]] = []
    answered = threading.Event()

    def receive(result: dict[str, Any]) -> None:
        response.append(result)
        answered.set()

    if app is None or not getattr(app, "is_running", True):
        return {"selected": [], "cancelled": True}
    if check_cancelled and check_cancelled():
        return {"selected": [], "cancelled": True}

    try:
        app.call_from_thread(app.push_screen, screen, receive)
    except Exception as exc:
        logger.warning("Failed to push TaskPromptScreen: %s", exc)
        return {"selected": [], "cancelled": True}

    seen_on_stack = False
    while not answered.wait(0.05):
        if not getattr(app, "is_running", True):
            return {"selected": [], "cancelled": True}
        loop = getattr(app, "_loop", None)
        if loop is not None and (loop.is_closed() or not loop.is_running()):
            return {"selected": [], "cancelled": True}
        stack = getattr(app, "screen_stack", None)
        if stack is not None:
            if screen in stack:
                seen_on_stack = True
            elif seen_on_stack:
                return {"selected": [], "cancelled": True}
        if check_cancelled and check_cancelled():
            with contextlib.suppress(Exception):
                app.call_from_thread(screen.force_cancel)
            return {"selected": [], "cancelled": True}

    return response[0] if response else {"selected": [], "cancelled": True}
