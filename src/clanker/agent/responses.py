"""Responses streaming shared by account providers that require stateless replay.

Preserves encrypted reasoning arriving at output_item.done, which LangChain's
current event decoder otherwise drops at a streamed tool boundary.
"""

from collections.abc import AsyncIterator, Iterator
from typing import Any, ClassVar

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import agenerate_from_stream, generate_from_stream
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI
from langchain_openai.chat_models.base import _convert_responses_chunk_to_generation_chunk


class ResponsesStreamError(ValueError):
    """An interrupted or failed Responses stream, without sensitive response bodies."""


class _ResponsesDecoder:
    """Retain encrypted reasoning emitted only at output_item.done.

    LangChain's current decoder ignores that event for reasoning items, so
    relying on it alone loses the encrypted replay state at a tool boundary.
    """

    def __init__(self, error_type: type[ValueError], provider_name: str) -> None:
        self.error_type = error_type
        self.provider_name = provider_name
        self.index = self.output_index = self.sub_index = -1
        self.reasoning_indices: dict[str, int] = {}
        self.finished = False

    def decode(self, event: Any) -> ChatGenerationChunk | None:
        if event.type in {"error", "response.failed"}:
            error = getattr(getattr(event, "response", None), "error", None)
            code = getattr(error, "code", None) or getattr(event, "code", None)
            if code == "context_length_exceeded":
                raise self.error_type(
                    f"{self.provider_name} context_length_exceeded: use /compact and retry."
                )
            raise self.error_type(
                f"{self.provider_name} returned a streaming error. Check account access and quota, or retry."
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
            raise self.error_type(
                f"{self.provider_name} stream ended before completion. Please retry."
            )


class StreamingResponsesModel(ChatOpenAI):
    """Decode streamed Responses consistently for invoke, stream, and tool replay."""

    stream_error_type: ClassVar[type[ValueError]] = ResponsesStreamError
    stream_provider_name: ClassVar[str] = "GitHub Copilot"

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
        decoder = _ResponsesDecoder(self.stream_error_type, self.stream_provider_name)
        payload = self._get_request_payload(messages, stop=stop, **kwargs)
        payload["stream"] = True
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
        decoder = _ResponsesDecoder(self.stream_error_type, self.stream_provider_name)
        payload = self._get_request_payload(messages, stop=stop, **kwargs)
        payload["stream"] = True
        async with await self.root_async_client.responses.create(**payload) as response:
            async for event in response:
                chunk = decoder.decode(event)
                if chunk:
                    if run_manager:
                        await run_manager.on_llm_new_token(chunk.text, chunk=chunk)
                    yield chunk
        decoder.check_complete()
