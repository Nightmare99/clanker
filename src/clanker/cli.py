"""Command-line interface for Clanker."""

import os
import sys

import click
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory

from clanker import __version__
from clanker.agent import create_agent_graph
from clanker.config import CONFIG_PATH, Settings, get_settings, reload_settings
from clanker.logging import get_logger, setup_logging
from clanker.memory.checkpointer import SessionManager
from clanker.ui.console import Console
from clanker.ui.streaming import stream_agent_response_sync

# Load environment variables
load_dotenv()

# Module logger (initialized after setup_logging is called)
logger = get_logger("cli")


def handle_command(command: str, console: Console, session_manager: SessionManager) -> bool:
    """Handle built-in commands.

    Args:
        command: The command string (starting with /).
        console: Console instance.
        session_manager: Session manager instance.

    Returns:
        True if should continue, False if should exit.
    """
    cmd = command.strip().lower()
    logger.debug("Handling command: %s", cmd)

    if cmd in ("/exit", "/quit", "/q"):
        logger.info("User requested exit")
        console.print("[bold cyan]*BZZZT*[/bold cyan] Shutdown sequence initiated. Until next time, human. [bold cyan]*WHIRR... click*[/bold cyan]")
        return False

    elif cmd == "/help":
        console.print_help()

    elif cmd == "/clear":
        console.clear()
        session_manager.new_session()
        logger.info("Conversation cleared, new session started")
        console.print("[bold cyan]*WHIRR*[/bold cyan] Memory banks wiped. Fresh slate initialized. [bold cyan]*CLANK*[/bold cyan]")

    elif cmd.startswith("/model"):
        parts = cmd.split(maxsplit=1)
        if len(parts) == 1:
            settings = get_settings()
            console.print_info(f"Current model: {settings.model.provider}/{settings.model.name}")
        else:
            console.print_warning("Model switching not yet implemented in this session.")

    elif cmd == "/config":
        settings = get_settings()
        console.print_info(f"Config file: {CONFIG_PATH}")
        console.print_info(f"Provider: {settings.model.provider}")
        console.print_info(f"Model: {settings.model.name}")
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

    else:
        console.print_warning(f"Unknown command: {command}")
        console.print_info("Type /help for available commands.")

    return True


def run_interactive(console: Console, settings: Settings) -> None:
    """Run the interactive REPL loop.

    Args:
        console: Console instance for output.
        settings: Application settings.
    """
    logger.info("Starting interactive mode")

    # Setup session
    session_manager = SessionManager()
    logger.debug("Session manager initialized: session_id=%s", session_manager.session_id)

    # Create agent
    try:
        logger.info("Creating agent graph with provider=%s, model=%s",
                   settings.model.provider, settings.model.name)
        graph = create_agent_graph(settings, checkpointer=session_manager.checkpointer)
        logger.info("Agent graph created successfully")
    except ValueError as e:
        logger.error("Failed to create agent: %s", e)
        console.print_error(str(e))
        console.print_info("Please set your API key in the environment or config file.")
        sys.exit(1)

    # Setup prompt history
    history_path = settings.memory.storage_path / "history"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_session: PromptSession = PromptSession(history=FileHistory(str(history_path)))

    console.print_welcome()

    working_dir = os.getcwd()

    while True:
        try:
            # Get user input
            user_input = prompt_session.prompt("❯ ").strip()

            if not user_input:
                continue

            # Handle commands
            if user_input.startswith("/"):
                if not handle_command(user_input, console, session_manager):
                    break
                continue

            # Prepare state
            state = {
                "messages": [HumanMessage(content=user_input)],
                "working_directory": working_dir,
            }

            # Run agent
            logger.info("Processing user message: %s", user_input[:100] + "..." if len(user_input) > 100 else user_input)
            console.rule()
            try:
                stream_agent_response_sync(
                    graph,
                    state,
                    session_manager.get_config(),
                    console,
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

    try:
        graph = create_agent_graph(settings, checkpointer=session_manager.checkpointer)
    except ValueError as e:
        console.print_error(str(e))
        sys.exit(1)

    state = {
        "messages": [HumanMessage(content=prompt)],
        "working_directory": os.getcwd(),
    }

    try:
        stream_agent_response_sync(
            graph,
            state,
            session_manager.get_config(),
            console,
        )
    except Exception as e:
        console.print_error(f"Agent error: {e}")
        sys.exit(1)


@click.command()
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
    type=click.Choice(["anthropic", "openai", "azure", "ollama"]),
    default=None,
    help="LLM provider (azure = Azure OpenAI)",
)
@click.option(
    "--resume",
    "-r",
    default=None,
    help="Resume a previous session by ID",
)
@click.option(
    "--version",
    "-v",
    is_flag=True,
    help="Show version and exit",
)
def main(
    prompt: str | None,
    model: str | None,
    provider: str | None,
    resume: str | None,
    version: bool,
) -> None:
    """Clanker - AI-Powered Coding Assistant.

    Start an interactive session or run a single prompt.

    Examples:

        clanker                     Start interactive mode

        clanker "explain this code" Run single prompt

        clanker -m gpt-4o           Use a specific model
    """
    if version:
        click.echo(f"Clanker v{__version__}")
        return

    console = Console()

    # Check if config exists before loading (to show first-run message)
    config_existed = CONFIG_PATH.exists()

    # Load settings (creates default config if missing)
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

    if not config_existed:
        console.print_info(f"Created default config at: {CONFIG_PATH}")
        console.print_info("Configure your provider settings there or via environment variables.\n")
        logger.info("Created default config at: %s", CONFIG_PATH)

    # Override settings from CLI args
    if provider:
        settings.model.provider = provider
    if model:
        settings.model.name = model

    if prompt:
        run_single_prompt(prompt, console, settings)
    else:
        run_interactive(console, settings)


if __name__ == "__main__":
    main()
