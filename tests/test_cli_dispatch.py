"""Tests for ClankerGroup's custom subcommand dispatch.

`main` has a group-level positional `prompt` argument that greedily consumes
the first token, so when that token happens to match a real subcommand name
(e.g. "config", "copilot-login"), `ClankerGroup.invoke` special-cases it and
dispatches to that subcommand instead of treating it as a prompt. This
previously used `ctx.invoke(cmd)`, which skips the subcommand's own argument
parsing entirely -- so flags like `--help` were silently dropped and the
subcommand body ran for real instead of printing usage and exiting. These
tests guard against that regression.
"""

from __future__ import annotations

from click.testing import CliRunner

from clanker.cli import main


def _runner() -> CliRunner:
    return CliRunner()


class TestSubcommandHelpDispatch:
    """`clanker <subcommand> --help` must print usage and exit, never run the command."""

    def test_config_help_prints_usage_and_exits_cleanly(self) -> None:
        result = _runner().invoke(main, ["config", "--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output
        assert "config" in result.output

    def test_copilot_login_help_prints_usage_and_exits_cleanly(self) -> None:
        result = _runner().invoke(main, ["copilot-login", "--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output
        assert "GitHub Copilot" in result.output

    def test_top_level_help_lists_both_subcommands(self) -> None:
        result = _runner().invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "config" in result.output
        assert "copilot-login" in result.output


class TestSubcommandArgParsing:
    """Flags passed to a dispatched subcommand must actually be parsed, not dropped."""

    def test_config_flags_are_parsed_and_passed_through(self, monkeypatch) -> None:
        import clanker.config.web

        captured = {}

        def fake_run_config_server(port, open_browser):
            captured["port"] = port
            captured["open_browser"] = open_browser

        monkeypatch.setattr(clanker.config.web, "run_config_server", fake_run_config_server)

        result = _runner().invoke(main, ["config", "--port", "9999", "--no-browser"])
        assert result.exit_code == 0
        assert captured == {"port": 9999, "open_browser": False}


class TestPromptVsSubcommandDisambiguation:
    """A genuine prompt string must still route as a prompt, not misfire as a subcommand."""

    def test_freeform_prompt_routes_to_run_single_prompt(self, monkeypatch) -> None:
        import clanker.cli as cli_mod

        captured = {}

        def fake_run_single_prompt(prompt, console, settings):
            captured["prompt"] = prompt

        monkeypatch.setattr(cli_mod, "run_single_prompt", fake_run_single_prompt)

        result = _runner().invoke(main, ["explain this code"])
        assert result.exit_code == 0
        assert captured.get("prompt") == "explain this code"

    def test_version_flag_still_works(self) -> None:
        # Exercises the invoke_without_command=True bare-group path, which
        # does not go through ClankerGroup.invoke's subcommand branch at all.
        result = _runner().invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "Clanker v" in result.output
