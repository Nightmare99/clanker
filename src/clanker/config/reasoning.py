"""Provider/model-specific reasoning controls shared by API and model factory."""

import re
from typing import TypedDict


class ReasoningCapabilities(TypedDict):
    levels: list[str]
    description: str
    adaptive_thinking: bool


def uses_adaptive_thinking(model: str | None) -> bool:
    normalized = (model or "").lower().replace(".", "-")
    return bool(
        re.search(
            r"claude-(?:opus-4-[678]|sonnet-4-6|(?:opus|sonnet)-5(?:-5)?|haiku-5-5|(?:fable|mythos)-5(?:-1)?)(?:-\d{8})?",
            normalized,
        )
    )


def reasoning_capabilities(
    provider: str, model: str | None, deployment_name: str | None = None
) -> ReasoningCapabilities:
    """Resolve documented choices without assuming protocols from model branding."""
    levels: list[str] = []
    description = "Reasoning effort is not verified for this provider/model."
    model_id = (model or deployment_name or "").lower()
    model_norm = model_id.replace(".", "-")
    baseline = ["low", "medium", "high"]

    if provider == "Anthropic":
        if re.search(r"claude-3[.-]7-sonnet", model_id) or re.search(r"claude-3-7-sonnet", model_norm):
            levels = baseline
            description = "Anthropic output_config.effort controls output and thinking on Claude 3.7 Sonnet."
        elif re.fullmatch(r"claude-opus-4-5(?:-\d{8})?", model_norm):
            levels = baseline
            description = "Anthropic output_config.effort controls all output, with or without thinking."
        elif uses_adaptive_thinking(model_id):
            levels = [*baseline, "max"]
            if re.search(r"claude-(?:opus-4-[78]|(?:opus|sonnet|haiku|fable|mythos)-5)", model_norm):
                levels = [*baseline, "xhigh", "max"]
            description = "Anthropic output_config.effort controls all output, with or without thinking."
        elif not model_id.startswith("claude-") and model_id:
            levels = baseline
            description = "Custom Anthropic model; output_config.effort will be passed to API."

    elif provider == "GitHubCopilot":
        # 1. Claude models on Copilot
        if "claude" in model_norm:
            if re.search(r"claude-(?:opus-4-[78]|(?:opus|sonnet|haiku|fable|mythos)-5)", model_norm):
                levels = [*baseline, "xhigh", "max"]
            elif uses_adaptive_thinking(model_id):
                levels = [*baseline, "max"]
            else:
                levels = baseline
            description = "GitHub Copilot reasoning effort for Claude models (low, medium, high)."
        # 2. OpenAI models on Copilot
        elif re.fullmatch(r"gpt-(?:6-astra|6\.1-sol)(?:-\d{4}-\d{2}-\d{2})?", model_id):
            levels = [*baseline, "xhigh", "max"]
        elif re.fullmatch(
            r"o1(?:-\d{4}-\d{2}-\d{2})?|o3(?:-mini)?(?:-\d{4}-\d{2}-\d{2})?|o4-mini(?:-\d{4}-\d{2}-\d{2})?",
            model_id,
        ):
            levels = baseline
        elif re.fullmatch(r"gpt-5(?:-mini|-nano)?(?:-\d{4}-\d{2}-\d{2})?", model_id):
            levels = ["minimal", *baseline]
        elif re.fullmatch(r"gpt-5\.1(?:-\d{4}-\d{2}-\d{2})?", model_id):
            levels = ["none", *baseline]
        elif re.fullmatch(r"gpt-5\.[2345](?:-\d{4}-\d{2}-\d{2})?", model_id):
            levels = ["none", *baseline, "xhigh"]
        elif re.fullmatch(r"gpt-5\.[23]-codex(?:-\d{4}-\d{2}-\d{2})?", model_id):
            levels = [*baseline, "xhigh"]
        elif model_id in {"gpt-5-codex", "gpt-5.1-codex", "gpt-5.1-codex-mini"}:
            levels = baseline
        elif model_id == "gpt-5.1-codex-max":
            levels = [*baseline, "xhigh"]
        elif model_id in {"o3-pro", "gpt-5-pro"}:
            levels = ["high"] if model_id == "gpt-5-pro" else baseline
        elif model_id == "gpt-5.2-pro":
            levels = ["medium", "high", "xhigh"]
        # 3. Gemini models on Copilot
        elif "gemini" in model_norm:
            levels = baseline
            description = "GitHub Copilot reasoning effort for Gemini models."
        # 4. Other reasoning models on Copilot
        elif not re.match(r"^(?:gpt-[34]|text-)", model_id):
            levels = baseline
            description = "GitHub Copilot reasoning effort for reasoning-capable models."

        if levels and not description.startswith("GitHub Copilot"):
            description = "GitHub Copilot reasoning effort; available levels depend on the specific model."

    elif provider == "Antigravity":
        if re.search(r"thinking|flash-tiered|gemini-2|gemini-3|claude", model_norm) or not model_id:
            levels = baseline
            description = "Antigravity reasoning effort mapped to thinking budget tokens (low=2k, medium=8k, high=16k)."

    elif provider == "Ollama":
        if re.search(r"r1|reason|think|qwq|deepseek|qwen2\.5", model_norm):
            levels = baseline
            description = "Ollama reasoning effort passed to local reasoning models."
        else:
            description = (
                "The legacy ChatOllama integration does not support think or reasoning effort for standard models."
            )

    elif provider in {"OpenAI", "AzureOpenAI", "ChatGPT"}:
        # Explicit variants precede their broader families.
        if re.fullmatch(r"gpt-(?:6-astra|6\.1-sol)(?:-\d{4}-\d{2}-\d{2})?", model_id):
            levels = [*baseline, "xhigh", "max"]
        elif re.fullmatch(
            r"o1(?:-\d{4}-\d{2}-\d{2})?|o3(?:-mini)?(?:-\d{4}-\d{2}-\d{2})?|o4-mini(?:-\d{4}-\d{2}-\d{2})?",
            model_id,
        ):
            levels = baseline
        elif re.fullmatch(r"gpt-5(?:-mini|-nano)?(?:-\d{4}-\d{2}-\d{2})?", model_id):
            levels = ["minimal", *baseline]
        elif re.fullmatch(r"gpt-5\.1(?:-\d{4}-\d{2}-\d{2})?", model_id):
            levels = ["none", *baseline]
        elif re.fullmatch(r"gpt-5\.[2345](?:-\d{4}-\d{2}-\d{2})?", model_id):
            levels = ["none", *baseline, "xhigh"]
        elif re.fullmatch(r"gpt-5\.[23]-codex(?:-\d{4}-\d{2}-\d{2})?", model_id):
            levels = [*baseline, "xhigh"]
        elif model_id in {"gpt-5-codex", "gpt-5.1-codex", "gpt-5.1-codex-mini"}:
            levels = baseline
        elif model_id == "gpt-5.1-codex-max":
            levels = [*baseline, "xhigh"]
        elif model_id == "o3-pro":
            levels = baseline
        elif model_id == "gpt-5-pro":
            levels = ["high"]
        elif model_id == "gpt-5.2-pro":
            levels = ["medium", "high", "xhigh"]
        elif not re.match(r"^(?:gpt-|o[134](?:-|$)|chatgpt-)", model_id):
            return {
                "adaptive_thinking": False,
                "levels": ["none", "minimal", *baseline, "xhigh", "max"],
                "description": "Opaque/custom model or deployment ID: choices are not capability-verified; actual server support must be verified. Set model to the underlying model ID for precise capabilities.",
            }
        if levels:
            description = "OpenAI reasoning effort; available levels depend on the specific model."

    return {
        "levels": levels,
        "description": description,
        "adaptive_thinking": (provider in {"Anthropic", "GitHubCopilot"}) and uses_adaptive_thinking(model_id),
    }


def validate_reasoning_effort(
    provider: str,
    model: str | None,
    effort: str | None,
    deployment_name: str | None = None,
) -> None:
    if effort is None:
        return
    capabilities = reasoning_capabilities(provider, model, deployment_name)
    if effort not in capabilities["levels"]:
        raise ValueError(
            f"Unsupported reasoning_effort {effort!r} for {provider}/{model or deployment_name or '(default)'}. "
            f"Allowed: {capabilities['levels']}. {capabilities['description']}"
        )
