# Agentic Coding CLI - Requirements Document

A comprehensive specification for building an AI-powered coding assistant CLI using LangChain and Python, inspired by Claude Code.

---

## 1. Project Overview

### 1.1 Vision
Build a command-line interface (CLI) tool that leverages LLMs to assist developers with software engineering tasks including code generation, debugging, refactoring, file manipulation, and codebase exploration.

### 1.2 Core Principles
- **Agentic Behavior**: The agent should autonomously plan, reason, and execute multi-step tasks
- **Tool-based Architecture**: Use a modular tool system for file operations, code execution, and search
- **Streaming Output**: Real-time response streaming for better user experience
- **Context Awareness**: Maintain conversation history and understand the codebase context
- **Safety First**: Implement guardrails to prevent destructive operations

---

## 2. Technology Stack

### 2.1 Core Framework
| Component | Technology | Purpose |
|-----------|------------|---------|
| Agent Framework | LangChain + LangGraph | Agent orchestration, tool management, state handling |
| LLM Provider | OpenAI / Anthropic / Ollama | Language model inference |
| CLI Framework | `click` or `typer` | Command-line interface |
| Terminal UI | `rich` or `prompt_toolkit` | Rich terminal output, syntax highlighting |

### 2.2 Python Dependencies
```txt
langchain>=0.3.0
langgraph>=0.2.0
langchain-openai>=0.2.0
langchain-anthropic>=0.2.0
click>=8.0.0
rich>=13.0.0
prompt-toolkit>=3.0.0
pydantic>=2.0.0
python-dotenv>=1.0.0
gitpython>=3.1.0
tree-sitter>=0.21.0
watchdog>=4.0.0
```

---

## 3. Architecture

### 3.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLI Interface                             │
│  (Input handling, Output rendering, Command parsing)            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Agent Orchestrator                           │
│  (LangGraph StateGraph, ReAct loop, Tool selection)             │
└─────────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│   Tool Layer    │ │  Memory Layer   │ │  Context Layer  │
│ (File, Bash,    │ │ (Conversation,  │ │ (Codebase,      │
│  Search, etc.)  │ │  Summaries)     │ │  Git, Config)   │
└─────────────────┘ └─────────────────┘ └─────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        LLM Provider                              │
│  (OpenAI, Anthropic, Ollama - with streaming support)           │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Agent State Schema (LangGraph)

```python
from typing_extensions import TypedDict, NotRequired
from langchain.messages import AnyMessage

class AgentState(TypedDict):
    messages: list[AnyMessage]           # Conversation history
    current_working_directory: str        # Current path context
    tool_results: NotRequired[list]       # Results from tool executions
    intermediate_steps: NotRequired[list] # Agent reasoning steps
    task_plan: NotRequired[list]          # Planned tasks/todos
    error_state: NotRequired[str]         # Error handling
```

### 3.3 Agent Workflow Graph

```python
from langgraph.graph import StateGraph, START, END

workflow = StateGraph(AgentState)

# Core nodes
workflow.add_node("parse_input", parse_user_input)
workflow.add_node("plan", create_task_plan)
workflow.add_node("reason", agent_reasoning)
workflow.add_node("execute_tool", execute_selected_tool)
workflow.add_node("synthesize", synthesize_response)

# Edges
workflow.add_edge(START, "parse_input")
workflow.add_edge("parse_input", "plan")
workflow.add_conditional_edges("plan", should_use_tools, {
    "yes": "reason",
    "no": "synthesize"
})
workflow.add_edge("reason", "execute_tool")
workflow.add_conditional_edges("execute_tool", is_task_complete, {
    "continue": "reason",
    "done": "synthesize"
})
workflow.add_edge("synthesize", END)
```

---

## 4. Core Features

### 4.1 Tool System

Define tools using the `@tool` decorator pattern:

```python
from langchain.tools import tool

@tool
def read_file(file_path: str) -> str:
    """Read contents of a file at the given path."""
    ...

@tool
def write_file(file_path: str, content: str) -> str:
    """Write content to a file at the given path."""
    ...

@tool
def edit_file(file_path: str, old_string: str, new_string: str) -> str:
    """Replace old_string with new_string in the specified file."""
    ...
```

#### Required Tools

| Tool | Description | Priority |
|------|-------------|----------|
| `read_file` | Read file contents with line numbers | P0 |
| `write_file` | Create/overwrite files | P0 |
| `edit_file` | Make targeted edits to existing files | P0 |
| `bash` | Execute shell commands with timeout | P0 |
| `glob` | Find files by pattern matching | P0 |
| `grep` | Search file contents with regex | P0 |
| `list_directory` | List directory contents | P1 |
| `git_status` | Get git repository status | P1 |
| `git_diff` | Show file differences | P1 |
| `web_search` | Search the web for information | P2 |
| `web_fetch` | Fetch and parse web content | P2 |

### 4.2 Streaming Support

Implement real-time streaming for responsive output:

```python
async def stream_response(graph, state):
    """Stream agent responses in real-time."""
    async for event in graph.astream_events(state, version="v2"):
        if event["event"] == "on_chat_model_stream":
            chunk = event["data"]["chunk"]
            yield chunk.content
        elif event["event"] == "on_tool_start":
            yield f"\n[Using tool: {event['name']}]\n"
        elif event["event"] == "on_tool_end":
            yield f"\n[Tool completed]\n"
```

### 4.3 Conversation Memory

```python
from langgraph.checkpoint.memory import InMemorySaver

# For persistent memory across sessions
checkpointer = InMemorySaver()
graph = workflow.compile(checkpointer=checkpointer)

# Execute with thread_id for session continuity
config = {"configurable": {"thread_id": session_id}}
result = graph.invoke(state, config)
```

### 4.4 Task Planning (Todo System)

```python
class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"

@dataclass
class Task:
    content: str
    status: TaskStatus
    active_form: str  # e.g., "Running tests"
```

---

## 5. CLI Interface

### 5.1 Commands

```bash
# Start interactive session
$ clanker

# Start with initial prompt
$ clanker "Explain this codebase"

# Resume previous session
$ clanker --resume <session_id>

# Configuration
$ clanker config --model claude-3-5-sonnet
$ clanker config --provider anthropic

# Built-in commands (during session)
/help          - Show available commands
/clear         - Clear conversation history
/compact       - Summarize and compact context
/model <name>  - Switch LLM model
/exit          - Exit the session
```

### 5.2 Interactive Mode

```python
import click
from rich.console import Console
from rich.markdown import Markdown
from prompt_toolkit import PromptSession

console = Console()

@click.command()
@click.argument('prompt', required=False)
@click.option('--model', default='claude-3-5-sonnet', help='LLM model to use')
@click.option('--resume', help='Resume session by ID')
def main(prompt, model, resume):
    """Agentic Coding CLI - Your AI pair programmer."""
    session = PromptSession()

    while True:
        try:
            user_input = session.prompt('> ')
            if user_input.startswith('/'):
                handle_command(user_input)
            else:
                response = run_agent(user_input)
                console.print(Markdown(response))
        except KeyboardInterrupt:
            break
```

### 5.3 Output Formatting

- Use `rich` for syntax-highlighted code blocks
- Display tool usage with clear indicators
- Show progress for long-running operations
- Support markdown rendering in terminal

---

## 6. Safety & Security

### 6.1 Command Sandboxing

```python
DANGEROUS_COMMANDS = [
    "rm -rf",
    "sudo",
    "> /dev/",
    "mkfs",
    "dd if=",
    ":(){:|:&};:",  # fork bomb
]

REQUIRE_CONFIRMATION = [
    "git push",
    "git reset --hard",
    "rm",
    "mv",
]
```

### 6.2 File Operation Guards

- Never write to system directories
- Confirm before overwriting files
- Backup files before destructive edits
- Respect `.gitignore` patterns
- Never commit secrets or credentials

### 6.3 Rate Limiting & Timeouts

```python
TOOL_TIMEOUTS = {
    "bash": 120_000,      # 2 minutes
    "web_fetch": 30_000,  # 30 seconds
    "read_file": 5_000,   # 5 seconds
}

MAX_TOOL_CALLS_PER_TURN = 20
MAX_FILE_SIZE_READ = 1_000_000  # 1MB
```

---

## 7. Configuration

### 7.1 Configuration File Structure

```yaml
# ~/.clanker/config.yaml
model:
  provider: anthropic  # openai, anthropic, ollama
  name: claude-3-5-sonnet
  temperature: 0.7
  max_tokens: 4096

safety:
  require_confirmation: true
  sandbox_commands: true
  max_file_size: 1000000

output:
  syntax_highlighting: true
  show_tool_calls: true
  stream_responses: true

memory:
  persist_sessions: true
  max_history_length: 100
```

### 7.2 Environment Variables

```bash
CLANKER_MODEL_PROVIDER=anthropic
CLANKER_API_KEY=<your-api-key>
OPENAI_API_KEY=<openai-key>
ANTHROPIC_API_KEY=<anthropic-key>
```

---

## 8. Project Structure

```
clanker/
├── pyproject.toml
├── README.md
├── src/
│   └── clanker/
│       ├── __init__.py
│       ├── __main__.py          # Entry point
│       ├── cli.py               # CLI interface (click/typer)
│       ├── agent/
│       │   ├── __init__.py
│       │   ├── graph.py         # LangGraph workflow
│       │   ├── state.py         # State definitions
│       │   ├── nodes.py         # Graph nodes
│       │   └── prompts.py       # System prompts
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── file_tools.py    # read, write, edit
│       │   ├── bash_tools.py    # shell execution
│       │   ├── search_tools.py  # glob, grep
│       │   ├── git_tools.py     # git operations
│       │   └── web_tools.py     # web search/fetch
│       ├── memory/
│       │   ├── __init__.py
│       │   ├── conversation.py  # Message history
│       │   └── checkpointer.py  # Session persistence
│       ├── ui/
│       │   ├── __init__.py
│       │   ├── console.py       # Rich console output
│       │   ├── streaming.py     # Stream handlers
│       │   └── formatting.py    # Output formatting
│       ├── config/
│       │   ├── __init__.py
│       │   ├── settings.py      # Configuration management
│       │   └── defaults.py      # Default values
│       └── utils/
│           ├── __init__.py
│           ├── sandbox.py       # Command sandboxing
│           └── validators.py    # Input validation
├── tests/
│   ├── __init__.py
│   ├── test_tools.py
│   ├── test_agent.py
│   └── test_cli.py
└── examples/
    └── sample_session.md
```

---

## 9. Implementation Phases

### Phase 1: Foundation
- [ ] Project setup with `pyproject.toml`
- [ ] Basic CLI with `click` or `typer`
- [ ] LLM integration (single provider)
- [ ] Basic conversation loop
- [ ] Simple streaming output

### Phase 2: Core Tools
- [ ] File read/write/edit tools
- [ ] Bash command execution with sandbox
- [ ] Glob and grep search tools
- [ ] Tool error handling

### Phase 3: Agent Intelligence
- [ ] LangGraph workflow implementation
- [ ] ReAct reasoning loop
- [ ] Multi-step task planning
- [ ] Tool selection logic

### Phase 4: Enhanced UX
- [ ] Rich terminal output
- [ ] Syntax highlighting
- [ ] Progress indicators
- [ ] Command history

### Phase 5: Advanced Features
- [ ] Session persistence
- [ ] Git integration
- [ ] Multi-provider support
- [ ] Web search/fetch tools
- [ ] Context summarization

### Phase 6: Polish
- [ ] Comprehensive testing
- [ ] Documentation
- [ ] Error messages and recovery
- [ ] Performance optimization

---

## 10. Key LangChain/LangGraph Patterns

### 10.1 Creating the Agent

```python
from langchain.chat_models import init_chat_model
from langchain.tools import tool
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver

# Initialize model
model = init_chat_model(
    "claude-3-5-sonnet",
    temperature=0,
)

# Bind tools to model
tools = [read_file, write_file, edit_file, bash, glob, grep]
model_with_tools = model.bind_tools(tools)
```

### 10.2 ReAct Agent Loop

```python
def agent_node(state: AgentState):
    """Main reasoning node using ReAct pattern."""
    messages = state["messages"]
    response = model_with_tools.invoke(messages)
    return {"messages": [response]}

def tool_node(state: AgentState):
    """Execute the tool called by the agent."""
    last_message = state["messages"][-1]
    tool_calls = last_message.tool_calls

    results = []
    for call in tool_calls:
        tool = tool_map[call["name"]]
        result = tool.invoke(call["args"])
        results.append(ToolMessage(content=result, tool_call_id=call["id"]))

    return {"messages": results}

def should_continue(state: AgentState) -> str:
    """Determine if we should continue or end."""
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        return "tools"
    return "end"
```

### 10.3 Streaming with Events

```python
async def run_agent_streaming(user_input: str):
    """Run agent with streaming output."""
    state = {"messages": [HumanMessage(content=user_input)]}

    async for event in graph.astream_events(state, version="v2"):
        kind = event["event"]

        if kind == "on_chat_model_stream":
            content = event["data"]["chunk"].content
            if content:
                print(content, end="", flush=True)

        elif kind == "on_tool_start":
            print(f"\n[Tool: {event['name']}]")

        elif kind == "on_tool_end":
            print(f"[Done]")
```

---

## 11. Testing Strategy

### 11.1 Unit Tests
- Tool functions with mocked filesystem
- State transitions in graph nodes
- Input validation and sanitization

### 11.2 Integration Tests
- Full agent loop with mock LLM
- Tool chain execution
- Session persistence

### 11.3 E2E Tests
- CLI command parsing
- Interactive session simulation
- Real LLM integration (optional, expensive)

---

## 12. Success Criteria

- [ ] User can start interactive session and converse with agent
- [ ] Agent can read, write, and edit files accurately
- [ ] Agent can execute bash commands safely
- [ ] Agent can search codebase with glob/grep
- [ ] Streaming output works smoothly
- [ ] Session history persists across restarts
- [ ] All dangerous operations require confirmation
- [ ] Error handling is graceful and informative

---

## References

- [LangChain Documentation](https://python.langchain.com/)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [Claude Code](https://claude.ai/code) - Reference implementation
- [ReAct Paper](https://arxiv.org/abs/2210.03629) - Reasoning and Acting pattern
