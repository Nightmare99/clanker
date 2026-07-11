"""Command-line interface for Clanker."""

import os
import sys
import time
import warnings

# Suppress pydantic v1 compatibility warning on Python 3.14+
warnings.filterwarnings("ignore", message="Core Pydantic V1 functionality")

import click
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.completion import Completer, Completion

from clanker import __version__
from clanker.agent import create_model
from clanker.config import (
    CONFIG_PATH,
    Settings,
    get_settings,
    reload_settings,
    list_model_names,
    get_model_by_name,
    get_default_model,
    set_default_model,
)
from clanker.config.setup_wizard import run_setup_wizard
from clanker.logging import get_log_path, get_logger, setup_logging
from clanker.memory.checkpointer import SessionManager
from clanker.memory.memories import get_memory_store
from clanker.ui.console import Console
from clanker.ui.streaming import StreamResult, stream_agent_response_sync, cleanup_event_loop
from clanker.ui.token_tracking import SessionTokenTracker
from clanker.ui.mid_turn_input import REPLApplication
from clanker.runtime import (
    set_yolo_mode,
)

# Load environment variables
load_dotenv()


def _configure_certificates() -> None:
    """Point TLS verification at certifi's CA bundle.

    In a PyInstaller-frozen binary the bundled Python has no system CA store,
    so HTTPS fails with ``CERTIFICATE_VERIFY_FAILED: unable to get local issuer
    certificate``. Setting these env vars to certifi's bundle fixes every HTTPS
    client at once (urllib for web_read, trafilatura's fallback fetcher, ddgs
    web search, and the GitHub update check). We only set vars that are unset so
    a user's explicit override is respected.
    """
    try:
        import certifi

        ca_bundle = certifi.where()
    except Exception:
        return

    for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        os.environ.setdefault(var, ca_bundle)


_configure_certificates()


def _preload_tool_dependencies() -> None:
    """Eagerly import third-party packages that tools otherwise import lazily.

    In a PyInstaller-frozen binary, module code is decompressed on demand from
    a zlib-compressed archive the first time it's imported. Forking a
    subprocess (execute_shell, bash_background -- i.e. any bash tool call)
    can corrupt that archive reader's file-descriptor state for the *parent*
    process, so importing a module for the first time AFTER a fork sometimes
    fails with ``zlib.error: incorrect header check`` / ``Error -3 while
    decompressing data``. Which package trips it depends purely on which tool
    the agent happens to call first after a bash command -- hence it looking
    "random." We hit this once already for pygments (see the eager-import
    block in ui/console.py); web_search (ddgs), web_read (trafilatura), and
    PDF reading (fitz/PyMuPDF, pypdf) are lazily imported inside their tool
    functions and are equally exposed, so we import them here -- before
    main() runs, before any subprocess can exist -- guaranteeing they're
    already in sys.modules by the time a tool call needs them.

    ``ddgs`` needs special handling: ``import ddgs`` alone only loads a thin
    lazy-loading proxy (``ddgs/__init__.py``'s ``_DDGSProxy``) -- the real
    implementation (~20 submodules, including the compiled ``primp`` HTTP
    client extension) is deferred until ``DDGS()`` is actually instantiated.
    A bare ``__import__("ddgs")`` therefore does NOT protect web_search; we
    have to construct ``DDGS()`` (side-effect-free, no network call) to force
    the proxy to resolve its real class and pull in everything web_search
    will need.

    Each import is independently guarded: a missing or broken package should
    degrade that one tool gracefully (its own lazy import + informative error
    message still runs), not break every other command at startup.
    """
    for module_name in ("trafilatura", "fitz", "pypdf"):
        try:
            __import__(module_name)
        except Exception:  # noqa: BLE001
            pass

    try:
        from ddgs import DDGS

        DDGS()  # forces the lazy proxy to load its real implementation now
    except Exception:  # noqa: BLE001
        pass


_preload_tool_dependencies()

# Module logger (initialized after setup_logging is called)
logger = get_logger("cli")


def handle_command(
    command: str,
    console: Console,
    session_manager: SessionManager,
    conversation_messages: list | None = None,
) -> str | None:
    """Handle built-in commands.

    Args:
        command: The command string (starting with /).
        console: Console instance.
        session_manager: Session manager instance.

    Returns:
        "exit" to exit, "restore:ID" to restore a session, None to continue.
    """
    cmd = command.strip().lower()
    parts = command.strip().split(maxsplit=1)
    logger.debug("Handling command: %s", cmd)

    if cmd in ("/exit", "/quit", "/q"):
        logger.info("User requested exit")
        console.print("[bold cyan]*BZZZT*[/bold cyan] Shutdown sequence initiated. Until next time, human. [bold cyan]*WHIRR... click*[/bold cyan]")
        return "exit"

    elif cmd == "/help":
        console.print_help()

    elif cmd == "/clear":
        console.clear()
        session_manager.new_session()
        logger.info("Conversation cleared, new session started")
        console.print("[bold cyan]*WHIRR*[/bold cyan] Memory banks wiped. Fresh slate initialized. [bold cyan]*CLANK*[/bold cyan]")

    elif cmd.startswith("/model"):
        parts = command.strip().split(maxsplit=1)

        # BYOK mode: show configured models
        model_names = list_model_names()

        if len(parts) == 1:
            # Show current model and list available models
            current = get_default_model()
            if current:
                console.print_info(f"Current model: {current.name} ({current.provider})")
            else:
                console.print_warning("No model configured.")

            if model_names:
                console.print_info("\nConfigured models:")
                for name in model_names:
                    model = get_model_by_name(name)
                    if model:
                        marker = " *" if current and current.name == name else ""
                        console.print(f"  [cyan]{name}[/cyan] ({model.provider}){marker}")
                console.print_info("\nUse /model <name> to switch models.")
            else:
                console.print_info("\nNo models configured in ~/.clanker/models.json")
                console.print_info("Add models via 'clanker config'.")
        else:
            # Switch to specified model
            target_name = parts[1].strip()
            model = get_model_by_name(target_name)
            if model:
                set_default_model(target_name)
                console.print_success(f"Switched to model: {model.name} ({model.provider})")
                console.print_info("Note: Changes take effect on next message.")
            else:
                console.print_warning(f"Model '{target_name}' not found.")
                if model_names:
                    console.print_info(f"Available: {', '.join(model_names)}")

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
            return None

        console.print_info(f"Open {session.verification_uri} and enter code: {session.user_code}")
        console.print_info("Waiting for approval... (Ctrl+C to cancel)")

        github_token: str | None = None
        try:
            while github_token is None:
                time.sleep(session.interval)
                github_token = poll_for_github_token(session)
        except KeyboardInterrupt:
            console.print_warning("Login cancelled.")
            return None
        except CopilotAuthError as e:
            console.print_error(str(e))
            return None

        try:
            complete_login(github_token)
            synced = sync_copilot_models()
        except CopilotAuthError as e:
            console.print_error(str(e))
            return None

        console.print_success(f"Connected! Synced {synced} Copilot model(s).")
        console.print_info("Use /model to switch to one.")

    elif cmd == "/config":
        settings = get_settings()
        console.print_info(f"Config file: {CONFIG_PATH}")
        console.print_info(f"Agent name: {settings.agent.name}")

        # Show model info from JSON config
        current_model = get_default_model()
        if current_model:
            console.print_info(f"Model: {current_model.name}")
            console.print_info(f"Provider: {current_model.provider}")
            if current_model.model:
                console.print_info(f"Model ID: {current_model.model}")
        else:
            console.print_warning("No model configured. Run 'clanker' to set up.")

        if settings.mcp.enabled and settings.mcp.servers:
            enabled = [n for n, s in settings.mcp.servers.items() if s.enabled]
            console.print_info(f"MCP servers: {len(enabled)} enabled")

    elif cmd == "/mcp":
        settings = get_settings()
        if not settings.mcp.enabled:
            console.print_info("MCP is disabled")
        elif not settings.mcp.servers:
            console.print_info("No MCP servers configured")
        else:
            console.print_info("MCP Servers:")
            for name, server in settings.mcp.servers.items():
                status = "enabled" if server.enabled else "disabled"
                if server.transport == "stdio":
                    detail = f"{server.command} {' '.join(server.args)}"
                else:
                    detail = server.url or ""
                console.print_info(f"  {name}: [{server.transport}] {status}")
                if detail:
                    console.print(f"    {detail[:60]}{'...' if len(detail) > 60 else ''}")

    elif cmd == "/logs":
        from clanker.logging import get_log_path
        settings = get_settings()
        if not settings.logging.enabled:
            console.print_info("Logging is disabled")
        else:
            log_path = get_log_path()
            if log_path and log_path.exists():
                console.print_info(f"Log file: {log_path}")
                console.print_info(f"Log level: {settings.logging.level}")
                console.print_info(f"Max file size: {settings.logging.max_file_size_mb} MB")
                console.print_info(f"Backup count: {settings.logging.backup_count}")
                # Show log directory contents
                log_dir = log_path.parent
                log_files = sorted(log_dir.glob("clanker.log*"))
                if log_files:
                    console.print_info(f"\nLog files in {log_dir}:")
                    for f in log_files:
                        size_kb = f.stat().st_size / 1024
                        console.print(f"  {f.name} ({size_kb:.1f} KB)")
            else:
                console.print_info(f"Log directory: {settings.logging.log_dir}")
                console.print_info("No log file created yet")

    elif cmd == "/history":
        # List JSON snapshot sessions
        sessions = session_manager.list_sessions()
        if not sessions:
            console.print_info("No conversation history found in this workspace.")
            console.print_info("Conversations are saved to .clanker/conversations/")
        else:
            console.print_info(f"Conversation history ({len(sessions)} sessions):\n")
            for s in sessions[:20]:  # Show last 20
                title = s["title"][:40] + "..." if len(s["title"]) > 40 else s["title"]
                created = s["created_at"][:10] if s["created_at"] else "unknown"
                console.print(f"  [bold cyan]{s['id']}[/bold cyan]  {title}")
                console.print(f"           {created}  ({s['message_count']} messages)")
            console.print_info("\nUse /restore <id> to resume a conversation.")

    elif cmd.startswith("/restore"):
        parts = command.strip().split(maxsplit=1)
        if len(parts) < 2:
            console.print_warning("Usage: /restore <session-id>")
            console.print_info("Use /history to see available sessions.")
        else:
            session_id = parts[1].strip()
            return f"restore:{session_id}"

    elif cmd == "/compact":
        if conversation_messages is None:
            console.print_warning("No active conversation messages context to compact.")
            return None
        if not conversation_messages:
            console.print_info("No conversation history to compact.")
            return None

        from clanker.config import get_settings
        from clanker.agent.graph import create_model
        from clanker.agent.summarization import RobustSummarizationMiddleware

        settings = get_settings()
        try:
            model = create_model()
        except ValueError as e:
            console.print_error(f"Cannot compact: {e}")
            return None

        keep_count = settings.context.keep_recent_turns * 2
        trigger_fraction = settings.context.summarization_threshold / 100.0
        summarization = RobustSummarizationMiddleware(
            model=model,
            trigger=("fraction", trigger_fraction),
            keep=("messages", keep_count),
        )

        summarization._ensure_message_ids(conversation_messages)

        cutoff_index = summarization._determine_cutoff_index(conversation_messages)
        if cutoff_index <= 0:
            cutoff_index = max(1, len(conversation_messages) - 1)

        console.print_info("Compacting conversation history...")
        messages_to_summarize, preserved_messages = summarization._partition_messages(
            conversation_messages, cutoff_index
        )

        try:
            summary = summarization._create_summary(messages_to_summarize)
            new_messages = summarization._build_new_messages(summary)
            compacted_messages = [*new_messages, *preserved_messages]

            from clanker.agent.graph import create_agent_graph
            from langchain_core.messages import RemoveMessage
            from langgraph.graph.message import REMOVE_ALL_MESSAGES

            graph = create_agent_graph(settings, checkpointer=session_manager.checkpointer)
            config = session_manager.get_config()
            graph.update_state(config, {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *compacted_messages]})

            conversation_messages.clear()
            conversation_messages.extend(compacted_messages)

            session_manager.save_conversation_snapshot(compacted_messages)

            console.print_success(
                f"Successfully compacted conversation! Condensed {len(messages_to_summarize)} messages "
                f"into a summary. History now contains {len(compacted_messages)} message(s)."
            )
        except Exception as e:
            logger.exception("Failed to compact conversation: %s", e)
            console.print_error(f"Failed to compact conversation: {e}")

    elif cmd == "/memories":
        store = get_memory_store()
        memories = store.list_all()
        if not memories:
            console.print_info("No memories stored for this workspace.")
            console.print_info("Ask me to remember something, or use the remember tool.")
        else:
            console.print_info(f"Workspace memories ({len(memories)}):\n")
            for m in memories[:20]:  # Show last 20
                content = m.content[:60] + "..." if len(m.content) > 60 else m.content
                tags = f" [{', '.join(m.tags)}]" if m.tags else ""
                console.print(f"  [bold cyan]{m.id}[/bold cyan]  {content}{tags}")
            console.print_info("\nMemories are automatically used in conversations.")

    elif cmd.startswith("/remember"):
        parts = command.strip().split(maxsplit=1)
        if len(parts) < 2:
            console.print_warning("Usage: /remember <something to remember>")
        else:
            content = parts[1].strip()
            store = get_memory_store()
            memory = store.add(content, source="user")
            console.print_info(f"Remembered (ID: {memory.id}): {content[:50]}{'...' if len(content) > 50 else ''}")

    elif cmd.startswith("/forget"):
        parts = command.strip().split(maxsplit=1)
        if len(parts) < 2:
            console.print_warning("Usage: /forget <memory-id>")
            console.print_info("Use /memories to see memory IDs.")
        else:
            memory_id = parts[1].strip()
            store = get_memory_store()
            if store.delete(memory_id):
                console.print_info(f"Memory {memory_id} deleted.")
            else:
                console.print_warning(f"Memory {memory_id} not found.")

    elif cmd.startswith("/workflow"):
        from clanker.workflows import list_workflows, load_workflow, MAX_WORKFLOW_CHARS, WORKFLOW_PREAMBLE
        parts = command.strip().split(maxsplit=1)
        if len(parts) < 2:
            # List available workflows
            workflows = list_workflows()
            if not workflows:
                console.print_info("No workflows found.")
                console.print_info("Create .md files in .clanker/workflows/ to add workflows.")
            else:
                console.print_info(f"Available workflows ({len(workflows)}):\n")
                for name in workflows:
                    console.print(f"  [bold cyan]{name}[/bold cyan]")
                console.print_info("\nUse /workflow <name> to execute a workflow.")
        else:
            workflow_name = parts[1].strip()
            content = load_workflow(workflow_name)
            if content:
                if len(content) > MAX_WORKFLOW_CHARS:
                    console.print_error(f"Workflow '{workflow_name}' is too large ({len(content)} chars). Workflows must be less than {MAX_WORKFLOW_CHARS} characters.")
                else:
                    return f"workflow:{WORKFLOW_PREAMBLE}{content}"
            else:
                console.print_warning(f"Workflow '{workflow_name}' not found.")
                workflows = list_workflows()
                if workflows:
                    console.print_info(f"Available: {', '.join(workflows)}")

    elif cmd.startswith("/skill"):
        from clanker.skills import list_skills, load_skill, MAX_SKILL_BODY_CHARS, SKILL_PREAMBLE
        parts = command.strip().split(maxsplit=1)
        skills = list_skills()
        if len(parts) < 2:
            # List available skills, grouped by source.
            if not skills:
                console.print_info("No skills found.")
                console.print_info(
                    "Create .clanker/skills/<name>/SKILL.md (project) or "
                    "~/.clanker/skills/<name>/SKILL.md (personal) to add skills."
                )
            else:
                console.print_info(f"Available skills ({len(skills)}):\n")
                for skill in skills.values():
                    desc = skill.description
                    if len(desc) > 80:
                        desc = desc[:80].rstrip() + "..."
                    console.print(f"  [bold cyan]{skill.name}[/bold cyan] [dim]({skill.source})[/dim] - {desc}")
                console.print_info("\nThe agent loads skills automatically. Use /skill <name> to load one manually.")
        else:
            skill_name = parts[1].strip()
            skill = load_skill(skill_name)
            if skill:
                body = skill.body
                if len(body) > MAX_SKILL_BODY_CHARS:
                    body = body[:MAX_SKILL_BODY_CHARS].rstrip() + "\n\n... [skill instructions truncated]"
                console.print_info(f"Loaded skill '{skill.name}' from {skill.directory}")
                return f"skill:{SKILL_PREAMBLE}{body}\n\nThis skill's files are in: {skill.directory}"
            else:
                console.print_warning(f"Skill '{skill_name}' not found.")
                if skills:
                    console.print_info(f"Available: {', '.join(skills.keys())}")

    else:
        console.print_warning(f"Unknown command: {command}")
        console.print_info("Type /help for available commands.")

    return None


class CommandCompleter(Completer):
    """Autocomplete for slash commands and model names."""

    COMMANDS = [
        "/help",
        "/exit",
        "/quit",
        "/q",
        "/clear",
        "/model",
        "/copilot-login",
        "/config",
        "/mcp",
        "/logs",
        "/history",
        "/restore",
        "/compact",
        "/memories",
        "/remember",
        "/forget",
        "/workflow",
        "/skill",
    ]

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return

        # Check if this is a /model command with a space (user wants model name completion)
        if text.startswith("/model "):
            model_prefix = text[7:]  # Remove "/model "
            try:
                model_names = list_model_names()
                for name in model_names:
                    if name.lower().startswith(model_prefix.lower()):
                        yield Completion(name, start_position=-len(model_prefix))
            except Exception:
                pass  # Silently fail if model loading fails
            return

        # Check if this is a /workflow command with a space (user wants workflow name completion)
        if text.startswith("/workflow "):
            workflow_prefix = text[10:]  # Remove "/workflow "
            try:
                from clanker.workflows import list_workflows
                workflows = list_workflows()
                for name in workflows:
                    if name.lower().startswith(workflow_prefix.lower()):
                        yield Completion(name, start_position=-len(workflow_prefix))
            except Exception:
                pass
            return

        # Check if this is a /skill command with a space (user wants skill name completion)
        if text.startswith("/skill "):
            skill_prefix = text[7:]  # Remove "/skill "
            try:
                from clanker.skills import list_skills
                for name in list_skills():
                    if name.lower().startswith(skill_prefix.lower()):
                        yield Completion(name, start_position=-len(skill_prefix))
            except Exception:
                pass
            return

        # Regular command completion
        for cmd in self.COMMANDS:
            if cmd.startswith(text):
                yield Completion(cmd, start_position=-len(text))


def run_interactive(console: Console, settings: Settings, resume_session: str | None = None) -> None:
    """Run the interactive REPL loop in fullscreen dashboard mode.

    Args:
        console: Console instance for output.
        settings: Application settings.
        resume_session: Optional session ID to resume.
    """
    logger.info("Starting interactive mode")

    # Setup session
    session_manager = SessionManager()

    # Resume session if specified
    resumed_messages: list | None = None
    if resume_session:
        messages = session_manager.get_session_messages(resume_session)
        if messages:
            session_manager.resume_session(resume_session)
            resumed_messages = messages
        else:
            console.print_warning(f"Session {resume_session} not found, starting new session")

    logger.debug("Session manager initialized: session_id=%s", session_manager.session_id)

    # Validate model configuration
    try:
        current_model = get_default_model()
        if current_model:
            logger.info("Validating model config: %s (provider=%s)",
                       current_model.name, current_model.provider)
        else:
            logger.warning("No model configured")
        # Validate model config by creating it
        create_model(settings)
        logger.info("Model configuration validated successfully")
    except ValueError as e:
        logger.error("Failed to validate model config: %s", e)
        console.print_error(str(e))
        console.print_info("Run 'clanker' to run the setup wizard.")
        sys.exit(1)

    working_dir = os.getcwd()

    # Track messages for saving
    conversation_messages = []

    # History that must be injected into the next turn's graph state so the
    # checkpointer (in-RAM, keyed by thread_id) actually holds it. Set on
    # --resume / /restore; consumed once when building the next state. Without
    # this, a restored session changes the thread_id but the graph has no prior
    # messages, so the agent starts with no memory of the conversation.
    pending_restore_messages: list = []
    if resumed_messages:
        conversation_messages = list(resumed_messages)
        pending_restore_messages = list(resumed_messages)

    # Token tracking
    current_model = get_default_model()
    tracker_model_name = current_model.name if current_model else "unknown"
    token_tracker = SessionTokenTracker(
        model_name=tracker_model_name,
        context_window=current_model.max_input_tokens if current_model else None,
    )

    # Initialize REPLApplication (which is the fullscreen dashboard UI)
    app = REPLApplication(
        console=console,
        settings=settings,
        session_manager=session_manager,
        token_tracker=token_tracker,
        conversation_messages=conversation_messages,
        pending_restore_messages=pending_restore_messages,
        working_dir=working_dir,
    )

    import asyncio
    # Start the fullscreen event loop
    asyncio.run(app.run_async())

    # Save final conversation snapshot on exit
    if conversation_messages:
        session_manager.save_conversation_snapshot(conversation_messages)

    cleanup_event_loop()



def run_single_prompt(prompt: str, console: Console, settings: Settings) -> None:
    """Run a single prompt and exit.

    Args:
        prompt: The user's prompt.
        console: Console instance for output.
        settings: Application settings.
    """
    session_manager = SessionManager()

    # Validate model configuration
    try:
        create_model(settings)
    except ValueError as e:
        console.print_error(str(e))
        sys.exit(1)

    # Token tracking. The context window comes solely from the user's model
    # config (max_input_tokens); None means it's unset and the usage line will
    # omit the context percentage.
    current_model = get_default_model()
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
        )

        # Display token usage
        if result.input_tokens > 0 or result.output_tokens > 0:
            # Compute cost for this turn (None when pricing not configured)
            current_model_cfg = get_default_model()
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
        """Invoke, handling the case where prompt matches a subcommand.

        `prompt` is a group-level positional argument, so it greedily
        consumes the first token (e.g. "config") before Click's own
        subcommand-name resolution ever runs. When that token happens to
        match a real subcommand, any remaining tokens (`ctx.args` -- e.g.
        `--help`, `--port 9000`) still need to go through THAT subcommand's
        own argument parsing. Building a fresh sub-context via
        `cmd.make_context` (rather than calling `ctx.invoke(cmd)` directly,
        which skips parsing entirely) ensures flags like `--help` are
        handled instead of being silently dropped -- previously `clanker
        config --help` (or any `clanker <subcommand> --help`) would ignore
        `--help` and run the subcommand for real instead of printing usage.
        """
        prompt = ctx.params.get("prompt")
        if prompt and prompt in self.commands:
            # Clear the prompt and invoke the subcommand
            ctx.params["prompt"] = None
            ctx.invoked_subcommand = prompt
            cmd = self.commands[prompt]
            # Leftover, not-yet-parsed tokens (e.g. "--help", "--port 9000")
            # live in ctx._protected_args (Click's internal name; exposed as
            # the deprecated `protected_args` property) alongside ctx.args --
            # mirrors click.Group.invoke's own "args = [*ctx._protected_args,
            # *ctx.args]" so the subcommand's flags are actually parsed.
            leftover_args = [*getattr(ctx, "_protected_args", []), *ctx.args]
            with ctx:
                sub_ctx = cmd.make_context(prompt, leftover_args, parent=ctx)
                with sub_ctx:
                    return cmd.invoke(sub_ctx)
        return super().invoke(ctx)


@click.group(cls=ClankerGroup, invoke_without_command=True)
@click.argument("prompt", required=False)
@click.option(
    "--model",
    "-m",
    default=None,
    help="Model to use (e.g., claude-sonnet-4-20250514, gpt-4o)",
)
@click.option(
    "--provider",
    "-p",
    type=click.Choice(["Anthropic", "OpenAI", "AzureOpenAI", "Ollama"]),
    default=None,
    help="LLM provider",
)
@click.option(
    "--resume",
    "-r",
    default=None,
    help="Resume a previous session by ID",
)
@click.option(
    "--history",
    is_flag=True,
    help="List conversation history and exit",
)
@click.option(
    "--memories",
    is_flag=True,
    help="List stored memories and exit",
)
@click.option(
    "--version",
    "-v",
    is_flag=True,
    help="Show version and exit",
)
@click.option(
    "--check-update",
    is_flag=True,
    help="Check for updates and exit",
)
@click.option(
    "--yolo",
    is_flag=True,
    help="Skip bash command approval (auto-execute all commands)",
)
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
    yolo: bool,
) -> None:
    """Clanker - AI-Powered Coding Assistant.

    Start an interactive session or run a single prompt.

    Examples:

        clanker                     Start interactive mode

        clanker "explain this code" Run single prompt

        clanker -m gpt-4o           Use a specific model

        clanker config              Open web-based configuration

        clanker --history           List past conversations

        clanker -r abc123           Resume conversation abc123
    """
    # If a subcommand is invoked, don't run the default behavior
    if ctx.invoked_subcommand is not None:
        return

    if version:
        click.echo(f"Clanker v{__version__}")
        return

    if check_update:
        from clanker.update import check_for_update, REPO
        click.echo(f"Current version: v{__version__}")
        click.echo("Checking for updates...")
        update_available, latest, _ = check_for_update()
        if update_available and latest:
            click.echo(f"Update available: {latest}")
            click.echo(f"\nTo update, run:")
            click.echo(f"  curl -fsSL https://raw.githubusercontent.com/{REPO}/main/scripts/install.sh | bash")
        elif latest:
            click.echo("You're on the latest version!")
        else:
            click.echo("Could not check for updates. Check your internet connection.")
        return

    # Set yolo mode (skip bash command approval)
    set_yolo_mode(yolo)

    console = Console()

    # Handle --history flag
    if history:
        session_manager = SessionManager()
        sessions = session_manager.list_sessions()
        if not sessions:
            console.print_info("No conversation history found in this workspace.")
            console.print_info("Conversations are saved to .clanker/conversations/")
        else:
            console.print_info(f"Conversation history ({len(sessions)} sessions):\n")
            for s in sessions:
                title = s["title"][:50] + "..." if len(s["title"]) > 50 else s["title"]
                created = s["created_at"][:10] if s["created_at"] else "unknown"
                console.print(f"  [bold cyan]{s['id']}[/bold cyan]  {title}")
                console.print(f"           {created}  ({s['message_count']} messages)")
            console.print_info("\nUse 'clanker -r <id>' to resume a conversation.")
        return

    # Handle --memories flag
    if memories:
        store = get_memory_store()
        mems = store.list_all()
        if not mems:
            console.print_info("No memories stored for this workspace.")
        else:
            console.print_info(f"Workspace memories ({len(mems)}):\n")
            for m in mems:
                content = m.content[:70] + "..." if len(m.content) > 70 else m.content
                tags = f" [{', '.join(m.tags)}]" if m.tags else ""
                console.print(f"  [bold cyan]{m.id}[/bold cyan]  {content}{tags}")
        return

    # Check if config exists - run setup wizard on first launch
    if not CONFIG_PATH.exists():
        try:
            settings = run_setup_wizard()
            reload_settings()  # Reload from saved file
        except (KeyboardInterrupt, SystemExit):
            return
    else:
        settings = get_settings()

    # Initialize logging based on settings
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
        logger.info("Config loaded from: %s", CONFIG_PATH)
        current_model = get_default_model()
        if current_model:
            logger.debug("Using model: %s (%s)", current_model.name, current_model.provider)
        else:
            logger.debug("No model configured")

    # Override model from CLI args by creating a temporary config
    if provider or model:
        from clanker.config.models import ModelConfig, add_model
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
        set_default_model("cli-override")

    if prompt:
        run_single_prompt(prompt, console, settings)
    else:
        run_interactive(console, settings, resume_session=resume)


@main.command()
@click.option(
    "--port",
    "-p",
    default=8765,
    help="Port to run the config server on",
)
@click.option(
    "--no-browser",
    is_flag=True,
    help="Don't open browser automatically",
)
def config(port: int, no_browser: bool) -> None:
    """Open web-based configuration interface.

    Starts a local web server and opens your browser to configure Clanker
    settings through a user-friendly interface.

    Examples:

        clanker config              Open config in browser

        clanker config --port 9000  Use custom port

        clanker config --no-browser Start server without opening browser
    """
    from clanker.config.web import run_config_server

    run_config_server(port=port, open_browser=not no_browser)


@main.command("copilot-login")
def copilot_login() -> None:
    """Connect your GitHub Copilot subscription as a model provider.

    Runs a GitHub device-code login (open a URL, enter a code) and, on
    success, auto-configures one model per Copilot model (named
    `copilot:<model>`) with its real context-window size. Use /model to
    switch to one afterward -- no API key needed, just your existing
    Copilot subscription.

    Examples:

        clanker copilot-login
    """
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
    click.echo("Use /model in a session to switch to one, or 'clanker -m copilot:<model>'.")


if __name__ == "__main__":
    main()
