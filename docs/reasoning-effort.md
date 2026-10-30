# Reasoning effort

Open **Models → Edit → Reasoning effort** in the web configuration UI. The picker
updates when the provider or underlying model ID changes. Settings are saved per
model in `~/.clanker/models.json` as `reasoning_effort`.

**Provider default** leaves the parameter unset. It does not disable thinking.
An explicit `none` is a separate option, offered only on models supporting it.
Higher effort typically increases latency and reasoning-token cost.

## Change effort during a conversation

- `/effort` — show the active model's current effort and supported levels.
- `/effort high` — select a supported level without restarting or losing history.
- `/effort default` — remove the explicit setting and use the provider default.

Changes are saved for the active model in `~/.clanker/models.json` and apply on
the next message (including future sessions using that model). Explicit `none`
is different from `default`. TUI changes are blocked while a turn or compaction
is running; finish or cancel it first. Tab completion offers supported levels.

## Supported controls

| Provider | Behavior |
|---|---|
| OpenAI / Azure OpenAI | Model-specific OpenAI effort values, sent through Chat Completions or Responses as appropriate. |
| ChatGPT account | Model-specific OpenAI/Codex effort values through the existing Responses adapter. |
| GitHub Copilot | OpenAI reasoning model effort through the selected endpoint. Claude/Gemini effort is not inferred from their names. Gateway availability may differ from direct OpenAI. |
| Anthropic | Native `output_config.effort`. Opus 4.5 supports low/medium/high; Opus/Sonnet 4.6 also support max; newer supported models can offer xhigh. |
| Antigravity | No verified effort mapping in this transport. Existing extended-thinking budgets remain available and are not relabeled as effort. |
| Ollama | The existing legacy ChatOllama adapter does not expose Ollama's native `think` control; effort is unavailable in this integration. |

For example, GPT-5 offers minimal/low/medium/high, GPT-5.1 offers
none/low/medium/high, and GPT-5.2–5.5 add xhigh. GPT-5.2/5.3 Codex instead offer
low/medium/high/xhigh (no none). GPT-5.2 Pro offers medium/high/xhigh.
GPT-6 Astra and GPT-6.1 Sol offer low/medium/high/xhigh/max; use Responses
for tool calling with these models.
Unsupported model/value combinations are rejected before a request or configuration
save; an unsupported saved value remains visible in the editor until changed or
cleared. Existing files are not rewritten automatically.

For an opaque Azure deployment or custom OpenAI-compatible model ID, choices are
explicitly **unverified**: the server is authoritative. Set the underlying `model`
ID (separate from Azure's deployment name) for precise filtering. Unknown named
OpenAI generations are not assumed to support a particular set of values.

### Anthropic thinking

Effort and thinking are separate controls. Effort affects all output, not just
thinking. On supported adaptive-thinking models, enabling thinking sends
`thinking: {"type": "adaptive"}` and hides the fixed-budget field. Older models
retain `thinking: {"type": "enabled", "budget_tokens": ...}` and require
`max_tokens` greater than the budget. Leave ample output tokens for reasoning as
well as the final answer.

## Sources

Capability rules are centralized in `src/clanker/config/reasoning.py`. Provider
support evolves; update those rules and their tests when adding a model.

- [OpenAI reasoning guide](https://developers.openai.com/api/docs/guides/reasoning)
- [GPT-5.5 model](https://developers.openai.com/api/docs/models/gpt-5.5)
- [GPT-5.2 Codex](https://developers.openai.com/api/docs/models/gpt-5.2-codex)
- [GPT-5.3 Codex](https://developers.openai.com/api/docs/models/gpt-5.3-codex)
- [GPT-5.2 Pro](https://developers.openai.com/api/docs/models/gpt-5.2-pro)
- [GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol)
- [GPT-6 Astra](https://developers.openai.com/api/docs/models/gpt-6-astra)
- [Azure OpenAI reasoning](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/reasoning?view=foundry-classic)
- [Anthropic effort](https://platform.claude.com/docs/en/build-with-claude/effort)

Verification uses local payload inspection and mocked persistence, not paid live
provider requests. Proxy, subscription, deployment, and API-version restrictions
still apply.
