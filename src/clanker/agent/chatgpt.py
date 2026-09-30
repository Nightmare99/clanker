"""Native ChatGPT/Codex Responses adapter inspired by openai-oauth's dev proxy.

LangChain's OpenAI adapter handles message/image/tool conversion and SSE decoding.
We normalize the account backend's request constraints and refresh auth per request.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Generator, Iterator
from typing import TYPE_CHECKING, Any

import httpx
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import LanguageModelInput
from langchain_core.language_models.chat_models import agenerate_from_stream, generate_from_stream
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI
from langchain_openai.chat_models.base import _convert_responses_chunk_to_generation_chunk
from pydantic import Field, SecretStr

from clanker.config.chatgpt_auth import BASE_URL, api_headers, get_credentials, model_info

if TYPE_CHECKING:
    from clanker.config.models import ModelConfig


class _AccountAuth(httpx.Auth):
    def sync_auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response, None]:
        request.headers.update(api_headers(get_credentials()))
        yield request

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        credentials = await asyncio.to_thread(get_credentials)
        request.headers.update(api_headers(credentials))
        yield request


class _ResponsesDecoder:
    """Retain encrypted reasoning emitted only at output_item.done.

    LangChain's current decoder ignores that event for reasoning items, so
    relying on it alone loses the encrypted replay state at a tool boundary.
    """

    def __init__(self) -> None:
        self.index = self.output_index = self.sub_index = -1
        self.reasoning_indices: dict[str, int] = {}
        self.finished = False

    def decode(self, event: Any) -> ChatGenerationChunk | None:
        from clanker.config.chatgpt_auth import ChatGPTAuthError

        if event.type in {"error", "response.failed"}:
            error = getattr(getattr(event, "response", None), "error", None)
            code = getattr(error, "code", None) or getattr(event, "code", None)
            if code == "context_length_exceeded":
                raise ChatGPTAuthError(
                    "ChatGPT context_length_exceeded: use /compact and retry."
                )
            raise ChatGPTAuthError(
                "ChatGPT returned a streaming error. Check account access and quota, or retry."
            )
        if event.type in {"response.completed", "response.incomplete"}:
            self.finished = True
        if event.type == "response.output_item.done" and event.item.type == "reasoning":
            encrypted = getattr(event.item, "encrypted_content", None)
            index = self.reasoning_indices.get(event.item.id)
            if encrypted and index is not None:
                return ChatGenerationChunk(
                    message=AIMessageChunk(
                        content=[
                            {
                                "type": "reasoning",
                                "index": index,
                                "encrypted_content": encrypted,
                            }
                        ]
                    )
                )
            return None
        self.index, self.output_index, self.sub_index, chunk = (
            _convert_responses_chunk_to_generation_chunk(
                event,
                self.index,
                self.output_index,
                self.sub_index,
                output_version="responses/v1",
            )
        )
        if event.type == "response.output_item.added" and event.item.type == "reasoning":
            self.reasoning_indices[event.item.id] = self.index
        return chunk

    def check_complete(self) -> None:
        if not self.finished:
            from clanker.config.chatgpt_auth import ChatGPTAuthError

            raise ChatGPTAuthError("ChatGPT stream ended before completion. Please retry.")


class ChatGPTModel(ChatOpenAI):
    """Stateless, always-streaming Responses API for a connected ChatGPT account."""

    account_model_info: dict[str, Any] = Field(default_factory=dict)

    @property
    def _llm_type(self) -> str:
        return "chatgpt-codex"

    def _get_request_payload(
        self, input_: LanguageModelInput, *, stop: list[str] | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        instructions = payload.get("instructions", "")
        input_items = []
        for item in payload.get("input", []):
            if item.get("role") in {"system", "developer"}:
                content = item.get("content", "")
                text = (
                    content
                    if isinstance(content, str)
                    else "\n".join(
                        block.get("text", "") for block in content if isinstance(block, dict)
                    )
                )
                instructions = "\n\n".join(part for part in (instructions, text) if part)
            else:
                # Older providers' unencrypted reasoning is not valid replay state.
                if item.get("type") == "reasoning" and not item.get("encrypted_content"):
                    continue
                input_items.append(item)
        payload.update(instructions=instructions, input=input_items, store=False, stream=True)
        include = list(payload.get("include") or [])
        if "reasoning.encrypted_content" not in include:
            include.append("reasoning.encrypted_content")
        payload["include"] = include
        for key in ("max_output_tokens", "previous_response_id", "stop"):
            payload.pop(key, None)
        metadata = self.account_model_info
        reasoning = dict(payload.get("reasoning") or {})
        if metadata.get("default_reasoning_level"):
            reasoning.setdefault("effort", metadata["default_reasoning_level"])
        if metadata.get("support_verbosity") and metadata.get("default_verbosity"):
            verbosity_settings = dict(payload.get("text") or {})
            verbosity_settings.setdefault("verbosity", metadata["default_verbosity"])
            payload["text"] = verbosity_settings
        if metadata.get("use_responses_lite"):
            reasoning["context"] = "all_turns"
            prefix = []
            if payload.get("tools"):
                prefix.append(
                    {"type": "additional_tools", "role": "developer", "tools": payload.pop("tools")}
                )
            if instructions:
                prefix.append(
                    {"role": "developer", "content": [{"type": "input_text", "text": instructions}]}
                )
            payload["input"] = prefix + input_items
            payload["instructions"] = ""
            payload["parallel_tool_calls"] = False
            payload["extra_headers"] = {
                **payload.get("extra_headers", {}),
                "x-openai-internal-codex-responses-lite": "true",
            }
        if reasoning:
            payload["reasoning"] = reasoning
        return payload

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return generate_from_stream(
            self._stream(messages, stop=stop, run_manager=run_manager, **kwargs)
        )

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return await agenerate_from_stream(
            self._astream(messages, stop=stop, run_manager=run_manager, **kwargs)
        )

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        decoder = _ResponsesDecoder()
        payload = self._get_request_payload(messages, stop=stop, **kwargs)
        with self.root_client.responses.create(**payload) as response:
            for event in response:
                chunk = decoder.decode(event)
                if chunk:
                    if run_manager:
                        run_manager.on_llm_new_token(chunk.text, chunk=chunk)
                    yield chunk
        decoder.check_complete()

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        decoder = _ResponsesDecoder()
        payload = self._get_request_payload(messages, stop=stop, **kwargs)
        async with await self.root_async_client.responses.create(**payload) as response:
            async for event in response:
                chunk = decoder.decode(event)
                if chunk:
                    if run_manager:
                        await run_manager.on_llm_new_token(chunk.text, chunk=chunk)
                    yield chunk
        decoder.check_complete()


def create_chatgpt_model(config: ModelConfig) -> ChatGPTModel:
    get_credentials()  # Fail with the login command before initializing an agent.
    if not config.model:
        raise ValueError(
            "ChatGPT requires a model ID. Run 'clanker openai-login' to discover models."
        )
    configured_timeout = config.stream_chunk_timeout
    timeout = (
        600
        if configured_timeout is None
        else None
        if configured_timeout <= 0
        else configured_timeout
    )
    return ChatGPTModel(
        model=config.model,
        # _AccountAuth replaces this placeholder on every outgoing request.
        api_key=SecretStr("chatgpt-account"),
        base_url=BASE_URL,
        use_responses_api=True,
        use_previous_response_id=False,
        output_version="responses/v1",
        store=False,
        reasoning_effort=config.reasoning_effort,
        profile={"max_input_tokens": config.max_input_tokens} if config.max_input_tokens else {},
        account_model_info=model_info(config.model),
        http_client=httpx.Client(auth=_AccountAuth()),
        http_async_client=httpx.AsyncClient(auth=_AccountAuth()),
        timeout=httpx.Timeout(timeout, connect=30),
    )
