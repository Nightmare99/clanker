"""Fullscreen unified REPL and mid-turn input application.

Provides a unified terminal dashboard:
- Top: Scrollable conversation history and agent streaming output.
- Middle: Agent status bar (e.g. "Ready", "Thinking...", "Running tool...").
- Bottom: Input field showing `❯` (when idle) and `✎` (when running) for commands and prompts.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
from collections.abc import Callable

from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import HTML, ANSI
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import HSplit, Window, FloatContainer, Float
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import TextArea
from prompt_toolkit.history import FileHistory

logger = logging.getLogger("ui")


class PTKConsoleStream:
    """Stream wrapper to redirect Console writes to the layout app."""

    def __init__(self, write_callback: Callable[[str], None]) -> None:
        self.write_callback = write_callback

    def write(self, s: str) -> int:
        self.write_callback(s)
        return len(s)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return True


class ScrollableWindow(Window):
    """Subclass of Window to override scroll calculations for non-focused wrap_lines.

    Ensures get_vertical_scroll is evaluated and honored even when wrap_lines=True.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.scroll_y = 0

    def _scroll_when_linewrapping(self, ui_content, width, height) -> None:
        super()._scroll_when_linewrapping(ui_content, width, height)
        self.vertical_scroll = self.scroll_y

    def _scroll_without_linewrapping(self, ui_content, width, height) -> None:
        super()._scroll_without_linewrapping(ui_content, width, height)
        self.vertical_scroll = self.scroll_y

    def _scroll_down(self) -> None:
        info = self.render_info
        if info is None:
            return
        max_scroll = max(0, info.content_height - info.window_height)
        if self.scroll_y < max_scroll:
            self.scroll_y += 1
            self.vertical_scroll = self.scroll_y

    def _scroll_up(self) -> None:
        if self.scroll_y > 0:
            self.scroll_y -= 1
            self.vertical_scroll = self.scroll_y


class REPLApplication:
    """The dedicated full-screen layout application for the entire Clanker session."""

    def __init__(
        self,
        console,
        settings,
        session_manager,
        token_tracker,
        conversation_messages: list,
        pending_restore_messages: list,
        working_dir: str,
    ) -> None:
        self.console = console
        self.settings = settings
        self.session_manager = session_manager
        self.token_tracker = token_tracker
        self.conversation_messages = conversation_messages
        self.pending_restore_messages = pending_restore_messages
        self.working_dir = working_dir

        self.output_text = ""
        self.status_text = "Ready"
        self.is_running = False
        self.carriage_returned = False
        self._mid_turn_queue: asyncio.Queue[str] = asyncio.Queue()
        self._app_task: asyncio.Task | None = None
        self._original_file = None
        self.on_cancel: Callable[[], None] | None = None

        # 1. Output Area (Scrollable window containing formatted ANSI text)
        self.output_control = FormattedTextControl(
            text=lambda: ANSI(self.output_text),
            focusable=False,
        )
        self.output_window = ScrollableWindow(
            content=self.output_control,
            wrap_lines=True,
        )

        # 2. Status Bar
        self.status_control = FormattedTextControl(self._get_status_text)
        self.status_window = Window(
            height=1,
            content=self.status_control,
            style="class:status-bar",
        )

        # 3. Input Field with persistent command history and autocompletion
        from clanker.cli import CommandCompleter
        completer = CommandCompleter()
        history_path = settings.memory.storage_path / "history"
        history_path.parent.mkdir(parents=True, exist_ok=True)
        self.input_field = TextArea(
            height=1,
            prompt=self._get_prompt,
            multiline=False,
            accept_handler=self._handle_input,
            history=FileHistory(str(history_path)),
            completer=completer,
            complete_while_typing=True,
        )

        # Keybindings
        kb = KeyBindings()

        @kb.add("c-c")
        def _(event) -> None:
            if self.is_running:
                if self.on_cancel:
                    self.on_cancel()
            else:
                event.app.exit()

        @kb.add("pageup")
        def _(event) -> None:
            self.output_window.scroll_y = max(0, self.output_window.scroll_y - 10)
            self.output_window.vertical_scroll = self.output_window.scroll_y

        @kb.add("pagedown")
        def _(event) -> None:
            info = self.output_window.render_info
            if info is not None:
                max_scroll = max(0, info.content_height - info.window_height)
                self.output_window.scroll_y = min(max_scroll, self.output_window.scroll_y + 10)
            else:
                self.output_window.scroll_y += 10
            self.output_window.vertical_scroll = self.output_window.scroll_y

        @kb.add("s-up")
        def _(event) -> None:
            self.output_window.scroll_y = max(0, self.output_window.scroll_y - 1)
            self.output_window.vertical_scroll = self.output_window.scroll_y

        @kb.add("s-down")
        def _(event) -> None:
            info = self.output_window.render_info
            if info is not None:
                max_scroll = max(0, info.content_height - info.window_height)
                self.output_window.scroll_y = min(max_scroll, self.output_window.scroll_y + 1)
            else:
                self.output_window.scroll_y += 1
            self.output_window.vertical_scroll = self.output_window.scroll_y

        # Style
        self.style = Style.from_dict({
            "status-bar": "bg:#1e1e1e #00d2b4 bold",
            "divider": "#333333",
        })

        # Layout: Wrap body in FloatContainer to support floating dropdown autocompletions
        body = HSplit([
            self.output_window,
            Window(height=1, char="─", style="class:divider"),
            self.status_window,
            self.input_field,
        ])
        self.layout = Layout(
            FloatContainer(
                content=body,
                floats=[
                    Float(
                        xcursor=True,
                        ycursor=True,
                        transparent=True,
                        content=CompletionsMenu(max_height=12, scroll_offset=1)
                    )
                ]
            ),
            focused_element=self.input_field,
        )

        self.app = Application(
            layout=self.layout,
            key_bindings=kb,
            style=self.style,
            full_screen=True,
            mouse_support=True,
        )

    # ------------------------------------------------------------------
    # REPL Run Methods
    # ------------------------------------------------------------------

    async def run_async(self) -> None:
        """Run the REPL application asynchronously."""
        # 1. Redirect Console writes to our layout
        self._original_file = self.console._console.file
        self.console._console.file = PTKConsoleStream(self.append_output)

        # 2. Show the welcome message
        from clanker.agent.prompts import load_user_instructions
        has_instructions = bool(load_user_instructions())
        self.console.print_welcome(user_instructions_loaded=has_instructions)

        # 3. Check for updates
        try:
            from clanker.update import get_update_message
            update_msg = get_update_message()
            if update_msg:
                self.console.print_update_available(update_msg)
        except Exception:
            pass

        # 4. Handle initial session resume message if pending
        if self.conversation_messages:
            self.append_output(f"Resuming session {self.session_manager.session_id} with {len(self.conversation_messages)} messages\n")
            self.append_output("Recent messages:\n")
            for msg in self.conversation_messages[-4:]:
                role = "You" if hasattr(msg, "type") and msg.type == "human" else "Assistant"
                content = msg.content[:100] + "..." if len(msg.content) > 100 else msg.content
                self.append_output(f"  [{role}] {content}\n")

        # 5. Run prompt_toolkit app
        try:
            await self.app.run_async()
        finally:
            # Cleanup redirects
            if self._original_file is not None:
                self.console._console.file = self._original_file
                self._original_file = None

    # ------------------------------------------------------------------
    # Mid-turn Listener Interface for streaming.py
    # ------------------------------------------------------------------

    def start_async(self) -> None:
        """No-op: Application is already running."""
        pass

    async def stop_async(self) -> None:
        """No-op: Application lifecycle is managed at the top-level."""
        pass

    async def suspend_async(self) -> None:
        """Suspend layout to let nested approvals/ask_user take over terminal."""
        # 1. Exit the app
        self.app.exit()
        # 2. Restore Console output
        if self._original_file is not None:
            self.console._console.file = self._original_file

    async def resume_async(self) -> None:
        """Resume layout after nested approvals close."""
        # 1. Redirect Console output
        self.console._console.file = PTKConsoleStream(self.append_output)
        # 2. Start a new prompt_toolkit run task
        self._app_task = asyncio.create_task(self.app.run_async())

    def finalize(self) -> None:
        """No-op: Finalization happens when run_async finishes."""
        pass

    def update_status(self, status: str) -> None:
        """Update the status text shown in the status bar."""
        self.status_text = status
        self.app.invalidate()

    def has_messages(self) -> bool:
        """True if there is at least one queued mid-turn message."""
        return not self._mid_turn_queue.empty()

    def drain(self) -> list[str]:
        """Drain and return all currently queued messages."""
        messages: list[str] = []
        while not self._mid_turn_queue.empty():
            try:
                messages.append(self._mid_turn_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return messages

    # ------------------------------------------------------------------
    # Internal Layout and Logic
    # ------------------------------------------------------------------

    def append_output(self, text: str) -> None:
        """Append printed output to the display buffer with auto-scroll preservation."""
        # Clean cursor show/hide escapes
        text = text.replace('\x1b[?25l', '').replace('\x1b[?25h', '')

        # Fast path: if there are no line-rewriting codes, do a direct append
        if not self.carriage_returned and not any(x in text for x in ('\r', '\x1b[2K', '\x1b[1A')):
            self.output_text += text
        else:
            # Slow path: process carriage returns and cursor movement escapes
            lines = self.output_text.split('\n')
            i = 0
            n = len(text)
            curr_line_idx = len(lines) - 1

            while i < n:
                if text[i:i+4] == '\x1b[1A':
                    if curr_line_idx > 0:
                        curr_line_idx -= 1
                        # Prune trailing empty lines if we moved the cursor above them
                        while len(lines) - 1 > curr_line_idx and lines[-1] == '':
                            lines.pop()
                    self.carriage_returned = False
                    i += 4
                elif text[i:i+4] == '\x1b[2K':
                    lines[curr_line_idx] = ''
                    self.carriage_returned = False
                    i += 4
                elif text[i] == '\r':
                    self.carriage_returned = True
                    i += 1
                elif text[i] == '\n':
                    if curr_line_idx == len(lines) - 1:
                        lines.append('')
                        curr_line_idx = len(lines) - 1
                    else:
                        curr_line_idx += 1
                    self.carriage_returned = False
                    i += 1
                else:
                    if self.carriage_returned:
                        lines[curr_line_idx] = ''
                        self.carriage_returned = False
                    lines[curr_line_idx] += text[i]
                    i += 1
            self.output_text = '\n'.join(lines)

        info = self.output_window.render_info
        if info is not None:
            max_scroll = max(0, info.content_height - info.window_height)
            # Only auto-scroll to the bottom if the user was already scrolled to the bottom
            # (allowing a minor 2-line threshold for cushion)
            if self.output_window.scroll_y >= max_scroll - 2:
                self.output_window.scroll_y = max_scroll
                self.output_window.vertical_scroll = max_scroll
        else:
            # Fallback when layout is not rendered yet: determine actual terminal height
            import shutil
            term_height = shutil.get_terminal_size().lines
            # Leave space for the status bar and text input field
            window_height_guess = max(10, term_height - 3)
            line_count = self.output_text.count("\n")
            max_scroll_fallback = max(0, line_count - window_height_guess)
            self.output_window.scroll_y = max_scroll_fallback
            self.output_window.vertical_scroll = max_scroll_fallback

        if hasattr(self, "app") and self.app:
            self.app.invalidate()

    def _get_status_text(self) -> HTML:
        return HTML(f"<b> Status:</b> {self.status_text}")

    def _get_prompt(self) -> HTML:
        # Prompt looks like a standard arrow ❯ when idle, and ✎ when running
        if self.is_running:
            return HTML("<ansicyan>  ✎ </ansicyan>")
        return HTML("<ansicyan>❯ </ansicyan>")

    def _handle_input(self, buffer) -> None:
        text = buffer.text.strip()
        if not text:
            return

        if self.is_running:
            # Echo input in scrollback
            self.append_output(f"\n❯ {text}\n")
            # Queue as mid-turn message
            self._mid_turn_queue.put_nowait(text)
        else:
            # Start new agent turn
            self.is_running = True
            asyncio.create_task(self._process_repl_input(text))

    async def _process_repl_input(self, text: str) -> None:
        # Echo user input in scrollback
        self.append_output(f"\n❯ {text}\n")

        # 1. Handle Slash Commands
        if text.startswith("/"):
            from clanker.cli import handle_command

            if text.strip().lower() in ("/exit", "/quit", "/q"):
                self.console.print("[bold cyan]*BZZZT*[/bold cyan] Shutdown sequence initiated. Until next time, human. [bold cyan]*WHIRR... click*[/bold cyan]\n")
                # Save snapshot before exit
                if self.conversation_messages:
                    self.session_manager.save_conversation_snapshot(self.conversation_messages)
                self.app.exit()
                return

            if text.strip().lower() == "/clear":
                self.output_text = ""
                self.output_field.text = ANSI("")
                self.session_manager.new_session()
                self.conversation_messages.clear()
                self.pending_restore_messages.clear()
                self.console.print("[bold cyan]*WHIRR*[/bold cyan] Memory banks wiped. Fresh slate initialized. [bold cyan]*CLANK*[/bold cyan]\n")
                self.is_running = False
                self.update_status("Ready")
                return

            # Execute command
            result = handle_command(text, self.console, self.session_manager, self.conversation_messages)

            if result == "exit":
                if self.conversation_messages:
                    self.session_manager.save_conversation_snapshot(self.conversation_messages)
                self.app.exit()
                return
            elif result and result.startswith("restore:"):
                session_id = result.split(":", 1)[1]
                messages = self.session_manager.get_session_messages(session_id)
                if messages:
                    self.session_manager.resume_session(session_id)
                    self.conversation_messages.clear()
                    self.conversation_messages.extend(messages)
                    self.pending_restore_messages.clear()
                    self.pending_restore_messages.extend(messages)
                    self.append_output(f"Restored session {session_id} with {len(messages)} messages\n")
                    self.append_output("Recent messages:\n")
                    for msg in messages[-4:]:
                        role = "You" if hasattr(msg, "type") and msg.type == "human" else "Assistant"
                        content = msg.content[:100] + "..." if len(msg.content) > 100 else msg.content
                        self.append_output(f"  [{role}] {content}\n")
                else:
                    self.append_output(f"Session {session_id} not found\n")
            elif result and result.startswith("workflow:"):
                workflow_prompt = result.split(":", 1)[1]
                asyncio.create_task(self._process_repl_input(workflow_prompt))
                return
            elif result and result.startswith("skill:"):
                skill_prompt = result.split(":", 1)[1]
                asyncio.create_task(self._process_repl_input(skill_prompt))
                return

            self.is_running = False
            self.update_status("Ready")
            return

        # 2. It's a new conversation turn! Run the agent graph.
        try:
            self.update_status("Thinking...")

            from langchain_core.messages import HumanMessage
            user_msg = HumanMessage(content=text)
            self.conversation_messages.append(user_msg)

            if self.pending_restore_messages:
                turn_messages = [*self.pending_restore_messages, user_msg]
                self.pending_restore_messages.clear()
            else:
                turn_messages = [user_msg]

            state = {
                "messages": turn_messages,
                "working_directory": self.working_dir,
            }

            from clanker.ui.streaming import stream_agent_response_async
            result = await stream_agent_response_async(
                self.settings,
                self.session_manager.checkpointer,
                state,
                self.session_manager.get_config(),
                self.console,
                self,  # Pass self as mid_turn_listener
            )

            # Track tokens
            if result.input_tokens > 0 or result.output_tokens > 0:
                from clanker.config import get_default_model
                cm = get_default_model()
                self.token_tracker.context_window = cm.max_input_tokens if cm else None
                turn_cost = cm.compute_cost(
                    result.input_tokens,
                    result.output_tokens,
                    result.cache_read_tokens,
                    result.cache_creation_tokens,
                ) if cm else None
                self.token_tracker.add_turn(
                    result.input_tokens,
                    result.output_tokens,
                    result.cache_read_tokens,
                    result.cache_creation_tokens,
                    turn_cost,
                )

            # Track AI response and save snapshot
            if result.response:
                from langchain_core.messages import AIMessage
                self.conversation_messages.append(AIMessage(content=result.response))
                self.session_manager.save_conversation_snapshot(self.conversation_messages)

            # Show token usage
            if (result.input_tokens > 0 or result.output_tokens > 0) and self.settings.output.show_token_usage:
                last_turn = self.token_tracker.turns[-1] if self.token_tracker.turns else None
                self.console.print_token_usage(
                    result.input_tokens,
                    result.output_tokens,
                    self.token_tracker.context_used_percent,
                    result.cache_read_tokens,
                    result.cache_creation_tokens,
                    cost_usd=last_turn.cost_usd if last_turn else None,
                    session_cost_usd=self.token_tracker.total_cost_usd,
                )

        except Exception as e:
            logger.exception("Agent error occurred: %s", e)
            self.append_output(f"\nAgent error: {e}\n")
        finally:
            self.is_running = False
            self.update_status("Ready")


# Backward compatibility alias
MidTurnInputListener = REPLApplication
