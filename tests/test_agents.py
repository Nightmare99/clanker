"""Unit tests for the agents module and load_agent tool."""

from pathlib import Path
from unittest.mock import patch

import pytest

from clanker.agents import (
    _load_agent_from_file,
    get_agents_catalog,
    list_agents,
    load_agent,
    parse_agent_md,
)
from clanker.tools.agent_tools import load_agent as load_agent_tool


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    """Point HOME at an empty dir so a real ~/.clanker/agents never leaks in."""
    monkeypatch.setenv("HOME", str(tmp_path / "isolated-home"))


class TestParseAgentMd:
    def test_valid_agent_file(self, tmp_path: Path) -> None:
        content = """---
name: reviewer
description: Reviews code quality.
tools: [read_file, grep_search]
---
You are a code reviewer.
"""
        file_path = tmp_path / "reviewer.md"
        file_path.write_text(content)

        result = parse_agent_md(file_path)
        assert result is not None
        meta, body = result
        assert meta["name"] == "reviewer"
        assert meta["description"] == "Reviews code quality."
        assert meta["tools"] == ["read_file", "grep_search"]
        assert body == "You are a code reviewer."

    def test_no_frontmatter(self, tmp_path: Path) -> None:
        file_path = tmp_path / "bad.md"
        file_path.write_text("Just plain text")
        assert parse_agent_md(file_path) is None

    def test_unterminated_frontmatter(self, tmp_path: Path) -> None:
        file_path = tmp_path / "bad.md"
        file_path.write_text("---\nname: test\n")
        assert parse_agent_md(file_path) is None

    def test_malformed_yaml(self, tmp_path: Path) -> None:
        file_path = tmp_path / "bad.md"
        file_path.write_text("---\nname: [invalid\n---\nbody")
        assert parse_agent_md(file_path) is None


class TestLoadAgentFromFile:
    def test_valid_agent(self, tmp_path: Path) -> None:
        content = """---
name: tester
description: Runs tests.
---
You are a test runner.
"""
        file_path = tmp_path / "tester.md"
        file_path.write_text(content)

        agent = _load_agent_from_file(file_path, "project")
        assert agent is not None
        assert agent.name == "tester"
        assert agent.description == "Runs tests."
        assert agent.system_prompt == "You are a test runner."
        assert agent.tools == []
        assert agent.model is None
        assert agent.source == "project"

    def test_valid_agent_with_model(self, tmp_path: Path) -> None:
        content = """---
name: reviewer
description: Reviews code.
model: claude-sonnet
tools: [read_file]
---
You are a code reviewer.
"""
        file_path = tmp_path / "reviewer.md"
        file_path.write_text(content)

        agent = _load_agent_from_file(file_path, "project")
        assert agent is not None
        assert agent.name == "reviewer"
        assert agent.model == "claude-sonnet"
        assert agent.tools == ["read_file"]

    def test_agent_with_empty_model(self, tmp_path: Path) -> None:
        content = """---
name: agent
description: Has empty model.
model: ""
---
System prompt.
"""
        file_path = tmp_path / "agent.md"
        file_path.write_text(content)

        agent = _load_agent_from_file(file_path, "project")
        assert agent is not None
        assert agent.model is None

    def test_agent_with_invalid_model_type(self, tmp_path: Path) -> None:
        content = """---
name: agent
description: Has invalid model.
model: 123
---
System prompt.
"""
        file_path = tmp_path / "agent.md"
        file_path.write_text(content)

        agent = _load_agent_from_file(file_path, "project")
        assert agent is not None
        assert agent.model is None

    def test_missing_description(self, tmp_path: Path) -> None:
        content = """---
name: incomplete
---
Some body.
"""
        file_path = tmp_path / "incomplete.md"
        file_path.write_text(content)

        agent = _load_agent_from_file(file_path, "project")
        assert agent is None

    def test_empty_body(self, tmp_path: Path) -> None:
        content = """---
name: empty
description: Has no body.
---
"""
        file_path = tmp_path / "empty.md"
        file_path.write_text(content)

        agent = _load_agent_from_file(file_path, "project")
        assert agent is None

    def test_non_md_file(self, tmp_path: Path) -> None:
        file_path = tmp_path / "agent.txt"
        file_path.write_text("not markdown")
        # _load_agent_from_file doesn't check extension, but list_agents does
        agent = _load_agent_from_file(file_path, "project")
        # Will be None because no frontmatter
        assert agent is None


class TestListAgents:
    def test_discover_project_agents(self, tmp_path: Path) -> None:
        agents_dir = tmp_path / ".clanker" / "agents"
        agents_dir.mkdir(parents=True)

        (agents_dir / "reviewer.md").write_text(
            "---\nname: reviewer\ndescription: Reviews code.\n---\nYou review code."
        )
        (agents_dir / "tester.md").write_text(
            "---\nname: tester\ndescription: Runs tests.\n---\nYou run tests."
        )

        with patch("clanker.agents.Path.cwd", return_value=tmp_path):
            agents = list_agents(str(tmp_path))

        assert len(agents) == 2
        assert "reviewer" in agents
        assert "tester" in agents
        assert agents["reviewer"].source == "project"

    def test_project_overrides_personal(self, tmp_path: Path) -> None:
        project_dir = tmp_path / ".clanker" / "agents"
        project_dir.mkdir(parents=True)
        (project_dir / "reviewer.md").write_text(
            "---\nname: reviewer\ndescription: Project reviewer.\n---\nProject prompt."
        )

        personal_dir = tmp_path / "home" / ".clanker" / "agents"
        personal_dir.mkdir(parents=True)
        (personal_dir / "reviewer.md").write_text(
            "---\nname: reviewer\ndescription: Personal reviewer.\n---\nPersonal prompt."
        )

        with patch("clanker.agents.Path.home", return_value=tmp_path / "home"):
            agents = list_agents(str(tmp_path))

        assert len(agents) == 1
        assert agents["reviewer"].description == "Project reviewer."
        assert agents["reviewer"].source == "project"

    def test_ignores_non_md_files(self, tmp_path: Path) -> None:
        agents_dir = tmp_path / ".clanker" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "reviewer.md").write_text(
            "---\nname: reviewer\ndescription: Reviews.\n---\nPrompt."
        )
        (agents_dir / "readme.txt").write_text("not an agent")

        with patch("clanker.agents.Path.cwd", return_value=tmp_path):
            agents = list_agents(str(tmp_path))

        assert len(agents) == 1
        assert "reviewer" in agents


def _write_agent_file(root: Path, name: str, description: str, root_dir: str = ".clanker") -> None:
    agents_dir = root / root_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\nPrompt for {name}."
    )


class TestDotAgentsFallback:
    """`.agents/agents/` is an emerging cross-tool convention supported as a
    fallback -- `.clanker` always wins a name collision against it."""

    def test_project_agents_dir_picked_up_when_no_clanker_agent(self, tmp_path: Path) -> None:
        _write_agent_file(tmp_path, "gamma", "G.", root_dir=".agents")
        agents = list_agents(str(tmp_path))
        assert set(agents) == {"gamma"}
        assert agents["gamma"].source == "project (.agents)"

    def test_personal_agents_dir_picked_up(self, tmp_path: Path) -> None:
        home = tmp_path / "isolated-home"
        _write_agent_file(home, "delta", "D.", root_dir=".agents")
        agents = list_agents(str(tmp_path))
        assert set(agents) == {"delta"}
        assert agents["delta"].source == "personal (.agents)"

    def test_clanker_project_wins_over_agents_project(self, tmp_path: Path) -> None:
        _write_agent_file(tmp_path, "dup", "CLANKER version.")
        _write_agent_file(tmp_path, "dup", "AGENTS version.", root_dir=".agents")
        agents = list_agents(str(tmp_path))
        assert agents["dup"].source == "project"
        assert agents["dup"].description == "CLANKER version."

    def test_clanker_personal_wins_over_agents_project(self, tmp_path: Path) -> None:
        home = tmp_path / "isolated-home"
        _write_agent_file(home, "dup", "CLANKER personal.")
        _write_agent_file(tmp_path, "dup", "AGENTS project.", root_dir=".agents")
        agents = list_agents(str(tmp_path))
        assert agents["dup"].source == "personal"
        assert agents["dup"].description == "CLANKER personal."

    def test_agents_project_wins_over_agents_personal(self, tmp_path: Path) -> None:
        home = tmp_path / "isolated-home"
        _write_agent_file(tmp_path, "dup", "AGENTS project.", root_dir=".agents")
        _write_agent_file(home, "dup", "AGENTS personal.", root_dir=".agents")
        agents = list_agents(str(tmp_path))
        assert agents["dup"].source == "project (.agents)"
        assert agents["dup"].description == "AGENTS project."

    def test_merges_all_four_sources(self, tmp_path: Path) -> None:
        home = tmp_path / "isolated-home"
        _write_agent_file(tmp_path, "a", "x")
        _write_agent_file(home, "b", "x")
        _write_agent_file(tmp_path, "c", "x", root_dir=".agents")
        _write_agent_file(home, "d", "x", root_dir=".agents")
        agents = list_agents(str(tmp_path))
        assert set(agents) == {"a", "b", "c", "d"}


class TestLoadAgent:
    def test_load_by_name(self, tmp_path: Path) -> None:
        agents_dir = tmp_path / ".clanker" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: Does stuff.\n---\nSystem prompt."
        )

        agent = load_agent("my-agent", str(tmp_path))
        assert agent is not None
        assert agent.name == "my-agent"

    def test_load_case_insensitive(self, tmp_path: Path) -> None:
        agents_dir = tmp_path / ".clanker" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: Does stuff.\n---\nSystem prompt."
        )

        agent = load_agent("MY-AGENT", str(tmp_path))
        assert agent is not None

    def test_load_not_found(self, tmp_path: Path) -> None:
        agent = load_agent("nonexistent", str(tmp_path))
        assert agent is None


class TestAgentsCatalog:
    def test_catalog_format(self, tmp_path: Path) -> None:
        agents_dir = tmp_path / ".clanker" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "a.md").write_text(
            "---\nname: alpha\ndescription: First agent.\n---\nPrompt."
        )
        (agents_dir / "b.md").write_text(
            "---\nname: beta\ndescription: Second agent.\n---\nPrompt."
        )

        catalog = get_agents_catalog(str(tmp_path))
        assert "- alpha: First agent. (project)" in catalog
        assert "- beta: Second agent. (project)" in catalog

    def test_empty_catalog(self, tmp_path: Path) -> None:
        catalog = get_agents_catalog(str(tmp_path))
        assert catalog == ""


class TestLoadAgentTool:
    def test_load_agent_tool_success(self, tmp_path: Path) -> None:
        agents_dir = tmp_path / ".clanker" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "reviewer.md").write_text(
            "---\nname: reviewer\ndescription: Reviews code.\ntools: [read_file]\n---\nYou review code."
        )

        with patch("clanker.tools.agent_tools.os.getcwd", return_value=str(tmp_path)):
            result = load_agent_tool.invoke({"name": "reviewer"})

        assert result["ok"] is True
        assert result["name"] == "reviewer"
        assert result["system_prompt"] == "You review code."
        assert result["tools"] == ["read_file"]

    def test_load_agent_tool_not_found(self, tmp_path: Path) -> None:
        with patch("clanker.tools.agent_tools.os.getcwd", return_value=str(tmp_path)):
            result = load_agent_tool.invoke({"name": "nonexistent"})

        assert result["ok"] is False
        assert "error" in result
        assert "available" in result
