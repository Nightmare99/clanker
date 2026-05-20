"""Custom middleware for LangChain agents."""

import json
from typing import Any, Callable

from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain.messages import ToolMessage

from clanker.logging import get_logger

logger = get_logger("agent.middleware")


def _process_tool_message(result: Any) -> Any:
    """Helper to convert a ToolMessage containing images into multimodal content."""
    # Check if result is a ToolMessage we can process
    if not isinstance(result, ToolMessage):
        return result

    # Try to parse content as JSON to check for images
    content = result.content
    if not isinstance(content, str):
        return result

    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return result

    if not isinstance(parsed, dict) or "images" not in parsed:
        return result

    images = parsed.get("images", [])
    if not images:
        return result

    # Build multimodal content
    logger.info("Converting tool result to multimodal content with %d images", len(images))

    multimodal_content = []

    # Add text content (without the images array to avoid duplication)
    text_result = {k: v for k, v in parsed.items() if k != "images"}
    text_result["images_included"] = len(images)
    multimodal_content.append({
        "type": "text",
        "text": json.dumps(text_result),
    })

    # Add image content
    for img in images:
        try:
            data = img.get("data", "")
            mime_type = img.get("mime_type", "image/png")
            page = img.get("page", "?")

            # Format as data URL for image_url type
            data_url = f"data:{mime_type};base64,{data}"

            multimodal_content.append({
                "type": "image_url",
                "image_url": {"url": data_url},
            })
            logger.debug("Added image for page %s to multimodal content", page)
        except Exception as e:
            logger.warning("Failed to add image to multimodal content: %s", e)

    # Return new ToolMessage with multimodal content
    return ToolMessage(
        content=multimodal_content,
        tool_call_id=result.tool_call_id,
        name=result.name if hasattr(result, "name") else None,
    )


class MultimodalToolResultsMiddleware(AgentMiddleware):
    """Middleware class that converts tool results with images to multimodal ToolMessages.

    Supports both synchronous and asynchronous agent execution.
    """

    def __init__(self) -> None:
        super().__init__()
        self.tools = []
        self.state_schema = AgentState

    def wrap_tool_call(self, request: Any, handler: Callable) -> Any:
        result = handler(request)
        return _process_tool_message(result)

    async def awrap_tool_call(self, request: Any, handler: Callable) -> Any:
        result = await handler(request)
        return _process_tool_message(result)


multimodal_tool_results = MultimodalToolResultsMiddleware()
