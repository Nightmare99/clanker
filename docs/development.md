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

## Safety Features

Clanker includes several safety features:

- **Command Sandboxing**: Dangerous commands are blocked
- **Path Protection**: System directories are protected from writes
- **Confirmation Prompts**: Destructive operations require confirmation
- **Output Limits**: Large outputs are truncated to prevent issues
