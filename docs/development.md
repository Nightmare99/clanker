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
│   ├── copilot/     # GitHub Copilot SDK integration
│   │   ├── auth.py      # OAuth device flow authentication
│   │   ├── client.py    # SDK client lifecycle
│   │   ├── session.py   # Session manager with MCP support
│   │   ├── tools.py     # Tool conversion utilities
│   │   └── registry.py  # Session persistence
│   ├── mcp/         # MCP server integration (BYOK mode)
│   ├── memory/      # Session persistence
│   ├── providers/   # LLM providers (includes Copilot wrapper)
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

# Build for production (outputs to src/clanker/config/web/static)
npm run build
```

## Safety Features

Clanker includes several safety features:

- **Command Sandboxing**: Dangerous commands are blocked
- **Path Protection**: System directories are protected from writes
- **Confirmation Prompts**: Destructive operations require confirmation
- **Output Limits**: Large outputs are truncated to prevent issues
