"""Tests for web search and web read tools."""

from unittest.mock import MagicMock, patch

import pytest

from clanker.tools.web_tools import web_read, web_search


class TestWebSearch:
    """Tests for the web_search tool."""

    def test_search_returns_formatted_results(self) -> None:
        """Test that search results are properly formatted."""
        mock_results = [
            {
                "title": "Python Docs",
                "href": "https://docs.python.org",
                "body": "Official Python documentation.",
            },
            {
                "title": "Real Python",
                "href": "https://realpython.com",
                "body": "Python tutorials and guides.",
            },
        ]

        with patch("ddgs.DDGS") as mock_ddgs_class:
            mock_instance = MagicMock()
            mock_instance.text.return_value = mock_results
            mock_ddgs_class.return_value = mock_instance

            result = web_search.invoke({"query": "python asyncio"})

        assert "python asyncio" in result
        assert "Python Docs" in result
        assert "https://docs.python.org" in result
        assert "Official Python documentation." in result
        assert "Real Python" in result

    def test_search_no_results(self) -> None:
        """Test handling of empty search results."""
        with patch("ddgs.DDGS") as mock_ddgs_class:
            mock_instance = MagicMock()
            mock_instance.text.return_value = []
            mock_ddgs_class.return_value = mock_instance

            result = web_search.invoke({"query": "xyznonexistent12345"})

        assert "No results found" in result

    def test_search_max_results_clamped(self) -> None:
        """Test that max_results is clamped between 1 and 10."""
        with patch("ddgs.DDGS") as mock_ddgs_class:
            mock_instance = MagicMock()
            mock_instance.text.return_value = []
            mock_ddgs_class.return_value = mock_instance

            # Over max
            web_search.invoke({"query": "test", "max_results": 50})
            mock_instance.text.assert_called_with("test", max_results=10)

            # Under min
            mock_instance.reset_mock()
            web_search.invoke({"query": "test", "max_results": 0})
            mock_instance.text.assert_called_with("test", max_results=1)

    def test_search_handles_exception(self) -> None:
        """Test graceful handling of search errors."""
        with patch("ddgs.DDGS") as mock_ddgs_class:
            mock_instance = MagicMock()
            mock_instance.text.side_effect = Exception("Network timeout")
            mock_ddgs_class.return_value = mock_instance

            result = web_search.invoke({"query": "test"})

        assert "Error" in result
        assert "Network timeout" in result

    def test_search_result_numbering(self) -> None:
        """Test that results are numbered sequentially."""
        mock_results = [
            {"title": f"Result {i}", "href": f"https://example.com/{i}", "body": f"Body {i}"}
            for i in range(1, 4)
        ]

        with patch("ddgs.DDGS") as mock_ddgs_class:
            mock_instance = MagicMock()
            mock_instance.text.return_value = mock_results
            mock_ddgs_class.return_value = mock_instance

            result = web_search.invoke({"query": "test"})

        assert "1. [Result 1]" in result
        assert "2. [Result 2]" in result
        assert "3. [Result 3]" in result

    def test_search_missing_body(self) -> None:
        """Test handling of results with missing body field."""
        mock_results = [
            {"title": "No Body", "href": "https://example.com"},
        ]

        with patch("ddgs.DDGS") as mock_ddgs_class:
            mock_instance = MagicMock()
            mock_instance.text.return_value = mock_results
            mock_ddgs_class.return_value = mock_instance

            result = web_search.invoke({"query": "test"})

        assert "No Body" in result
        assert "https://example.com" in result


class TestWebRead:
    """Tests for the web_read tool."""

    def test_read_returns_content(self) -> None:
        """Test successful page reading."""
        with patch("clanker.tools.web_tools._fetch_with_browser_headers") as mock_fetch, \
             patch("trafilatura.extract") as mock_extract:
            mock_fetch.return_value = "<html><body>Hello world</body></html>"
            mock_extract.return_value = "Hello world extracted content"

            result = web_read.invoke({"url": "https://example.com"})

        assert "Hello world extracted content" in result
        assert "https://example.com" in result

    def test_read_invalid_url(self) -> None:
        """Test rejection of non-HTTP URLs."""
        result = web_read.invoke({"url": "ftp://example.com"})
        assert "Error" in result
        assert "http://" in result

        result = web_read.invoke({"url": "not-a-url"})
        assert "Error" in result

    def test_read_fetch_failure(self) -> None:
        """Test handling of fetch failures."""
        with patch("clanker.tools.web_tools._fetch_with_browser_headers") as mock_fetch:
            mock_fetch.return_value = None

            result = web_read.invoke({"url": "https://nonexistent.example.com"})

        assert "Error" in result
        assert "Could not fetch" in result

    def test_read_extraction_failure(self) -> None:
        """Test handling when no content can be extracted."""
        with patch("clanker.tools.web_tools._fetch_with_browser_headers") as mock_fetch, \
             patch("trafilatura.extract") as mock_extract:
            mock_fetch.return_value = "<html></html>"
            mock_extract.return_value = None

            result = web_read.invoke({"url": "https://example.com"})

        assert "Error" in result
        assert "No meaningful content" in result

    def test_read_truncation(self) -> None:
        """Test that long content is truncated."""
        long_content = "x" * 25000

        with patch("clanker.tools.web_tools._fetch_with_browser_headers") as mock_fetch, \
             patch("trafilatura.extract") as mock_extract:
            mock_fetch.return_value = "<html><body>content</body></html>"
            mock_extract.return_value = long_content

            result = web_read.invoke({"url": "https://example.com", "max_length": 5000})

        assert len(result) < 25000
        assert "truncated" in result

    def test_read_max_length_clamped(self) -> None:
        """Test that max_length is clamped between 1000 and 50000."""
        with patch("clanker.tools.web_tools._fetch_with_browser_headers") as mock_fetch, \
             patch("trafilatura.extract") as mock_extract:
            mock_fetch.return_value = "<html><body>short</body></html>"
            mock_extract.return_value = "short content"

            # Under min - should still work (clamped to 1000)
            result = web_read.invoke({"url": "https://example.com", "max_length": 10})
            assert "short content" in result

    def test_read_fetch_exception(self) -> None:
        """Test handling of network exceptions during fetch."""
        with patch("clanker.tools.web_tools._fetch_with_browser_headers") as mock_browser, \
             patch("trafilatura.fetch_url") as mock_traf:
            mock_browser.side_effect = Exception("Connection refused")
            mock_traf.side_effect = Exception("Connection refused")

            result = web_read.invoke({"url": "https://example.com"})

        assert "Error" in result
        assert "Connection refused" in result

    def test_read_extract_exception(self) -> None:
        """Test handling of exceptions during content extraction."""
        with patch("clanker.tools.web_tools._fetch_with_browser_headers") as mock_fetch, \
             patch("trafilatura.extract") as mock_extract:
            mock_fetch.return_value = "<html>data</html>"
            mock_extract.side_effect = Exception("Parse error")

            result = web_read.invoke({"url": "https://example.com"})

        assert "Error" in result
        assert "Parse error" in result


class TestWebToolsIntegration:
    """Integration tests verifying tools work with the tool registry."""

    def test_tools_in_registry(self) -> None:
        """Test that web tools appear in get_tools()."""
        from clanker.tools import get_tools

        tools = get_tools()
        tool_names = [t.name for t in tools]

        assert "web_search" in tool_names
        assert "web_read" in tool_names

    def test_tools_excluded_when_disabled(self) -> None:
        """Test that web tools are excluded when disabled in config."""
        mock_settings = MagicMock()
        mock_settings.web_search.enabled = False

        with patch("clanker.config.settings.get_settings", return_value=mock_settings):
            from clanker.tools import get_tools

            tools = get_tools()
            tool_names = [t.name for t in tools]

            assert "web_search" not in tool_names
            assert "web_read" not in tool_names
