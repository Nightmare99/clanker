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


class TestSSLCertificates:
    """Regression for CERTIFICATE_VERIFY_FAILED in the frozen binary.

    The fetcher must verify HTTPS using certifi's CA bundle (not a disabled
    context), so packaged binaries without a system CA store still work.
    """

    def test_ssl_context_verifies_and_uses_certifi(self) -> None:
        import ssl

        import certifi

        from clanker.tools.web_tools import _get_ssl_context

        ctx = _get_ssl_context()
        # Verification stays ON — we fix the CA path, we don't disable checking.
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert ctx.check_hostname is True
        # Built from certifi's bundle (best-effort: at least one cert loaded).
        assert certifi.where()  # bundle exists
        assert ctx.cert_store_stats()["x509"] > 0

    def test_fetch_passes_ssl_context_to_urlopen(self) -> None:
        from clanker.tools import web_tools

        captured = {}

        class FakeResp:
            headers = MagicMock()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b"<html>ok</html>"

        def fake_urlopen(req, timeout=None, context=None):
            captured["context"] = context
            resp = FakeResp()
            resp.headers.get.return_value = ""
            resp.headers.get_content_charset.return_value = "utf-8"
            return resp

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            web_tools._fetch_with_browser_headers("https://example.com")

        # A verifying SSL context must be passed (not None = system default).
        import ssl

        assert isinstance(captured["context"], ssl.SSLContext)
        assert captured["context"].verify_mode == ssl.CERT_REQUIRED

    def test_configure_certificates_sets_and_respects_overrides(self, monkeypatch) -> None:
        import certifi

        from clanker.cli import _configure_certificates

        for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
            monkeypatch.delenv(var, raising=False)

        _configure_certificates()
        import os

        assert os.environ["SSL_CERT_FILE"] == certifi.where()
        assert os.environ["REQUESTS_CA_BUNDLE"] == certifi.where()

        # An explicit user override is preserved (setdefault, not overwrite).
        monkeypatch.setenv("SSL_CERT_FILE", "/custom/ca.pem")
        _configure_certificates()
        assert os.environ["SSL_CERT_FILE"] == "/custom/ca.pem"


class TestRawTextFallback:
    """web_read must return raw text/code when trafilatura extracts nothing.

    Fetching a .py/.md/.json from raw.githubusercontent.com yields plain text;
    trafilatura targets HTML articles and returns nothing, which used to surface
    as 'No meaningful content could be extracted'.
    """

    def test_looks_like_plain_text(self) -> None:
        from clanker.tools.web_tools import _looks_like_plain_text

        assert _looks_like_plain_text("# Copyright\nimport os\ndef f(): ...")
        assert _looks_like_plain_text('{"key": "value"}')
        assert not _looks_like_plain_text("<!DOCTYPE html><html><body>x</body></html>")
        assert not _looks_like_plain_text("<div class='a'>hello</div>")
        assert not _looks_like_plain_text("")

    def test_raw_code_returned_when_extract_empty(self) -> None:
        from clanker.tools import web_tools

        raw_code = "# Copyright 2023\nimport os\n\ndef run():\n    return 1\n"

        with patch.object(web_tools, "_fetch_with_browser_headers", return_value=raw_code), \
             patch("trafilatura.extract", return_value=None):
            result = web_tools.web_read.invoke({"url": "https://raw.example.com/x.py"})

        assert "import os" in result
        assert "def run" in result
        assert "No meaningful content" not in result

    def test_html_with_no_extract_still_errors(self) -> None:
        from clanker.tools import web_tools

        html = "<!DOCTYPE html><html><body><div>nav only</div></body></html>"

        with patch.object(web_tools, "_fetch_with_browser_headers", return_value=html), \
             patch("trafilatura.extract", return_value=None):
            result = web_tools.web_read.invoke({"url": "https://example.com/page"})

        # Real HTML that yields nothing is still reported as no-content (not dumped).
        assert "No meaningful content" in result
