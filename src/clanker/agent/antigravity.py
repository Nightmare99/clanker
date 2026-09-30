"""Native LangChain adapter for Antigravity's Cloud Code wire format.

Protocol reference: badrisnarayanan/antigravity-claude-proxy (MIT). No local
proxy, Node runtime, external credential database, or shared event loop needed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Any

import httpx
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel, generate_from_stream
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.messages.ai import UsageMetadata
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool

from clanker.config.antigravity_auth import (
    ENDPOINTS,
    AntigravityAuthError,
    api_headers,
    get_credentials,
)


def _schema(value: dict[str, Any]) -> dict[str, Any]:
    """Translate resolved JSON schemas into Cloud Code's protobuf Schema subset."""
    value = dict(value)
    options = value.pop("anyOf", None) or value.pop("oneOf", None)
    if options:
        non_null = [option for option in options if option.get("type") != "null"]
        if non_null:
            value = {**non_null[0], **value}
        if len(non_null) != len(options):
            value["nullable"] = True
    kind = value.get("type", "object" if "properties" in value else "string")
    if isinstance(kind, list):
        value["nullable"] = "null" in kind
        kind = next((item for item in kind if item != "null"), "string")
    output = {
        key: value[key] for key in ("description", "enum", "nullable", "format") if key in value
    }
    if "enum" in output and not all(isinstance(item, str) for item in output["enum"]):
        # Google's Schema enum is repeated string; keep numeric argument types
        # and describe their allowed values instead of sending invalid protobuf.
        values = json.dumps(output.pop("enum"))
        output["description"] = f"{output.get('description', '')} Allowed values: {values}".strip()
    output["type"] = kind.upper()
    if output["type"] == "OBJECT":
        properties = value.get("properties") or {}
        output["properties"] = {key: _schema(item) for key, item in properties.items()}
        required = [key for key in value.get("required", []) if key in properties]
        if required:
            output["required"] = required
    if output["type"] == "ARRAY":
        output["items"] = _schema(value.get("items") or {"type": "string"})
    return output


def _wire_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name)[:64]


def _parts(content: str | list[Any], *, assistant: bool = False) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"text": content}] if content else []
    parts: list[dict[str, Any]] = []
    for block in content:
        if isinstance(block, str):
            parts.append({"text": block})
        elif isinstance(block, dict):
            kind = block.get("type")
            if kind == "text":
                part: dict[str, Any] = {"text": block.get("text", "")}
                if assistant and block.get("signature"):
                    part["thoughtSignature"] = block["signature"]
                parts.append(part)
            elif kind == "thinking" and assistant and block.get("signature"):
                parts.append(
                    {
                        "text": block.get("thinking", ""),
                        "thought": True,
                        "thoughtSignature": block["signature"],
                    }
                )
            elif kind == "image":
                source = block.get("source") or {}
                if source.get("type") == "base64":
                    parts.append(
                        {"inlineData": {"mimeType": source["media_type"], "data": source["data"]}}
                    )
                elif block.get("base64"):
                    parts.append(
                        {
                            "inlineData": {
                                "mimeType": block.get("mime_type", "image/png"),
                                "data": block["base64"],
                            }
                        }
                    )
                else:
                    raise ValueError("Antigravity requires images as base64 data, not remote URLs.")
            elif kind == "image_url":
                image_url = block.get("image_url", {})
                url = image_url if isinstance(image_url, str) else image_url.get("url", "")
                match = re.fullmatch(r"data:([^;]+);base64,(.+)", url, re.DOTALL)
                if not match:
                    raise ValueError("Antigravity requires images as base64 data, not remote URLs.")
                parts.append({"inlineData": {"mimeType": match[1], "data": match[2]}})
    return parts


def _contents(
    messages: list[BaseMessage], model: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    system: list[dict[str, Any]] = []
    contents: list[dict[str, Any]] = []
    call_names: dict[str, str] = {}
    parts: list[dict[str, Any]]
    for message in messages:
        if isinstance(message, SystemMessage):
            system.extend(_parts(message.content))
            continue
        role = "model" if isinstance(message, AIMessage) else "user"
        if isinstance(message, ToolMessage):
            name = call_names.get(message.tool_call_id) or message.name
            if not name:
                # Legacy snapshots omit tool IDs/names. Preserve their text as
                # historical context instead of inventing a function response.
                parts = _parts(message.content) or [{"text": "."}]
                if contents and contents[-1]["role"] == "user":
                    contents[-1]["parts"].extend(parts)
                else:
                    contents.append({"role": "user", "parts": parts})
                continue
            result_parts = _parts(message.content)
            text = "\n".join(part["text"] for part in result_parts if "text" in part)
            parts = [
                {
                    "functionResponse": {
                        "id": message.tool_call_id,
                        "name": _wire_name(name),
                        "response": {"result": text},
                    }
                }
            ]
            parts.extend(part for part in result_parts if "inlineData" in part)
        else:
            parts = _parts(message.content, assistant=isinstance(message, AIMessage))
            if isinstance(message, AIMessage):
                signatures = message.additional_kwargs.get("antigravity_signatures", {})
                # Signatures are opaque and model-specific; never replay one
                # after switching to another model/provider.
                same_model = message.response_metadata.get("model_name") == model
                if not same_model:
                    parts = [part for part in parts if not part.get("thought")]
                    for part in parts:
                        part.pop("thoughtSignature", None)
                for call in message.tool_calls:
                    call_id = call["id"] or f"call_{uuid.uuid4().hex}"
                    call_names[call_id] = call["name"]
                    function_part: dict[str, Any] = {
                        "functionCall": {
                            "id": call_id,
                            "name": _wire_name(call["name"]),
                            "args": call["args"],
                        }
                    }
                    if same_model and signatures.get(call_id):
                        function_part["thoughtSignature"] = signatures[call_id]
                    elif not same_model and model.startswith("gemini-"):
                        # Google's documented marker for transferred traces
                        # from another model that have no Gemini signature:
                        # ai.google.dev/gemini-api/docs/generate-content/thought-signatures
                        function_part["thoughtSignature"] = "skip_thought_signature_validator"
                    parts.append(function_part)
        if not parts:
            parts = [{"text": "."}]
        if contents and contents[-1]["role"] == role:
            # Parallel tool results must stay together, with images after the
            # consecutive functionResponse parts.
            contents[-1]["parts"].extend(parts)
        else:
            contents.append({"role": role, "parts": parts})
    for content in contents:
        content["parts"] = sorted(content["parts"], key=lambda part: "inlineData" in part)
    return contents, system


class _Decoder:
    def __init__(self, model: str, names: dict[str, str]) -> None:
        self.model = model
        self.names = names
        self.index = -1
        self.kind = ""
        self.tool_index = 0
        self.last_call_id: str | None = None
        self.usage: UsageMetadata | None = None
        self.seen = False
        self.finished = False
        self.block_signed = False

    def decode(self, event: dict[str, Any]) -> Iterator[ChatGenerationChunk]:
        response = event.get("response", event)
        if response.get("error") or event.get("error"):
            raise AntigravityAuthError(
                "Antigravity returned a streaming API error. Try again or check account access."
            )
        if response.get("usageMetadata"):
            usage = response["usageMetadata"]
            prompt = int(usage.get("promptTokenCount", 0))
            output = int(usage.get("candidatesTokenCount", 0)) + int(
                usage.get("thoughtsTokenCount", 0)
            )
            self.usage = {
                "input_tokens": prompt,
                "output_tokens": output,
                "total_tokens": prompt + output,
                "input_token_details": {"cache_read": int(usage.get("cachedContentTokenCount", 0))},
            }
        candidates = response.get("candidates") or []
        if not candidates:
            if (response.get("promptFeedback") or {}).get("blockReason"):
                raise AntigravityAuthError("Antigravity blocked this prompt.")
            return
        candidate = candidates[0]
        for part in (candidate.get("content") or {}).get("parts", []):
            signature = part.get("thoughtSignature")
            additional: dict[str, Any] = {}
            tool_chunks: list[Any] = []
            blocks: list[Any] = []
            if "functionCall" in part:
                call = part["functionCall"]
                call_id = call.get("id") or f"call_{uuid.uuid4().hex}"
                self.last_call_id = call_id
                tool_chunks = [
                    {
                        "name": self.names.get(call["name"], call["name"]),
                        "args": json.dumps(call.get("args") or {}),
                        "id": call_id,
                        "index": self.tool_index,
                        "type": "tool_call_chunk",
                    }
                ]
                self.tool_index += 1
                self.kind = "tool"
                if signature:
                    additional["antigravity_signatures"] = {call_id: signature}
            elif "text" in part:
                kind = "thinking" if part.get("thought") else "text"
                if kind != self.kind or self.block_signed:
                    self.index += 1
                    self.kind = kind
                    self.block_signed = False
                block = {
                    "type": kind,
                    "index": self.index,
                    "thinking" if kind == "thinking" else "text": part["text"],
                }
                if signature:
                    block["signature"] = signature
                    self.block_signed = True
                blocks = [block]
            elif signature and self.kind in {"thinking", "text"}:
                blocks = [{"type": self.kind, "index": self.index, "signature": signature}]
                self.block_signed = True
            elif signature and self.kind == "tool" and self.last_call_id:
                additional["antigravity_signatures"] = {self.last_call_id: signature}
            else:
                continue
            self.seen = True
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content=blocks,
                    tool_call_chunks=tool_chunks,
                    additional_kwargs=additional,
                )
            )
        if candidate.get("finishReason"):
            self.finished = True
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    response_metadata={
                        "finish_reason": candidate["finishReason"],
                    },
                )
            )

    def finish(self) -> ChatGenerationChunk:
        if not self.seen or not self.finished:
            raise AntigravityAuthError(
                "Antigravity returned an empty or incomplete stream. Please retry."
            )
        return ChatGenerationChunk(
            message=AIMessageChunk(
                content="",
                usage_metadata=self.usage,
                response_metadata={"model_name": self.model, "provider": "antigravity"},
            )
        )


def _event(lines: list[str]) -> dict[str, Any] | None:
    data = "\n".join(line[5:].lstrip() for line in lines if line.startswith("data:"))
    if not data or data == "[DONE]":
        return None
    try:
        value = json.loads(data)
    except ValueError as exc:
        raise AntigravityAuthError(
            "Antigravity returned invalid stream data. Please retry."
        ) from exc
    if not isinstance(value, dict):
        raise AntigravityAuthError("Antigravity returned an unexpected stream format.")
    return value


class ChatAntigravity(BaseChatModel):
    """Claude/Gemini streaming, tool calling, images, reasoning, and usage."""

    model: str
    max_tokens: int = 8192
    thinking_enabled: bool = False
    thinking_budget_tokens: int = 10000
    timeout: float | None = 600

    @property
    def _llm_type(self) -> str:
        return "antigravity"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"model_name": self.model}

    def bind_tools(self, tools: Sequence[Any], *, tool_choice: Any = None, **kwargs: Any) -> Any:
        declarations = []
        names: dict[str, str] = {}
        for tool in tools:
            function = convert_to_openai_tool(tool)["function"]
            original = function["name"]
            name = _wire_name(original)
            if name in names:
                raise ValueError(f"Antigravity tool names collide after normalization: {original}")
            names[name] = original
            declaration = {"name": name, "description": function.get("description", "")}
            if function.get("parameters", {}).get("properties"):
                declaration["parameters"] = _schema(function["parameters"])
            declarations.append(declaration)
        return self.bind(tools=declarations, tool_names=names, tool_choice=tool_choice, **kwargs)

    def _payload(
        self,
        messages: list[BaseMessage],
        credentials: dict[str, Any],
        stop: list[str] | None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        contents, system = _contents(messages, self.model)
        generation: dict[str, Any] = {"maxOutputTokens": self.max_tokens}
        if stop:
            generation["stopSequences"] = stop
        if self.thinking_enabled or "thinking" in self.model:
            if self.model.startswith("claude"):
                generation["thinkingConfig"] = {
                    "include_thoughts": True,
                    "thinking_budget": self.thinking_budget_tokens,
                }
                generation["maxOutputTokens"] = max(
                    self.max_tokens, self.thinking_budget_tokens + 8192
                )
            else:
                generation["thinkingConfig"] = {
                    "includeThoughts": True,
                    "thinkingBudget": self.thinking_budget_tokens,
                }
        request: dict[str, Any] = {"contents": contents, "generationConfig": generation}
        if system:
            request["systemInstruction"] = {"role": "user", "parts": system}
        # Stable across tool rounds, without persisting any prompt or account ID.
        first_user = next((message.content for message in messages if message.type == "human"), "")
        request["sessionId"] = hashlib.sha256(json.dumps(first_user).encode()).hexdigest()[:32]
        if kwargs.get("tools"):
            request["tools"] = [{"functionDeclarations": kwargs["tools"]}]
            choice = kwargs.get("tool_choice")
            mode = {"auto": "AUTO", "none": "NONE", "any": "ANY", "required": "ANY"}.get(
                str(choice)
            )
            config: dict[str, Any] = {
                "mode": mode or ("VALIDATED" if self.model.startswith("claude") else "AUTO")
            }
            if isinstance(choice, str) and choice not in {"auto", "none", "any", "required"}:
                config = {"mode": "ANY", "allowedFunctionNames": [_wire_name(choice)]}
            request["toolConfig"] = {"functionCallingConfig": config}
        return {
            "project": credentials["project_id"],
            "model": self.model,
            "request": request,
            "userAgent": "antigravity",
            "requestType": "agent",
            "requestId": f"agent-{uuid.uuid4()}",
        }

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return generate_from_stream(self._stream(messages, stop, run_manager, **kwargs))

    def _headers(self, credentials: dict[str, Any], payload: dict[str, Any]) -> dict[str, str]:
        headers = {
            **api_headers(credentials["access_token"]),
            "Accept": "text/event-stream",
            "X-Machine-Session-Id": payload["request"]["sessionId"],
        }
        if self.model.startswith("claude-") and (self.thinking_enabled or "thinking" in self.model):
            headers["anthropic-beta"] = "interleaved-thinking-2025-05-14"
        return headers

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        credentials = get_credentials()
        payload = self._payload(messages, credentials, stop, **kwargs)
        decoder = _Decoder(self.model, kwargs.get("tool_names", {}))
        try:
            with httpx.Client(timeout=httpx.Timeout(self.timeout, connect=30)) as client:
                for endpoint in ENDPOINTS:
                    with client.stream(
                        "POST",
                        f"{endpoint}/v1internal:streamGenerateContent?alt=sse",
                        json=payload,
                        headers=self._headers(credentials, payload),
                    ) as response:
                        if (
                            response.status_code in {404, 502, 503, 504}
                            and endpoint != ENDPOINTS[-1]
                        ):
                            continue
                        if response.status_code != 200:
                            raise AntigravityAuthError(
                                f"Antigravity generation failed (HTTP {response.status_code}). Check account access, quota, or reconnect."
                            )
                        lines: list[str] = []
                        for line in response.iter_lines():
                            if line:
                                lines.append(line)
                            else:
                                event = _event(lines)
                                lines = []
                                if event:
                                    yield from decoder.decode(event)
                        if lines and (event := _event(lines)):
                            yield from decoder.decode(event)
                        yield decoder.finish()
                        return
        except httpx.HTTPError as exc:
            raise AntigravityAuthError(
                "Antigravity connection interrupted. Check your connection and retry."
            ) from exc

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        credentials = await asyncio.to_thread(get_credentials)
        payload = self._payload(messages, credentials, stop, **kwargs)
        decoder = _Decoder(self.model, kwargs.get("tool_names", {}))
        try:
            # Per-request clients avoid the cross-loop pool sharing that breaks
            # concurrently running subagents, and close on cancellation.
            async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout, connect=30)) as client:
                for endpoint in ENDPOINTS:
                    async with client.stream(
                        "POST",
                        f"{endpoint}/v1internal:streamGenerateContent?alt=sse",
                        json=payload,
                        headers=self._headers(credentials, payload),
                    ) as response:
                        if (
                            response.status_code in {404, 502, 503, 504}
                            and endpoint != ENDPOINTS[-1]
                        ):
                            continue
                        if response.status_code != 200:
                            raise AntigravityAuthError(
                                f"Antigravity generation failed (HTTP {response.status_code}). Check account access, quota, or reconnect."
                            )
                        lines: list[str] = []
                        async for line in response.aiter_lines():
                            if line:
                                lines.append(line)
                            else:
                                event = _event(lines)
                                lines = []
                                if event:
                                    for chunk in decoder.decode(event):
                                        yield chunk
                        if lines and (event := _event(lines)):
                            for chunk in decoder.decode(event):
                                yield chunk
                        yield decoder.finish()
                        return
        except httpx.HTTPError as exc:
            raise AntigravityAuthError(
                "Antigravity connection interrupted. Check your connection and retry."
            ) from exc
