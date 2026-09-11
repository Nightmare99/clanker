"""In-app questions and command approvals from managed task threads."""

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, SelectionList, Static


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
        self.preface = preface
        self._cancel_pending = False

    def compose(self) -> ComposeResult:
        with Vertical(id="task-question"):
            yield Static(Text(f"{self.agent} needs your input", style="bold cyan"))
            if self.preface:
                yield Static(Text(self.preface))
            yield Static(Text(self.question))
            yield SelectionList(
                *[(Text(option), i) for i, option in enumerate(self.options)], id="question-options"
            )
            if self.allow_other:
                yield Input(placeholder="Or enter your answer", id="question-other")
            yield Static("Select an option with Space, then choose Respond.", id="question-help")
            with Horizontal(id="question-actions"):
                yield Button("Respond", id="question-submit", variant="primary")
                yield Button("Cancel", id="question-cancel")

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
        if self.is_current:
            self.dismiss({"selected": [], "cancelled": True})
        else:
            self._cancel_pending = True

    def on_screen_resume(self) -> None:
        if self._cancel_pending:
            self.action_cancel()
