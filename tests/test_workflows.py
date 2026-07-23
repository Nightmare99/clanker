"""Tests for workflow loading."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_workflows_module():
    """Load workflows module directly without triggering heavy imports."""
    module_path = Path("src/clanker/workflows.py")
    spec = importlib.util.spec_from_file_location("clanker_workflows_test", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestListWorkflows:
    """Tests for list_workflows function."""

    def test_empty_when_no_dir(self, tmp_path) -> None:
        """Returns empty list when workflows dir doesn't exist."""
        mod = _load_workflows_module()
        assert mod.list_workflows(str(tmp_path)) == []

    def test_empty_when_dir_exists_but_empty(self, tmp_path) -> None:
        """Returns empty list when workflows dir has no .md files."""
        mod = _load_workflows_module()
        (tmp_path / ".clanker" / "workflows").mkdir(parents=True)
        assert mod.list_workflows(str(tmp_path)) == []

    def test_lists_md_files_without_extension(self, tmp_path) -> None:
        """Lists .md filenames without the extension."""
        mod = _load_workflows_module()
        wf_dir = tmp_path / ".clanker" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "deploy.md").write_text("Deploy to prod")
        (wf_dir / "test-suite.md").write_text("Run tests")
        result = mod.list_workflows(str(tmp_path))
        assert result == ["deploy", "test-suite"]

    def test_ignores_non_md_files(self, tmp_path) -> None:
        """Ignores files that aren't .md."""
        mod = _load_workflows_module()
        wf_dir = tmp_path / ".clanker" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "deploy.md").write_text("Deploy")
        (wf_dir / "notes.txt").write_text("Not a workflow")
        (wf_dir / "script.py").write_text("# not a workflow")
        result = mod.list_workflows(str(tmp_path))
        assert result == ["deploy"]

    def test_sorted_alphabetically(self, tmp_path) -> None:
        """Workflow names are sorted alphabetically."""
        mod = _load_workflows_module()
        wf_dir = tmp_path / ".clanker" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "zebra.md").write_text("z")
        (wf_dir / "alpha.md").write_text("a")
        (wf_dir / "middle.md").write_text("m")
        result = mod.list_workflows(str(tmp_path))
        assert result == ["alpha", "middle", "zebra"]


class TestLoadWorkflow:
    """Tests for load_workflow function."""

    def test_returns_none_when_not_found(self, tmp_path) -> None:
        """Returns None when workflow doesn't exist."""
        mod = _load_workflows_module()
        assert mod.load_workflow("nonexistent", str(tmp_path)) is None

    def test_returns_none_when_dir_missing(self, tmp_path) -> None:
        """Returns None when workflows dir doesn't exist."""
        mod = _load_workflows_module()
        assert mod.load_workflow("deploy", str(tmp_path)) is None

    def test_loads_workflow_content(self, tmp_path) -> None:
        """Loads and returns workflow file content."""
        mod = _load_workflows_module()
        wf_dir = tmp_path / ".clanker" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "deploy.md").write_text("Run the deploy script and verify.")
        result = mod.load_workflow("deploy", str(tmp_path))
        assert result == "Run the deploy script and verify."

    def test_strips_whitespace(self, tmp_path) -> None:
        """Strips leading/trailing whitespace from content."""
        mod = _load_workflows_module()
        wf_dir = tmp_path / ".clanker" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "clean.md").write_text("  \n  Run cleanup  \n  ")
        result = mod.load_workflow("clean", str(tmp_path))
        assert result == "Run cleanup"

    def test_returns_none_for_empty_file(self, tmp_path) -> None:
        """Returns None for empty workflow file."""
        mod = _load_workflows_module()
        wf_dir = tmp_path / ".clanker" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "empty.md").write_text("   \n  ")
        result = mod.load_workflow("empty", str(tmp_path))
        # strip() makes it empty, which is falsy but still a string
        assert result == ""

    def test_multiline_content_preserved(self, tmp_path) -> None:
        """Multi-line workflow content is preserved."""
        mod = _load_workflows_module()
        wf_dir = tmp_path / ".clanker" / "workflows"
        wf_dir.mkdir(parents=True)
        content = "Step 1: Read the code\nStep 2: Run tests\nStep 3: Deploy"
        (wf_dir / "full.md").write_text(content)
        result = mod.load_workflow("full", str(tmp_path))
        assert result == content


class TestGetWorkflowsDir:
    """Tests for get_workflows_dir function."""

    def test_returns_correct_path(self, tmp_path) -> None:
        """Returns .clanker/workflows/ under workspace."""
        mod = _load_workflows_module()
        result = mod.get_workflows_dir(str(tmp_path))
        assert result == tmp_path / ".clanker" / "workflows"

    def test_defaults_to_cwd(self, tmp_path, monkeypatch) -> None:
        """Defaults to current directory when no arg given."""
        mod = _load_workflows_module()
        monkeypatch.chdir(tmp_path)
        result = mod.get_workflows_dir()
        assert result == tmp_path / ".clanker" / "workflows"
