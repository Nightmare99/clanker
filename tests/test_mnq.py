"""Tests for MNQ multi-agent mode."""

import json
from pathlib import Path
import pytest

from clanker.config.settings import Settings
from clanker.agent.mnq.board import TaskBoard
from clanker.agent.mnq.orchestrator import resolve_context_refs
from clanker.agent.mnq.agent import resolve_model_for_role


class TestMNQSettings:
    """Tests for MNQ settings."""

    def test_default_mnq_settings(self) -> None:
        """Test defaults for MNQ settings are parsed/initialized correctly."""
        settings = Settings()

        assert settings.mnq.enabled is False
        assert settings.mnq.models.architect == "strong"
        assert settings.mnq.models.frontend == "strong"
        assert settings.mnq.models.backend == "strong"
        assert settings.mnq.models.devops == "mid"
        assert settings.mnq.models.dba == "mid"
        assert settings.mnq.models.tester == "strong"

    def test_mnq_settings_save_load(self, tmp_path: Path) -> None:
        """Test that MNQ settings roundtrip properly through YAML files."""
        settings = Settings()
        settings.mnq.enabled = True
        settings.mnq.models.backend = "my-custom-backend-model"

        config_file = tmp_path / "config.yaml"
        settings.save_yaml(config_file)

        reloaded = Settings.from_yaml(config_file)
        assert reloaded.mnq.enabled is True
        assert reloaded.mnq.models.backend == "my-custom-backend-model"
        assert reloaded.mnq.models.architect == "strong"


class TestTaskBoard:
    """Tests for TaskBoard SQLite implementation."""

    @pytest.fixture
    def board(self, tmp_path: Path) -> TaskBoard:
        """Fixture for an empty SQLite task board."""
        db_path = tmp_path / "test_board.db"
        tb = TaskBoard(db_path)
        yield tb
        tb.close()

    def test_add_and_get_task(self, board: TaskBoard) -> None:
        """Test adding and retrieving a task."""
        board.add_task(
            id="t1",
            title="Implement database schema",
            type="feature",
            assignee_role="dba",
            status="pending",
            priority="high",
            depends_on=[],
            description="Create tables",
            context_refs=["schema.sql"],
            acceptance_criteria=["Table users exists"],
            created_by="architect",
        )

        task = board.get_task("t1")
        assert task is not None
        assert task["id"] == "t1"
        assert task["title"] == "Implement database schema"
        assert task["assignee_role"] == "dba"
        assert task["status"] == "pending"
        assert task["depends_on"] == []
        assert task["context_refs"] == ["schema.sql"]
        assert task["acceptance_criteria"] == ["Table users exists"]
        assert task["needs_followup"] is False

    def test_update_task(self, board: TaskBoard) -> None:
        """Test updating task properties."""
        board.add_task(
            id="t1",
            title="Design API",
            type="feature",
            assignee_role="backend",
            status="pending",
            priority="medium",
            depends_on=[],
            description="Create routes",
            context_refs=[],
            acceptance_criteria=[],
            created_by="architect",
        )

        board.update_task("t1", {
            "status": "complete",
            "result_summary": "Created routes",
            "diff_ref": "git:abc123",
            "needs_followup": True,
            "followup_question": "Which port to use?",
        })

        task = board.get_task("t1")
        assert task["status"] == "complete"
        assert task["result_summary"] == "Created routes"
        assert task["diff_ref"] == "git:abc123"
        assert task["needs_followup"] is True
        assert task["followup_question"] == "Which port to use?"

    def test_claim_task(self, board: TaskBoard) -> None:
        """Test atomic task claiming."""
        board.add_task(
            id="t1",
            title="Design API",
            type="feature",
            assignee_role="backend",
            status="pending",
            priority="medium",
            depends_on=[],
            description="Create routes",
            context_refs=[],
            acceptance_criteria=[],
            created_by="architect",
        )

        # Claim with correct role should succeed
        success = board.claim_task("backend", "t1")
        assert success is True

        task = board.get_task("t1")
        assert task["status"] == "in_progress"

        # Claiming again or with wrong role should fail
        success2 = board.claim_task("backend", "t1")
        assert success2 is False

        success3 = board.claim_task("frontend", "t1")
        assert success3 is False

        # Transition to complete
        board.update_task("t1", {"status": "complete"})

        # Tester claiming completed task should succeed
        success_tester = board.claim_task("tester", "t1")
        assert success_tester is True

        task = board.get_task("t1")
        assert task["status"] == "in_progress"

    def test_dependencies(self, board: TaskBoard) -> None:
        """Test dependency satisfaction checking."""
        board.add_task(
            id="t1",
            title="Create DB Schema",
            type="feature",
            assignee_role="dba",
            status="pending",
            priority="medium",
            depends_on=[],
            description="DB",
            context_refs=[],
            acceptance_criteria=[],
            created_by="architect",
        )

        board.add_task(
            id="t2",
            title="Create API Endpoints",
            type="feature",
            assignee_role="backend",
            status="pending",
            priority="medium",
            depends_on=["t1"],
            description="API",
            context_refs=[],
            acceptance_criteria=[],
            created_by="architect",
        )

        task1 = board.get_task("t1")
        task2 = board.get_task("t2")

        # t1 has no dependencies -> satisfied
        assert board.is_dependency_satisfied(task1) is True

        # t2 depends on t1, t1 is pending -> not satisfied
        assert board.is_dependency_satisfied(task2) is False

        # Mark t1 as complete (still not verified)
        board.update_task("t1", {"status": "complete"})
        task2 = board.get_task("t2")
        assert board.is_dependency_satisfied(task2) is False

        # Mark t1 as verified -> satisfied
        board.update_task("t1", {"status": "verified"})
        task2 = board.get_task("t2")
        assert board.is_dependency_satisfied(task2) is True

    def test_get_runnable_tasks(self, board: TaskBoard) -> None:
        """Test retrieving runnable tasks for a role."""
        board.add_task(
            id="t1",
            title="Task 1",
            type="feature",
            assignee_role="backend",
            status="pending",
            priority="medium",
            depends_on=[],
            description="T1",
            context_refs=[],
            acceptance_criteria=[],
            created_by="architect",
        )

        board.add_task(
            id="t2",
            title="Task 2",
            type="feature",
            assignee_role="backend",
            status="pending",
            priority="medium",
            depends_on=["t3"],  # depends on non-existent/unverified t3
            description="T2",
            context_refs=[],
            acceptance_criteria=[],
            created_by="architect",
        )

        runnable = board.get_runnable_tasks("backend")
        assert len(runnable) == 1
        assert runnable[0]["id"] == "t1"


class TestOrchestratorHelpers:
    """Tests for orchestrator and agent helper functions."""

    def test_resolve_context_refs(self, tmp_path: Path) -> None:
        """Test resolving file content from context refs."""
        # Setup mock files
        file1 = tmp_path / "hello.py"
        file1.write_text("line1\nline2\nline3\nline4\nline5\n")

        # Ref with line range
        ref1 = f"{file1}:2-4"
        res1 = resolve_context_refs([ref1])
        assert "line2" in res1
        assert "line3" in res1
        assert "line4" in res1
        assert "line1" not in res1

        # Ref without range
        ref2 = str(file1)
        res2 = resolve_context_refs([ref2])
        assert "line1" in res2
        assert "line5" in res2

        # Non-existent file
        ref3 = "ghost.py"
        res3 = resolve_context_refs([ref3])
        assert "ghost.py" in res3
        assert "not found" in res3

    def test_orchestrator_session_switching(self, tmp_path: Path) -> None:
        """Test switching database session in the orchestrator."""
        from clanker.agent.mnq.orchestrator import MNQOrchestrator
        from clanker.ui.console import Console
        from clanker.agent.mnq.board import TaskBoard
        from clanker.agent.mnq.tools import set_active_board

        settings = Settings()
        console = Console()

        # Create orchestrator
        orchestrator = MNQOrchestrator(settings, console, None, session_id="sess_1")
        # Override db directory to temp directory
        orchestrator.db_dir = tmp_path
        orchestrator.db_path = tmp_path / "mnq_board_sess_1.db"
        orchestrator.board = TaskBoard(orchestrator.db_path)
        set_active_board(orchestrator.board)

        # Add a task to sess_1
        orchestrator.board.add_task(
            id="t_sess_1",
            title="Task 1",
            type="feature",
            assignee_role="backend",
            status="pending",
            priority="medium",
            depends_on=[],
            description="DB",
            context_refs=[],
            acceptance_criteria=[],
            created_by="architect",
        )

        # Switch to sess_2
        orchestrator.switch_session("sess_2")

        # Check task board in sess_2 is empty
        assert orchestrator.board.get_task("t_sess_1") is None

        # Switch back to sess_1
        orchestrator.switch_session("sess_1")
        assert orchestrator.board.get_task("t_sess_1") is not None

    def test_orchestrator_resets_in_progress(self, tmp_path: Path) -> None:
        """Test that execute_workflow resets interrupted in_progress tasks back to pending."""
        from clanker.agent.mnq.orchestrator import MNQOrchestrator
        from clanker.ui.console import Console
        from clanker.agent.mnq.board import TaskBoard
        from clanker.agent.mnq.tools import set_active_board
        import unittest.mock as mock

        settings = Settings()
        console = Console()

        # Create orchestrator
        orchestrator = MNQOrchestrator(settings, console, None, session_id="sess_reset")
        orchestrator.db_dir = tmp_path
        orchestrator.db_path = tmp_path / "mnq_board_sess_reset.db"
        orchestrator.board = TaskBoard(orchestrator.db_path)
        set_active_board(orchestrator.board)

        # Add a task with status in_progress
        orchestrator.board.add_task(
            id="t_in_progress",
            title="Task 1",
            type="feature",
            assignee_role="backend",
            status="in_progress",
            priority="medium",
            depends_on=[],
            description="DB",
            context_refs=[],
            acceptance_criteria=[],
            created_by="architect",
        )

        with mock.patch.object(orchestrator.board, "has_unverified_tasks", return_value=False):
            orchestrator.execute_workflow()

        # Ensure task is reset to pending
        task = orchestrator.board.get_task("t_in_progress")
        assert task["status"] == "pending"
