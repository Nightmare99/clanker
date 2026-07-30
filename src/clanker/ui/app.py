"""Clanker Textual TUI Application."""

from __future__ import annotations

import asyncio
import itertools
from pathlib import Path
from typing import TYPE_CHECKING

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Input, Label, Static

from clanker.ui.chat_log import ChatLog, MessageType
from clanker.ui.status_bar import StatusBar
from clanker.ui.completion_menu import CompletionMenu

if TYPE_CHECKING:
    from clanker.config import Settings
    from clanker.ui.console import Console
    from clanker.ui.streaming import StreamResult

# ansi_shadow CLNKR — reads clearly, block style
_CLNKR_ART = r"""
  ██████╗██╗     ███╗   ██╗██╗  ██╗██████╗
 ██╔════╝██║     ████╗  ██║██║ ██╔╝██╔══██╗
 ██║     ██║     ██╔██╗ ██║█████╔╝ ██████╔╝
 ██║     ██║     ██║╚██╗██║██╔═██╗ ██╔══██╗
 ╚██████╗███████╗██║ ╚████║██║  ██╗██║  ██║
  ╚═════╝╚══════╝╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝  ╚═╝
  """

_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

_SLASH_COMMANDS = [
    "/clear", "/compact", "/config", "/copilot-login", "/exit", "/forget",
    "/help", "/history", "/list_memories", "/logs", "/memories", "/model",
    "/mcp", "/remember", "/restore", "/skill", "/workflow",
]


class PromptInput(Input):
    """Input widget with Tab completion menu and Alt+Up/Down history navigation."""

    can_focus_within = False

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._history: list[str] = []
        self._history_index: int = -1
        self._saved_input: str = ""
        self._completion_menu: CompletionMenu | None = None
        self._menu_active = False
        # True once the user has explicitly taken keyboard control of the menu
        # (via Tab). Until then the menu is only a visual hint — Up/Down/Enter
        # keep their normal behavior (history nav / submit).
        self._menu_engaged = False
        # Cursor offset at the moment Tab was pressed, so we can restore it
        self._tab_cursor_offset: int = 0
        # Tracks previous value so watch_value can detect the "/" transition
        self._previous_value: str = ""
        self._on_history_add: callable | None = None

    def set_completion_menu(self, menu: CompletionMenu) -> None:
        self._completion_menu = menu

    def set_history(self, history: list[str]) -> None:
        """Set app-scoped history (loaded from file)."""
        self._history = list(history)
        self._history_index = -1

    def set_history_add_callback(self, callback: callable) -> None:
        """Set callback invoked when a new item is added to history."""
        self._on_history_add = callback

    # -- key handling ----------------------------------------------------------

    def on_key(self, event) -> None:
        key = event.key

        # Tab: activate / cycle / accept completion
        if key == "tab":
            self._on_tab()
            event.stop()
            return

        # While menu is active AND engaged (user pressed Tab to take control) …
        if self._menu_active and self._menu_engaged and self._completion_menu:
            if key == "enter":
                selected = self._completion_menu.get_selected()
                if selected:
                    self._accept_completion(selected)
                    event.stop()
                    return
            elif key == "up":
                self._completion_menu.prev_item()
                event.stop()
                return
            elif key == "down":
                self._completion_menu.next_item()
                event.stop()
                return
            elif key == "escape":
                self._hide_menu()
                event.stop()
                return
            # Printable keys, backspace, delete — let the Input widget handle
            # them normally so the text updates; watch_value will re-filter
            # the menu afterward.

        # Up / Down (and Alt+Up / Alt+Down): history navigation when menu is closed
        if key in ("up", "m-up"):
            self._navigate_history(-1)
            event.stop()
            return
        if key in ("down", "m-down"):
            self._navigate_history(1)
            event.stop()
            return

        # Plain Escape (no menu): clear input
        if key == "escape":
            self.value = ""
            event.stop()

    # -- auto-show menu on "/" transition --------------------------------------

    def watch_value(self, value: str) -> None:
        """Show (or re-filter) the completion menu when input starts with '/'.

        Fires on the initial "/" transition and then keeps the menu in sync
        whenever the menu is already open — without consuming the key event
        so the Input widget still processes every keystroke normally.
        """
        prev = self._previous_value
        self._previous_value = value

        if not value.startswith("/"):
            if self._menu_active and self._completion_menu:
                self._hide_menu()
            return

        # Case 1: just typed "/" — open the menu
        if not prev.startswith("/"):
            if self._completion_menu and not self._menu_active:
                self._completion_menu.show(value)
                if self._completion_menu._matches:
                    self._menu_active = True
        # Case 2: menu already open — re-filter to match edited text
        elif self._menu_active and self._completion_menu:
            self._completion_menu.show(value, engaged=self._menu_engaged)

    # -- tab completion --------------------------------------------------------

    def _on_tab(self) -> None:
        text = self.value
        if not text or not text.startswith("/"):
            return

        if not self._completion_menu:
            # Fallback: inline completion without menu
            self._tab_inline()
            return

        # Record cursor position so we can restore relative position
        self._tab_cursor_offset = self.cursor_position

        if self._menu_active and self._menu_engaged:
            # Menu already engaged — accept highlighted item
            selected = self._completion_menu.get_selected()
            if selected:
                self._accept_completion(selected)
            return

        # Menu may already be visible (auto-shown on "/"), but not yet engaged.
        if not self._menu_active:
            self._completion_menu.show(text, engaged=True)
        else:
            self._completion_menu.set_engaged(True)

        if self._completion_menu._matches:
            self._menu_active = True
            self._menu_engaged = True

    def _tab_inline(self) -> None:
        """Inline completion fallback when no menu is wired."""
        text = self.value
        matches = [c for c in _SLASH_COMMANDS if c.startswith(text)]
        if matches:
            self.value = matches[0]
            self.cursor_position = len(matches[0])

    def _accept_completion(self, completion: str) -> None:
        """Replace the pre-cursor text with the completion, restore cursor offset."""
        cursor = self._tab_cursor_offset
        before = self.value[:cursor]
        after = self.value[cursor:]
        self.value = completion + after
        self.cursor_position = len(completion) + len(after)
        self._hide_menu()

    def _hide_menu(self) -> None:
        if self._menu_active and self._completion_menu:
            self._menu_active = False
            self._menu_engaged = False
            self._completion_menu.hide()

    # -- history navigation (Alt+Up / Alt+Down) --------------------------------

    def _navigate_history(self, direction: int) -> None:
        if not self._history:
            return
        self._hide_menu()
        if direction < 0:
            if self._history_index == -1:
                self._saved_input = self.value
            next_idx = self._history_index + 1
            if next_idx < len(self._history):
                self._history_index = next_idx
                self.value = self._history[len(self._history) - 1 - self._history_index]
                self.cursor_position = len(self.value)
        else:
            if self._history_index <= 0:
                self._history_index = -1
                self.value = self._saved_input
                self._saved_input = ""
                self.cursor_position = len(self.value)
                return
            self._history_index -= 1
            self.value = self._history[len(self._history) - 1 - self._history_index]
            self.cursor_position = len(self.value)

    def add_to_history(self, text: str) -> None:
        if text.strip():
            self._history.append(text.strip())
            self._history_index = -1
            if self._on_history_add:
                self._on_history_add(text.strip())


class MessageQueue(Static):
    """Shows messages queued while the agent is processing, above the input bar."""

    DEFAULT_CSS = """
    MessageQueue {
        dock: bottom;
        background: black;
        color: rgb(150, 150, 150);
        padding: 0 1;
        display: none;
    }
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._entries: list[tuple[str, bool]] = []  # (text, picked_up)

    def add_pending(self, text: str) -> None:
        self._entries.append((text, False))
        self._refresh()

    def mark_all_picked_up(self) -> None:
        self._entries = [(text, True) for text, _ in self._entries]
        self._refresh()
        self.set_timer(1.5, self._clear_if_all_picked_up)

    def _clear_if_all_picked_up(self) -> None:
        if all(picked for _, picked in self._entries):
            self.clear()

    def clear(self) -> None:
        self._entries = []
        self._refresh()

    def _refresh(self) -> None:
        if not self._entries:
            self.display = False
            self.update("")
            return
        self.display = True
        lines = []
        for text, picked in self._entries:
            mark = "✓" if picked else "⏳"
            preview = text if len(text) <= 80 else text[:77] + "..."
            lines.append(f"{mark} {preview}")
        self.update("\n".join(lines))


class PromptBar(Horizontal):
    """Bottom input bar with > prompt symbol, Input widget, and completion menu."""

    DEFAULT_CSS = """
    PromptBar {
        height: 1;
        dock: bottom;
        background: black;
        padding: 0;
    }

    PromptBar #prompt-symbol {
        color: rgb(0, 240, 240);
        width: 2;
    }

    PromptBar #prompt-input {
        width: 1fr;
        border: none;
        background: black;
        color: rgb(200, 200, 200);
        padding: 0;
    }

    PromptBar #prompt-input:focus {
        border: none;
        background: black;
        color: rgb(200, 200, 200);
    }

    PromptBar #prompt-input:hover {
        border: none;
        background: black;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label(">", id="prompt-symbol")
        yield PromptInput(
            placeholder="Type your message... (ctrl+c interrupt)",
            id="prompt-input",
        )


class ClankerApp(App):
    """Main Textual application for Clanker."""

    CSS_PATH = str(Path(__file__).parent / "styles.tcss")

    BINDINGS = [
        # Priority so this always wins over Input's own "ctrl+c: copy selection
        # within the field" binding and Screen's silent built-in copy binding —
        # both would otherwise pre-empt this action with no user feedback.
        Binding("ctrl+c", "copy_or_interrupt", "Copy/Interrupt", show=True, priority=True),
        Binding("ctrl+d", "quit", "Quit", show=True),
    ]

    def __init__(
        self,
        console: Console,
        model_info: str = "",
        update_message: str | None = None,
    ) -> None:
        super().__init__()
        self.clanker_console = console
        self.interrupt_requested = False
        self._interrupt_event = asyncio.Event()
        self._model_info = model_info
        self._update_message = update_message
        self._processing = False
        self._input_history: list[str] = self._load_history()
        self._input_queue: asyncio.Queue[str] = asyncio.Queue()

    def _load_history(self) -> list[str]:
        """Load input history from file across sessions."""
        try:
            history_file = Path.home() / ".clanker" / "input_history.txt"
            if history_file.exists():
                lines = history_file.read_text().strip().split("\n")
                return [l for l in lines if l.strip()][-500:]
        except OSError:
            pass
        return []

    def _save_history(self) -> None:
        """Persist input history to file."""
        try:
            history_file = Path.home() / ".clanker" / "input_history.txt"
            history_file.parent.mkdir(parents=True, exist_ok=True)
            history_file.write_text("\n".join(self._input_history[-500:]) + "\n")
        except OSError:
            pass

    def compose(self) -> ComposeResult:
        yield ChatLog(id="chat-log")
        yield StatusBar(id="status-bar")
        yield MessageQueue(id="message-queue")
        yield PromptBar(id="prompt-bar")
        yield CompletionMenu(_SLASH_COMMANDS)

    def on_mount(self) -> None:
        prompt_input = self.query_one("#prompt-input", PromptInput)
        prompt_input.focus()
        prompt_input.set_history(self._input_history)
        prompt_input.set_history_add_callback(self._on_input_history_add)

        # Wire completion menu to input
        menu = self.query_one("#completion-menu", CompletionMenu)
        prompt_input.set_completion_menu(menu)
        menu.set_subcommand_completer(self._complete_subcommand)

        chat_log = self.get_chat_log()

        if self._update_message:
            chat_log.add_message(
                f"[Update Available] {self._update_message}",
                MessageType.INFO,
            )

        self.run_worker(self._play_hero(chat_log))

    async def _play_hero(self, chat_log: ChatLog) -> None:
        """Play the hero animation inside the chat log — persists after reveal."""
        from clanker.runtime import is_yolo_mode

        art_lines = _CLNKR_ART.split("\n")
        spinner = itertools.cycle(_SPINNER_FRAMES)

        for i in range(1, len(art_lines) + 1):
            partial = "\n".join(art_lines[:i])
            chat_log.update_hero_art(partial)
            await asyncio.sleep(0.08)

        for _ in range(6):
            frame = next(spinner)
            chat_log.update_hero_art(_CLNKR_ART, init_text=f"  {frame} Initializing subsystems...")
            await asyncio.sleep(0.12)

        chat_log.update_hero_final(
            art=_CLNKR_ART,
            model_info=self._model_info,
            yolo_mode=is_yolo_mode(),
        )

    # --- Widget accessors ---

    def get_chat_log(self) -> ChatLog:
        return self.query_one("#chat-log", ChatLog)

    def get_status_bar(self) -> StatusBar:
        return self.query_one("#status-bar", StatusBar)

    def get_prompt_input(self) -> PromptInput:
        return self.query_one("#prompt-input", PromptInput)

    def get_message_queue(self) -> MessageQueue:
        return self.query_one("#message-queue", MessageQueue)

    # --- Actions ---

    def _on_input_history_add(self, text: str) -> None:
        self._input_history.append(text)
        self._save_history()
        prompt_input = self.get_prompt_input()
        prompt_input.set_history(self._input_history)

    def action_copy_or_interrupt(self) -> None:
        """Copy selected text if any, otherwise interrupt the agent.

        Checks the focused Input's own in-field selection first (its own
        cursor-based selection system), then the screen-wide mouse-drag
        selection, before falling back to interrupting the agent.
        """
        focused = self.focused
        input_selection = (
            focused.selected_text if isinstance(focused, Input) else None
        )
        selected_text = input_selection or self.screen.get_selected_text()
        if selected_text:
            self.copy_to_clipboard(selected_text)
            self.notify(f"Copied {len(selected_text)} characters", severity="information")
        else:
            self.action_interrupt()

    def action_interrupt(self) -> None:
        from clanker.ui.streaming import _cancel_streaming_task

        self.interrupt_requested = True
        self._interrupt_event.set()
        _cancel_streaming_task()

    def action_quit(self) -> None:
        self._save_history()
        self.exit()

    def reset_interrupt(self) -> None:
        from clanker.ui.streaming import reset_interrupted

        self.interrupt_requested = False
        self._interrupt_event.clear()
        reset_interrupted()

    def add_subagent_tokens(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
    ) -> None:
        """Accumulate subagent tokens and cost into the session tracker.

        Subagent has its own context window, so tokens do not affect the
        parent's context remaining. But we accumulate input/output tokens
        and cost so the status bar shows accurate session totals.
        """
        try:
            from clanker.config import get_default_model

            token_tracker = self._token_tracker
            cm = get_default_model()
            if cm:
                turn_cost = cm.compute_cost(
                    input_tokens,
                    output_tokens,
                    cache_read_tokens,
                    cache_creation_tokens,
                )
            else:
                turn_cost = None
            # Accumulate token counts and cost
            token_tracker.total_input += input_tokens
            token_tracker.total_output += output_tokens
            if turn_cost is not None:
                token_tracker.total_cost_usd = (
                    (token_tracker.total_cost_usd or 0.0) + turn_cost
                )
            # Refresh the status bar to show updated totals
            try:
                from clanker.config import get_settings
                settings = get_settings()
                if settings.output.show_token_usage:
                    status_bar = self.get_status_bar()
                    status_bar.set_token_usage(
                        token_tracker.total_input,
                        token_tracker.total_output,
                        token_tracker.context_remaining_percent,
                        turn_cost,
                    )
            except Exception:
                pass
        except Exception:
            pass

    # --- Input handling ---

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        text = event.value.strip()
        if not text:
            return

        prompt_input = self.get_prompt_input()
        prompt_input.add_to_history(text)
        prompt_input.value = ""

        if self._processing and not text.startswith("/"):
            self._input_queue.put_nowait(text)
            self._add_user_message_to_ui(text)
            self.get_message_queue().add_pending(text)
            return

        cmd_result = self._handle_slash_command(text)
        if cmd_result is not None:
            if cmd_result == "exit":
                self.exit()
            elif cmd_result == "skip":
                pass
            else:
                self._set_processing(True)
                self._add_user_message_to_ui(cmd_result)
                self.run_worker(self._run_agent(cmd_result), exclusive=True)
            return

        self._set_processing(True)
        self._add_user_message_to_ui(text)
        self.run_worker(self._run_agent(text), exclusive=True)

    def _add_user_message_to_ui(self, text: str) -> None:
        chat_log = self.get_chat_log()
        chat_log.add_message(text, MessageType.USER)

    def _set_processing(self, processing: bool) -> None:
        self._processing = processing
        prompt_input = self.get_prompt_input()
        prompt_input.disabled = False
        prompt_input.placeholder = (
            "Type a follow-up... (queued until agent's next step)"
            if processing
            else "Type your message... (ctrl+c interrupt)"
        )
        if not processing:
            prompt_input.focus()
            self.get_message_queue().clear()

    def _handle_slash_command(self, text: str) -> str | None:
        if not text.startswith("/"):
            return None

        if text.strip().lower() == "/copilot-login":
            # Runs in a background worker instead of through handle_command's
            # blocking poll loop -- that loop runs on the same thread as the
            # UI event loop, so a time.sleep()-based wait would freeze the
            # entire TUI for however long the user takes to approve in their
            # browser (often well over a minute).
            self.run_worker(
                self._copilot_login_flow(), exclusive=True, group="copilot-login"
            )
            return "skip"

        from clanker.cli import handle_command

        console = self.clanker_console
        session_manager = self._session_manager
        conversation_messages = self._conversation_messages
        chat_log = self.get_chat_log()

        result = handle_command(
            text, console, session_manager, conversation_messages, chat_log
        )
        if result == "exit":
            return "exit"
        if result and result.startswith("restore:"):
            session_id = result.split(":", 1)[1]
            messages = session_manager.get_session_messages(session_id)
            if messages:
                if conversation_messages:
                    session_manager.save_conversation_snapshot(conversation_messages)
                session_manager.resume_session(session_id)
                conversation_messages = list(messages)
                self._pending_restore_messages = list(messages)
                chat_log.add_message(
                    f"Restored session {session_id} with {len(messages)} messages",
                    MessageType.INFO,
                )
            else:
                chat_log.add_message(
                    f"Session {session_id} not found", MessageType.WARNING
                )
            return "skip"
        if result and (result.startswith("workflow:") or result.startswith("skill:")):
            return result.split(":", 1)[1]
        if result is None or result == "":
            return "skip"
        return "skip"

    # --- Agent execution ---

    async def _run_agent(self, user_input: str) -> None:
        from langchain_core.messages import AIMessage, HumanMessage

        from clanker.config import get_default_model
        from clanker.logging import get_logger
        from clanker.ui.streaming import stream_agent_response_async

        self.reset_interrupt()

        logger = get_logger("tui")

        console = self.clanker_console
        settings: Settings = self._settings
        session_manager = self._session_manager
        conversation_messages = self._conversation_messages
        pending_restore_messages = self._pending_restore_messages
        token_tracker = self._token_tracker
        working_dir = self._working_dir

        chat_log = self.get_chat_log()
        status_bar = self.get_status_bar()

        user_msg = HumanMessage(content=user_input)
        conversation_messages.append(user_msg)

        if pending_restore_messages:
            turn_messages = [*pending_restore_messages, user_msg]
            self._pending_restore_messages = []
        else:
            turn_messages = [user_msg]

        state = {
            "messages": turn_messages,
            "working_directory": working_dir,
        }

        console._textual_app = self

        try:
            logger.info("Processing user message: %s", user_input[:100])

            result: StreamResult = await stream_agent_response_async(
                settings,
                session_manager.checkpointer,
                state,
                session_manager.get_config(),
                console,
                input_queue=self._input_queue,
            )

            if result.input_tokens > 0 or result.output_tokens > 0:
                cm = get_default_model()
                token_tracker.context_window = cm.max_input_tokens if cm else None
                turn_cost = cm.compute_cost(
                    result.input_tokens,
                    result.output_tokens,
                    result.cache_read_tokens,
                    result.cache_creation_tokens,
                ) if cm else None
                token_tracker.add_turn(
                    result.input_tokens,
                    result.output_tokens,
                    result.cache_read_tokens,
                    result.cache_creation_tokens,
                    turn_cost,
                )

            if result.response:
                conversation_messages.append(AIMessage(content=result.response))
                session_manager.save_conversation_snapshot(conversation_messages)
            else:
                logger.warning(
                    "Empty agent response. summarization=%s input=%d output=%d",
                    getattr(result, "summarization_occurred", "?"),
                    result.input_tokens,
                    result.output_tokens,
                )

            if (
                result.input_tokens > 0
                or result.output_tokens > 0
            ) and settings.output.show_token_usage:
                last_turn = token_tracker.turns[-1] if token_tracker.turns else None
                status_bar.set_token_usage(
                    result.input_tokens,
                    result.output_tokens,
                    token_tracker.context_remaining_percent,
                    last_turn.cost_usd if last_turn else None,
                )

            chat_log.add_separator()
            logger.debug("Agent response completed successfully")

        except Exception as e:
            logger.exception("Agent error: %s", e)
            chat_log.add_message(f"Agent error: {e}", MessageType.ERROR)
        finally:
            self._set_processing(False)

    # --- Copilot device-code login ---

    async def _copilot_login_flow(self) -> None:
        """Run the GitHub Copilot device-code login without blocking the UI.

        Mirrors ``handle_command``'s ``/copilot-login`` branch (used by the
        non-TUI REPL, where blocking is harmless) but polls with
        ``asyncio.sleep`` and runs each blocking HTTP call via
        ``asyncio.to_thread`` so the rest of the app stays responsive while
        waiting for the user to approve the code in their browser. Ctrl+C
        sets the same interrupt event the agent-streaming path uses, so it
        doubles as "cancel this login".
        """
        from clanker.config.copilot_auth import (
            CopilotAuthError,
            complete_login,
            poll_for_github_token,
            start_device_flow,
            sync_copilot_models,
        )

        chat_log = self.get_chat_log()
        self.reset_interrupt()

        try:
            session = await asyncio.to_thread(start_device_flow)
        except CopilotAuthError as e:
            chat_log.add_message(str(e), MessageType.ERROR)
            return

        chat_log.add_message(
            f"Open {session.verification_uri} and enter code: {session.user_code}\n"
            "Waiting for approval... (Ctrl+C to cancel)",
            MessageType.INFO,
        )

        github_token: str | None = None
        try:
            while github_token is None:
                if self._interrupt_event.is_set():
                    chat_log.add_message("Login cancelled.", MessageType.WARNING)
                    return
                await asyncio.sleep(session.interval)
                github_token = await asyncio.to_thread(poll_for_github_token, session)
        except CopilotAuthError as e:
            chat_log.add_message(str(e), MessageType.ERROR)
            return
        finally:
            self.reset_interrupt()

        try:
            await asyncio.to_thread(complete_login, github_token)
            synced = await asyncio.to_thread(sync_copilot_models)
        except CopilotAuthError as e:
            chat_log.add_message(str(e), MessageType.ERROR)
            return

        chat_log.add_message(
            f"Connected! Synced {synced} Copilot model(s).\nUse /model to switch to one.",
            MessageType.SUCCESS,
        )

    # --- Subcommand completion ---

    def _complete_subcommand(self, cmd: str, arg_prefix: str) -> list[str]:
        """Return completions for a specific subcommand's arguments."""
        try:
            if cmd == "/model":
                from clanker.config import list_model_names
                completions = list_model_names()
            elif cmd == "/skill":
                from clanker.skills import list_skills
                completions = list(list_skills().keys())
            elif cmd == "/workflow":
                from clanker.workflows import list_workflows
                completions = list_workflows()
            elif cmd == "/restore":
                completions = []
                try:
                    sm = self._session_manager
                    for sess in sm.list_sessions():
                        completions.append(sess.get("id", ""))
                except Exception:
                    pass
            else:
                return []

            if arg_prefix:
                completions = [c for c in completions if arg_prefix.lower() in c.lower()]
            return completions
        except Exception:
            return []
