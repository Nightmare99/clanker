"""Multiline Markdown composer with an optional rendered preview."""

import asyncio
import re

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Markdown, Static, TabbedContent, TabPane, TextArea

from clanker.ui.clipboard_image import ClipboardImage, read_clipboard_image
from clanker.ui.prompt_history import PromptDraft


class ComposerEditor(TextArea):
    """Paste text normally; use the OS clipboard for image paste gestures."""

    async def _on_paste(self, event: events.Paste) -> None:
        event.prevent_default()
        event.stop()
        if event.text:
            normalized = event.text.replace("\r\n", "\n").replace("\r", "\n")
            await super()._on_paste(events.Paste(normalized))
        else:
            self.screen.start_image_paste()

    def action_paste(self) -> None:
        self.screen.start_image_paste(fallback_text=self.app.clipboard)

    def action_cursor_up(self, select: bool = False) -> None:
        if (
            not select and self.selection.is_empty
            and self.get_cursor_up_location() == self.cursor_location
            and self.screen.navigate_history(1)
        ):
            return
        super().action_cursor_up(select)

    def action_cursor_down(self, select: bool = False) -> None:
        if (
            not select and self.selection.is_empty
            and self.get_cursor_down_location() == self.cursor_location
            and self.screen.navigate_history(-1)
        ):
            return
        super().action_cursor_down(select)


class MessageComposer(ModalScreen[PromptDraft | None]):
    BINDINGS = [
        Binding("escape", "discard", "Discard", priority=True),
        Binding("ctrl+enter", "send", "Send", priority=True),
    ]

    DEFAULT_CSS = """
    MessageComposer { align: center middle; }
    MessageComposer #composer {
        width: 90%; height: 85%;
        border: round rgb(0,240,240); background: black; padding: 1 2;
    }
    MessageComposer #composer-title { height: 1; color: rgb(0,240,240); }
    MessageComposer TabbedContent { height: 1fr; }
    MessageComposer ContentSwitcher { height: 1fr; }
    MessageComposer TabPane { height: 1fr; padding: 0; }
    MessageComposer TextArea { height: 1fr; }
    MessageComposer #composer-actions { height: 3; margin-top: 1; }
    MessageComposer Button { margin-right: 1; }
    """

    def __init__(
        self, text: str = "", *, images: list[tuple[str, ClipboardImage]] | None = None,
        history: list[PromptDraft] | None = None,
    ) -> None:
        super().__init__()
        self._initial_text = text
        self._images = list(images or [])
        self._image_counter = max((int(n) for n in re.findall(r"\[Image #(\d+)\]", text)), default=0)
        self._pasting = False
        self._history = list(reversed(history or []))
        self._history_index = -1
        self._history_drafts: dict[int, PromptDraft] = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="composer"):
            yield Static("Markdown message · Ctrl+Enter send · Esc discard", id="composer-title")
            with TabbedContent():
                with TabPane("Write", id="composer-write"):
                    yield ComposerEditor(
                        self._initial_text, language="markdown", soft_wrap=True,
                        id="composer-editor",
                    )
                with TabPane("Preview", id="composer-preview"), VerticalScroll():
                    yield Markdown(self._initial_text, id="composer-markdown")
            with Horizontal(id="composer-actions"):
                yield Button("Send", id="composer-send", variant="primary",
                             disabled=not self._initial_text.strip())
                yield Button("Discard", id="composer-discard")

    def on_mount(self) -> None:
        self.query_one(TextArea).focus()

    def navigate_history(self, direction: int) -> bool:
        """Browse at editor boundaries without losing the draft or local edits."""
        index = self._history_index + direction
        if self._pasting or not -1 <= index < len(self._history):
            return False
        editor = self.query_one(TextArea)
        self._history_drafts[self._history_index] = PromptDraft(editor.text, images=list(self._images))
        draft = self._history_drafts.get(index)
        if draft is None:
            draft = self._history[index]
        text = draft.expanded_text()
        self._images = list(draft.images)
        self._image_counter = max((int(n) for n in re.findall(r"\[Image #(\d+)\]", text)), default=0)
        self._history_index = index
        editor.load_text(text)
        if direction < 0:
            lines = text.split("\n")
            editor.move_cursor((len(lines) - 1, len(lines[-1])))
        return True

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self.query_one("#composer-send", Button).disabled = self._pasting or not event.text_area.text.strip()

    def start_image_paste(self, fallback_text: str = "") -> None:
        if self._pasting:
            return
        self._pasting = True
        self.query_one("#composer-send", Button).disabled = True
        self.run_worker(self._paste_image(fallback_text), group="composer-image")

    async def _paste_image(self, fallback_text: str) -> None:
        editor = self.query_one(TextArea)
        try:
            image = await asyncio.to_thread(read_clipboard_image)
            if not self.is_mounted:
                return
            if image is not None:
                self._image_counter += 1
                label = f"[Image #{self._image_counter}]"
                self._images.append((label, image))
                result = editor.replace(label, *editor.selection, maintain_selection_offset=False)
                editor.move_cursor(result.end_location)
            elif fallback_text:
                await editor._on_paste(events.Paste(fallback_text))
            else:
                self.notify("No clipboard image found or image clipboard access is unavailable.")
        finally:
            self._pasting = False
            if self.is_mounted:
                self.query_one("#composer-send", Button).disabled = not editor.text.strip()

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if event.pane.id == "composer-preview":
            self.query_one(Markdown).update(self.query_one(TextArea).text)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "composer-send":
            self.action_send()
        elif event.button.id == "composer-discard":
            self.action_discard()

    def action_send(self) -> None:
        text = self.query_one(TextArea).text
        if text.strip() and not self._pasting:
            images = sorted(
                [(label, image) for label, image in self._images if label in text],
                key=lambda item: text.index(item[0]),
            )
            self.dismiss(PromptDraft(text, images=images))

    def action_discard(self) -> None:
        self.dismiss(None)
