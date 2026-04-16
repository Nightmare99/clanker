"""Tests for Clanker tools."""

import tempfile
from pathlib import Path

import pytest
from pypdf import PdfWriter

from clanker.tools.file_tools import edit_file, list_directory, read_file, write_file
from clanker.tools.search_tools import glob_search, grep_search


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """Create a sample PDF file with text content for testing."""
    pdf_path = tmp_path / "sample.pdf"
    writer = PdfWriter()

    # Create 3 pages with different content
    for i in range(1, 4):
        page = writer.add_blank_page(width=612, height=792)
        # Add text annotation (pypdf doesn't support direct text writing easily,
        # so we'll use a different approach)

    writer.write(pdf_path)
    return pdf_path


@pytest.fixture
def large_pdf(tmp_path: Path) -> Path:
    """Create a PDF with many pages for testing page limits."""
    pdf_path = tmp_path / "large.pdf"
    writer = PdfWriter()

    # Create 15 blank pages
    for _ in range(15):
        writer.add_blank_page(width=612, height=792)

    writer.write(pdf_path)
    return pdf_path


class TestFileTools:
    """Tests for file operation tools."""

    def test_read_file_success(self, tmp_path: Path) -> None:
        """Test reading an existing file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line 1\nline 2\nline 3\n")

        result = read_file.invoke({"file_path": str(test_file)})

        assert result["ok"] is True
        assert "line 1" in result["content"]
        assert "line 2" in result["content"]
        assert "line 3" in result["content"]

    def test_read_file_not_found(self) -> None:
        """Test reading a non-existent file."""
        result = read_file.invoke({"file_path": "/nonexistent/file.txt"})

        assert result["ok"] is False
        assert "not found" in result["error"].lower()

    def test_write_file_success(self, tmp_path: Path) -> None:
        """Test writing to a file."""
        test_file = tmp_path / "output.txt"
        content = "Hello, World!"

        result = write_file.invoke({"file_path": str(test_file), "content": content})

        assert result["ok"] is True
        assert test_file.read_text() == content

    def test_write_file_creates_directories(self, tmp_path: Path) -> None:
        """Test that write_file creates parent directories."""
        test_file = tmp_path / "subdir" / "deep" / "file.txt"
        content = "Nested content"

        result = write_file.invoke({"file_path": str(test_file), "content": content})

        assert result["ok"] is True
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

        assert result["ok"] is True
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

        assert result["ok"] is False
        assert "not found" in result["error"].lower()

    def test_edit_file_multiple_matches(self, tmp_path: Path) -> None:
        """Test editing with ambiguous matches."""
        test_file = tmp_path / "edit.txt"
        test_file.write_text("foo foo foo")

        result = edit_file.invoke({
            "file_path": str(test_file),
            "old_string": "foo",
            "new_string": "bar",
        })

        assert result["ok"] is False
        assert "3 times" in result["error"]

    def test_list_directory(self, tmp_path: Path) -> None:
        """Test listing a directory."""
        # Create some files and dirs
        (tmp_path / "file1.txt").write_text("content")
        (tmp_path / "file2.py").write_text("print('hello')")
        (tmp_path / "subdir").mkdir()

        result = list_directory.invoke({"path": str(tmp_path)})

        assert result["ok"] is True
        items = result["items"]
        names = [item["name"] for item in items]
        assert "file1.txt" in names
        assert "file2.py" in names
        assert "subdir" in names


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


class TestPDFReading:
    """Tests for PDF file reading functionality."""

    def test_read_pdf_small_file(self, sample_pdf: Path) -> None:
        """Test reading a small PDF file without page specification."""
        result = read_file.invoke({"file_path": str(sample_pdf)})

        # Should succeed for small PDFs (3 pages)
        assert result["ok"] is True
        assert "path" in result

    def test_read_pdf_with_page_range(self, sample_pdf: Path) -> None:
        """Test reading specific pages from a PDF."""
        result = read_file.invoke({
            "file_path": str(sample_pdf),
            "pages": "1-2",
        })

        assert result["ok"] is True
        assert result.get("pages_read", 0) <= 2

    def test_read_pdf_single_page(self, sample_pdf: Path) -> None:
        """Test reading a single page from a PDF."""
        result = read_file.invoke({
            "file_path": str(sample_pdf),
            "pages": "1",
        })

        assert result["ok"] is True
        assert result.get("pages_read", 0) == 1

    def test_read_large_pdf_without_pages_fails(self, large_pdf: Path) -> None:
        """Test that large PDFs require page specification."""
        result = read_file.invoke({"file_path": str(large_pdf)})

        # Should fail and request page range
        assert result["ok"] is False
        assert "pages" in result.get("error", "").lower()
        assert result.get("total_pages") == 15

    def test_read_large_pdf_with_pages_succeeds(self, large_pdf: Path) -> None:
        """Test that large PDFs work with page specification."""
        result = read_file.invoke({
            "file_path": str(large_pdf),
            "pages": "1-5",
        })

        assert result["ok"] is True
        assert result.get("pages_read") == 5

    def test_read_pdf_invalid_page_range(self, sample_pdf: Path) -> None:
        """Test reading PDF with invalid page range."""
        result = read_file.invoke({
            "file_path": str(sample_pdf),
            "pages": "100-200",  # Beyond actual pages
        })

        # Should fail gracefully
        assert result["ok"] is False
        assert "error" in result

    def test_read_pdf_not_found(self) -> None:
        """Test reading a non-existent PDF file."""
        result = read_file.invoke({"file_path": "/nonexistent/file.pdf"})

        assert result["ok"] is False
        assert "not found" in result.get("error", "").lower()

    def test_read_pdf_comma_separated_pages(self, sample_pdf: Path) -> None:
        """Test reading non-contiguous pages."""
        result = read_file.invoke({
            "file_path": str(sample_pdf),
            "pages": "1,3",
        })

        assert result["ok"] is True
        assert result.get("pages_read") == 2
