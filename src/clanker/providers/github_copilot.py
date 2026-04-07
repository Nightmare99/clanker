"""GitHub Copilot provider - LangChain chat model wrapper."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, AsyncIterator, Iterator, List, Optional

from langchain_core.callbacks import CallbackManagerForLLMRun, AsyncCallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field

from clanker.logging import get_logger

# Re-export from copilot modules for backward compatibility
from clanker.copilot.auth import (
    authenticate_copilot_sync,
    get_github_token as _get_github_token,
    load_copilot_token as _load_copilot_token,
    save_copilot_token as _save_copilot_token,
)
from clanker.copilot.client import (
    get_model_token_limit_sync,
    is_available as is_copilot_available,
    list_models as list_copilot_models_async,
)
from clanker.copilot.tools import (
    convert_langchain_tools_to_copilot as _convert_langchain_tools_to_copilot,
    get_tool_call_callback,
    normalize_tool_result as _normalize_tool_result,
    set_tool_call_callback,
)

logger = get_logger("providers.github_copilot")

# Global session state for LangChain provider
_copilot_client: Any = None
_copilot_session: Any = None
_copilot_session_id: str | None = None
_copilot_current_model: str | None = None
_copilot_loop_id: int | None = None
_copilot_session_tools: set | None = None
_copilot_system_message: str | None = None


async def _ensure_client() -> Any:
    """Ensure the Copilot client is initialized for LangChain provider."""
    global _copilot_client, _copilot_loop_id

    current_loop_id = id(asyncio.get_event_loop())
    if _copilot_client is not None and _copilot_loop_id != current_loop_id:
        logger.debug("Event loop changed, resetting Copilot client")
        _copilot_client = None

    if _copilot_client is None:
        try:
            from copilot import CopilotClient
            from copilot.types import SubprocessConfig
        except ImportError:
            raise ImportError(
                "github-copilot-sdk is not installed. "
                "Install it with: pip install github-copilot-sdk"
            )

        token = _get_github_token() or _load_copilot_token()
        if not token:
            logger.info("No Copilot token found, starting device flow authentication")
            token = authenticate_copilot_sync()

        config = SubprocessConfig(
            github_token=token,
            use_logged_in_user=False,
        )
        _copilot_client = CopilotClient(config)
        _copilot_loop_id = current_loop_id
        await _copilot_client.start()
        logger.info("GitHub Copilot client initialized")

    return _copilot_client


async def _ensure_session(
    model: str,
    tools: list | None = None,
    system_message: str | None = None,
) -> Any:
    """Ensure a Copilot session exists for LangChain provider."""
    global _copilot_session, _copilot_session_id, _copilot_current_model
    global _copilot_session_tools, _copilot_system_message

    client = await _ensure_client()

    current_tool_names = {t.name for t in tools} if tools else set()
    tools_changed = _copilot_session_tools is not None and current_tool_names != _copilot_session_tools

    if tools_changed and _copilot_session is not None:
        logger.info("Tools changed, recreating session")
        try:
            await _copilot_session.disconnect()
        except Exception as e:
            logger.warning("Error disconnecting old session: %s", e)
        _copilot_session = None

    if _copilot_session is None:
        from copilot import PermissionHandler

        if _copilot_session_id is not None:
            logger.info("Resuming Copilot session: %s", _copilot_session_id)
            try:
                resume_kwargs = {
                    "on_permission_request": PermissionHandler.approve_all,
                    "model": model,
                }
                if tools:
                    tool_names = [t.name for t in tools]
                    resume_kwargs["tools"] = tools
                    resume_kwargs["available_tools"] = tool_names

                _copilot_session = await client.resume_session(_copilot_session_id, **resume_kwargs)
                _copilot_current_model = model
                _copilot_session_tools = current_tool_names
                return _copilot_session
            except Exception as e:
                logger.warning("Failed to resume session: %s, creating new", e)

        _copilot_session_id = f"clanker-{uuid.uuid4().hex[:8]}"
        session_kwargs = {
            "session_id": _copilot_session_id,
            "model": model,
            "streaming": True,
            "on_permission_request": PermissionHandler.approve_all,
        }

        if tools:
            tool_names = [t.name for t in tools]
            session_kwargs["tools"] = tools
            session_kwargs["available_tools"] = tool_names

        if system_message:
            session_kwargs["system_message"] = {"mode": "replace", "content": system_message}

        _copilot_session = await client.create_session(**session_kwargs)
        _copilot_current_model = model
        _copilot_session_tools = current_tool_names
        _copilot_system_message = system_message
        logger.info("Created Copilot session: %s with model: %s", _copilot_session_id, model)

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
    """List available Copilot models."""
    return await list_copilot_models_async()


async def cleanup_copilot() -> None:
    """Clean up Copilot client and session."""
    global _copilot_client, _copilot_session, _copilot_session_id
    global _copilot_current_model, _copilot_session_tools, _copilot_system_message

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
    _copilot_session_tools = None
    _copilot_system_message = None
    logger.info("GitHub Copilot client cleaned up")


def _convert_messages_to_prompt(messages: List[BaseMessage]) -> tuple[str, str | None]:
    """Convert LangChain messages to Copilot prompt format."""
    system_message = None

    for msg in messages:
        if isinstance(msg, SystemMessage):
            system_message = str(msg.content) if msg.content else None
            break

    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            content = msg.content
            if isinstance(content, list):
                content = " ".join(str(c) for c in content if isinstance(c, str))
            return str(content), system_message

    prompt_parts = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            continue
        content = msg.content
        if isinstance(content, list):
            content = " ".join(str(c) for c in content if isinstance(c, str))
        prompt_parts.append(str(content))

    return "\n".join(prompt_parts), system_message


class ChatGitHubCopilot(BaseChatModel):
    """LangChain chat model wrapping GitHub Copilot SDK.

    Maintains a persistent session across calls, preserving
    conversation history even when switching models.
    """

    model: str = Field(default="gpt-4.1", description="Copilot model ID")
    streaming: bool = Field(default=True, description="Enable streaming responses")
    max_input_tokens: int = Field(default=128000, description="Max input tokens")
    profile: dict = Field(default_factory=dict, description="Model profile")

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
        if not self.profile:
            max_tokens = get_model_token_limit_sync(self.model) or self.max_input_tokens
            object.__setattr__(self, 'profile', {"max_input_tokens": max_tokens})

    def get_num_tokens(self, text: str) -> int:
        return len(text) // 4

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        import threading

        result_holder = []
        error_holder = []

        def run_in_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(
                    self._agenerate(messages, stop, None, **kwargs)
                )
                result_holder.append(result)
            except Exception as e:
                error_holder.append(e)

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
        prompt, system_msg = _convert_messages_to_prompt(messages)

        copilot_tools = None
        if self._bound_tools:
            copilot_tools = _convert_langchain_tools_to_copilot(self._bound_tools)

        session = await _ensure_session(
            model=self.model,
            tools=copilot_tools,
            system_message=system_msg,
        )

        content_parts = []
        usage_data = {}
        error_msg = None

        def handle_event(event):
            nonlocal content_parts, usage_data, error_msg
            event_type = event.type.value if hasattr(event.type, 'value') else str(event.type)

            if event_type == "assistant.message_delta":
                delta = getattr(event.data, 'delta_content', None) or ""
                if delta:
                    content_parts.append(delta)
            elif event_type == "assistant.message":
                content = getattr(event.data, 'content', None)
                if content:
                    content_parts = [content]
            elif event_type == "assistant.usage":
                usage_data['input_tokens'] = getattr(event.data, 'input_tokens', 0)
                usage_data['output_tokens'] = getattr(event.data, 'output_tokens', 0)
            elif event_type == "tool.execution_start":
                tool_name = getattr(event.data, 'tool_name', None) or getattr(event.data, 'toolName', 'unknown')
                arguments = (
                    getattr(event.data, 'arguments', None) or
                    getattr(event.data, 'toolArgs', None) or
                    getattr(event.data, 'tool_args', None) or {}
                )
                if hasattr(arguments, 'model_dump'):
                    arguments = arguments.model_dump()
                elif hasattr(arguments, '__dict__'):
                    arguments = vars(arguments)
                callback = get_tool_call_callback()
                if callback:
                    try:
                        callback(tool_name, arguments, None)
                    except Exception:
                        pass
            elif event_type == "tool.execution_complete":
                tool_name = getattr(event.data, 'tool_name', None) or getattr(event.data, 'toolName', 'unknown')
                result = getattr(event.data, 'result', None)
                result_str = _normalize_tool_result(result)
                callback = get_tool_call_callback()
                if callback and result_str:
                    try:
                        callback(tool_name, {}, result_str)
                    except Exception:
                        pass
            elif event_type == "session.error":
                error_msg = getattr(event.data, 'message', 'Unknown error')

        session.on(handle_event)

        try:
            response = await session.send_and_wait(prompt)

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

        content = "".join(content_parts)
        message = AIMessage(
            content=content,
            additional_kwargs={"model": self.model},
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
                chunk_queue.put(None)

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
        new_model = ChatGitHubCopilot(
            model=self.model,
            streaming=self.streaming,
            max_input_tokens=self.max_input_tokens,
            profile=self.profile,
        )
        new_model._bound_tools = tools
        return new_model

    def with_structured_output(self, schema, **kwargs):
        return self
