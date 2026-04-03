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
from clanker.logging import get_logger, setup_logging
from clanker.memory.checkpointer import SessionManager
from clanker.memory.memories import get_memory_store
from clanker.ui.console import Console
from clanker.ui.streaming import StreamResult, stream_agent_response_sync, cleanup_event_loop
from clanker.ui.token_tracking import SessionTokenTracker
from clanker.runtime import set_yolo_mode

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
        model_names = list_model_names()

        # Try to get Copilot models
        copilot_models = []
        try:
            from clanker.providers.github_copilot import is_copilot_available, list_copilot_models
            if is_copilot_available():
                import asyncio
                try:
                    copilot_models = asyncio.run(list_copilot_models())
                except RuntimeError:
                    # Fallback if there's already a loop
                    loop = asyncio.new_event_loop()
                    copilot_models = loop.run_until_complete(list_copilot_models())
                    loop.close()
        except Exception as e:
            logger.debug("Failed to list Copilot models: %s", e)

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

            if copilot_models:
                console.print_info("\nGitHub Copilot models:")
                for m in copilot_models:
                    console.print(f"  [green]copilot:{m['id']}[/green] ({m['name']})")
                console.print_info("\nUse /model copilot:<model-id> to use a Copilot model.")

            if not model_names and not copilot_models:
                console.print_info("\nNo models configured in ~/.clanker/models.json")
                console.print_info("Add models via 'clanker config' or use '/gh-login' for GitHub Copilot.")
            else:
                console.print_info("\nUse /model <name> to switch models.")
        else:
            # Switch to specified model
            target_name = parts[1].strip()

            # Check if it's a Copilot model (copilot:model-id format)
            if target_name.startswith("copilot:"):
                copilot_model_id = target_name[8:]  # Remove "copilot:" prefix
                # Create a temporary model config for Copilot
                from clanker.config.models import ModelConfig, add_model
                copilot_config = ModelConfig(
                    name=f"Copilot {copilot_model_id}",
                    provider="GitHubCopilot",
                    model=copilot_model_id,
                )
                add_model(copilot_config)
                set_default_model(copilot_config.name)
                console.print_success(f"Switched to GitHub Copilot: {copilot_model_id}")
                console.print_info("Note: Conversation history is preserved across model switches.")
            else:
                model = get_model_by_name(target_name)
                if model:
                    set_default_model(target_name)
                    console.print_success(f"Switched to model: {model.name} ({model.provider})")
                    console.print_info("Note: Changes take effect on next message.")
                else:
                    console.print_warning(f"Model '{target_name}' not found.")
                    if model_names:
                        console.print_info(f"Available: {', '.join(model_names)}")
                    if copilot_models:
                        console.print_info(f"Copilot: {', '.join(['copilot:' + m['id'] for m in copilot_models])}")

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

    elif cmd == "/gh-login":
        # GitHub Copilot OAuth device flow authentication
        console.print_info("Starting GitHub Copilot authentication...")
        console.print_info("This will use OAuth device flow to authenticate.")
        try:
            from clanker.providers.github_copilot import authenticate_copilot_sync, _load_copilot_token

            # Check if already authenticated
            existing_token = _load_copilot_token()
            if existing_token:
                console.print_info("Found existing Copilot token.")
                console.print_info("Re-authenticating will replace it.")

            # Run device flow authentication
            token = authenticate_copilot_sync()
            if token:
                console.print_success("GitHub Copilot authentication successful!")
                console.print_info("Token saved to ~/.clanker/copilot_token")
                console.print_info("You can now use /model copilot:<model-id> to use Copilot models.")

                # List available models
                try:
                    from clanker.providers.github_copilot import list_copilot_models
                    import asyncio
                    try:
                        models = asyncio.run(list_copilot_models())
                    except RuntimeError:
                        loop = asyncio.new_event_loop()
                        models = loop.run_until_complete(list_copilot_models())
                        loop.close()
                    if models:
                        console.print_info("\nAvailable Copilot models:")
                        for m in models:
                            console.print(f"  [green]copilot:{m['id']}[/green] ({m['name']})")
                except Exception as e:
                    logger.debug("Failed to list Copilot models after login: %s", e)
        except KeyboardInterrupt:
            console.print_info("\nAuthentication cancelled.")
        except Exception as e:
            console.print_error(f"Authentication failed: {e}")

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
        "/config",
        "/mcp",
        "/logs",
        "/gh-login",
        "/history",
        "/restore",
        "/memories",
        "/remember",
        "/forget",
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

        # Regular command completion
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

    # Setup prompt history
    history_path = settings.memory.storage_path / "history"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_session: PromptSession = PromptSession(
        history=FileHistory(str(history_path)),
        completer=CommandCompleter(),
        complete_while_typing=True,
    )

    console.print_welcome()

    # Check for updates (non-blocking, silent on failure)
    try:
        from clanker.update import get_update_message
        update_msg = get_update_message()
        if update_msg:
            console.print_update_available(update_msg)
    except Exception:
        pass  # Silently ignore update check failures

    working_dir = os.getcwd()

    # Track messages for saving
    conversation_messages = []

    # Token tracking
    current_model = get_default_model()
    tracker_model_name = current_model.name if current_model else "unknown"
    token_tracker = SessionTokenTracker(model_name=tracker_model_name)

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
                    # Cleanup Copilot if used
                    try:
                        from clanker.providers.github_copilot import cleanup_copilot
                        from clanker.ui.streaming import _get_or_create_loop
                        loop = _get_or_create_loop()
                        loop.run_until_complete(cleanup_copilot())
                    except Exception:
                        pass
                    # Cleanup the persistent event loop
                    cleanup_event_loop()
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
                continue

            # Add user message to tracking
            user_msg = HumanMessage(content=user_input)
            conversation_messages.append(user_msg)

            # Prepare state - the graph handles summarization automatically via SummarizationNode
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

                # Track AI response
                if result.response:
                    from langchain_core.messages import AIMessage
                    conversation_messages.append(AIMessage(content=result.response))
                    # Auto-save after each exchange
                    session_manager.save_conversation_snapshot(conversation_messages)

                # Show token usage
                if (result.input_tokens > 0 or result.output_tokens > 0) and settings.output.show_token_usage:
                    console.print_token_usage(
                        result.input_tokens,
                        result.output_tokens,
                        token_tracker.context_used_percent,
                        result.cache_read_tokens,
                        result.cache_creation_tokens,
                    )

                logger.debug("Agent response completed successfully")
            except Exception as e:
                logger.exception("Agent error occurred: %s", e)
                console.print_error(f"Agent error: {e}")

            console.rule()

        except KeyboardInterrupt:
            console.print()
            continue

        except EOFError:
            # Save conversation before exiting
            if conversation_messages:
                session_manager.save_conversation_snapshot(conversation_messages)
            # Cleanup Copilot if used
            try:
                from clanker.providers.github_copilot import cleanup_copilot
                import asyncio
                try:
                    asyncio.run(cleanup_copilot())
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    loop.run_until_complete(cleanup_copilot())
                    loop.close()
            except Exception:
                pass
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
    current_model = get_default_model()
    tracker_model_name = current_model.name if current_model else "unknown"
    token_tracker = SessionTokenTracker(model_name=tracker_model_name)

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

    def invoke(self, ctx: click.Context):
        """Invoke, handling the case where prompt matches a subcommand."""
        # If prompt is a subcommand name, invoke that subcommand instead
        prompt = ctx.params.get("prompt")
        if prompt and prompt in self.commands:
            # Clear the prompt and invoke the subcommand
            ctx.params["prompt"] = None
            ctx.invoked_subcommand = prompt
            with ctx:
                cmd = self.commands[prompt]
                return ctx.invoke(cmd)
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


if __name__ == "__main__":
    main()
