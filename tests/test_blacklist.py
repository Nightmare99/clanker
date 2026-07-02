"""Tests for command blacklisting (system-wide + project-specific)."""

from __future__ import annotations

import pytest

from clanker.config.blacklist import get_effective_blacklist, load_project_blacklist
from clanker.tools import bash_tools
from clanker.tools.bash_tools import set_approval_callback
from clanker.utils.sandbox import is_command_safe


class TestIsCommandSafeBlacklist:
    """is_command_safe honours the extra_blacklist argument."""

    def test_substring_match_blocks(self) -> None:
        is_safe, reason = is_command_safe("git push origin main", ["git push"])
        assert not is_safe
        assert "blacklisted" in reason
        assert "git push" in reason

    def test_case_insensitive(self) -> None:
        is_safe, _ = is_command_safe("GIT PUSH origin main", ["git push"])
        assert not is_safe
        # Entry casing also does not matter.
        is_safe, _ = is_command_safe("git push origin main", ["GIT PUSH"])
        assert not is_safe

    def test_non_match_allowed(self) -> None:
        is_safe, reason = is_command_safe("git status", ["git push"])
        assert is_safe
        assert reason == ""

    def test_builtin_blocks_still_apply(self) -> None:
        # An empty blacklist must not weaken the built-in dangerous-command set.
        is_safe, _ = is_command_safe("rm -rf /", [])
        assert not is_safe

    def test_backward_compatible_no_extra(self) -> None:
        # Old signature (no second arg) behaves exactly as before.
        assert is_command_safe("ls -la")[0] is True
        assert is_command_safe("rm -rf /")[0] is False

    def test_none_and_empty_extra(self) -> None:
        assert is_command_safe("anything", None)[0] is True
        assert is_command_safe("anything", [])[0] is True

    def test_blank_entries_ignored(self) -> None:
        # Whitespace-only entries must not block every command.
        is_safe, _ = is_command_safe("ls -la", ["", "   "])
        assert is_safe

    def test_multiple_entries(self) -> None:
        extra = ["terraform apply", "npm publish"]
        assert is_command_safe("npm publish --access public", extra)[0] is False
        assert is_command_safe("terraform apply -auto-approve", extra)[0] is False
        assert is_command_safe("npm test", extra)[0] is True


class TestLoadProjectBlacklist:
    """load_project_blacklist reads .clanker/blacklist from the workspace."""

    def _write(self, tmp_path, content: str):
        d = tmp_path / ".clanker"
        d.mkdir(parents=True, exist_ok=True)
        (d / "blacklist").write_text(content, encoding="utf-8")

    def test_missing_file_returns_empty(self, tmp_path) -> None:
        assert load_project_blacklist(str(tmp_path)) == []

    def test_reads_lines(self, tmp_path) -> None:
        self._write(tmp_path, "git push\nnpm publish\n")
        assert load_project_blacklist(str(tmp_path)) == ["git push", "npm publish"]

    def test_skips_comments_and_blanks(self, tmp_path) -> None:
        self._write(
            tmp_path,
            "# project bans\n\ngit push\n   \n# another\nterraform apply\n",
        )
        assert load_project_blacklist(str(tmp_path)) == ["git push", "terraform apply"]

    def test_strips_whitespace(self, tmp_path) -> None:
        self._write(tmp_path, "  git push  \n\tnpm publish\t\n")
        assert load_project_blacklist(str(tmp_path)) == ["git push", "npm publish"]

    def test_defaults_to_cwd(self, tmp_path, monkeypatch) -> None:
        self._write(tmp_path, "curl\n")
        monkeypatch.chdir(tmp_path)
        assert load_project_blacklist() == ["curl"]


class TestGetEffectiveBlacklist:
    """get_effective_blacklist unions system + project, de-duplicated."""

    def _write(self, tmp_path, content: str):
        d = tmp_path / ".clanker"
        d.mkdir(parents=True, exist_ok=True)
        (d / "blacklist").write_text(content, encoding="utf-8")

    def _set_system(self, monkeypatch, entries):
        from clanker.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings.safety, "command_blacklist", list(entries))

    def test_system_only(self, tmp_path, monkeypatch) -> None:
        self._set_system(monkeypatch, ["curl"])
        assert get_effective_blacklist(str(tmp_path)) == ["curl"]

    def test_project_only(self, tmp_path, monkeypatch) -> None:
        self._set_system(monkeypatch, [])
        self._write(tmp_path, "npm publish\n")
        assert get_effective_blacklist(str(tmp_path)) == ["npm publish"]

    def test_union(self, tmp_path, monkeypatch) -> None:
        self._set_system(monkeypatch, ["curl"])
        self._write(tmp_path, "npm publish\n")
        result = get_effective_blacklist(str(tmp_path))
        assert result == ["curl", "npm publish"]

    def test_dedupe_case_insensitive(self, tmp_path, monkeypatch) -> None:
        self._set_system(monkeypatch, ["git push"])
        self._write(tmp_path, "GIT PUSH\nnpm publish\n")
        result = get_effective_blacklist(str(tmp_path))
        # "GIT PUSH" duplicates the system entry (case-insensitive) and is dropped.
        assert result == ["git push", "npm publish"]


class TestRunSafetyChecksBlacklist:
    """run_safety_checks enforces the effective blacklist behind sandbox_commands."""

    @pytest.fixture(autouse=True)
    def _reset(self, monkeypatch):
        from clanker import runtime

        runtime._yolo_mode = False
        set_approval_callback(None)
        yield
        runtime._yolo_mode = False
        set_approval_callback(None)

    def _configure(self, monkeypatch, *, sandbox: bool, system=None):
        from clanker.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings.safety, "sandbox_commands", sandbox)
        monkeypatch.setattr(settings.safety, "require_confirmation", False)
        monkeypatch.setattr(settings.safety, "command_blacklist", list(system or []))

    def test_blacklisted_command_blocked(self, tmp_path, monkeypatch) -> None:
        self._configure(monkeypatch, sandbox=True, system=["curl"])
        monkeypatch.chdir(tmp_path)
        result = bash_tools.run_safety_checks("curl https://example.com")
        assert result is not None
        assert "Command blocked" in result
        assert "blacklisted" in result

    def test_clean_command_passes(self, tmp_path, monkeypatch) -> None:
        self._configure(monkeypatch, sandbox=True, system=["curl"])
        monkeypatch.chdir(tmp_path)
        assert bash_tools.run_safety_checks("ls -la") is None

    def test_project_blacklist_enforced(self, tmp_path, monkeypatch) -> None:
        self._configure(monkeypatch, sandbox=True, system=[])
        d = tmp_path / ".clanker"
        d.mkdir(parents=True)
        (d / "blacklist").write_text("npm publish\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        assert bash_tools.run_safety_checks("npm publish") is not None
        assert bash_tools.run_safety_checks("npm test") is None

    def test_disabled_when_sandbox_off(self, tmp_path, monkeypatch) -> None:
        # With sandbox_commands off, the blacklist (and built-in blocks) are
        # not enforced -- the command flows past the block gate.
        self._configure(monkeypatch, sandbox=False, system=["curl"])
        monkeypatch.chdir(tmp_path)
        assert bash_tools.run_safety_checks("curl https://example.com") is None


def test_module_matching_alignment() -> None:
    """Sanity: get_effective_blacklist output feeds is_command_safe correctly."""
    extra = ["git push"]
    is_safe, reason = is_command_safe("git push --force", extra)
    assert not is_safe
    assert reason == "Command is blacklisted: git push"
