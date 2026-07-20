# Skills

Skills are model-discovered capabilities that extend what Clanker can do. Unlike
[workflows](workflows.md) (which you trigger manually with `/workflow`), the
agent discovers and loads skills **automatically** when a task matches one.

A skill packages instructions — and optionally scripts, templates, or data —
into a directory. Clanker uses **progressive disclosure**: only each skill's
name and description are always in context, so you can have many skills without
bloating the prompt. The full instructions are pulled in on demand.

## How it works

1. **Always-on catalog**: every skill's `name` and `description` are injected
   into the system prompt under an `AVAILABLE SKILLS` section.
2. **On-demand loading**: when your request matches a skill, the agent calls the
   `load_skill` tool to retrieve that skill's full `SKILL.md` instructions.
3. **Execution**: the instructions can reference bundled files. The agent reads
   them with `read_file` and runs bundled scripts with `execute_shell` — under
   the same confirmation and sandbox safety as any other command.

This is the same pattern used by Anthropic's Agent Skills: small descriptions
loaded always, full instructions loaded only when relevant.

## Locations

Skills are discovered from two places:

| Location | Scope | Use for |
|----------|-------|---------|
| `.clanker/skills/` | **Project** (committed to the repo) | Conventions and procedures specific to this codebase |
| `~/.clanker/skills/` | **Personal** (apply to every project) | Your own reusable skills across all projects |

If a project skill and a personal skill share the same name, the **project**
skill wins.

## Skill format

Each skill is a directory containing a `SKILL.md` file:

```
.clanker/skills/
  changelog/
    SKILL.md
  pdf-filler/
    SKILL.md
    fill.py
    template.json
```

`SKILL.md` has YAML frontmatter followed by a markdown body:

```markdown
---
name: pdf-filler
description: Fill PDF forms from a JSON data file. Use when the user wants to populate a PDF template with field values.
---

# PDF Filler

1. Read the field map at `template.json` in this skill's directory.
2. Run the filler:
   `python <skill_directory>/fill.py --data <input.json> --out <output.pdf>`
3. Confirm the output PDF was created and report the path.
```

### Frontmatter fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | No* | Canonical skill id. Defaults to the directory name if omitted. |
| `description` | **Yes** | What the skill does **and when to use it**. This is the trigger signal the agent matches against — be specific. |

\* `name` is optional but recommended; without it the folder name is used.

### Body

The body is free-form markdown — typically a numbered procedure. Reference
bundled files by name; the agent receives the skill's absolute directory path
when it loads the skill, so it can locate them.

## Writing a good description

The `description` is the only part of a skill the agent sees until it decides to
load it, so it determines whether the skill gets used at all. Include **what it
does** and **when to use it**:

- Good: `Generate release notes from git history. Use when the user asks to cut a release, tag a version, or write a changelog.`
- Weak: `Release helper.`

## Bundled files (scripts and resources)

A skill can ship runnable scripts and data alongside `SKILL.md`. The agent:

- **reads** resources (templates, configs, data) with `read_file`
- **runs** scripts with `execute_shell` (subject to the usual approval prompt
  unless `--yolo` is set)

There is no separate execution environment — bundled scripts run exactly like
any command the agent would otherwise run, so the normal safety model applies.

## Using skills

### Automatic (the normal case)

Just make a request. If it matches a skill's description, the agent loads the
skill and follows it:

```
❯ Fill out the onboarding PDF for the new hire from this JSON
  > load_skill: pdf-filler
  > read_file: template.json
  > execute_shell: python .../fill.py --data new_hire.json --out onboarding.pdf
```

### Manual

List and load skills yourself with the `/skill` command:

```
❯ /skill
Available skills (2):

  changelog (project) - Generate release notes from git history...
  pdf-filler (personal) - Fill PDF forms from a JSON data file...

The agent loads skills automatically. Use /skill <name> to load one manually.

❯ /skill changelog
Loaded skill 'changelog' from /path/to/.clanker/skills/changelog
```

`/skill` supports tab completion for skill names.

## Skills vs. workflows vs. agents

| | Workflows | Skills | Agents |
|---|-----------|--------|--------|
| **Triggered by** | You, via `/workflow <name>` | The agent, automatically | The agent, automatically |
| **Format** | A single `.md` file | A directory with `SKILL.md` + files | A single `.md` file with frontmatter |
| **Execution** | Prompt injected into main agent | Main agent follows instructions | Independent subagent with own prompt |
| **In context** | Whole file injected | Only name + description, until loaded | Only name + description, until spawned |
| **Output** | Main agent responds | Main agent responds | Subagent streams live, parent gets summary |
| **Best for** | Repeatable prompts you invoke | Procedures the agent follows | Delegating subtasks to a specialist |

Use a **workflow** when you want a canned prompt you fire deliberately. Use a
**skill** when you want the agent to recognize a situation and apply a procedure
on its own. Use an **[agent](agents.md)** when you want to delegate a subtask to
an independent specialist with its own system prompt.

## Mode support

Skills are available to the model across all configured providers — the
`load_skill` tool is always registered.
