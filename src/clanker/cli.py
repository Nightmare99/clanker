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
from clanker.memory.checkpointer import SessionManager
from clanker.ui.console import Console
from clanker.ui.streaming import stream_agent_response_sync

# Load environment variables
load_dotenv()


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

    if cmd in ("/exit", "/quit", "/q"):
        console.print_info("Goodbye!")
        return False

    elif cmd == "/help":
        console.print_help()

    elif cmd == "/clear":
        console.clear()
        session_manager.new_session()
        console.print_info("Conversation cleared.")

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
    # Setup session
    session_manager = SessionManager()

    # Create agent
    try:
        graph = create_agent_graph(settings, checkpointer=session_manager.checkpointer)
    except ValueError as e:
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
            console.rule()
            try:
                stream_agent_response_sync(
                    graph,
                    state,
                    session_manager.get_config(),
                    console,
                )
            except Exception as e:
                console.print_error(f"Agent error: {e}")

            console.rule()

        except KeyboardInterrupt:
            console.print()
            continue

        except EOFError:
            console.print_info("\nGoodbye!")
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

    if not config_existed:
        console.print_info(f"Created default config at: {CONFIG_PATH}")
        console.print_info("Configure your provider settings there or via environment variables.\n")

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
