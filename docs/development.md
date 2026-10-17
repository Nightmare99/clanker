# Development

## Setup

```bash
# Clone the repository
git clone https://github.com/yourusername/clanker.git
cd clanker

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install in development mode
pip install -e ".[dev]"
```

## Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=clanker

# Run specific test file
pytest tests/test_tools.py
```

## Code Quality

```bash
# Format and lint
ruff check --fix .
ruff format .

# Type checking
mypy src/clanker
```

## Architecture

```
clanker/
├── src/clanker/
│   ├── agent/       # LangGraph agent definition
│   ├── config/      # Settings management
│   │   └── web/     # Web configuration UI (FastAPI + Vue)
│   ├── context/     # Context management
│   ├── mcp/         # MCP server integration
│   ├── memory/      # Session persistence
│   ├── providers/   # LLM providers
│   ├── tools/       # Tool implementations
│   ├── ui/          # Console and streaming
│   ├── utils/       # Validators and sandbox
│   └── cli.py       # Main CLI entry point
├── web-ui/          # Vue 3 + Naive UI frontend source
├── docs/            # Documentation
└── tests/           # Test suite
```

## Web UI Development

The web configuration UI uses Vue 3 with Naive UI components.

```bash
cd web-ui

# Install dependencies
npm install

# Development server
npm run dev

# Type-check and build for production (outputs to web-ui/dist)
npm run build

# Build and copy into the Python package for clanker config / binary builds
npm run deploy
```

Google Antigravity authentication lives in `config/antigravity_auth.py`; its
native LangChain streaming adapter is `agent/antigravity.py`. Copilot and Google
share `AccountConnectionCard.vue` in the web UI. `tests/test_antigravity.py`
exercises OAuth, cancellation, refresh, model discovery, and sync/async tool
round trips with mocked API responses and a real local callback listener. Live
account authorization needs a manual check; no Google credentials are required
for the test suite.

Copilot discovery persists `supported_endpoints` in each model configuration.
Its factory resolves `copilot_api_endpoint`, the legacy `use_responses_api`
preference, then discovery metadata; old configs use a numbered GPT-generation
fallback until refreshed. The web Test action uses the same factory as the
agent. Copilot refresh preserves endpoint overrides and other custom settings.
`tests/test_copilot_responses.py` covers routing, web edits, refresh, and real
sync/async Clanker tool rounds with mocked HTTP responses.

ChatGPT authentication is in `config/chatgpt_auth.py`; `agent/chatgpt.py` uses
LangChain's Responses request conversion and streaming event decoder, with
account authentication on each request and encrypted reasoning capture at
`response.output_item.done`. Its wire protocol follows the `openai-oauth` dev
proxy/core, including Responses Lite capability metadata. The shared account
card also handles ChatGPT browser and manual callback login. `tests/test_chatgpt.py`
checks OAuth/refresh/cancellation, secure storage, model discovery, CLI/web/TUI
flows, and real sync/async Clanker graphs with tools and encrypted reasoning.
These tests require no real account; live authorization/inference is a manual check.
`agent/responses.py` shares the streaming decoder between ChatGPT and Copilot
Responses models, including encrypted reasoning delivered at `output_item.done`.

Compaction is implemented by `agent/summarization.py`. The TUI's `/compact`
worker uses `run_compaction_async`, reports chunk progress, and cancels native
async model calls on Ctrl+C. After automatic compaction, both interactive modes
read retained messages through `SessionManager.get_checkpoint_messages()` and
project them onto the user/assistant transcript; they do not summarize again.
Tool protocol and encrypted reasoning remain in the live graph checkpoint.
`tests/test_tui_compaction.py` covers responsiveness, cancellation, checkpoint
failure, import replay, and syncing a large imported transcript without another
model call.

The TUI uses `ui/selection_screen.py` as its default screen. Its hit-test guard
rejects detached widgets left in a previous compositor frame, preventing
Textual's selection handler from dereferencing a removed Markdown block's
parent. Typewriter reveals suspend screen text selection without pausing the
animation, and restore selection after the last overlapping reveal finishes.
The suspension also ends on cancellation or removal of the message.
`tests/test_text_selection.py` reproduces the stale-hit crash and exercises
selection blocking during reveals, drag/copy after completion, and removal.

The TUI accepts Command shortcuts as Textual `super` bindings when the terminal
forwards them. `ui/keyboard.py` shares platform detection and editing shortcut
labels. On macOS Command+C only copies and Ctrl+C always interrupts, including
when text is selected. Priority bindings consume inherited Ctrl editing aliases
on macOS before Input/TextArea or modal bindings can handle them; other platforms
skip that guard and retain their Ctrl behavior.
App-level edit bindings delegate to the focused Input/TextArea so prompt and
composer paste handling stays intact. The composer also accepts Command+Enter
and Command+Shift+Z. Terminal-owned clipboard shortcuts and bracketed paste
continue through the normal terminal path. Unix navigation/deletion shortcuts
and Ctrl+D remain unchanged. `tests/test_keyboard_shortcuts.py` exercises both
platform policies, selection copying, disabled aliases, image paste, and help.

On every platform, completed text selections copy automatically without a
copy shortcut. Screen `TextSelected` events and focused editor
selection changes schedule a copy after refresh; active drags, reveals, empty
selections, and password inputs are excluded. This keeps mouse controls active
and works when iTerm2 intercepts Command+C. Tests exercise the selection event
path under both platform shortcut policies without injecting a copy key or
writing the developer's clipboard, and verify terminal OSC 52 clipboard writes.
Copies show a 1.5-second character-count toast. Informational toasts use the
theme's dark surface, foreground text, and lime success border with compact
padding. Native macOS copies confirm only after the clipboard worker succeeds.

`ui/native_clipboard.py` writes local macOS copies through `pbcopy` in a
cancellable worker with a timeout, alongside Textual's internal clipboard
and OSC 52 write. It skips headless apps and SSH sessions; it never places
clipboard text in command arguments or logs. Tests mock subprocesses rather
than changing the developer's clipboard. iTerm2 can intercept Command keys;
copy-on-selection needs no terminal key mapping.

Agent turns have a `TurnCancellation` scope in `execution.py`. Ctrl+C sets its
stop event and cancels the active stream task on its owning loop, so cancellation
does not depend on another model/tool event arriving. Built-in file writes check
the scope, owned shell process groups are killed, and process monitors remain
with promoted/background commands. Each new turn gets a fresh scope. Subagents
retain their own stop flags. Cancellation repairs orphaned tool calls, clears
tool/loading indicators, and restores callbacks before returning to the prompt.
`tests/test_active_turn_cancellation.py` exercises real tool nodes and checkpoints,
including shell descendants, repeated interruption, and the following user turn.

## Safety Features

Clanker includes several safety features:

- **Command Sandboxing**: Dangerous commands are blocked
- **Path Protection**: System directories are protected from writes
- **Confirmation Prompts**: Destructive operations require confirmation
- **Output Limits**: Large outputs are truncated to prevent issues
