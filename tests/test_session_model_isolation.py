"""Tests verifying session-level model pinning and isolation across sessions, subagents, and CLI workflows.

Ensures model choices persist in session snapshots/metadata, and external model
configuration changes (e.g. models.json default changes) do not bleed into active sessions.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner
from langchain_core.messages import HumanMessage

from clanker.cli import handle_command, main, run_single_prompt
from clanker.config.models import (
    ModelConfig,
    ModelsConfig,
    get_default_model,
    save_models_config,
    set_default_model,
)
from clanker.config.settings import Settings
from clanker.memory.checkpointer import SessionManager
from clanker.tools.subagent import spawn_subagent
from clanker.ui.console import Console
from clanker.ui.streaming import StreamResult


@pytest.fixture
def isolated_models(tmp_path, monkeypatch):
    """Provide an isolated models.json configuration for tests."""
    import clanker.config.models as models_mod

    config_path = tmp_path / "models.json"
    monkeypatch.setattr(models_mod, "MODELS_CONFIG_PATH", config_path)

    initial_config = ModelsConfig(
        default="model-alpha",
        models=[
            ModelConfig(name="model-alpha", provider="OpenAI", model="gpt-4o"),
            ModelConfig(name="model-beta", provider="Anthropic", model="claude-3-5-sonnet"),
            ModelConfig(name="model-gamma", provider="OpenAI", model="gpt-4o-mini"),
        ],
    )
    save_models_config(initial_config)
    return models_mod


class TestSessionManagerModelIsolation:
    """Test model pinning directly on SessionManager."""

    def test_pinned_model_isolated_from_external_default_changes(
        self, tmp_path, isolated_models
    ) -> None:
        """Active session retains its pinned model when global default changes."""
        session = SessionManager(workspace_path=str(tmp_path), model_name="model-alpha")

        assert session.model_name == "model-alpha"

        # External change to models.json default
        set_default_model("model-beta")
        assert get_default_model().name == "model-beta"

        # Active session must remain pinned to model-alpha
        assert session.model_name == "model-alpha"

    def test_metadata_and_snapshot_persistence(
        self, tmp_path, isolated_models
    ) -> None:
        """Session metadata, snapshots, and listings persist the pinned model."""
        session = SessionManager(workspace_path=str(tmp_path), model_name="model-alpha")

        # Save conversation snapshot which writes both snapshot.json and metadata.json
        session.save_conversation_snapshot([HumanMessage(content="Hello")])

        # 1. Metadata JSON on disk contains "model"
        meta_path = session._storage.conversations_dir / f"{session.session_id}.meta.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta.get("model") == "model-alpha"

        # 2. Snapshot JSON contains "model"
        snapshot_path = session._storage.conversations_dir / f"{session.session_id}.json"
        assert snapshot_path.exists()
        snapshot = json.loads(snapshot_path.read_text())
        assert snapshot.get("model") == "model-alpha"

        # 3. list_sessions contains "model"
        sessions = session.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["model"] == "model-alpha"

        # 4. Modifying model_name updates metadata
        session.model_name = "model-gamma"
        meta_updated = json.loads(meta_path.read_text())
        assert meta_updated.get("model") == "model-gamma"

    def test_resume_session_restores_pinned_model(
        self, tmp_path, isolated_models
    ) -> None:
        """Resuming a session restores its pinned model without changing global default."""
        session1 = SessionManager(workspace_path=str(tmp_path), model_name="model-alpha")
        session1.save_conversation_snapshot([HumanMessage(content="First session")])
        s1_id = session1.session_id

        # Switch global default to model-beta
        set_default_model("model-beta")
        assert get_default_model().name == "model-beta"

        # A new session created without explicit model gets default (model-beta)
        session2 = SessionManager(workspace_path=str(tmp_path))
        assert session2.model_name == "model-beta"

        # Resume session1 into session2
        session2.resume_session(s1_id)
        assert session2.model_name == "model-alpha"

        # Global default must remain unchanged
        assert get_default_model().name == "model-beta"


class TestSubagentModelInheritance:
    """Test model inheritance and isolation for subagents."""

    @pytest.mark.asyncio
    async def test_subagent_inherits_session_pinned_model(
        self, isolated_models
    ) -> None:
        """Subagents without an explicit model inherit the parent session's pinned model."""
        mock_result = StreamResult(response="Done", input_tokens=10, output_tokens=5)

        mock_agent = MagicMock()
        mock_agent.name = "reviewer"
        mock_agent.system_prompt = "Review code"
        mock_agent.tools = []
        mock_agent.model = None  # No model configured on agent

        mock_session = MagicMock()
        mock_session.model_name = "model-alpha"

        mock_app = MagicMock()
        mock_app._session_manager = mock_session

        mock_console = MagicMock()
        mock_console._textual_app = mock_app

        with patch("clanker.tools.subagent.load_agent_config", return_value=mock_agent), \
             patch("clanker.ui.streaming.get_active_console", return_value=mock_console), \
             patch("clanker.ui.streaming.stream_agent_response_async", new_callable=AsyncMock, return_value=mock_result) as mock_stream:

            # Change global default model to model-gamma externally
            set_default_model("model-gamma")

            res = await spawn_subagent.ainvoke(
                {"agent_name": "reviewer", "prompt": "Review this PR"}
            )

            assert res["success"] is True
            # Subagent must use parent session's model ("model-alpha"), NOT the global default ("model-gamma")
            assert mock_stream.call_args[1]["model_name"] == "model-alpha"

    @pytest.mark.asyncio
    async def test_subagent_explicit_model_overrides_session(
        self, isolated_models
    ) -> None:
        """Explicit agent config model takes precedence over session's pinned model."""
        mock_result = StreamResult(response="Done", input_tokens=10, output_tokens=5)

        mock_agent = MagicMock()
        mock_agent.name = "specialist"
        mock_agent.system_prompt = "Specialized task"
        mock_agent.tools = []
        mock_agent.model = "model-beta"  # Explicitly configured model

        mock_session = MagicMock()
        mock_session.model_name = "model-alpha"

        mock_app = MagicMock()
        mock_app._session_manager = mock_session

        mock_console = MagicMock()
        mock_console._textual_app = mock_app

        with patch("clanker.tools.subagent.load_agent_config", return_value=mock_agent), \
             patch("clanker.ui.streaming.get_active_console", return_value=mock_console), \
             patch("clanker.ui.streaming.stream_agent_response_async", new_callable=AsyncMock, return_value=mock_result) as mock_stream:

            res = await spawn_subagent.ainvoke(
                {"agent_name": "specialist", "prompt": "Do specialist task"}
            )

            assert res["success"] is True
            assert mock_stream.call_args[1]["model_name"] == "model-beta"


class TestCLIAndSlashCommandModelIsolation:
    """Test CLI commands and slash command interactions."""

    def test_slash_model_updates_both_global_and_session(
        self, tmp_path, isolated_models
    ) -> None:
        """Running /model updates the active session and sets the default for future sessions."""
        session = SessionManager(workspace_path=str(tmp_path), model_name="model-alpha")
        console = MagicMock(spec=Console)

        assert session.model_name == "model-alpha"
        assert get_default_model().name == "model-alpha"

        # Switch model via /model
        handle_command("/model model-beta", console, session, [])

        # Both the active session and global default are updated
        assert session.model_name == "model-beta"
        assert get_default_model().name == "model-beta"

    def test_run_single_prompt_pins_and_forwards_model(
        self, isolated_models
    ) -> None:
        """run_single_prompt creates the pinned model and passes it to streaming."""
        console = MagicMock(spec=Console)
        settings = Settings()

        mock_result = StreamResult(response="Answer", input_tokens=10, output_tokens=5)

        with patch("clanker.cli.create_model") as mock_create, \
             patch("clanker.cli.stream_agent_response_sync", return_value=mock_result) as mock_stream:

            run_single_prompt(
                prompt="test prompt",
                console=console,
                settings=settings,
                initial_model="model-beta",
            )

            # create_model and stream_agent_response_sync must both receive model_beta
            assert mock_create.call_args[1]["model_name"] == "model-beta"
            assert mock_stream.call_args[1]["model_name"] == "model-beta"

    def test_cli_main_model_flag_preserves_global_default(
        self, isolated_models, monkeypatch
    ) -> None:
        """Passing --model via CLI sets initial_model without changing models.json default."""
        captured = {}

        def fake_run_single_prompt(prompt, console, settings, initial_model=None):
            captured["prompt"] = prompt
            captured["initial_model"] = initial_model

        monkeypatch.setattr("clanker.cli.run_single_prompt", fake_run_single_prompt)

        runner = CliRunner()
        result = runner.invoke(main, ["-m", "model-beta", "explain this"])
        assert result.exit_code == 0
        assert captured["initial_model"] == "model-beta"

        # Global default in models.json must remain model-alpha
        assert get_default_model().name == "model-alpha"

    def test_cli_main_resume_with_model_override(
        self, isolated_models, monkeypatch
    ) -> None:
        """Resuming a session with --model passes the model override to interactive mode."""
        captured = {}

        def fake_run_interactive(console, settings, resume_session=None, initial_model=None):
            captured["resume_session"] = resume_session
            captured["initial_model"] = initial_model

        monkeypatch.setattr("clanker.cli.run_interactive", fake_run_interactive)

        runner = CliRunner()
        result = runner.invoke(main, ["--resume", "session-xyz", "--model", "model-gamma"])
        assert result.exit_code == 0
        assert captured["resume_session"] == "session-xyz"
        assert captured["initial_model"] == "model-gamma"

    @pytest.mark.asyncio
    async def test_tui_app_run_agent_uses_session_pinned_model(
        self, isolated_models
    ) -> None:
        """ClankerApp._run_agent passes session_manager.model_name to streaming agent."""
        from clanker.ui.app import ClankerApp
        from clanker.ui.token_tracking import SessionTokenTracker

        app = ClankerApp.__new__(ClankerApp)
        app.clanker_console = MagicMock()
        mock_session = MagicMock()
        mock_session.model_name = "model-beta"
        mock_session.checkpointer = MagicMock()
        mock_session.get_config.return_value = {"configurable": {"thread_id": "test"}}
        app._session_manager = mock_session
        app._settings = Settings()
        app._conversation_messages = []
        app._pending_restore_messages = []
        app._token_tracker = SessionTokenTracker(model_name="model-beta")
        app._working_dir = "/tmp"
        app._input_queue = AsyncMock()
        app._change_journal = MagicMock()
        app._subagent_runs = []
        app.get_chat_log = MagicMock(return_value=MagicMock())
        app.get_status_bar = MagicMock(return_value=MagicMock())
        app.get_prompt_input = MagicMock(return_value=MagicMock())
        app.get_message_queue = MagicMock(return_value=MagicMock())
        app.query_one = MagicMock(return_value=MagicMock())

        mock_result = StreamResult(response="Done", input_tokens=10, output_tokens=5)

        with patch("clanker.ui.streaming.stream_agent_response_async", new_callable=AsyncMock, return_value=mock_result) as mock_stream:
            # Change global default model in config to model-gamma
            set_default_model("model-gamma")

            await app._run_agent("Test prompt")

            # Streaming must be called with the session model (model-beta), NOT global default
            assert mock_stream.call_args[1]["model_name"] == "model-beta"
            assert app._token_tracker.model_name == "model-beta"
