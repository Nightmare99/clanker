"""Command-line interface for Clanker."""

import os
import sys
import warnings

# Suppress pydantic v1 compatibility warning on Python 3.14+
warnings.filterwarnings("ignore", message="Core Pydantic V1 functionality")

import click
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.completion import Completer, Completion

from clanker import __version__
from clanker.agent import create_model
from clanker.config import CONFIG_PATH, Settings, get_settings, reload_settings
from clanker.config.setup_wizard import run_setup_wizard
from clanker.logging import get_logger, setup_logging
from clanker.context.compaction import compact_context_sync, should_compact
from clanker.memory.checkpointer import SessionManager
from clanker.memory.memories import get_memory_store
from clanker.ui.console import Console
from clanker.ui.streaming import StreamResult, stream_agent_response_sync
from clanker.ui.token_tracking import SessionTokenTracker

# Load environment variables
load_dotenv()

# Module logger (initialized after setup_logging is called)
logger = get_logger("cli")


def handle_command(command: str, console: Console, session_manager: SessionManager) -> str | None:
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
        if len(parts) == 1:
            # Reload settings from config to show current state
            current_settings = reload_settings()
            provider = current_settings.model.provider
            if provider == "github_copilot":
                model_name = current_settings.model.github_copilot.model or "default"
            elif provider == "azure":
                model_name = current_settings.model.azure.deployment_name or "default"
            elif provider == "azure_anthropic":
                model_name = current_settings.model.azure_anthropic.deployment_name or "default"
            else:
                model_name = current_settings.model.name
            console.print_info(f"Current model: {provider}/{model_name}")
            console.print()
            console.print_info("Usage: /model <provider>/<model>")
            console.print_info("Tab to see available models")
        else:
            model_spec = parts[1].strip()
            return f"model:{model_spec}"

    elif cmd == "/config":
        current_settings = reload_settings()
        provider = current_settings.model.provider
        if provider == "github_copilot":
            model_name = current_settings.model.github_copilot.model or "default"
        elif provider == "azure":
            model_name = current_settings.model.azure.deployment_name or "default"
        elif provider == "azure_anthropic":
            model_name = current_settings.model.azure_anthropic.deployment_name or "default"
        else:
            model_name = current_settings.model.name
        console.print_info(f"Config file: {CONFIG_PATH}")
        console.print_info(f"Agent name: {current_settings.agent.name}")
        console.print_info(f"Provider: {provider}")
        console.print_info(f"Model: {model_name}")
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
            from clanker.memory.memories import MemorySource
            memory = store.add(content, source=MemorySource.USER)
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

    else:
        console.print_warning(f"Unknown command: {command}")
        console.print_info("Type /help for available commands.")

    return None


class CommandCompleter(Completer):
    """Autocomplete for slash commands and model options."""

    COMMANDS = [
        "/help",
        "/exit",
        "/quit",
        "/q",
        "/clear",
        "/model",
        "/config",
        "/mcp",
        "/logs",
        "/history",
        "/restore",
        "/memories",
        "/remember",
        "/forget",
    ]

    def __init__(self):
        """Initialize completer with cached model list."""
        self._model_cache: list[str] | None = None

    def _get_available_models(self) -> list[str]:
        """Get available models from all configured providers."""
        if self._model_cache is not None:
            return self._model_cache

        models = []

        # GitHub Copilot models (fetched from API)
        try:
            from clanker.auth.github_copilot import get_available_copilot_models
            copilot_models = get_available_copilot_models()
            for m in copilot_models:
                models.append(f"github_copilot/{m}")
        except Exception:
            pass

        # Azure deployments from config
        try:
            settings = get_settings()
            if settings.model.azure.deployment_name:
                models.append(f"azure/{settings.model.azure.deployment_name}")
            if settings.model.azure_anthropic.deployment_name:
                models.append(f"azure_anthropic/{settings.model.azure_anthropic.deployment_name}")
        except Exception:
            pass

        # Ollama models (fetch from local API)
        try:
            import requests
            resp = requests.get("http://localhost:11434/api/tags", timeout=2)
            if resp.ok:
                for m in resp.json().get("models", []):
                    name = m.get("name", "").split(":")[0]
                    if name:
                        models.append(f"ollama/{name}")
        except Exception:
            pass

        # Always show provider names so users can type full model name
        providers = ["anthropic", "openai", "azure", "github_copilot", "ollama"]
        for p in providers:
            if not any(m.startswith(f"{p}/") or m == p for m in models):
                models.append(p)

        self._model_cache = models
        return models

    def refresh_models(self):
        """Clear model cache to force refresh."""
        self._model_cache = None

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return

        # Check if we're completing a /model argument
        if text.startswith("/model "):
            model_text = text[7:]  # Text after "/model "
            for model in self._get_available_models():
                if model.lower().startswith(model_text.lower()):
                    # Show provider as metadata
                    provider = model.split("/")[0] if "/" in model else model
                    yield Completion(
                        model,
                        start_position=-len(model_text),
                        display_meta=provider
                    )
            return

        # Complete command names
        for cmd in self.COMMANDS:
            if cmd.startswith(text):
                yield Completion(cmd, start_position=-len(text))


def run_interactive(console: Console, settings: Settings, resume_session: str | None = None) -> None:
    """Run the interactive REPL loop.

    Args:
        console: Console instance for output.
        settings: Application settings.
        resume_session: Optional session ID to resume.
    """
    logger.info("Starting interactive mode")

    # Setup session
    session_manager = SessionManager()

    # Resume session if specified
    if resume_session:
        messages = session_manager.get_session_messages(resume_session)
        if messages:
            session_manager.resume_session(resume_session)
            console.print_info(f"Resuming session {resume_session} with {len(messages)} messages")
        else:
            console.print_warning(f"Session {resume_session} not found, starting new session")

    logger.debug("Session manager initialized: session_id=%s", session_manager.session_id)

    # Validate model configuration
    try:
        logger.info("Validating model config: provider=%s, model=%s",
                   settings.model.provider, settings.model.name)
        # Create model for compaction (without tools) - also validates API key
        compaction_model = create_model(settings)
        logger.info("Model configuration validated successfully")
    except ValueError as e:
        logger.error("Failed to validate model config: %s", e)
        console.print_error(str(e))
        console.print_info("Please set your API key in the environment or config file.")
        sys.exit(1)

    # Setup prompt history
    history_path = settings.memory.storage_path / "history"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_session: PromptSession = PromptSession(
        history=FileHistory(str(history_path)),
        completer=CommandCompleter(),
        complete_while_typing=True,
    )

    console.print_welcome()

    working_dir = os.getcwd()

    # Track messages for saving
    conversation_messages = []

    # Token tracking
    token_tracker = SessionTokenTracker(model_name=settings.model.name)

    while True:
        try:
            # Get user input
            user_input = prompt_session.prompt("❯ ").strip()

            if not user_input:
                continue

            # Handle commands
            if user_input.startswith("/"):
                result = handle_command(user_input, console, session_manager)
                if result == "exit":
                    # Save conversation before exiting
                    if conversation_messages:
                        session_manager.save_conversation_snapshot(conversation_messages)
                    break
                elif result and result.startswith("restore:"):
                    # Restore a session
                    session_id = result.split(":", 1)[1]
                    messages = session_manager.get_session_messages(session_id)
                    if messages:
                        # Save current conversation first
                        if conversation_messages:
                            session_manager.save_conversation_snapshot(conversation_messages)
                        # Switch to restored session
                        session_manager.resume_session(session_id)
                        conversation_messages = list(messages)
                        console.print_info(f"Restored session {session_id} with {len(messages)} messages")
                        # Show last few messages as context
                        console.print_info("Recent messages:")
                        for msg in messages[-4:]:
                            role = "You" if hasattr(msg, "type") and msg.type == "human" else "Assistant"
                            content = msg.content[:100] + "..." if len(msg.content) > 100 else msg.content
                            console.print(f"  [{role}] {content}")
                    else:
                        console.print_warning(f"Session {session_id} not found")
                elif result and result.startswith("model:"):
                    # Switch model/provider
                    model_spec = result.split(":", 1)[1]
                    try:
                        if "/" in model_spec:
                            new_provider, new_model = model_spec.split("/", 1)
                        else:
                            new_provider = model_spec
                            new_model = None

                        # Validate provider
                        valid_providers = ["anthropic", "openai", "azure", "azure_anthropic", "github_copilot", "ollama"]
                        if new_provider not in valid_providers:
                            console.print_error(f"Unknown provider: {new_provider}")
                            console.print_info(f"Valid providers: {', '.join(valid_providers)}")
                            continue

                        # Update settings based on provider
                        settings.model.provider = new_provider
                        if new_model:
                            # Set model in the right place based on provider
                            if new_provider == "github_copilot":
                                settings.model.github_copilot.model = new_model
                            elif new_provider == "azure":
                                # For Azure, the "model" is actually the deployment name
                                settings.model.azure.deployment_name = new_model
                            elif new_provider == "azure_anthropic":
                                settings.model.azure_anthropic.deployment_name = new_model
                            else:
                                settings.model.name = new_model

                        # Validate new model config
                        compaction_model = create_model(settings)

                        # Save to config file and reload cache
                        settings.save_yaml(CONFIG_PATH)
                        reload_settings()

                        # Get effective model name for display
                        if new_provider == "github_copilot":
                            effective_model = settings.model.github_copilot.model or "default"
                        elif new_provider == "azure":
                            effective_model = settings.model.azure.deployment_name or "default"
                        elif new_provider == "azure_anthropic":
                            effective_model = settings.model.azure_anthropic.deployment_name or "default"
                        else:
                            effective_model = new_model or settings.model.name
                        token_tracker = SessionTokenTracker(model_name=effective_model)

                        # Clear model cache in completer
                        if hasattr(prompt_session.completer, 'refresh_models'):
                            prompt_session.completer.refresh_models()

                        console.print_info(f"[bold cyan]*CLANK*[/bold cyan] Switched to {new_provider}/{effective_model}")
                        logger.info("Switched model to %s/%s (saved to config)", new_provider, effective_model)
                    except ValueError as e:
                        console.print_error(f"Failed to switch model: {e}")
                continue

            # Add user message to tracking
            user_msg = HumanMessage(content=user_input)
            conversation_messages.append(user_msg)

            # Prepare state - include full context if we've compacted
            # (compacted messages include summary + recent messages)
            has_summary = any(
                isinstance(m, SystemMessage) and "[CONVERSATION SUMMARY" in str(m.content)
                for m in conversation_messages
            )
            if has_summary:
                # Include all messages (summary + recent + new)
                state = {
                    "messages": conversation_messages,
                    "working_directory": working_dir,
                }
            else:
                # Normal flow - just the new message (checkpointer handles history)
                state = {
                    "messages": [user_msg],
                    "working_directory": working_dir,
                }

            # Run agent
            logger.info("Processing user message: %s", user_input[:100] + "..." if len(user_input) > 100 else user_input)
            console.rule()
            try:
                result = stream_agent_response_sync(
                    settings,
                    session_manager.checkpointer,
                    state,
                    session_manager.get_config(),
                    console,
                )

                # Track tokens
                if result.input_tokens > 0 or result.output_tokens > 0:
                    token_tracker.add_turn(
                        result.input_tokens,
                        result.output_tokens,
                        result.cache_read_tokens,
                        result.cache_creation_tokens,
                    )
                    if settings.output.show_token_usage:
                        console.print_token_usage(
                            result.input_tokens,
                            result.output_tokens,
                            token_tracker.context_used_percent,
                            result.cache_read_tokens,
                            result.cache_creation_tokens,
                        )

                # Track AI response
                if result.response:
                    from langchain_core.messages import AIMessage
                    conversation_messages.append(AIMessage(content=result.response))
                    # Auto-save after each exchange
                    session_manager.save_conversation_snapshot(conversation_messages)

                # Check if context compaction is needed
                if should_compact(token_tracker.context_used_percent):
                    logger.info("Context compaction triggered at %.1f%% usage",
                               token_tracker.context_used_percent)
                    compacted_messages, was_compacted = compact_context_sync(
                        conversation_messages,
                        compaction_model,
                        token_tracker.context_used_percent,
                        console,
                    )
                    if was_compacted:
                        conversation_messages = compacted_messages
                        # Start a new session/thread with compacted context
                        session_manager.new_session()
                        # Reset token tracker since we've compacted
                        # Estimate new context usage (rough approximation)
                        estimated_tokens = sum(
                            len(m.content) // 4 if isinstance(m.content, str) else 100
                            for m in conversation_messages
                        )
                        token_tracker = SessionTokenTracker(model_name=settings.model.name)
                        token_tracker.current_context_tokens = estimated_tokens
                        logger.info("Context compacted, new session started, estimated tokens: %d", estimated_tokens)

                logger.debug("Agent response completed successfully")
            except Exception as e:
                logger.exception("Agent error occurred: %s", e)
                import traceback
                error_details = str(e) or traceback.format_exc()
                console.print_error(f"Agent error: {error_details}")

            console.rule()

        except KeyboardInterrupt:
            console.print()
            continue

        except EOFError:
            # Save conversation before exiting
            if conversation_messages:
                session_manager.save_conversation_snapshot(conversation_messages)
            console.print("\n[bold cyan]*BZZZT*[/bold cyan] Signal lost. Powering down. [bold cyan]*click*[/bold cyan]")
            break


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

    # Token tracking
    token_tracker = SessionTokenTracker(model_name=settings.model.name)

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
            token_tracker.add_turn(
                result.input_tokens,
                result.output_tokens,
                result.cache_read_tokens,
                result.cache_creation_tokens,
            )
            if settings.output.show_token_usage:
                console.print_token_usage(
                    result.input_tokens,
                    result.output_tokens,
                    token_tracker.context_used_percent,
                    result.cache_read_tokens,
                    result.cache_creation_tokens,
                )
    except Exception as e:
        console.print_error(f"Agent error: {e}")
        sys.exit(1)


class ClankerGroup(click.Group):
    """Custom group that handles prompt argument alongside subcommands."""

    def invoke(self, ctx: click.Context) -> None:
        """Invoke the group, handling subcommand routing."""
        # Check if prompt captured a subcommand name
        prompt = ctx.params.get("prompt")
        if prompt and prompt in self.commands:
            # This was meant to be a subcommand, not a prompt
            ctx.params["prompt"] = None
            ctx.invoked_subcommand = prompt
            with ctx:
                cmd = self.commands[prompt]
                ctx.invoke(cmd)
            return
        # Normal invocation
        super().invoke(ctx)


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
    type=click.Choice(["anthropic", "openai", "azure", "azure_anthropic", "github_copilot", "ollama"]),
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
        logger.debug("Settings: provider=%s, model=%s", settings.model.provider, settings.model.name)

    # Override settings from CLI args
    if provider:
        settings.model.provider = provider
    if model:
        settings.model.name = model

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


@main.command(name="login")
def login_github() -> None:
    """Authenticate with GitHub Copilot.

    Initiates the GitHub device authorization flow. You'll be prompted
    to visit a URL and enter a code to authenticate.

    The token is stored locally and used automatically when you select
    the github_copilot provider.

    Examples:

        clanker login         Authenticate with GitHub Copilot
    """
    from clanker.auth import authenticate_github_copilot, is_github_token_valid
    from clanker.ui.console import Console

    console = Console()

    if is_github_token_valid():
        console.print_info("You already have a GitHub token stored.")
        console.print_info("Re-authenticating will replace the existing token.")
        console.print()

    token = authenticate_github_copilot(console)
    if token:
        console.print()
        console.print_info("You can now use: clanker --provider github_copilot")


@main.command(name="logout")
def logout_github() -> None:
    """Remove stored GitHub Copilot token.

    Clears the locally stored GitHub token.

    Examples:

        clanker logout        Remove stored GitHub token
    """
    from clanker.auth.github_copilot import clear_github_token
    from clanker.ui.console import Console

    console = Console()
    clear_github_token()
    console.print_success("GitHub token cleared.")


if __name__ == "__main__":
    main()
