# Workflows

Workflows are stored prompts that let you program repeatable tasks into Clanker. They live as markdown files in the `.clanker/workflows/` directory of your workspace.

## Setup

Create the workflows directory and add markdown files:

```bash
mkdir -p .clanker/workflows
```

Each `.md` file is a workflow. The filename (without extension) becomes the workflow name.

## Creating a Workflow

Create a markdown file in `.clanker/workflows/`:

```bash
# .clanker/workflows/test.md
echo "Run the test suite with pytest. Show any failures with full tracebacks. If all tests pass, report the count." > .clanker/workflows/test.md
```

The file content is sent directly to the agent as a prompt when executed.

### Examples

**`.clanker/workflows/review.md`**
```markdown
Review the most recently changed files. Look for bugs, security issues, and style problems. Provide a summary of findings.
```

**`.clanker/workflows/deploy-check.md`**
```markdown
Run the linter and tests. If everything passes, show me a summary of what changed since the last tag.
```

**`.clanker/workflows/morning.md`**
```markdown
Show me a summary of:
1. Any failing tests
2. TODO comments added recently
3. Open issues if there's a GitHub MCP server connected
```

## Using Workflows

### List Available Workflows

```
❯ /workflow
Available workflows (3):

  deploy-check
  morning
  review

Use /workflow <name> to execute a workflow.
```

### Execute a Workflow

```
❯ /workflow review
```

This reads `.clanker/workflows/review.md` and sends its content to the agent as if you typed it.

### Tab Completion

The `/workflow` command supports tab completion. Type `/workflow ` and press Tab to see available workflows. The list is refreshed on every tab press, so newly added workflows appear immediately.

## Tips

- Keep workflow prompts focused on a single task or related set of tasks
- Use markdown formatting in workflow files — the agent handles it well
- Workflows can reference files, run commands, and use all agent capabilities
- Combine with MCP tools for powerful automation (e.g., GitHub workflows)
- Workflow names support hyphens and underscores (any valid filename works)

## File Structure

```
.clanker/
├── workflows/
│   ├── test.md
│   ├── review.md
│   └── deploy-check.md
├── conversations/
├── memories/
└── instructions.md
```
