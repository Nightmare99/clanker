"""GitHub Copilot provider for LangChain integration."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any, AsyncIterator, Iterator, List, Optional, ClassVar

from langchain_core.callbacks import CallbackManagerForLLMRun, AsyncCallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field

from clanker.logging import get_logger

logger = get_logger("providers.github_copilot")

# Global client instance for persistence across model switches
_copilot_client: Any = None
_copilot_session: Any = None
_copilot_session_id: str | None = None
_copilot_current_model: str | None = None
_copilot_initialized: bool = False
_copilot_loop_id: int | None = None  # Track which event loop the client was created on
_copilot_session_tools: set | None = None  # Track tool names for session recreation
_copilot_system_message: str | None = None  # Track system message
_copilot_models_cache: dict[str, int] | None = None  # Cache model_id -> max_tokens

# Callback for tool call notifications (set by streaming layer)
from typing import Callable
_tool_call_callback: Callable[[str, dict, str | None], None] | None = None


async def _get_model_token_limit(model_id: str) -> int:
    """Get max token limit for a model from SDK, with caching."""
    global _copilot_models_cache

    # Return from cache if available
    if _copilot_models_cache and model_id in _copilot_models_cache:
        return _copilot_models_cache[model_id]

    # Fetch models and build cache
    try:
        client = await _ensure_client()
        models = await client.list_models()
        _copilot_models_cache = {}
        for m in models:
            limits = getattr(m.capabilities, 'limits', None)
            max_tokens = getattr(limits, 'max_context_window_tokens', 128000) if limits else 128000
            _copilot_models_cache[m.id] = max_tokens

        return _copilot_models_cache.get(model_id, 128000)
    except Exception as e:
        logger.warning("Failed to fetch model limits: %s", e)
        return 128000  # Default fallback


def get_model_token_limit_sync(model_id: str) -> int:
    """Synchronous wrapper to get model token limit."""
    global _copilot_models_cache

    # Return from cache if available
    if _copilot_models_cache and model_id in _copilot_models_cache:
        return _copilot_models_cache[model_id]

    # Can't fetch async from sync context, return default
    return 128000


def set_tool_call_callback(callback: Callable[[str, dict, str | None], None] | None) -> None:
    """Register callback for tool call notifications.

    Args:
        callback: Function(tool_name, args, result) called when tools execute.
    """
    global _tool_call_callback
    _tool_call_callback = callback


def get_tool_call_callback() -> Callable[[str, dict, str | None], None] | None:
    """Get the current tool call callback."""
    return _tool_call_callback


def _get_github_token() -> str | None:
    """Get GitHub token from environment."""
    import os

    # Check environment variables in priority order
    # COPILOT_TOKEN is specific to our Copilot OAuth token
    for var in ["COPILOT_TOKEN", "COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"]:
        token = os.environ.get(var)
        if token:
            logger.debug("Using token from %s", var)
            return token

    return None


def _get_copilot_token_path() -> Path:
    """Get path to stored Copilot token."""
    from pathlib import Path
    return Path.home() / ".clanker" / "copilot_token"


def _load_copilot_token() -> str | None:
    """Load stored Copilot token if valid."""
    import json
    import time

    token_path = _get_copilot_token_path()
    if not token_path.exists():
        return None

    try:
        data = json.loads(token_path.read_text())
        # Check if token is expired (tokens last ~8 hours, we refresh at 7)
        if data.get("expires_at", 0) > time.time():
            return data.get("access_token")
        else:
            logger.debug("Stored Copilot token expired")
    except Exception as e:
        logger.debug("Failed to load stored token: %s", e)

    return None


def _save_copilot_token(access_token: str, expires_in: int = 28800) -> None:
    """Save Copilot token for reuse."""
    import json
    import time

    token_path = _get_copilot_token_path()
    token_path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "access_token": access_token,
        "expires_at": time.time() + expires_in - 3600,  # Refresh 1 hour early
    }
    token_path.write_text(json.dumps(data))
    logger.debug("Saved Copilot token to %s", token_path)


def authenticate_copilot_sync() -> str:
    """Authenticate with GitHub Copilot using device flow (sync version).

    Returns the access token.
    """
    import time
    import urllib.request
    import json as json_lib

    # Copilot client ID (same as used by copilot.vim)
    CLIENT_ID = "Iv1.b507a08c87ecfe98"

    headers = {
        "Accept": "application/json",
        "Editor-Version": "Neovim/0.9.0",
        "Editor-Plugin-Version": "copilot.vim/1.16.0",
        "Content-Type": "application/json",
        "User-Agent": "GithubCopilot/1.155.0",
    }

    # Step 1: Request device code
    req = urllib.request.Request(
        "https://github.com/login/device/code",
        data=json_lib.dumps({"client_id": CLIENT_ID, "scope": "read:user"}).encode(),
        headers=headers,
        method="POST",
    )

    with urllib.request.urlopen(req) as resp:
        data = json_lib.loads(resp.read().decode())

    device_code = data["device_code"]
    user_code = data["user_code"]
    verification_uri = data["verification_uri"]
    interval = data.get("interval", 5)

    print(f"\n  To authenticate with GitHub Copilot:")
    print(f"  1. Visit: {verification_uri}")
    print(f"  2. Enter code: {user_code}")
    print(f"\n  Waiting for authentication...")

    # Step 2: Poll for access token
    while True:
        time.sleep(interval)

        req = urllib.request.Request(
            "https://github.com/login/oauth/access_token",
            data=json_lib.dumps({
                "client_id": CLIENT_ID,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            }).encode(),
            headers=headers,
            method="POST",
        )

        with urllib.request.urlopen(req) as resp:
            data = json_lib.loads(resp.read().decode())

        if "access_token" in data:
            access_token = data["access_token"]
            _save_copilot_token(access_token)
            print("  Authentication successful!\n")
            return access_token

        error = data.get("error")
        if error == "authorization_pending":
            continue
        elif error == "slow_down":
            interval += 5
        elif error == "expired_token":
            raise RuntimeError("Device code expired. Please try again.")
        elif error == "access_denied":
            raise RuntimeError("Access denied. Please try again.")
        else:
            raise RuntimeError(f"Authentication failed: {error}")


async def _ensure_client() -> Any:
    """Ensure the Copilot client is initialized."""
    global _copilot_client, _copilot_initialized, _copilot_session, _copilot_loop_id
    global _copilot_session_id, _copilot_current_model, _copilot_session_tools, _copilot_system_message
    import os

    # Check if we need to recreate the client (event loop changed)
    current_loop_id = id(asyncio.get_event_loop())
    if _copilot_client is not None and _copilot_loop_id != current_loop_id:
        logger.debug("Event loop changed, resetting Copilot client (keeping session_id for resume)")
        # Reset client state - but KEEP session_id so we can resume
        _copilot_client = None
        _copilot_session = None
        # Keep _copilot_session_id to resume the session
        # Keep _copilot_current_model, _copilot_session_tools, _copilot_system_message for resume
        _copilot_initialized = False

    if _copilot_client is None:
        try:
            from copilot import CopilotClient
            from copilot.types import SubprocessConfig
        except ImportError:
            raise ImportError(
                "github-copilot-sdk is not installed. "
                "Install it with: pip install github-copilot-sdk"
            )

        # Try to get Copilot token (in order of preference)
        token = _get_github_token() or _load_copilot_token()

        if not token:
            # Need to authenticate
            logger.info("No Copilot token found, starting device flow authentication")
            token = authenticate_copilot_sync()

        # Pass token directly via SubprocessConfig
        config = SubprocessConfig(
            github_token=token,
            use_logged_in_user=False,
        )
        _copilot_client = CopilotClient(config)
        _copilot_loop_id = current_loop_id
        logger.info("GitHub Copilot client initialized with explicit token")

        await _copilot_client.start()
        _copilot_initialized = True

        # Populate models cache for token limits
        await _populate_models_cache()

    return _copilot_client


async def _populate_models_cache() -> None:
    """Fetch and cache model information from SDK."""
    global _copilot_models_cache

    if _copilot_client is None:
        return

    try:
        models = await _copilot_client.list_models()
        _copilot_models_cache = {}
        for m in models:
            limits = getattr(m.capabilities, 'limits', None)
            max_tokens = getattr(limits, 'max_context_window_tokens', 128000) if limits else 128000
            _copilot_models_cache[m.id] = max_tokens
        logger.debug("Cached %d Copilot models", len(_copilot_models_cache))
    except Exception as e:
        logger.warning("Failed to cache model info: %s", e)


async def _ensure_session(
    model: str,
    tools: list | None = None,
    system_message: str | None = None,
) -> Any:
    """Ensure a Copilot session exists, creating or resuming as needed.

    Args:
        model: The model ID to use
        tools: List of Copilot Tool objects to make available
        system_message: System message/instructions for the session
    """
    global _copilot_session, _copilot_session_id, _copilot_current_model
    global _copilot_session_tools, _copilot_system_message

    client = await _ensure_client()

    # Check if we need to recreate session due to tool changes
    current_tool_names = {t.name for t in tools} if tools else set()
    tools_changed = _copilot_session_tools is not None and current_tool_names != _copilot_session_tools

    if tools_changed and _copilot_session is not None:
        logger.info("Tools changed, recreating session")
        try:
            await _copilot_session.disconnect()
        except Exception as e:
            logger.warning("Error disconnecting old session: %s", e)
        _copilot_session = None

    # If no session exists, create or resume one
    if _copilot_session is None:
        # Import PermissionHandler for approve_all
        from copilot import PermissionHandler

        # Check if we have an existing session_id to resume
        if _copilot_session_id is not None:
            # Resume existing session (e.g., after event loop change)
            logger.info("Resuming Copilot session: %s", _copilot_session_id)
            try:
                # Resume with tools and model
                resume_kwargs = {
                    "on_permission_request": PermissionHandler.approve_all,
                    "model": model,
                }
                if tools:
                    tool_names = [t.name for t in tools]
                    resume_kwargs["tools"] = tools
                    resume_kwargs["available_tools"] = tool_names

                _copilot_session = await client.resume_session(
                    _copilot_session_id,
                    **resume_kwargs,
                )
                _copilot_current_model = model
                _copilot_session_tools = current_tool_names
                logger.info("Resumed Copilot session: %s with model: %s", _copilot_session_id, model)
                return _copilot_session
            except Exception as e:
                logger.warning("Failed to resume session %s: %s, creating new session", _copilot_session_id, e)
                # Fall through to create a new session

        # Create new session
        _copilot_session_id = f"clanker-{uuid.uuid4().hex[:8]}"

        # Build session config
        session_kwargs = {
            "session_id": _copilot_session_id,
            "model": model,
            "streaming": True,
            "on_permission_request": PermissionHandler.approve_all,
        }

        # Add tools if provided - whitelist only our tools to prevent built-in tool usage
        if tools:
            tool_names = [t.name for t in tools]
            session_kwargs["tools"] = tools
            session_kwargs["available_tools"] = tool_names  # Only allow our custom tools
            logger.info("Creating session with %d tools: %s", len(tools), tool_names)

        # Add system message if provided (replace mode for full control)
        if system_message:
            session_kwargs["system_message"] = {
                "mode": "replace",
                "content": system_message,
            }
            logger.debug("Setting system message (replace mode)")

        _copilot_session = await client.create_session(**session_kwargs)
        _copilot_current_model = model
        _copilot_session_tools = current_tool_names
        _copilot_system_message = system_message
        logger.info("Created Copilot session: %s with model: %s", _copilot_session_id, model)

    # If model changed, switch model on existing session
    elif model != _copilot_current_model:
        logger.info("Switching model from %s to %s", _copilot_current_model, model)
        from copilot import PermissionHandler
        _copilot_session = await client.resume_session(
            _copilot_session_id,
            on_permission_request=PermissionHandler.approve_all,
            model=model,
        )
        _copilot_current_model = model

    return _copilot_session


def get_copilot_client() -> Any:
    """Get the global Copilot client instance."""
    return _copilot_client


async def list_copilot_models() -> list[dict]:
    """List available Copilot models from subscription.

    Returns:
        List of model info dicts with 'id', 'name', and 'capabilities'.
    """
    try:
        client = await _ensure_client()
        models = await client.list_models()
        return [
            {
                "id": m.id,
                "name": m.name,
                "capabilities": {
                    "vision": getattr(m.capabilities.supports, "vision", False),
                    "reasoning": getattr(m.capabilities.supports, "reasoning_effort", False),
                    "max_tokens": getattr(m.capabilities.limits, "max_context_window_tokens", None),
                }
            }
            for m in models
        ]
    except Exception as e:
        logger.warning("Failed to list Copilot models: %s", e)
        return []


def is_copilot_available() -> bool:
    """Check if GitHub Copilot SDK is available."""
    try:
        from copilot import CopilotClient
        return True
    except ImportError:
        return False


async def cleanup_copilot() -> None:
    """Clean up Copilot client and session."""
    global _copilot_client, _copilot_session, _copilot_session_id, _copilot_current_model, _copilot_initialized
    global _copilot_session_tools, _copilot_system_message, _copilot_models_cache

    if _copilot_session is not None:
        try:
            await _copilot_session.disconnect()
        except Exception as e:
            logger.warning("Error disconnecting session: %s", e)
        _copilot_session = None

    if _copilot_client is not None:
        try:
            await _copilot_client.stop()
        except Exception as e:
            logger.warning("Error stopping client: %s", e)
        _copilot_client = None

    _copilot_session_id = None
    _copilot_current_model = None
    _copilot_initialized = False
    _copilot_session_tools = None
    _copilot_system_message = None
    _copilot_models_cache = None
    logger.info("GitHub Copilot client cleaned up")


def _normalize_tool_result(result: Any) -> str:
    """Normalize tool result for display. Delegates to centralized function."""
    from clanker.ui.tool_display import normalize_tool_output
    return normalize_tool_output(result)


def _convert_messages_to_prompt(messages: List[BaseMessage]) -> tuple[str, str | None]:
    """Convert LangChain messages to Copilot prompt format.

    Returns:
        Tuple of (prompt, system_message).
    """
    system_message = None

    # Extract system message if present
    for msg in messages:
        if isinstance(msg, SystemMessage):
            system_message = str(msg.content) if msg.content else None
            break

    # Get the last human message as the prompt
    # Copilot SDK expects a simple string prompt
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            content = msg.content
            # Ensure it's a string
            if isinstance(content, list):
                # Handle multimodal content
                content = " ".join(str(c) for c in content if isinstance(c, str))
            return str(content), system_message

    # Fallback: join all non-system messages
    prompt_parts = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            continue
        content = msg.content
        if isinstance(content, list):
            content = " ".join(str(c) for c in content if isinstance(c, str))
        prompt_parts.append(str(content))

    return "\n".join(prompt_parts), system_message


def _convert_langchain_tools_to_copilot(tools: list) -> list:
    """Convert LangChain tools to Copilot tool format using define_tool."""
    copilot_tools = []

    try:
        from copilot import define_tool
    except ImportError:
        logger.warning("Copilot SDK not available for tool conversion")
        return []

    for tool in tools:
        # Get the Pydantic model for tool parameters if available
        params_type = None
        if hasattr(tool, "args_schema") and tool.args_schema:
            params_type = tool.args_schema

        def make_handler(t):
            """Create an async handler for a LangChain tool."""
            async def handler(params, invocation):
                try:
                    # Convert params (Pydantic model) to dict
                    if params is None:
                        args = {}
                    elif hasattr(params, "model_dump"):
                        args = params.model_dump(exclude_none=True)
                    elif hasattr(params, "dict"):
                        args = params.dict(exclude_none=True)
                    elif isinstance(params, dict):
                        args = params
                    else:
                        args = {}

                    logger.debug("Tool %s called with args: %s", t.name, args)

                    # Always use ainvoke since we're in async context
                    # This works for both sync and async tools (LangChain handles it)
                    result = await t.ainvoke(args)

                    result_str = str(result)
                    logger.debug("Tool %s result length: %d", t.name, len(result_str))

                    return result_str
                except Exception as e:
                    logger.error("Tool %s error: %s", t.name, e)
                    return f"Error: {str(e)}"
            return handler

        # Create tool using define_tool
        copilot_tool = define_tool(
            name=tool.name,
            description=tool.description or "",
            handler=make_handler(tool),
            params_type=params_type,
            overrides_built_in_tool=True,
        )
        copilot_tools.append(copilot_tool)
        logger.debug("Converted tool: %s", tool.name)

    return copilot_tools


class ChatGitHubCopilot(BaseChatModel):
    """LangChain chat model wrapping GitHub Copilot SDK.

    This provider maintains a persistent session across calls,
    preserving conversation history even when switching models.

    Example:
        ```python
        from clanker.providers import ChatGitHubCopilot

        llm = ChatGitHubCopilot(model="gpt-4.1")
        response = await llm.ainvoke("Hello!")
        ```
    """

    model: str = Field(default="gpt-4.1", description="Copilot model ID")
    streaming: bool = Field(default=True, description="Enable streaming responses")
    max_input_tokens: int = Field(default=128000, description="Max input tokens for the model")
    profile: dict = Field(default_factory=dict, description="Model profile for token limits")

    # Tools bound to this model
    _bound_tools: list = []

    class Config:
        arbitrary_types_allowed = True

    @property
    def _llm_type(self) -> str:
        return "github-copilot"

    @property
    def _identifying_params(self) -> dict:
        return {"model": self.model}

    def model_post_init(self, __context) -> None:
        """Set profile after model initialization."""
        if not self.profile:
            # Get token limit from cache or use default (async fetch happens later)
            max_tokens = get_model_token_limit_sync(self.model) or self.max_input_tokens
            object.__setattr__(self, 'profile', {"max_input_tokens": max_tokens})

    def get_num_tokens(self, text: str) -> int:
        """Estimate token count for text."""
        # Rough estimate: ~4 chars per token
        return len(text) // 4

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Synchronous generation - wraps async."""
        import concurrent.futures
        import threading

        result_holder = []
        error_holder = []

        def run_in_thread():
            # Create a fresh event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(
                    self._agenerate(messages, stop, None, **kwargs)
                )
                result_holder.append(result)
            except Exception as e:
                error_holder.append(e)
            finally:
                # Don't close - let it be reused
                pass

        thread = threading.Thread(target=run_in_thread)
        thread.start()
        thread.join()

        if error_holder:
            raise error_holder[0]
        return result_holder[0]

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Asynchronous generation using Copilot SDK."""
        try:
            from copilot.generated.session_events import SessionEventType
        except ImportError:
            raise ImportError(
                "github-copilot-sdk is not installed. "
                "Install it with: pip install github-copilot-sdk"
            )

        # Convert messages to prompt and extract system message
        prompt, system_msg = _convert_messages_to_prompt(messages)

        # Convert bound tools to Copilot format
        copilot_tools = None
        if self._bound_tools:
            copilot_tools = _convert_langchain_tools_to_copilot(self._bound_tools)

        # Ensure session exists with tools and system message
        session = await _ensure_session(
            model=self.model,
            tools=copilot_tools,
            system_message=system_msg,
        )

        # Collect response using event-based pattern (matching SDK examples)
        content_parts = []
        usage_data = {}
        done_event = asyncio.Event()
        error_msg = None

        def handle_event(event):
            nonlocal content_parts, usage_data, error_msg

            # Use event.type.value for string comparison (Python SDK pattern)
            event_type = event.type.value if hasattr(event.type, 'value') else str(event.type)

            if event_type == "assistant.message_delta":
                delta = getattr(event.data, 'delta_content', None) or ""
                if delta:
                    content_parts.append(delta)
            elif event_type == "assistant.message":
                # Final complete message
                content = getattr(event.data, 'content', None)
                if content:
                    content_parts = [content]
            elif event_type == "assistant.usage":
                usage_data['input_tokens'] = getattr(event.data, 'input_tokens', 0)
                usage_data['output_tokens'] = getattr(event.data, 'output_tokens', 0)
            elif event_type == "tool.execution_start":
                # Tool is starting - notify callback
                tool_name = getattr(event.data, 'tool_name', None) or getattr(event.data, 'toolName', 'unknown')
                # Try multiple attribute names for arguments
                arguments = (
                    getattr(event.data, 'arguments', None) or
                    getattr(event.data, 'toolArgs', None) or
                    getattr(event.data, 'tool_args', None) or
                    {}
                )
                # Convert to dict if needed
                if hasattr(arguments, 'model_dump'):
                    arguments = arguments.model_dump()
                elif hasattr(arguments, '__dict__'):
                    arguments = vars(arguments)
                logger.debug("Tool event data attrs: %s", dir(event.data))
                logger.info("Tool starting: %s with args: %s", tool_name, arguments)
                callback = _tool_call_callback
                if callback:
                    try:
                        callback(tool_name, arguments, None)
                    except Exception as e:
                        logger.error("Tool callback error: %s", e)
            elif event_type == "tool.execution_complete":
                # Tool finished - notify callback with result
                tool_name = getattr(event.data, 'tool_name', None) or getattr(event.data, 'toolName', 'unknown')
                success = getattr(event.data, 'success', True)
                result = getattr(event.data, 'result', None)

                # Extract meaningful content from result
                result_str = _normalize_tool_result(result)

                logger.info("Tool complete: %s success=%s", tool_name, success)
                callback = _tool_call_callback
                if callback and result_str:
                    try:
                        callback(tool_name, {}, result_str)
                    except Exception as e:
                        logger.error("Tool callback error: %s", e)
            elif event_type == "session.idle":
                done_event.set()
            elif event_type == "session.error":
                error_msg = getattr(event.data, 'message', 'Unknown error')
                logger.error("Session error: %s", error_msg)
                done_event.set()

        session.on(handle_event)

        try:
            # Pass prompt as STRING directly (not a dict!)
            response = await session.send_and_wait(prompt)

            # Extract content from response if events didn't capture it
            if not content_parts and response:
                if hasattr(response, 'data') and hasattr(response.data, 'content'):
                    content_parts = [response.data.content]
                elif hasattr(response, 'content'):
                    content_parts = [response.content]

            if error_msg:
                raise RuntimeError(f"Session error: {error_msg}")
        except Exception as e:
            logger.error("Error during send_and_wait: %s", e)
            raise

        # Build response
        content = "".join(content_parts)

        message = AIMessage(
            content=content,
            additional_kwargs={
                "model": self.model,
            },
            usage_metadata={
                "input_tokens": usage_data.get("input_tokens", 0),
                "output_tokens": usage_data.get("output_tokens", 0),
                "total_tokens": usage_data.get("input_tokens", 0) + usage_data.get("output_tokens", 0),
            } if usage_data else None,
        )

        return ChatResult(
            generations=[ChatGeneration(message=message)],
            llm_output={"model": self.model},
        )

    async def _astream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Stream responses - falls back to generate for now."""
        # Use _agenerate and yield the result as a single chunk
        # TODO: Implement proper streaming once basic functionality works
        result = await self._agenerate(messages, stop, run_manager, **kwargs)
        content = result.generations[0].message.content
        yield ChatGenerationChunk(message=AIMessageChunk(content=content))

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        """Synchronous streaming - wraps async."""
        import queue
        import threading

        chunk_queue: queue.Queue = queue.Queue()
        error_holder: list = []

        async def run_stream():
            try:
                async for chunk in self._astream(messages, stop, None, **kwargs):
                    chunk_queue.put(chunk)
            except Exception as e:
                error_holder.append(e)
            finally:
                chunk_queue.put(None)  # Signal completion

        def run_in_thread():
            asyncio.run(run_stream())

        thread = threading.Thread(target=run_in_thread, daemon=True)
        thread.start()

        while True:
            chunk = chunk_queue.get()
            if chunk is None:
                break
            yield chunk
            if run_manager:
                run_manager.on_llm_new_token(chunk.text)

        thread.join(timeout=1.0)

        if error_holder:
            raise error_holder[0]

    def bind_tools(self, tools: list, **kwargs) -> "ChatGitHubCopilot":
        """Bind tools to this model instance."""
        new_model = ChatGitHubCopilot(
            model=self.model,
            streaming=self.streaming,
            max_input_tokens=self.max_input_tokens,
            profile=self.profile,
        )
        new_model._bound_tools = tools
        return new_model

    def with_structured_output(self, schema, **kwargs):
        """Return model configured for structured output."""
        # For now, just return self - structured output handled by tools
        return self
