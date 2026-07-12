"""Subagent spawning tool."""

import asyncio
import os
import uuid
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage

from clanker.config import get_settings
from clanker.logging import get_logger

logger = get_logger("tools.subagent")


@tool
async def spawn_subagent(prompt: str, system_prompt: str | None = None) -> dict:
    """Spawn a new, independent subagent to solve a subtask in-process.

    The subagent will run asynchronously, and its thinking, output, and tool
    executions will stream to the user terminal. It has access to all the same tools.

    Args:
        prompt: Detailed instructions for the subagent specifying what it needs to do.
        system_prompt: Optional custom role definition or system instructions for the subagent.

    Returns:
        A dictionary containing the subagent's final response and execution status/token usage.
    """
    logger.info("Spawning subagent with prompt: %s...", prompt[:80])

    # Lazy imports to prevent circular dependencies at package load time
    from clanker.ui.streaming import stream_agent_response_async, get_active_console
    from clanker.ui.console import Console

    settings = get_settings()
    parent_console = get_active_console()

    # Create a new Console wrapper to isolate the Live display stack (avoiding clear_live IndexError),
    # but reuse the output file stream of the active parent console to print correctly under the REPL
    sub_console = Console()
    sub_console._console.file = parent_console._console.file

    # 1. Print visual start boundary
    parent_console.print_info(f"🤖 [bold]Spawning Subagent[/bold]: {prompt[:80]}...")

    # 2. Prepare subagent state and config
    config = {
        "configurable": {
            "thread_id": f"subagent-{uuid.uuid4().hex[:8]}"
        },
        "recursion_limit": settings.context.max_agent_steps,
    }
    state = {
        "messages": [HumanMessage(content=prompt)],
        "working_directory": os.getcwd(),
    }

    try:
        # 3. Run the subagent graph (disable mid-turn user input injection for subagents)
        result = await stream_agent_response_async(
            settings=settings,
            checkpointer=None,  # stateless
            state=state,
            config=config,
            console=sub_console,
            system_prompt=system_prompt,
        )

        # 4. Print visual end boundary
        parent_console.print_success("🤖 [bold]Subagent execution completed successfully.[/bold]")

        return {
            "success": True,
            "response": result.response,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
        }
    except Exception as e:
        logger.exception("Error in subagent execution: %s", e)
        parent_console.print_error(f"🤖 [bold]Subagent execution failed:[/bold] {e}")
        return {
            "success": False,
            "error": str(e),
        }
