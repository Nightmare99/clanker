"""Command-line interface for Clanker."""
# ruff: noqa: E402

import contextlib
import os
import sqlite3
import sys
import tempfile
import time
import warnings

warnings.filterwarnings("ignore", message="Core Pydantic V1 functionality")

import click
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage
from rich.markup import escape

from clanker import __version__
from clanker.agent import create_model
from clanker.config import (
    CONFIG_PATH,
    Settings,
    get_default_model,
    get_model_by_name,
    get_settings,
    list_model_names,
    reload_settings,
    set_default_model,
)
from clanker.config.setup_wizard import run_setup_wizard
from clanker.logging import get_log_path, get_logger, setup_logging
from clanker.memory.checkpointer import SessionManager
from clanker.memory.memories import get_memory_store
from clanker.runtime import set_yolo_mode
from clanker.ui.chat_log import MessageType
from clanker.ui.console import Console
from clanker.ui.streaming import cleanup_event_loop, stream_agent_response_sync
from clanker.ui.token_tracking import SessionTokenTracker

load_dotenv()


def _configure_certificates() -> None:
    try:
        import certifi
        ca_bundle = certifi.where()
    except Exception:
        return
    for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        os.environ.setdefault(var, ca_bundle)


_configure_certificates()


def _preload_tool_dependencies() -> None:
    # "pymupdf", not "fitz" -- fitz is pymupdf's legacy-name compatibility
    # shim (`from pymupdf import *`), and newer pymupdf releases print a
    # "the `fitz` API is deprecated" warning straight to stderr the moment
    # it's imported. That fired here, at CLI import time, before the TUI
    # takes over the terminal -- so it showed up as raw text in the tty.
    for module_name in ("trafilatura", "pymupdf", "pypdf"):
        with contextlib.suppress(Exception):
            __import__(module_name)
    with contextlib.suppress(Exception):
        from ddgs import DDGS
        DDGS()


_preload_tool_dependencies()

logger = get_logger("cli")


def sync_conversation_after_auto_compaction(
    conversation_messages: list,
    session_manager: SessionManager,
    settings: Settings,
    console: Console,
    chat_log=None,
) -> None:
    """Keep `conversation_messages` in sync after the middleware auto-compacts mid-turn.

    The middleware compacts the graph's own internal message list (which
    includes tool calls/results) from deep inside LangGraph -- it has no way
    to reach this app-layer, simplified per-turn transcript. Without this,
    `conversation_messages` (and therefore F3 history, session snapshots, and
    `/restore`) would keep growing forever, silently diverging from what the
    model actually retains after a turn that triggered auto-compaction.

    Mirrors the manual `/compact` command exactly: same `run_compaction` call,
    same summary pipeline, same UI feedback -- called from both the TUI
    (`app.py`, after `stream_agent_response_async`) and the legacy `--no-tui`
    REPL below, so the two entry points behave identically.
    """
    from clanker.agent.summarization import run_compaction

    try:
        model = create_model(settings)
        result = run_compaction(conversation_messages, model, settings, force=True)
        if result is None:
            return

        conversation_messages.clear()
        conversation_messages.extend(result.compacted_messages)
        session_manager.save_conversation_snapshot(conversation_messages)

        msg = (
            f"Auto-compacted conversation history ({result.summarized_count} "
            "messages summarized) to stay within the model's context window."
        )
        console.print_info(msg)
        if chat_log:
            chat_log.add_message(msg, MessageType.INFO)
    except Exception as e:
        logger.warning("Failed to sync conversation_messages after auto-compaction: %s", e)


def handle_command(
    command: str,
    console: Console,
    session_manager: SessionManager,
    conversation_messages: list | None = None,
    chat_log=None,
) -> str | None:
    """Handle built-in commands."""
    cmd = command.strip().lower()
    parts = command.strip().split(maxsplit=1)
    logger.debug("Handling command: %s", cmd)

    def _mirror(text: str, msg_type: MessageType = MessageType.INFO) -> None:
        """Mirror a plain-text command result into the TUI chat log, if present.

        Callers build ``text`` directly (no Rich markup, no baked-in line
        wrapping) so the chat log's own Text widget reflows it at its actual
        render width instead of double-wrapping console-captured output.
        """
        if chat_log and text.strip():
            chat_log.add_message(text.strip(), msg_type)

    if cmd in ("/exit", "/quit", "/q"):
        logger.info("User requested exit")
        console.print("[bold cyan]*BZZZT*[/bold cyan] Shutdown sequence initiated. [bold cyan]*WHIRR... click*[/bold cyan]")
        if chat_log:
            chat_log.add_message("Shutdown sequence initiated. *WHIRR... click*", MessageType.SYSTEM)
        return "exit"

    elif cmd == "/help":
        from clanker.ui.console import build_help_text

        console.print_help()
        _mirror(build_help_text(markup=False))

    elif cmd == "/clear":
        if conversation_messages:
            session_manager.save_conversation_snapshot(conversation_messages)
            conversation_messages.clear()
        console.clear()
        session_manager.new_session()

        from clanker.tools.todo_tools import get_todo_store

        get_todo_store().clear()
        if chat_log:
            with contextlib.suppress(Exception):
                chat_log.app.get_todo_panel().set_todos([])

        logger.info("Conversation cleared, new session started")
        console.print("[bold cyan]*WHIRR*[/bold cyan] Memory banks wiped. Fresh slate initialized. [bold cyan]*CLANK*[/bold cyan]")
        if chat_log:
            chat_log.clear()
            chat_log.add_message("Memory banks wiped. Fresh slate initialized.", MessageType.SYSTEM)

    elif cmd.startswith("/model"):
        model_names = list_model_names()
        if len(parts) == 1:
            session_model = session_manager.model_name if session_manager else None
            current = (get_model_by_name(session_model) if session_model else None) or get_default_model()
            default_model = get_default_model()
            lines = []
            if current:
                model_desc = f"Current model: {current.name} ({current.provider})"
                if default_model and default_model.name != current.name:
                    model_desc += f"  (default: {default_model.name})"
                console.print_info(model_desc)
                lines.append(model_desc)
            else:
                console.print_warning("No model configured.")
                lines.append("No model configured.")
            if model_names:
                console.print_info("\nConfigured models:")
                lines.append("\nConfigured models:")
                for name in model_names:
                    model = get_model_by_name(name)
                    if model:
                        marker = " *" if current and current.name == name else ""
                        console.print(f"  [cyan]{name}[/cyan] ({model.provider}){marker}")
                        lines.append(f"  {name} ({model.provider}){marker}")
                console.print_info("\nUse /model <name> to switch models.")
                lines.append("\nUse /model <name> to switch models.")
            else:
                console.print_info("\nNo models configured in ~/.clanker/models.json")
                console.print_info("Add models via 'clanker config'.")
                lines.append("\nNo models configured in ~/.clanker/models.json")
                lines.append("Add models via 'clanker config'.")
            if chat_log:
                chat_log.add_message("\n".join(lines), MessageType.INFO)
        else:
            target_name = parts[1].strip()
            model = get_model_by_name(target_name)
            if model:
                if session_manager:
                    session_manager.model_name = target_name
                set_default_model(target_name)
                console.print_success(f"Switched to model: {model.name} ({model.provider})")
                console.print_info("Note: Changes take effect on next message.")
                if chat_log:
                    chat_log.add_message(
                        f"Switched to model: {model.name} ({model.provider})\n"
                        "Note: Changes take effect on next message.",
                        MessageType.SUCCESS,
                    )
            else:
                console.print_warning(f"Model '{target_name}' not found.")
                msg = f"Model '{target_name}' not found."
                if model_names:
                    console.print_info(f"Available: {', '.join(model_names)}")
                    msg += f"\nAvailable: {', '.join(model_names)}"
                if chat_log:
                    chat_log.add_message(msg, MessageType.WARNING)

    elif cmd == "/openai-login":
        from clanker.config.chatgpt_auth import ChatGPTAuthError

        def emit_chatgpt_login(message: str) -> None:
            console.print_info(message)
            _mirror(message)

        try:
            synced = _run_openai_login(emit_chatgpt_login)
            message = f"Connected! Synced {synced} ChatGPT model(s). Use /model to switch to one."
            console.print_success(message)
            _mirror(message, MessageType.SUCCESS)
        except KeyboardInterrupt:
            console.print_warning("ChatGPT login cancelled.")
            _mirror("ChatGPT login cancelled.", MessageType.WARNING)
        except ChatGPTAuthError as exc:
            console.print_error(str(exc))
            _mirror(str(exc), MessageType.ERROR)

    elif cmd == "/antigravity-login":
        from clanker.config.antigravity_auth import AntigravityAuthError

        def emit_login(message: str) -> None:
            console.print_info(message)
            _mirror(message)

        try:
            synced = _run_antigravity_login(emit_login)
            message = f"Connected! Synced {synced} Antigravity model(s). Use /model to switch to one."
            console.print_success(message)
            _mirror(message, MessageType.SUCCESS)
        except KeyboardInterrupt:
            console.print_warning("Google login cancelled.")
            _mirror("Google login cancelled.", MessageType.WARNING)
        except AntigravityAuthError as exc:
            console.print_error(str(exc))
            _mirror(str(exc), MessageType.ERROR)

    elif cmd == "/copilot-login":
        from clanker.config.copilot_auth import (
            CopilotAuthError,
            complete_login,
            poll_for_github_token,
            start_device_flow,
            sync_copilot_models,
        )
        try:
            session = start_device_flow()
        except CopilotAuthError as e:
            console.print_error(str(e))
            _mirror(str(e), MessageType.ERROR)
            return None
        code_msg = f"Open {session.verification_uri} and enter code: {session.user_code}"
        console.print_info(code_msg)
        console.print_info("Waiting for approval... (Ctrl+C to cancel)")
        _mirror(f"{code_msg}\nWaiting for approval... (Ctrl+C to cancel)")
        github_token: str | None = None
        try:
            while github_token is None:
                time.sleep(session.interval)
                github_token = poll_for_github_token(session)
        except KeyboardInterrupt:
            console.print_warning("Login cancelled.")
            _mirror("Login cancelled.", MessageType.WARNING)
            return None
        except CopilotAuthError as e:
            console.print_error(str(e))
            _mirror(str(e), MessageType.ERROR)
            return None
        try:
            complete_login(github_token)
            synced = sync_copilot_models()
        except CopilotAuthError as e:
            console.print_error(str(e))
            _mirror(str(e), MessageType.ERROR)
            return None
        success_msg = f"Connected! Synced {synced} Copilot model(s).\nUse /model to switch to one."
        console.print_success(f"Connected! Synced {synced} Copilot model(s).")
        console.print_info("Use /model to switch to one.")
        _mirror(success_msg, MessageType.SUCCESS)

    elif cmd == "/config":
        settings = get_settings()
        lines = [f"Config file: {CONFIG_PATH}", f"Agent name: {settings.agent.name}"]
        session_model = session_manager.model_name if session_manager else None
        current_model = (get_model_by_name(session_model) if session_model else None) or get_default_model()
        if current_model:
            lines.append(f"Model: {current_model.name}")
            lines.append(f"Provider: {current_model.provider}")
            if current_model.model:
                lines.append(f"Model ID: {current_model.model}")
        else:
            lines.append("No model configured. Run 'clanker' to set up.")
        if settings.mcp.enabled and settings.mcp.servers:
            enabled = [n for n, s in settings.mcp.servers.items() if s.enabled]
            lines.append(f"MCP servers: {len(enabled)} enabled")
        for line in lines:
            console.print_info(line)
        _mirror("\n".join(lines))

    elif cmd == "/mcp":
        settings = get_settings()
        lines = []
        if not settings.mcp.enabled:
            lines.append("MCP is disabled")
        elif not settings.mcp.servers:
            lines.append("No MCP servers configured")
        else:
            lines.append("MCP Servers:")
            for name, server in settings.mcp.servers.items():
                status = "enabled" if server.enabled else "disabled"
                if server.transport == "stdio":
                    detail = f"{server.command} {' '.join(server.args)}"
                else:
                    detail = server.url or ""
                lines.append(f"  {name}: [{server.transport}] {status}")
                if detail:
                    lines.append(f"    {detail[:60]}{'...' if len(detail) > 60 else ''}")
        for line in lines:
            console.print_info(line)
        _mirror("\n".join(lines))

    elif cmd == "/logs":
        settings = get_settings()
        lines = []
        if not settings.logging.enabled:
            lines.append("Logging is disabled")
        else:
            log_path = get_log_path()
            if log_path and log_path.exists():
                lines.append(f"Log file: {log_path}")
                lines.append(f"Log level: {settings.logging.level}")
                lines.append(f"Max file size: {settings.logging.max_file_size_mb} MB")
                lines.append(f"Backup count: {settings.logging.backup_count}")
                log_dir = log_path.parent
                log_files = sorted(log_dir.glob("clanker.log*"))
                if log_files:
                    lines.append(f"\nLog files in {log_dir}:")
                    for f in log_files:
                        size_kb = f.stat().st_size / 1024
                        lines.append(f"  {f.name} ({size_kb:.1f} KB)")
            else:
                lines.append(f"Log directory: {settings.logging.log_dir}")
                lines.append("No log file created yet")
        for line in lines:
            console.print_info(line)
        _mirror("\n".join(lines))

    elif cmd == "/history":
        sessions = session_manager.list_sessions()
        lines = []
        if not sessions:
            lines.append("No conversation history found in this workspace.")
            lines.append("Conversations are saved to .clanker/conversations/")
            for line in lines:
                console.print_info(line)
        else:
            header = f"Conversation history ({len(sessions)} sessions):\n"
            console.print_info(header)
            lines.append(header)
            for s in sessions[:20]:
                title = s["title"][:40] + "..." if len(s["title"]) > 40 else s["title"]
                created = s["created_at"][:10] if s["created_at"] else "unknown"
                console.print(f"  [bold cyan]{escape(s['id'])}[/bold cyan]  {escape(title)}")
                console.print(f"           {created}  ({s['message_count']} messages)")
                lines.append(f"  {s['id']}  {title}")
                lines.append(f"           {created}  ({s['message_count']} messages)")
            footer = "\nUse /restore or /resume to pick a conversation."
            console.print_info(footer)
            lines.append(footer)
        _mirror("\n".join(lines))

    elif parts[0].lower() in ("/restore", "/resume"):
        parts = command.strip().split(maxsplit=1)
        if len(parts) < 2:
            return "restore_picker"
        else:
            session_id = parts[1].strip()
            return f"restore:{session_id}"

    elif cmd == "/import":
        return "import_wizard"

    elif cmd == "/compact":
        if conversation_messages is None:
            msg = "No active conversation messages context to compact."
            console.print_warning(msg)
            _mirror(msg, MessageType.WARNING)
            return None
        if not conversation_messages:
            msg = "No conversation history to compact."
            console.print_info(msg)
            _mirror(msg)
            return None
        from clanker.agent.summarization import run_compaction

        settings = get_settings()
        try:
            model = create_model()
        except ValueError as e:
            msg = f"Cannot compact: {e}"
            console.print_error(msg)
            _mirror(msg, MessageType.ERROR)
            return None

        console.print_info("Compacting conversation history...")
        if chat_log:
            chat_log.add_message("Compacting conversation history...", MessageType.INFO)

        try:
            from clanker.agent.graph import create_agent_graph

            result = run_compaction(conversation_messages, model, settings, force=True)
            if result is None:
                msg = "Nothing to compact."
                console.print_info(msg)
                _mirror(msg)
                return None

            graph = create_agent_graph(settings, checkpointer=session_manager.checkpointer)
            config = session_manager.get_config()
            graph.update_state(config, result.graph_state_update)

            conversation_messages.clear()
            conversation_messages.extend(result.compacted_messages)
            session_manager.save_conversation_snapshot(conversation_messages)
            success_msg = (
                f"Successfully compacted conversation! Condensed {result.summarized_count} messages "
                f"into a summary. History now contains {len(result.compacted_messages)} message(s)."
            )
            console.print_success(success_msg)
            _mirror(success_msg, MessageType.SUCCESS)
        except Exception as e:
            logger.exception("Failed to compact conversation: %s", e)
            error_msg = f"Failed to compact conversation: {e}"
            console.print_error(error_msg)
            _mirror(error_msg, MessageType.ERROR)

    elif cmd == "/memories":
        store = get_memory_store()
        memories = store.list_all()
        lines = []
        if not memories:
            lines.append("No memories stored for this workspace.")
            lines.append("Ask me to remember something, or use the remember tool.")
            for line in lines:
                console.print_info(line)
        else:
            header = f"Memories ({len(memories)}):\n"
            console.print_info(header)
            lines.append(header)
            for m in memories[:20]:
                content = m.content[:60] + "..." if len(m.content) > 60 else m.content
                tags = f" [{', '.join(m.tags)}]" if m.tags else ""
                console.print(f"  [bold cyan]{escape(m.id)}[/bold cyan]  {escape(content)}{escape(tags)}")
                lines.append(f"  {m.id}  {content}{tags}")
            footer = "\nMemories are automatically used in conversations."
            console.print_info(footer)
            lines.append(footer)
        _mirror("\n".join(lines))

    elif cmd.startswith("/remember"):
        parts = command.strip().split(maxsplit=1)
        if len(parts) < 2:
            msg = "Usage: /remember <something to remember>"
            console.print_warning(msg)
            _mirror(msg, MessageType.WARNING)
        else:
            content = parts[1].strip()
            store = get_memory_store()
            memory = store.add(content, source="user")
            msg = f"Remembered (ID: {memory.id}): {content[:50]}{'...' if len(content) > 50 else ''}"
            console.print_info(msg)
            _mirror(msg)

    elif cmd.startswith("/forget"):
        parts = command.strip().split(maxsplit=1)
        if len(parts) < 2:
            console.print_warning("Usage: /forget <memory-id>")
            console.print_info("Use /memories to see memory IDs.")
            _mirror(
                "Usage: /forget <memory-id>\nUse /memories to see memory IDs.",
                MessageType.WARNING,
            )
        else:
            memory_id = parts[1].strip()
            store = get_memory_store()
            if store.delete(memory_id):
                msg = f"Memory {memory_id} deleted."
                console.print_info(msg)
                _mirror(msg)
            else:
                msg = f"Memory {memory_id} not found."
                console.print_warning(msg)
                _mirror(msg, MessageType.WARNING)

    elif cmd.startswith("/workflow"):
        from clanker.workflows import (
            MAX_WORKFLOW_CHARS,
            WORKFLOW_PREAMBLE,
            list_workflows,
            load_workflow,
        )
        parts = command.strip().split(maxsplit=1)
        if len(parts) < 2:
            workflows = list_workflows()
            lines = []
            if not workflows:
                lines.append("No workflows found.")
                lines.append(
                    "Create .md files in .clanker/workflows/ (project) or "
                    "~/.clanker/workflows/ (personal) to add workflows."
                )
                for line in lines:
                    console.print_info(line)
            else:
                header = f"Available workflows ({len(workflows)}):\n"
                console.print_info(header)
                lines.append(header)
                for name in workflows:
                    console.print(f"  [bold cyan]{escape(name)}[/bold cyan]")
                    lines.append(f"  {name}")
                footer = "\nUse /workflow <name> to execute a workflow."
                console.print_info(footer)
                lines.append(footer)
            _mirror("\n".join(lines))
        else:
            workflow_name = parts[1].strip()
            content = load_workflow(workflow_name)
            if content:
                if len(content) > MAX_WORKFLOW_CHARS:
                    msg = f"Workflow '{workflow_name}' is too large ({len(content)} chars)."
                    console.print_error(msg)
                    _mirror(msg, MessageType.ERROR)
                else:
                    return f"workflow:{WORKFLOW_PREAMBLE}{content}"
            else:
                console.print_warning(f"Workflow '{workflow_name}' not found.")
                msg = f"Workflow '{workflow_name}' not found."
                workflows = list_workflows()
                if workflows:
                    console.print_info(f"Available: {', '.join(workflows)}")
                    msg += f"\nAvailable: {', '.join(workflows)}"
                _mirror(msg, MessageType.WARNING)

    elif cmd.startswith("/skill"):
        from clanker.skills import MAX_SKILL_BODY_CHARS, SKILL_PREAMBLE, list_skills, load_skill
        parts = command.strip().split(maxsplit=1)
        skills = list_skills()
        if len(parts) < 2:
            lines = []
            if not skills:
                lines.append("No skills found.")
                lines.append(
                    "Create .clanker/skills/<name>/SKILL.md (project) or "
                    "~/.clanker/skills/<name>/SKILL.md (personal) to add skills."
                )
                for line in lines:
                    console.print_info(line)
            else:
                header = f"Available skills ({len(skills)}):\n"
                console.print_info(header)
                lines.append(header)
                for skill in skills.values():
                    desc = skill.description
                    if len(desc) > 80:
                        desc = desc[:80].rstrip() + "..."
                    console.print(
                        f"  [bold cyan]{escape(skill.name)}[/bold cyan] "
                        f"[dim]({escape(skill.source)})[/dim] - {escape(desc)}"
                    )
                    lines.append(f"  {skill.name} ({skill.source}) - {desc}")
                footer = "\nThe agent loads skills automatically. Use /skill <name> to load one manually."
                console.print_info(footer)
                lines.append(footer)
            _mirror("\n".join(lines))
        else:
            skill_name = parts[1].strip()
            skill = load_skill(skill_name)
            if skill:
                body = skill.body
                if len(body) > MAX_SKILL_BODY_CHARS:
                    body = body[:MAX_SKILL_BODY_CHARS].rstrip() + "\n\n... [skill instructions truncated]"
                loaded_msg = f"Loaded skill '{skill.name}' from {skill.directory}"
                console.print_info(loaded_msg)
                _mirror(loaded_msg)
                return f"skill:{SKILL_PREAMBLE}{body}\n\nThis skill's files are in: {skill.directory}"
            else:
                msg = f"Skill '{skill_name}' not found."
                console.print_warning(msg)
                if skills:
                    available = f"Available: {', '.join(skills.keys())}"
                    console.print_info(available)
                    msg += f"\n{available}"
                _mirror(msg, MessageType.WARNING)

    else:
        msg = f"Unknown command: {command}\nType /help for available commands."
        console.print_warning(f"Unknown command: {command}")
        console.print_info("Type /help for available commands.")
        _mirror(msg, MessageType.WARNING)

    return None


class CommandCompleter:
    """Autocomplete for slash commands (used by legacy REPL and tests)."""

    COMMANDS = [
        "/help", "/exit", "/quit", "/q", "/clear", "/model", "/copilot-login", "/antigravity-login", "/openai-login",
        "/config", "/mcp", "/logs", "/history", "/restore", "/resume", "/import", "/compact",
        "/memories", "/remember", "/forget", "/workflow", "/skill",
    ]


def _print_resume_hint(console: Console, session_id: str) -> None:
    """Show a command that reopens the saved conversation from this workspace."""
    console.print_info(f"Session ID: {session_id}")
    console.print_info(f"Resume here: clanker --resume {session_id}")


def run_interactive(
    console: Console,
    settings: Settings,
    resume_session: str | None = None,
    initial_model: str | None = None,
) -> None:
    """Run the interactive TUI."""
    logger.info("Starting interactive TUI mode")

    # Setup here can take a few seconds (Copilot token refresh, the GitHub
    # release check) with no other output on screen, which reads as "stuck".
    # This spinner covers that gap and clears itself the instant the `with`
    # block exits -- including via sys.exit() below -- right before the TUI
    # takes the alternate screen.
    with console.loading_spinner("Booting up...") as update_status:
        session_manager = SessionManager(model_name=initial_model)

        resumed_messages: list | None = None
        if resume_session:
            update_status(f"Resuming session {resume_session}...")
            messages = session_manager.get_session_messages(resume_session)
            if messages:
                session_manager.resume_session(resume_session)
                if initial_model:
                    session_manager.model_name = initial_model
                resumed_messages = messages
                console.print_info(f"Resuming session {resume_session} with {len(messages)} messages")
            else:
                console.print_warning(f"Session {resume_session} not found, starting new session")

        logger.debug("Session manager initialized: session_id=%s", session_manager.session_id)

        try:
            active_model_name = session_manager.model_name
            current_model = (get_model_by_name(active_model_name) if active_model_name else None) or get_default_model()
            if current_model:
                logger.info("Validating model config: %s (provider=%s)",
                            current_model.name, current_model.provider)
                update_status(f"Validating {current_model.name}...")
            create_model(settings, model_name=active_model_name)
            logger.info("Model configuration validated successfully")
        except ValueError as e:
            logger.error("Failed to validate model config: %s", e)
            console.print_error(str(e))
            console.print_info("Run 'clanker' to run the setup wizard.")
            sys.exit(1)

        from clanker.agent.prompts import load_user_instructions
        _has_user_instructions = bool(load_user_instructions())

        active_model_name = session_manager.model_name
        current_model = (get_model_by_name(active_model_name) if active_model_name else None) or get_default_model()
        tracker_model_name = current_model.name if current_model else "unknown"
        token_tracker = SessionTokenTracker(
            model_name=tracker_model_name,
            context_window=current_model.max_input_tokens if current_model else None,
        )

        conversation_messages = list(resumed_messages) if resumed_messages else []
        pending_restore_messages = list(resumed_messages) if resumed_messages else []
        working_dir = os.getcwd()

        # Launch Textual TUI
        from clanker.ui.app import ClankerApp

        model_info = ""
        if current_model:
            model_info = f"{current_model.name} ({current_model.provider})"

        update_status("Checking for updates...")
        update_info = None
        try:
            from clanker.update import get_update_info
            update_info = get_update_info()
        except Exception:
            pass

        update_status(console.get_loading_message())
        app = ClankerApp(console, model_info=model_info, update_info=update_info)

        # Wire console ↔ app so streaming.py can reach Textual widgets
        console._textual_app = app

        # Store state on the app for the TUI to access
        app._session_manager = session_manager
        app._settings = settings
        app._conversation_messages = conversation_messages
        app._pending_restore_messages = pending_restore_messages
        app._token_tracker = token_tracker
        app._working_dir = working_dir
        app._user_instructions_loaded = _has_user_instructions

    app.run()

    # Cleanup on exit
    if conversation_messages:
        session_manager.save_conversation_snapshot(conversation_messages)
        _print_resume_hint(console, session_manager.session_id)
    cleanup_event_loop()


def run_single_prompt(
    prompt: str,
    console: Console,
    settings: Settings,
    initial_model: str | None = None,
) -> None:
    """Run a single prompt and exit."""
    session_manager = SessionManager(model_name=initial_model)
    active_model_name = session_manager.model_name

    try:
        create_model(settings, model_name=active_model_name)
    except ValueError as e:
        console.print_error(str(e))
        sys.exit(1)

    current_model = (get_model_by_name(active_model_name) if active_model_name else None) or get_default_model()
    tracker_model_name = current_model.name if current_model else "unknown"
    token_tracker = SessionTokenTracker(
        model_name=tracker_model_name,
        context_window=current_model.max_input_tokens if current_model else None,
    )

    state = {
        "messages": [HumanMessage(content=prompt)],
        "working_directory": os.getcwd(),
    }

    try:
        result = stream_agent_response_sync(
            settings,
            session_manager.checkpointer,
            state,
            session_manager.get_config(),
            console,
            model_name=active_model_name,
        )

        if result.input_tokens > 0 or result.output_tokens > 0:
            current_model_cfg = (get_model_by_name(active_model_name) if active_model_name else None) or get_default_model()
            turn_cost = current_model_cfg.compute_cost(
                result.input_tokens,
                result.output_tokens,
                result.cache_read_tokens,
                result.cache_creation_tokens,
            ) if current_model_cfg else None
            token_tracker.add_turn(
                result.input_tokens,
                result.output_tokens,
                result.cache_read_tokens,
                result.cache_creation_tokens,
                turn_cost,
            )
            if settings.output.show_token_usage:
                last_turn = token_tracker.turns[-1] if token_tracker.turns else None
                console.print_token_usage(
                    result.input_tokens,
                    result.output_tokens,
                    token_tracker.context_used_percent,
                    result.cache_read_tokens,
                    result.cache_creation_tokens,
                    cost_usd=last_turn.cost_usd if last_turn else None,
                    session_cost_usd=token_tracker.total_cost_usd,
                )
    except Exception as e:
        console.print_error(f"Agent error: {e}")
        sys.exit(1)


class ClankerGroup(click.Group):
    """Custom group that handles prompt argument alongside subcommands."""

    def invoke(self, ctx: click.Context):
        prompt = ctx.params.get("prompt")
        if prompt and prompt in self.commands:
            ctx.params["prompt"] = None
            ctx.invoked_subcommand = prompt
            cmd = self.commands[prompt]
            leftover_args = [*getattr(ctx, "_protected_args", []), *ctx.args]
            with ctx:
                sub_ctx = cmd.make_context(prompt, leftover_args, parent=ctx)
                with sub_ctx:
                    return cmd.invoke(sub_ctx)
        return super().invoke(ctx)


@click.group(cls=ClankerGroup, invoke_without_command=True)
@click.argument("prompt", required=False)
@click.option("--model", "-m", default=None, help="Model to use")
@click.option("--provider", "-p", type=click.Choice(["Anthropic", "OpenAI", "AzureOpenAI", "Ollama"]), default=None, help="LLM provider")
@click.option("--resume", "-r", default=None, help="Resume a previous session by ID")
@click.option("--history", is_flag=True, help="List conversation history and exit")
@click.option("--memories", is_flag=True, help="List stored memories and exit")
@click.option("--version", "-v", is_flag=True, help="Show version and exit")
@click.option("--check-update", is_flag=True, help="Check for updates and exit")
@click.option("--memory-index-check", is_flag=True, hidden=True)
@click.option("--yolo", is_flag=True, help="Skip bash command approval")
@click.option("--tui/--no-tui", default=True, help="Use TUI mode (default) or legacy console mode")
@click.pass_context
def main(
    ctx: click.Context,
    prompt: str | None,
    model: str | None,
    provider: str | None,
    resume: str | None,
    history: bool,
    memories: bool,
    version: bool,
    check_update: bool,
    memory_index_check: bool,
    yolo: bool,
    tui: bool,
) -> None:
    """Clanker - AI-Powered Coding Assistant."""
    if ctx.invoked_subcommand is not None:
        return

    if version:
        click.echo(f"Clanker v{__version__}")
        return

    if memory_index_check:
        from clanker.memory.index import fts5_available
        from clanker.memory.memories import MemoryStore

        if not fts5_available():
            click.echo("SQLite FTS5 unavailable in this build", err=True)
            ctx.exit(1)
        with tempfile.TemporaryDirectory() as directory:
            store = MemoryStore(directory, include_global=False)
            probe = store.add("SQLite FTS5 bundled memory index probe")
            if not any(memory.id == probe.id for memory in store.search("bundled index")):
                click.echo("Memory index probe failed", err=True)
                ctx.exit(1)
        click.echo("SQLite FTS5 available")
        return

    if check_update:
        from clanker.update import REPO, check_for_update
        click.echo(f"Current version: v{__version__}")
        click.echo("Checking for updates...")
        update_available, latest, _ = check_for_update()
        if update_available and latest:
            click.echo(f"Update available: {latest}")
            click.echo("\nTo update, run:")
            click.echo(f"  curl -fsSL https://raw.githubusercontent.com/{REPO}/main/scripts/install.sh | bash")
        elif latest:
            click.echo("You're on the latest version!")
        else:
            click.echo("Could not check for updates.")
        return

    set_yolo_mode(yolo)
    console = Console()

    if history:
        session_manager = SessionManager()
        sessions = session_manager.list_sessions()
        if not sessions:
            console.print_info("No conversation history found.")
        else:
            console.print_info(f"Conversation history ({len(sessions)} sessions):\n")
            for s in sessions:
                title = s["title"][:50] + "..." if len(s["title"]) > 50 else s["title"]
                created = s["created_at"][:10] if s["created_at"] else "unknown"
                console.print(f"  [bold cyan]{s['id']}[/bold cyan]  {title}")
                console.print(f"           {created}  ({s['message_count']} messages)")
        return

    if memories:
        store = get_memory_store()
        mems = store.list_all()
        if not mems:
            console.print_info("No memories stored for this workspace.")
        else:
            console.print_info(f"Memories ({len(mems)}):\n")
            for m in mems:
                content = m.content[:70] + "..." if len(m.content) > 70 else m.content
                tags = f" [{', '.join(m.tags)}]" if m.tags else ""
                console.print(f"  [bold cyan]{m.id}[/bold cyan]  {content}{tags}")
        return

    if not CONFIG_PATH.exists():
        try:
            settings = run_setup_wizard()
            reload_settings()
        except (KeyboardInterrupt, SystemExit):
            return
    else:
        settings = get_settings()

    if settings.logging.enabled:
        setup_logging(
            log_dir=settings.logging.log_dir,
            level=settings.logging.level,
            max_bytes=settings.logging.max_file_size_mb * 1024 * 1024,
            backup_count=settings.logging.backup_count,
            console_output=settings.logging.console_output,
            detailed_format=settings.logging.detailed_format,
        )
        logger.info("Clanker v%s starting", __version__)
        current_model = get_default_model()
        if current_model:
            logger.debug("Using model: %s (%s)", current_model.name, current_model.provider)

    initial_model: str | None = None
    if provider or model:
        from clanker.config.models import ModelConfig, add_model
        existing = get_model_by_name(model) if model and not provider else None
        if existing:
            initial_model = existing.name
        else:
            current = get_default_model()
            temp_model = ModelConfig(
                name="cli-override",
                provider=provider or (current.provider if current else "OpenAI"),
                model=model or (current.model if current else None),
                base_url=current.base_url if current else None,
                deployment_name=current.deployment_name if current else None,
                api_key=current.api_key if current else None,
            )
            add_model(temp_model)
            initial_model = "cli-override"

    if prompt:
        if initial_model:
            run_single_prompt(prompt, console, settings, initial_model=initial_model)
        else:
            run_single_prompt(prompt, console, settings)
    else:
        if tui:
            if initial_model:
                run_interactive(console, settings, resume_session=resume, initial_model=initial_model)
            else:
                run_interactive(console, settings, resume_session=resume)
        else:
            if initial_model:
                run_interactive_legacy(console, settings, resume_session=resume, initial_model=initial_model)
            else:
                run_interactive_legacy(console, settings, resume_session=resume)


def _choose_legacy(items, label, prompt_session, console, title):
    """Small paged picker for --no-tui sessions and import wizard steps."""
    if not items:
        console.print_info(f"{title}: no conversations found.")
        return None
    page = 0
    pages = (len(items) + 9) // 10
    while True:
        console.print_info(f"{title} ({len(items)} total, page {page + 1}/{pages})")
        for index, item in enumerate(items[page * 10:(page + 1) * 10], start=1):
            console.print(f"  {index}. {escape(str(label(item)))}")
        answer = prompt_session.prompt("Number, n next, p previous, q cancel: ").strip().lower()
        if answer == "q" or not answer:
            return None
        if answer == "n":
            page = min(page + 1, pages - 1)
        elif answer == "p":
            page = max(page - 1, 0)
        elif answer.isdigit() and 1 <= int(answer) <= len(items[page * 10:(page + 1) * 10]):
            return items[page * 10 + int(answer) - 1]


def run_interactive_legacy(
    console: Console,
    settings: Settings,
    resume_session: str | None = None,
    initial_model: str | None = None,
) -> None:
    """Legacy interactive REPL using prompt-toolkit (for --no-tui mode)."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.history import FileHistory

    logger.info("Starting legacy interactive mode")

    session_manager = SessionManager(model_name=initial_model)
    resumed_messages: list | None = None
    if resume_session:
        messages = session_manager.get_session_messages(resume_session)
        if messages:
            session_manager.resume_session(resume_session)
            if initial_model:
                session_manager.model_name = initial_model
            resumed_messages = messages
            console.print_info(f"Resuming session {resume_session} with {len(messages)} messages")
        else:
            console.print_warning(f"Session {resume_session} not found, starting new session")

    active_model_name = session_manager.model_name
    try:
        current_model = (get_model_by_name(active_model_name) if active_model_name else None) or get_default_model()
        create_model(settings, model_name=active_model_name)
    except ValueError as e:
        console.print_error(str(e))
        sys.exit(1)

    history_path = settings.memory.storage_path / "history"
    history_path.parent.mkdir(parents=True, exist_ok=True)

    class CommandCompleter(Completer):
        COMMANDS = ["/help", "/exit", "/quit", "/q", "/clear", "/model", "/copilot-login", "/antigravity-login", "/openai-login",
                    "/config", "/mcp", "/logs", "/history", "/restore", "/resume", "/import", "/compact",
                    "/memories", "/remember", "/forget", "/workflow", "/skill"]

        def get_completions(self, document, complete_event):
            text = document.text_before_cursor
            if not text.startswith("/"):
                return
            if text.startswith("/model "):
                model_prefix = text[7:]
                try:
                    for name in list_model_names():
                        if name.lower().startswith(model_prefix.lower()):
                            yield Completion(name, start_position=-len(model_prefix))
                except Exception:
                    pass
                return
            for cmd in self.COMMANDS:
                if cmd.startswith(text):
                    yield Completion(cmd, start_position=-len(text))

    prompt_session: PromptSession = PromptSession(
        history=FileHistory(str(history_path)),
        completer=CommandCompleter(),
        complete_while_typing=True,
    )

    from clanker.agent.prompts import load_user_instructions
    _has_user_instructions = bool(load_user_instructions())
    console.print_welcome(user_instructions_loaded=_has_user_instructions)
    console.print_info(f"Session ID: {session_manager.session_id}")

    active_model_name = session_manager.model_name
    current_model = (get_model_by_name(active_model_name) if active_model_name else None) or get_default_model()
    token_tracker = SessionTokenTracker(
        model_name=current_model.name if current_model else "unknown",
        context_window=current_model.max_input_tokens if current_model else None,
    )

    conversation_messages = list(resumed_messages) if resumed_messages else []
    pending_restore_messages = list(resumed_messages) if resumed_messages else []
    working_dir = os.getcwd()

    while True:
        try:
            user_input = prompt_session.prompt("❯ ").strip()
            if not user_input:
                continue

            if user_input.startswith("/"):
                result = handle_command(user_input, console, session_manager, conversation_messages)
                if user_input.lower() == "/clear":
                    pending_restore_messages = []
                    console.print_info(f"Session ID: {session_manager.session_id}")
                if result == "exit":
                    if conversation_messages:
                        session_manager.save_conversation_snapshot(conversation_messages)
                    cleanup_event_loop()
                    break
                elif result == "restore_picker":
                    sessions = session_manager.list_sessions()
                    sessions.sort(key=lambda s: s.get("updated_at") or s.get("created_at") or "", reverse=True)
                    selected = _choose_legacy(
                        sessions, lambda s: f"{s.get('title') or 'Untitled'}  ·  {s.get('updated_at', '')[:16]}  ·  {s.get('id')}",
                        prompt_session, console, "Choose a conversation",
                    )
                    result = f"restore:{selected['id']}" if selected else None
                elif result == "import_wizard":
                    from clanker.memory.importers import SOURCES, discover, load

                    source = _choose_legacy(
                        list(SOURCES), str, prompt_session, console, "Import: choose source"
                    )
                    if source:
                        candidates = discover(source, working_dir)
                        candidate = _choose_legacy(
                            candidates,
                            lambda c: f"{c.title}  ·  {c.updated_at[:16]}  ·  {c.session_id}",
                            prompt_session, console, f"Import: choose {source} conversation",
                        )
                        if candidate:
                            try:
                                imported = load(candidate)
                            except (OSError, ValueError, sqlite3.Error) as exc:
                                console.print_warning(f"Could not import session: {exc}")
                                continue
                            console.print_info(
                                f"{candidate.title} · {len(imported)} messages · {candidate.cwd or 'workspace unknown'}"
                            )
                            if prompt_session.prompt("Import this conversation? [y/N] ").strip().lower() == "y":
                                if conversation_messages:
                                    session_manager.save_conversation_snapshot(conversation_messages)
                                session_manager.new_session()
                                session_manager.set_title(f"{source}: {candidate.title}"[:100])
                                session_manager.save_conversation_snapshot(imported)
                                conversation_messages = list(imported)
                                pending_restore_messages = list(imported)
                                console.print_info(f"Imported as session {session_manager.session_id}")
                    continue
                if result and result.startswith("restore:"):
                    session_id = result.split(":", 1)[1]
                    messages = session_manager.get_session_messages(session_id)
                    if messages:
                        if conversation_messages:
                            session_manager.save_conversation_snapshot(conversation_messages)
                        session_manager.resume_session(session_id)
                        active_name = session_manager.model_name
                        cm = (get_model_by_name(active_name) if active_name else None) or get_default_model()
                        token_tracker.model_name = cm.name if cm else "unknown"
                        token_tracker.context_window = cm.max_input_tokens if cm else None
                        conversation_messages = list(messages)
                        pending_restore_messages = list(messages)
                        console.print_info(f"Restored session {session_id} with {len(messages)} messages")
                    continue
                elif result and result.startswith("workflow:") or result and result.startswith("skill:"):
                    user_input = result.split(":", 1)[1]
                else:
                    continue

            user_msg = HumanMessage(content=user_input)
            conversation_messages.append(user_msg)
            console.rule()

            if pending_restore_messages:
                turn_messages = [*pending_restore_messages, user_msg]
                pending_restore_messages = []
            else:
                turn_messages = [user_msg]
            state = {"messages": turn_messages, "working_directory": working_dir}

            try:
                result = stream_agent_response_sync(
                    settings, session_manager.checkpointer, state,
                    session_manager.get_config(), console,
                    model_name=session_manager.model_name,
                )

                if result.input_tokens > 0 or result.output_tokens > 0:
                    active_name = session_manager.model_name
                    cm = (get_model_by_name(active_name) if active_name else None) or get_default_model()
                    token_tracker.model_name = cm.name if cm else "unknown"
                    token_tracker.context_window = cm.max_input_tokens if cm else None
                    turn_cost = cm.compute_cost(
                        result.input_tokens, result.output_tokens,
                        result.cache_read_tokens, result.cache_creation_tokens,
                    ) if cm else None
                    token_tracker.add_turn(
                        result.input_tokens, result.output_tokens,
                        result.cache_read_tokens, result.cache_creation_tokens, turn_cost,
                    )

                if result.response:
                    conversation_messages.append(AIMessage(content=result.response))
                    session_manager.save_conversation_snapshot(conversation_messages)

                if result.summarization_occurred:
                    sync_conversation_after_auto_compaction(
                        conversation_messages, session_manager, settings, console
                    )

                if (result.input_tokens > 0 or result.output_tokens > 0) and settings.output.show_token_usage:
                    last_turn = token_tracker.turns[-1] if token_tracker.turns else None
                    console.print_token_usage(
                        result.input_tokens, result.output_tokens,
                        token_tracker.context_used_percent,
                        result.cache_read_tokens, result.cache_creation_tokens,
                        cost_usd=last_turn.cost_usd if last_turn else None,
                        session_cost_usd=token_tracker.total_cost_usd,
                    )
            except Exception as e:
                logger.exception("Agent error: %s", e)
                console.print_error(f"Agent error: {e}")

            console.rule()

        except KeyboardInterrupt:
            console.print()
            continue
        except EOFError:
            if conversation_messages:
                session_manager.save_conversation_snapshot(conversation_messages)
            console.print("\n[bold cyan]*BZZZT*[/bold cyan] Powering down. [bold cyan]*click*[/bold cyan]")
            break

    if conversation_messages:
        _print_resume_hint(console, session_manager.session_id)


@main.command()
@click.option("--port", "-p", default=8765, help="Port to run the config server on")
@click.option("--no-browser", is_flag=True, help="Don't open browser automatically")
def config(port: int, no_browser: bool) -> None:
    """Open web-based configuration interface."""
    from clanker.config.web import run_config_server
    run_config_server(port=port, open_browser=not no_browser)


@main.command("copilot-login")
def copilot_login() -> None:
    """Connect your GitHub Copilot subscription as a model provider."""
    from clanker.config.copilot_auth import (
        CopilotAuthError,
        complete_login,
        poll_for_github_token,
        start_device_flow,
        sync_copilot_models,
    )
    click.echo("Starting GitHub device login for Copilot...")
    try:
        session = start_device_flow()
    except CopilotAuthError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    click.echo(f"\nOpen {session.verification_uri} and enter code: {session.user_code}\n")
    click.echo("Waiting for approval...")
    github_token: str | None = None
    try:
        while github_token is None:
            time.sleep(session.interval)
            github_token = poll_for_github_token(session)
    except KeyboardInterrupt:
        click.echo("\nLogin cancelled.")
        sys.exit(1)
    except CopilotAuthError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    try:
        complete_login(github_token)
        synced = sync_copilot_models()
    except CopilotAuthError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    click.echo(f"Connected! Synced {synced} Copilot model(s).")
    click.echo("Use /model in a session to switch to one.")


def _run_openai_login(emit, *, no_browser: bool = False, manual: bool = False) -> int:
    import webbrowser

    from clanker.config.chatgpt_auth import poll_login, start_login, submit_callback

    session = start_login(manual=manual)
    try:
        emit(f"Open this ChatGPT login link:\n{session.url}")
        if not no_browser:
            with contextlib.suppress(webbrowser.Error):
                webbrowser.open(session.url)
        if manual:
            callback = click.prompt("Paste the full callback URL from your browser", hide_input=True)
            submit_callback(session, callback)
        emit("Waiting for ChatGPT authorization... (Ctrl+C to cancel)")
        while (synced := poll_login(session)) is None:
            time.sleep(0.25)
        return synced
    finally:
        session.close()


@main.command("openai-login")
@click.option("--no-browser", is_flag=True, help="Print the ChatGPT login link without opening a browser.")
@click.option("--manual", is_flag=True, help="Paste the callback URL for remote/headless login; no local callback listener.")
def openai_login(no_browser: bool, manual: bool) -> None:
    """Connect your ChatGPT account to use its available coding models."""
    from clanker.config.chatgpt_auth import ChatGPTAuthError

    try:
        synced = _run_openai_login(click.echo, no_browser=no_browser, manual=manual)
    except KeyboardInterrupt:
        raise click.ClickException("ChatGPT login cancelled.") from None
    except ChatGPTAuthError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Connected! Synced {synced} ChatGPT model(s). Use /model to switch to one.")


def _run_antigravity_login(emit, *, no_browser: bool = False, manual: bool = False) -> int:
    import webbrowser

    from clanker.config.antigravity_auth import (
        LOGIN_NOTICE,
        poll_login,
        start_login,
        submit_callback,
    )

    emit(LOGIN_NOTICE)
    session = start_login()
    try:
        emit(f"Open this Google login link:\n{session.url}")
        if not no_browser:
            try:
                webbrowser.open(session.url)
            except webbrowser.Error:
                emit("Could not open a browser automatically. Open the link above.")
        if manual:
            callback = click.prompt("Paste the full callback URL from your browser", hide_input=True)
            submit_callback(session, callback)
        emit("Waiting for Google authorization... (Ctrl+C to cancel)")
        while (synced := poll_login(session)) is None:
            time.sleep(0.25)
        return synced
    finally:
        session.close()


@main.command("antigravity-login")
@click.option("--no-browser", is_flag=True, help="Print the Google login link without opening a browser.")
@click.option("--manual", is_flag=True, help="Paste the callback URL for a remote/headless login.")
def antigravity_login(no_browser: bool, manual: bool) -> None:
    """Connect your Google account to the unofficial Antigravity model provider."""
    from clanker.config.antigravity_auth import AntigravityAuthError

    try:
        synced = _run_antigravity_login(click.echo, no_browser=no_browser, manual=manual)
    except KeyboardInterrupt:
        raise click.ClickException("Google login cancelled.") from None
    except AntigravityAuthError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Connected! Synced {synced} Antigravity model(s). Use /model to switch to one.")


if __name__ == "__main__":
    main()
