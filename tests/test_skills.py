"""Tests for Agent Skills discovery, loading, and the load_skill tool."""

from __future__ import annotations

import pytest

from clanker import skills


def _write_skill(
    root, name, *, frontmatter=None, body="Do the thing.", source="project", filename="SKILL.md"
):
    """Create a skill directory under the given workspace root.

    Args:
        root: workspace root (Path); project skills go under .clanker/skills,
              personal would be created directly by the caller under home.
        name: skill directory name.
        frontmatter: dict of frontmatter, or a raw string for malformed cases,
                     or None to omit frontmatter entirely.
    """
    base = root / ".clanker" / "skills"
    skill_dir = base / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    if frontmatter is None:
        content = body
    elif isinstance(frontmatter, str):
        content = f"---\n{frontmatter}\n---\n\n{body}"
    else:
        fm = "\n".join(f"{k}: {v}" for k, v in frontmatter.items())
        content = f"---\n{fm}\n---\n\n{body}"
    (skill_dir / filename).write_text(content, encoding="utf-8")
    return skill_dir


class TestParseSkillMd:
    def test_valid_frontmatter(self, tmp_path) -> None:
        d = _write_skill(tmp_path, "demo", frontmatter={"name": "demo", "description": "A demo."})
        parsed = skills.parse_skill_md(d / "SKILL.md")
        assert parsed is not None
        meta, body = parsed
        assert meta["name"] == "demo"
        assert meta["description"] == "A demo."
        assert body == "Do the thing."

    def test_body_starting_with_dash_preserved(self, tmp_path) -> None:
        # Regression: body that starts with '-' must not be eaten by the parser.
        d = _write_skill(
            tmp_path,
            "demo",
            frontmatter={"name": "demo", "description": "x"},
            body="- first bullet\n- second bullet",
        )
        _meta, body = skills.parse_skill_md(d / "SKILL.md")
        assert body == "- first bullet\n- second bullet"

    def test_no_frontmatter_returns_none(self, tmp_path) -> None:
        d = _write_skill(tmp_path, "demo", frontmatter=None, body="just text, no frontmatter")
        assert skills.parse_skill_md(d / "SKILL.md") is None

    def test_unterminated_frontmatter_returns_none(self, tmp_path) -> None:
        skill_dir = tmp_path / ".clanker" / "skills" / "demo"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\nname: demo\ndescription: x\n(no close)")
        assert skills.parse_skill_md(skill_dir / "SKILL.md") is None

    def test_malformed_yaml_returns_none(self, tmp_path) -> None:
        d = _write_skill(tmp_path, "demo", frontmatter="name: [unclosed")
        assert skills.parse_skill_md(d / "SKILL.md") is None

    def test_non_mapping_frontmatter_returns_none(self, tmp_path) -> None:
        d = _write_skill(tmp_path, "demo", frontmatter="- just\n- a\n- list")
        assert skills.parse_skill_md(d / "SKILL.md") is None


class TestListSkills:
    def test_empty_when_no_dirs(self, tmp_path, monkeypatch) -> None:
        # Point HOME at an empty dir so personal skills don't leak in.
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        assert skills.list_skills(str(tmp_path)) == {}

    def test_project_only(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        _write_skill(tmp_path, "alpha", frontmatter={"name": "alpha", "description": "A."})
        result = skills.list_skills(str(tmp_path))
        assert set(result) == {"alpha"}
        assert result["alpha"].source == "project"

    def test_personal_only(self, tmp_path, monkeypatch) -> None:
        home = tmp_path / "home"
        monkeypatch.setenv("HOME", str(home))
        _write_skill(
            home, "beta", frontmatter={"name": "beta", "description": "B."}, source="personal"
        )
        result = skills.list_skills(str(tmp_path))
        assert set(result) == {"beta"}
        assert result["beta"].source == "personal"

    def test_merge_project_and_personal(self, tmp_path, monkeypatch) -> None:
        home = tmp_path / "home"
        monkeypatch.setenv("HOME", str(home))
        _write_skill(tmp_path, "alpha", frontmatter={"name": "alpha", "description": "A."})
        _write_skill(
            home, "beta", frontmatter={"name": "beta", "description": "B."}, source="personal"
        )
        result = skills.list_skills(str(tmp_path))
        assert set(result) == {"alpha", "beta"}

    def test_project_wins_collision(self, tmp_path, monkeypatch) -> None:
        home = tmp_path / "home"
        monkeypatch.setenv("HOME", str(home))
        _write_skill(
            tmp_path, "dup", frontmatter={"name": "dup", "description": "PROJECT version."}
        )
        _write_skill(
            home,
            "dup",
            frontmatter={"name": "dup", "description": "PERSONAL version."},
            source="personal",
        )
        result = skills.list_skills(str(tmp_path))
        assert result["dup"].source == "project"
        assert "PROJECT" in result["dup"].description

    def test_sorted_alphabetically(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        for n in ["zebra", "apple", "mango"]:
            _write_skill(tmp_path, n, frontmatter={"name": n, "description": "x"})
        assert list(skills.list_skills(str(tmp_path))) == ["apple", "mango", "zebra"]

    def test_dir_without_skill_md_ignored(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / ".clanker" / "skills" / "notaskill").mkdir(parents=True)
        _write_skill(tmp_path, "real", frontmatter={"name": "real", "description": "x"})
        assert set(skills.list_skills(str(tmp_path))) == {"real"}

    def test_skill_missing_description_skipped(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        _write_skill(tmp_path, "nodesc", frontmatter={"name": "nodesc"})
        assert skills.list_skills(str(tmp_path)) == {}

    def test_name_falls_back_to_dir_name(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        _write_skill(tmp_path, "fromdir", frontmatter={"description": "no name field"})
        result = skills.list_skills(str(tmp_path))
        assert "fromdir" in result


class TestLoadSkill:
    def test_found(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        _write_skill(
            tmp_path, "demo", frontmatter={"name": "demo", "description": "x"}, body="Run it."
        )
        skill = skills.load_skill("demo", str(tmp_path))
        assert skill is not None
        assert skill.body == "Run it."
        assert skill.directory.name == "demo"
        assert skill.directory.is_absolute()

    def test_case_insensitive(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        _write_skill(tmp_path, "demo", frontmatter={"name": "demo", "description": "x"})
        assert skills.load_skill("DEMO", str(tmp_path)) is not None

    def test_missing_returns_none(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        assert skills.load_skill("ghost", str(tmp_path)) is None


class TestCatalog:
    def test_empty_when_none(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        assert skills.get_skills_catalog(str(tmp_path)) == ""

    def test_format(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        _write_skill(tmp_path, "demo", frontmatter={"name": "demo", "description": "Does a thing."})
        cat = skills.get_skills_catalog(str(tmp_path))
        assert "demo" in cat
        assert "Does a thing." in cat
        assert "(project)" in cat

    def test_description_truncated(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        long_desc = "A" * (skills.MAX_DESC_CHARS + 200)
        _write_skill(tmp_path, "demo", frontmatter={"name": "demo", "description": long_desc})
        cat = skills.get_skills_catalog(str(tmp_path))
        assert "..." in cat
        assert len(cat) < len(long_desc) + 100


def _langchain_available() -> bool:
    try:
        import langchain_core  # noqa: F401

        return True
    except ImportError:
        return False


@pytest.mark.skipif(not _langchain_available(), reason="langchain not installed")
class TestLoadSkillTool:
    def test_found_returns_instructions(self, tmp_path, monkeypatch) -> None:
        from clanker.tools.skill_tools import load_skill as load_skill_tool

        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.chdir(tmp_path)
        _write_skill(
            tmp_path, "demo", frontmatter={"name": "demo", "description": "x"}, body="Step 1."
        )
        out = load_skill_tool.invoke({"name": "demo"})
        assert out["ok"] is True
        assert out["name"] == "demo"
        assert "Step 1." in out["instructions"]
        assert out["skill_directory"].endswith("demo")
        assert "note" in out

    def test_missing_returns_error_and_available(self, tmp_path, monkeypatch) -> None:
        from clanker.tools.skill_tools import load_skill as load_skill_tool

        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.chdir(tmp_path)
        _write_skill(tmp_path, "real", frontmatter={"name": "real", "description": "x"})
        out = load_skill_tool.invoke({"name": "ghost"})
        assert out["ok"] is False
        assert "ghost" in out["error"]
        assert out["available"] == ["real"]

    def test_registered_in_tool_registry(self) -> None:
        from clanker.tools import get_tools

        assert "load_skill" in [t.name for t in get_tools()]

    def test_body_truncated_to_max(self, tmp_path, monkeypatch) -> None:
        from clanker.tools.skill_tools import load_skill as load_skill_tool

        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.chdir(tmp_path)
        big = "X" * (skills.MAX_SKILL_BODY_CHARS + 5000)
        _write_skill(tmp_path, "big", frontmatter={"name": "big", "description": "x"}, body=big)
        out = load_skill_tool.invoke({"name": "big"})
        assert len(out["instructions"]) <= skills.MAX_SKILL_BODY_CHARS + 100
        assert "truncated" in out["instructions"]
