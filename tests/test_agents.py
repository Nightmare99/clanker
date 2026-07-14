"""Unit tests for the agents module and load_agent tool."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from clanker.agents import (
    Agent,
    list_agents,
    load_agent,
    get_agents_catalog,
    parse_agent_md,
    _load_agent_from_file,
)
from clanker.tools.agent_tools import load_agent as load_agent_tool


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
        assert agent.source == "project"

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
