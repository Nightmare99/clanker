"""Provider/model-specific reasoning controls shared by API and model factory."""

import re
from typing import TypedDict


class ReasoningCapabilities(TypedDict):
    levels: list[str]
    description: str
    adaptive_thinking: bool


def uses_adaptive_thinking(model: str | None) -> bool:
    return bool(
        re.fullmatch(
            r"claude-(?:opus-4-[678]|sonnet-4-6|(?:opus|sonnet)-5(?:-5)?|haiku-5-5|(?:fable|mythos)-5(?:-1)?)(?:-\d{8})?",
            model or "",
        )
    )


def reasoning_capabilities(
    provider: str, model: str | None, deployment_name: str | None = None
) -> ReasoningCapabilities:
    """Resolve documented choices without assuming protocols from model branding."""
    levels: list[str] = []
    description = "Reasoning effort is not verified for this provider/model."
    model_id = (model or deployment_name or "").lower()
    baseline = ["low", "medium", "high"]
    if provider == "Anthropic":
        if re.fullmatch(r"claude-opus-4-5(?:-\d{8})?", model_id):
            levels = baseline
        elif uses_adaptive_thinking(model_id):
            levels = [*baseline, "max"]
            if re.match(r"claude-(?:opus-4-[78]|(?:opus|sonnet|haiku|fable|mythos)-5)", model_id):
                levels = [*baseline, "xhigh", "max"]
        if levels:
            description = (
                "Anthropic output_config.effort controls all output, with or without thinking."
            )
    elif provider == "Ollama":
        description = (
            "The legacy ChatOllama integration does not support think or reasoning effort."
        )
    elif provider == "Antigravity":
        description = (
            "Antigravity effort protocol is unverified; thinking budgets are not effort levels."
        )
    elif provider in {"OpenAI", "AzureOpenAI", "ChatGPT", "GitHubCopilot"}:
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
        elif not re.match(r"^(?:gpt-|o[134](?:-|$)|chatgpt-)", model_id) and provider in {
            "OpenAI",
            "AzureOpenAI",
        }:
            return {
                "adaptive_thinking": False,
                "levels": ["none", "minimal", *baseline, "xhigh", "max"],
                "description": "Opaque/custom model or deployment ID: choices are not capability-verified; actual server support must be verified. Set model to the underlying model ID for precise capabilities.",
            }
        if levels:
            description = "OpenAI reasoning effort; available levels depend on the specific model."
        if provider == "GitHubCopilot" and not levels:
            description = "Only verified OpenAI reasoning models support effort through Copilot; Claude/Gemini protocols are not assumed."
    return {
        "levels": levels,
        "description": description,
        "adaptive_thinking": provider == "Anthropic" and uses_adaptive_thinking(model_id),
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
