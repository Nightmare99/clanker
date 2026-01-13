"""Tests for Clanker tools."""

import tempfile
from pathlib import Path

import pytest

from clanker.tools.file_tools import edit_file, list_directory, read_file, write_file
from clanker.tools.search_tools import glob_search, grep_search


class TestFileTools:
    """Tests for file operation tools."""

    def test_read_file_success(self, tmp_path: Path) -> None:
        """Test reading an existing file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line 1\nline 2\nline 3\n")

        result = read_file.invoke({"file_path": str(test_file)})

        assert "line 1" in result
        assert "line 2" in result
        assert "line 3" in result
        assert "1\t" in result  # Line numbers

    def test_read_file_not_found(self) -> None:
        """Test reading a non-existent file."""
        result = read_file.invoke({"file_path": "/nonexistent/file.txt"})

        assert "Error" in result
        assert "not found" in result.lower()

    def test_write_file_success(self, tmp_path: Path) -> None:
        """Test writing to a file."""
        test_file = tmp_path / "output.txt"
        content = "Hello, World!"

        result = write_file.invoke({"file_path": str(test_file), "content": content})

        assert "Successfully" in result
        assert test_file.read_text() == content

    def test_write_file_creates_directories(self, tmp_path: Path) -> None:
        """Test that write_file creates parent directories."""
        test_file = tmp_path / "subdir" / "deep" / "file.txt"
        content = "Nested content"

        result = write_file.invoke({"file_path": str(test_file), "content": content})

        assert "Successfully" in result
        assert test_file.exists()
        assert test_file.read_text() == content

    def test_edit_file_success(self, tmp_path: Path) -> None:
        """Test editing a file."""
        test_file = tmp_path / "edit.txt"
        test_file.write_text("Hello, World!")

        result = edit_file.invoke({
            "file_path": str(test_file),
            "old_string": "World",
            "new_string": "Python",
        })

        assert "Successfully" in result
        assert test_file.read_text() == "Hello, Python!"

    def test_edit_file_string_not_found(self, tmp_path: Path) -> None:
        """Test editing with non-existent string."""
        test_file = tmp_path / "edit.txt"
        test_file.write_text("Hello, World!")

        result = edit_file.invoke({
            "file_path": str(test_file),
            "old_string": "Goodbye",
            "new_string": "Hi",
        })

        assert "Error" in result
        assert "not found" in result.lower()

    def test_edit_file_multiple_matches(self, tmp_path: Path) -> None:
        """Test editing with ambiguous matches."""
        test_file = tmp_path / "edit.txt"
        test_file.write_text("foo foo foo")

        result = edit_file.invoke({
            "file_path": str(test_file),
            "old_string": "foo",
            "new_string": "bar",
        })

        assert "Error" in result
        assert "3 times" in result

    def test_list_directory(self, tmp_path: Path) -> None:
        """Test listing a directory."""
        # Create some files and dirs
        (tmp_path / "file1.txt").write_text("content")
        (tmp_path / "file2.py").write_text("print('hello')")
        (tmp_path / "subdir").mkdir()

        result = list_directory.invoke({"path": str(tmp_path)})

        assert "file1.txt" in result
        assert "file2.py" in result
        assert "subdir" in result
        assert "[DIR]" in result


class TestSearchTools:
    """Tests for search tools."""

    def test_glob_search_finds_files(self, tmp_path: Path) -> None:
        """Test glob search finds matching files."""
        (tmp_path / "test1.py").write_text("content")
        (tmp_path / "test2.py").write_text("content")
        (tmp_path / "other.txt").write_text("content")

        result = glob_search.invoke({"pattern": "*.py", "path": str(tmp_path)})

        assert "test1.py" in result
        assert "test2.py" in result
        assert "other.txt" not in result

    def test_glob_search_no_matches(self, tmp_path: Path) -> None:
        """Test glob search with no matches."""
        (tmp_path / "test.txt").write_text("content")

        result = glob_search.invoke({"pattern": "*.py", "path": str(tmp_path)})

        assert "No files found" in result

    def test_grep_search_finds_content(self, tmp_path: Path) -> None:
        """Test grep search finds matching content."""
        (tmp_path / "test.py").write_text("def hello():\n    return 'world'\n")

        result = grep_search.invoke({
            "pattern": "def hello",
            "path": str(tmp_path),
        })

        assert "def hello" in result
        assert "test.py" in result

    def test_grep_search_case_insensitive(self, tmp_path: Path) -> None:
        """Test grep search with case insensitive flag."""
        (tmp_path / "test.txt").write_text("Hello World\n")

        result = grep_search.invoke({
            "pattern": "hello",
            "path": str(tmp_path),
            "ignore_case": True,
        })

        assert "Hello World" in result

    def test_grep_search_no_matches(self, tmp_path: Path) -> None:
        """Test grep search with no matches."""
        (tmp_path / "test.txt").write_text("Hello World\n")

        result = grep_search.invoke({
            "pattern": "goodbye",
            "path": str(tmp_path),
        })

        assert "No matches found" in result
