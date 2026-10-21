"""Preserve Copilot's thinking fields through Chat Completions and tool replay."""

from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI

_THINKING_FIELDS = ("reasoning_text", "reasoning_opaque", "reasoning_content")


def _thinking_fields(value: dict[str, Any]) -> dict[str, str]:
    return {key: value[key] for key in _THINKING_FIELDS if isinstance(value.get(key), str)}


class ChatCopilot(ChatOpenAI):
    """Keep readable thinking separate from content, including signed replay state.

    ChatOpenAI intentionally drops non-standard response fields. Copilot uses
    reasoning_text/reasoning_opaque for Claude thinking on /chat/completions.
    Leave tool conversion, token usage, transport, and authentication to it.
    """

    def _convert_chunk_to_generation_chunk(
        self, chunk: dict[str, Any], default_chunk_class: type,
        base_generation_info: dict[str, Any] | None,
    ) -> ChatGenerationChunk | None:
        result = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info,
        )
        choices = chunk.get("choices") or chunk.get("chunk", {}).get("choices", [])
        if result is not None and isinstance(result.message, AIMessageChunk) and choices:
            result.message.additional_kwargs.update(_thinking_fields(choices[0].get("delta") or {}))
        return result

    def _create_chat_result(
        self, response: Any, generation_info: dict[str, Any] | None = None,
    ) -> ChatResult:
        result = super()._create_chat_result(response, generation_info)
        data = response if isinstance(response, dict) else response.model_dump()
        for generation, choice in zip(result.generations, data.get("choices", []), strict=False):
            if isinstance(generation.message, AIMessage):
                generation.message.additional_kwargs.update(_thinking_fields(choice.get("message") or {}))
        return result

    def _get_request_payload(
        self, input_: Any, *, stop: list[str] | None = None, **kwargs: Any,
    ) -> dict[str, Any]:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        messages = self._convert_input(input_).to_messages()
        for message, serialized in zip(messages, payload.get("messages", []), strict=False):
            if isinstance(message, AIMessage):
                serialized.update(_thinking_fields(message.additional_kwargs))
        return payload
