# Usage

## CLI Flags

| Flag | Short | Description |
|------|-------|-------------|
| `--help` | `-h` | Show help and exit |
| `--version` | `-v` | Show version and exit |
| `--check-update` | | Check for updates and exit |
| `--model <name>` | `-m` | Use a specific model |
| `--provider <name>` | `-p` | Use a specific provider |
| `--resume <id>` | `-r` | Resume a previous session |
| `--history` | | List past conversations |
| `--memories` | | Show stored memories |
| `--yolo` | | Skip bash command approval |

## Interactive Mode

```bash
# Start with default model
clanker

# Start with a specific model (from models.json)
clanker -m "Claude Sonnet"

# Resume a previous session
clanker --resume <session-id>

# Skip bash command approval (yolo mode)
clanker --yolo

# Check for updates
clanker --check-update
```

## Single Prompt

```bash
# Run a single prompt and exit
clanker "Explain the code in src/main.py"

# With specific provider
clanker -p AzureOpenAI "Find all Python files in this project"
```

## Commands

Inside the interactive session:

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/clear` | Clear conversation history |
| `/compact` | Summarize older context with the current session model; Ctrl+C cancels in the TUI |
| `/model` | List available models and show current |
| `/model <name>` | Switch to a different model |
| `/copilot-login` | Connect a GitHub Copilot subscription as a model provider |
| `/antigravity-login` | Connect a Google account for Antigravity models (unofficial integration) |
| `/openai-login` | Connect a ChatGPT account and discover available coding models |
| `/workflow` | List available workflows |
| `/workflow <name>` | Execute a stored workflow |
| `/skill` | List available skills |
| `/skill <name>` | Manually load a skill (the agent also loads skills automatically) |
| `/config` | Show configuration |
| `/mcp` | Show MCP server status |
| `/logs` | Show logging status and log files |
| `/history` | List past conversations |
| `/restore` or `/resume` | Open a picker for saved conversations, newest first |
| `/restore <id>` or `/resume <id>` | Resume a known session ID directly |
| `/import` | Import a local Codex, Claude Code, OpenCode, or GitHub Copilot CLI conversation |
| `/memories` | Search and manage workspace and global memories in the TUI |
| `/remember <text>` | Save a memory |
| `/forget <id>` | Delete a memory |
| `/reload` | Reload Clanker in place and resume the current session (useful after updating the app) |
| `/exit` | Exit Clanker |

### Switching Models

To connect an account first, use `clanker copilot-login`,
`clanker antigravity-login`, or `clanker openai-login`, the equivalent slash command, or the connected
account cards in the **Accounts** tab of `clanker config`. Discovered models appear
in **Models**. See [Google Antigravity setup and account-risk
notes](configuration.md#google-antigravity). For remote Google login, use
`clanker antigravity-login --no-browser --manual`.

For ChatGPT, use `clanker openai-login --no-browser --manual` on a remote machine,
then select a discovered `chatgpt:<model-id>` entry. See [ChatGPT account setup](configuration.md#chatgpt-openai-account).

You can switch between configured models during a session:

```
❯ /model
Current model: Claude Sonnet (Anthropic)

Available models:
  Claude Sonnet (Anthropic) *
  GPT-4o (AzureOpenAI)
  Llama Local (Ollama)

Use /model <name> to switch models.

❯ /model GPT-4o
Switched to model: GPT-4o (AzureOpenAI)
```

Models are configured in `~/.clanker/models.json` or via `clanker config`.

### Compacting conversation context

Use `/compact` to summarize older messages while preserving the recent tail
and current TODO state. In the TUI, compaction runs in the background and shows
chunk progress. Press Ctrl+C to cancel; the current history is retained if the
summary has not been applied. Wait for completion or cancel before sending a
new prompt, clearing the session, or switching models.

Large imported conversations may trigger automatic compaction when you first
continue them. This can require several model calls. The session transcript
and saved snapshot reuse the graph's completed summary, so Clanker does not
generate a second summary of the original import. Manual compaction also uses
the current checkpoint when available. After compacting a restored/imported
session, its original transcript is not replayed on the next prompt.

### Resuming and importing conversations

Use `/restore` or `/resume` to browse this workspace's saved conversations.
The picker sorts by the most recent update, displays 10 entries per page,
and supports filtering by title or ID. Use PageUp/PageDown or the page buttons,
then Enter to resume. Escape cancels without changing the current conversation.
The CLI flag `clanker --resume <session-id>` still resumes a known ID at startup.
The active session ID appears in the TUI's top status bar. When you exit a
conversation with messages, Clanker prints its ID and the
`clanker --resume <session-id>` command in the terminal. Run it from the same workspace.

Use `/import` for a guided import: choose the source, choose a local session,
review its title and message count, then select **Import**. It creates a new
Clanker session in the current workspace and opens it for your next message.
Only sessions from the current workspace with a user prompt appear in the picker;
setup records such as Codex's injected `AGENTS.md` instructions are excluded.
Existing Clanker and source sessions are left intact. Clanker imports user
prompts and assistant replies as text. Source tool calls, tool results,
reasoning, system instructions, and image bytes are not transferred. A source
session's tools or model settings are not carried into Clanker.

The wizard discovers local histories at `~/.codex/sessions/` (and
`archived_sessions/`), `~/.claude/projects/`,
`~/.local/share/opencode/opencode.db`, and
`~/.copilot/session-state/*/events.jsonl`. It honors `CODEX_HOME`,
`CLAUDE_CONFIG_DIR`, `XDG_DATA_HOME`, and `COPILOT_HOME` where applicable.
GitHub Copilot import covers the Copilot **CLI** history; editor chat history
uses different storage. The same flow is available with numbered pages in
`--no-tui` mode.

### Reloading a session

Use `/reload` to close and reopen Clanker in place without manually exiting and restarting. This is particularly useful when you update Clanker in another terminal window (via the installation script, binary update, or package manager) and want to start using the updated version immediately in your running session.

When you run `/reload`:
- Your current session snapshot is cleanly saved to disk.
- Clanker replaces the process image in the same terminal window and resumes the active session (`--resume <session-id>`).
- Current runtime flags are preserved:
  - Adheres to the current YOLO mode state (passing `--yolo` if YOLO mode is active or was enabled mid-session).
  - Retains the active model and any relevant startup flags (such as `--no-tui` or `--provider`).

If an agent or compaction operation is actively running, `/reload` is rejected until the turn completes or you interrupt it with Ctrl+C.

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Tab` | While typing a slash command (e.g. `/model `, `/workflow `, `/skill `, `/restore `), opens the completion menu and gives it keyboard control. Press `Tab` again to accept the highlighted match. |
| `↑` / `↓` | Navigate input history, or — once the completion menu has keyboard control (after pressing `Tab`) — move the highlight up/down within it. |
| `Alt+↑` / `Alt+↓` | Navigate input history even while the completion menu has keyboard control. |
| `Enter` | Submit the input, or — with the completion menu engaged — accept the highlighted match. |
| `Ctrl+C` | On macOS, always interrupt the agent. On other platforms, copy selected text if any; otherwise interrupt. |
| `Ctrl+D` | Quit Clanker. |
| `Cmd+V` (macOS) / `Ctrl+V` (other platforms) / terminal paste | Paste text or an image — see [Pasting](#pasting) below. |
| `F1` | Open the keyboard shortcut help popup. |
| `F2` | Open the **Subagents** panel — view past and in-flight subagent runs, their prompts, status, and tool call history for the session (see [Agents → Progress and history](agents.md#progress-and-history)). |
| `F3` | Open the **History** panel — the full conversation so far, independent of how much the chat log has trimmed from view (see [TUI Performance](configuration.md#tui-performance)) and populated even after `/restore`, when the restored turns aren't replayed into the chat log. |
| `F4` | Open **Changes**: review recorded file-tool edits and undo an edit or a turn with conflict checks. Also available as `/changes`. |
| `F5` / `Ctrl+↑` | Open the multiline Markdown composer. |
| `F6` | Open **Memories** to search, inspect, and manage stored memories. Also available as `/memories`. |
| `Esc` | Cancel an open menu or approval prompt. |

On every platform, completing a text selection automatically copies it to the
clipboard. Drag to select, release, then paste—no copy shortcut or extra mode
is required. A brief, themed toast confirms **Copied N characters**.
Input and composer selections also copy automatically, including
keyboard selections; password inputs are excluded. Mouse controls remain available.

On macOS, standard editing actions use Command instead of Ctrl when the
terminal forwards the shortcuts. Copy-on-selection works with iTerm2's default
settings even when it intercepts Cmd+C, and Ctrl+C always interrupts.

| Key | Action |
|-----|--------|
| `Cmd+C` | Explicitly copy selected text if the terminal forwards the key. Selections also copy automatically, so iTerm2 can retain its default shortcut. Never interrupts the agent. |
| `Cmd+X` / `Cmd+V` | Cut / paste in the focused input or composer, using the existing text and image paste handling. |
| `Cmd+A` | Select all text in the focused input or composer. |
| `Cmd+Z` / `Cmd+Shift+Z` | Undo / redo in the multiline composer. |
| `Cmd+Enter` | Send from the multiline composer (`Ctrl+Enter` on other platforms). |

Terminals may handle `Cmd+C` and `Cmd+V` themselves rather than forwarding
the keys to Clanker. Terminal paste still delivers text through the normal
paste path. Other Command shortcuts require a terminal that forwards them
with extended keyboard support, or a terminal key mapping. On macOS, Ctrl
aliases for copy, cut, paste, select-all, undo, redo, and composer send are
disabled. `Ctrl+C` always interrupts, even with a selection. `Ctrl+D` still
quits, and Unix cursor movement/deletion shortcuts (such as `Ctrl+A` to move
to the start of the line), `Ctrl+↑`, and function keys keep their existing
behavior. Other platforms retain their Ctrl shortcuts.

Use `/tasks` as an alternative to F2. Task history stays available for the entire
session. The task panel supports follow-up messages and stopping an individual
task; Ctrl+C stops the parent and its managed tasks (on other platforms,
clear any selection first).

Interrupts cancel a pending model or async tool request immediately and stop
the current turn's owned shell process trees, including promoted/background
commands. Unfinished tool calls receive interrupted results in the checkpoint,
so your next message can continue in the same session without rerunning them.
Background jobs from earlier completed turns are retained. Blocking Python
tools stop cooperatively: their awaits are cancelled, and Clanker's file tools
reject further writes from the stopped turn.

Screen text selection is temporarily disabled while response text is being
revealed. The typewriter animation continues normally; selection becomes
available automatically after all active reveals finish. Then drag to select
text: it copies automatically when you release the mouse on every platform.

Models that provide marked reasoning show it in separate Thinking cards,
including Claude models through Copilot. These cards and any assistant preamble
appear before the corresponding tool call. Opaque signatures and encrypted
data are never displayed.

### Reviewing changes

F4 lists each recorded edit with its file, turn and author. Select an edit to
view its diff. Press `u` to undo that edit or `t` to undo its turn, then repeat
the control to confirm. Undo is disabled while an agent is working and refuses
to overwrite a file that no longer matches the recorded version. Older edits
must be undone after newer edits to the same file. Pre-existing changes are
preserved; undo does not reset Git's index.

The journal covers `write_file`, `append_file`, and `edit_file` in the current
TUI session, including managed subagent edits. Shell and MCP changes are not
journaled. Closing Clanker clears the in-memory journal; conversation restore
does not restore undo history. The agent is told which files you undo so it
can re-read them on its next turn.

Input history is persisted across sessions to `~/.clanker/input_history.json`
(last 500 entries, including pasted content and image attachments). Existing
`input_history.txt` entries are loaded when the JSON history does not exist.

### Pasting

The input field is single-line, so both multi-line text and images are
shown as a compact placeholder rather than dropped or garbled:

- **Multi-line text** collapses to `[pasted N lines]`. The real text is
  swapped back in when you submit — the placeholder is just what's shown in
  the field.
- **Images** — pasting an image (e.g. a screenshot) shows `[Image #N]`.
  Terminal paste can only ever carry text, so this works by checking the OS
  clipboard directly when a paste delivers nothing usable, via `osascript`
  on macOS or `xclip`/`wl-clipboard` on Linux (not installed by default on
  many distros — Clanker warns once per session if neither is found). The
  image is sent to the model alongside your message; Windows/WSL isn't
  supported. Pasting an image while the agent is mid-turn (i.e. it would be
  queued as a follow-up) isn't supported yet — the text is sent, with a
  warning that the image was left out.
- Both placeholders can hold **multiple** pastes in one message
  (`[pasted 3 lines] and [pasted 5 lines]`, `[Image #1]` and `[Image #2]`,
  or a mix) and expand back in order.
- **Backspace/Delete** removes a whole placeholder in one keystroke rather
  than eating into it character by character — including when the cursor
  has been moved into the middle of one.
- Input history (↑/↓ recall) keeps the placeholder form in the single-line
  field; opening the multiline composer restores the full pasted text.

### Sending Messages While the Agent Is Working

You can type and submit a follow-up message while the agent is still
processing a previous turn — it doesn't need to finish first. The message is
queued (shown above the input bar) and injected as soon as the agent reaches
its next step, rather than being dropped or requiring you to wait. Slash
commands are not queued this way; they still require the agent to be idle.

## Examples

### Reading and Understanding Code

```
❯ Read the main.py file and explain what it does
```

### Making Edits

```
❯ In src/utils.py, change the function name from 'getData' to 'fetch_data'
```

### Searching the Codebase

```
❯ Find all files that import the 'requests' library
```

### Running Commands

```
❯ Run the tests and show me any failures
```

## Command Approval

By default, all bash commands require approval before execution. When the AI wants to run a command, you'll see an arrow-key menu showing the command and three choices:

```
  Bash Command
  $ npm test

  Run this command?
  ↑/↓ to move · enter to select · esc cancels

  ❯ Yes, execute
    Yes, and don't ask again (this session)
    No, reject and stop
```

- **Yes, execute** — run this command.
- **Yes, and don't ask again (this session)** — run it and stop prompting for the rest of the session (equivalent to enabling yolo mode until you exit).
- **No, reject and stop** — reject the command. Use ↑/↓ to move, Enter to select, and Esc to cancel.

When stdin isn't an interactive terminal (piped input, one-shot `clanker "prompt"`, CI), the prompt falls back to a numbered list — type `1`, `2`, or `3`.

**Note:** Rejecting a command terminates the current AI response. This prevents the AI from trying alternative approaches after you've declined.

### Yolo Mode

If you trust the AI's commands and want to skip approval prompts entirely from the start, launch Clanker with the `--yolo` flag:

```bash
clanker --yolo
```

In yolo mode, all bash commands execute automatically without asking for approval. A warning indicator will appear in the welcome message to remind you that this mode is active. (Choosing "Yes, and don't ask again" at an approval prompt turns this on mid-session.)

## Checking for Updates

Clanker can check for new releases on GitHub:

```bash
# Manual check
clanker --check-update
```

On startup, Clanker automatically checks for updates and shows a notification if a new version is available:

```
[Update Available]
v0.1.0 -> v0.2.0
Run: curl -fsSL https://raw.githubusercontent.com/Nightmare99/clanker/main/scripts/install.sh | bash
```

To update, run the install script - it will detect the existing installation and prompt before upgrading.
