"""Web search and page reading tools.

Uses DuckDuckGo for search (no API key required) and trafilatura for
clean content extraction from web pages.
"""

from __future__ import annotations

from langchain_core.tools import tool

from clanker.logging import get_logger

logger = get_logger("tools.web")

# Limits
MAX_RESULTS = 10
DEFAULT_RESULTS = 5
MAX_PAGE_LENGTH = 20_000

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


def _get_ssl_context():
    """Build an SSL context backed by certifi's CA bundle.

    PyInstaller-frozen binaries have no system CA store, so the default context
    can't verify certificates ("unable to get local issuer certificate"). Using
    certifi's bundle explicitly fixes verification regardless of environment.
    """
    import ssl

    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _fetch_with_browser_headers(url: str, timeout: int = 15) -> str | None:
    """Fetch a URL using browser-like headers to avoid bot detection."""
    import gzip
    import urllib.error
    import urllib.request
    import zlib

    req = urllib.request.Request(url, headers=_BROWSER_HEADERS)
    context = _get_ssl_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
            data = resp.read()
            encoding = resp.headers.get("Content-Encoding", "")
            if encoding == "gzip":
                data = gzip.decompress(data)
            elif encoding == "deflate":
                data = zlib.decompress(data, -zlib.MAX_WBITS)
            charset = resp.headers.get_content_charset() or "utf-8"
            return data.decode(charset, errors="replace")
    except urllib.error.HTTPError as e:
        logger.warning("HTTP %d fetching %s", e.code, url)
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        logger.warning("Fetch error for %s: %s", url, e)
        raise


def _get_trafilatura_config():
    """Build a complete trafilatura config to avoid missing-option bugs in bundled binaries."""
    import configparser
    config = configparser.ConfigParser()
    config['DEFAULT'] = {
        'download_timeout': '30',
        'max_file_size': '20000000',
        'min_file_size': '10',
        'sleep_time': '5.0',
        'user_agents': '',
        'cookie': '',
        'max_redirects': '2',
        'min_extracted_size': '250',
        'min_extracted_comm_size': '1',
        'min_output_size': '1',
        'min_output_comm_size': '1',
        'max_tree_size': '',
        'extraction_timeout': '30',
        'min_duplcheck_size': '100',
        'max_repetitions': '2',
        'extensive_date_search': 'on',
        'external_urls': 'off',
    }
    return config


@tool
def web_search(query: str, max_results: int = DEFAULT_RESULTS) -> str:
    """Search the web for current information using DuckDuckGo.

    Use this to find documentation, look up error messages, check library
    versions, or research implementation approaches. Returns concise
    results with titles, URLs, and relevant snippets.

    Args:
        query: Search query string. Be specific for best results.
        max_results: Number of results to return (1-10, default 5).

    Returns:
        Search results with titles, URLs, and content snippets.
    """
    max_results = max(1, min(max_results, MAX_RESULTS))

    try:
        from ddgs import DDGS
    except ImportError:
        return (
            "Error: ddgs package is not installed. "
            "Install it with: pip install ddgs"
        )

    try:
        results = DDGS().text(query, max_results=max_results)
    except Exception as e:
        logger.error("Web search failed: %s", e)
        return f"Error: Web search failed: {e}"

    if not results:
        return f"No results found for: {query}"

    # Format results for LLM consumption
    lines = [f'Web search results for: "{query}"\n']
    for i, result in enumerate(results, 1):
        title = result.get("title", "No title")
        url = result.get("href", result.get("link", ""))
        snippet = result.get("body", result.get("snippet", ""))

        lines.append(f"{i}. [{title}]({url})")
        if snippet:
            lines.append(f"   {snippet}")
        lines.append("")

    return "\n".join(lines).strip()


@tool
def web_read(url: str, max_length: int = MAX_PAGE_LENGTH) -> str:
    """Read and extract the main content from a web page.

    Fetches the URL and extracts meaningful text, stripping navigation,
    ads, scripts, and boilerplate HTML. Returns clean, readable content
    suitable for understanding documentation, articles, or code examples.

    Args:
        url: The URL to read.
        max_length: Maximum characters to return (default 20000).

    Returns:
        Clean extracted text content from the page.
    """
    max_length = max(1000, min(max_length, 50_000))

    if not url.startswith(("http://", "https://")):
        return "Error: URL must start with http:// or https://"

    try:
        import trafilatura
    except ImportError:
        return (
            "Error: trafilatura package is not installed. "
            "Install it with: pip install trafilatura"
        )

    try:
        downloaded = _fetch_with_browser_headers(url)
    except Exception as e:
        logger.debug("Browser-header fetch failed for %s: %s", url, e)
        downloaded = None
        fetch_error = e
    else:
        fetch_error = None

    # Fallback to trafilatura's own fetcher (different session/retry logic)
    if downloaded is None:
        try:
            downloaded = trafilatura.fetch_url(url)
        except Exception as e:
            logger.error("All fetch methods failed for %s: %s", url, e)
            return f"Error: Failed to fetch URL: {e}"

    if downloaded is None:
        # Report the original HTTP error if we have one
        if fetch_error is not None:
            import urllib.error
            if isinstance(fetch_error, urllib.error.HTTPError):
                return (
                    f"Error: HTTP {fetch_error.code} fetching {url}. "
                    f"The site may block automated requests."
                )
            return f"Error: Could not fetch content from {url} ({fetch_error})"
        return f"Error: Could not fetch content from {url}"

    try:
        content = trafilatura.extract(downloaded, config=_get_trafilatura_config())
    except Exception as e:
        logger.error("Failed to extract content from %s: %s", url, e)
        return f"Error: Failed to extract content: {e}"

    if not content:
        # trafilatura targets HTML articles and returns nothing for raw text
        # files (e.g. a .py/.md/.json fetched from raw.githubusercontent.com).
        # If the download looks like plain text/code rather than an HTML page,
        # return it directly instead of reporting "no content".
        if _looks_like_plain_text(downloaded):
            content = downloaded
        else:
            return f"Error: No meaningful content could be extracted from {url}"

    # Truncate if needed
    if len(content) > max_length:
        content = content[:max_length] + "\n\n... (content truncated)"

    return f"Content from {url}:\n\n{content}"


def _looks_like_plain_text(text: str) -> bool:
    """Heuristic: is this raw text/code rather than an HTML document?

    True when there's no obvious HTML document structure in the leading content,
    so we can safely return it verbatim when the HTML extractor finds nothing.
    """
    if not text:
        return False
    head = text[:1000].lower()
    html_markers = ("<!doctype html", "<html", "<head", "<body", "<div", "<p>", "<span")
    return not any(marker in head for marker in html_markers)
