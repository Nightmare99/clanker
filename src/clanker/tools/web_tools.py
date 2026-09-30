"""Web search and page reading tools.

Uses DDGS metasearch (no API key required) and trafilatura for
clean content extraction from web pages.
"""

from __future__ import annotations

import configparser
import ipaddress
import re
import ssl
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from langchain_core.tools import tool

from clanker.logging import get_logger

logger = get_logger("tools.web")

# Limits
MAX_RESULTS = 10
DEFAULT_RESULTS = 5
MAX_PAGE_LENGTH = 20_000
MAX_PER_DOMAIN = 3
MAX_FETCH_TOP = 3
FETCH_TOP_MAX_LENGTH = 4000
MAX_SEARCH_CANDIDATES = 20
MAX_DOWNLOAD_BYTES = 5_000_000
MAX_DECOMPRESSED_BYTES = 10_000_000
RECENCY_VALUES = {"d", "w", "m", "y"}

# Retry
MAX_SEARCH_ATTEMPTS = 3
RETRY_BASE_DELAY = 0.3

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


def _valid_web_url(url: str) -> bool:
    """Reject malformed URLs and direct references to local network services."""
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").rstrip(".").lower()
        if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
            return False
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            return False
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return (
                host != "localhost"
                and not host.endswith((".localhost", ".local", ".internal"))
                and "." in host
                and not all(character.isdigit() or character == "." for character in host)
            )
        return address.is_global
    except (TypeError, ValueError):
        return False


def _canonical_url(url: str) -> str:
    """Normalize tracking-only differences without changing meaningful query parameters."""
    parsed = urlsplit(url)
    query = urlencode([
        (key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}
    ])
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, query, ""))


def _get_ssl_context() -> ssl.SSLContext:
    """Build an SSL context backed by certifi's CA bundle.

    PyInstaller-frozen binaries have no system CA store, so the default context
    can't verify certificates ("unable to get local issuer certificate"). Using
    certifi's bundle explicitly fixes verification regardless of environment.
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _fetch_with_browser_headers(url: str, timeout: int = 15) -> str:
    """Fetch a URL using browser-like headers to avoid bot detection."""
    import urllib.error
    import urllib.request
    import zlib

    if not _valid_web_url(url):
        raise ValueError("URL must point to a public http:// or https:// host")
    req = urllib.request.Request(url, headers=_BROWSER_HEADERS)
    context = _get_ssl_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
            data = resp.read(MAX_DOWNLOAD_BYTES + 1)
            if len(data) > MAX_DOWNLOAD_BYTES:
                raise ValueError("Page download exceeds the 5 MB safety limit")
            encoding = resp.headers.get("Content-Encoding", "").lower()
            if encoding == "gzip":
                decompressor = zlib.decompressobj(zlib.MAX_WBITS | 16)
                data = decompressor.decompress(data, MAX_DECOMPRESSED_BYTES + 1)
            elif encoding == "deflate":
                decompressor = zlib.decompressobj(-zlib.MAX_WBITS)
                data = decompressor.decompress(data, MAX_DECOMPRESSED_BYTES + 1)
            else:
                decompressor = None
            if len(data) > MAX_DECOMPRESSED_BYTES or (decompressor and (
                decompressor.unconsumed_tail or not decompressor.eof
            )):
                raise ValueError("Decompressed page exceeds the 10 MB safety limit")
            media_type = resp.headers.get("Content-Type", "").split(";", 1)[0].lower()
            if media_type and not (media_type.startswith("text/") or media_type in {
                "application/json", "application/xml", "application/xhtml+xml",
            }):
                raise ValueError(f"Unsupported page content type: {media_type}")
            charset = resp.headers.get_content_charset() or "utf-8"
            return str(data.decode(charset, errors="replace"))
    except urllib.error.HTTPError as e:
        logger.warning("HTTP %d fetching %s", e.code, url)
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        logger.warning("Fetch error for %s: %s", url, e)
        raise


def _get_trafilatura_config() -> configparser.ConfigParser:
    """Build a complete trafilatura config to avoid missing-option bugs in bundled binaries."""
    config = configparser.ConfigParser()
    config['DEFAULT'] = {
        'download_timeout': '30',
        'max_file_size': str(MAX_DOWNLOAD_BYTES),
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


def _dedup_and_diversify(
    results: list[dict[str, Any]], max_per_domain: int = MAX_PER_DOMAIN,
) -> list[dict[str, Any]]:
    """Drop duplicate URLs and cap how many results a single domain can occupy.

    DDGS aggregates across several backend engines and already dedupes exact
    href collisions internally, but near-duplicate mirrors from the same
    domain (or slightly differing URL formatting) can still slip through.
    """
    seen_urls: set[str] = set()
    domain_counts: dict[str, int] = {}
    deduped = []
    for result in results:
        url = result.get("href", result.get("link", ""))
        if not _valid_web_url(url):
            continue
        normalized = _canonical_url(url)
        if normalized in seen_urls:
            continue
        domain = urlsplit(url).hostname or ""
        if domain and domain_counts.get(domain, 0) >= max_per_domain:
            continue
        seen_urls.add(normalized)
        if domain:
            domain_counts[domain] = domain_counts.get(domain, 0) + 1
        deduped.append(result)
    return deduped


def _tokenize(text: str) -> set[str]:
    return {t for t in re.split(r"\W+", text.casefold()) if len(t) >= 3}


def _rerank(results: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    """Reorder results by query-term overlap in the title and body/snippet.

    DDGS's built-in ranker only sorts into coarse buckets (title+body hit,
    title-only, body-only, neither) and unconditionally floats any
    wikipedia.org result to the very top regardless of relevance -- not
    ideal for the docs/library/error-message lookups this tool targets.
    This rescoring uses proportional token-overlap counts instead, weighting
    title matches higher than body matches. Sort is stable, so results with
    equal scores keep their original relative order.
    """
    tokens = _tokenize(query)
    if not tokens:
        return results

    def score(result: dict[str, Any]) -> int:
        title = _tokenize(result.get("title") or "")
        body = _tokenize(result.get("body") or result.get("snippet") or "")
        title_hits = len(tokens & title)
        body_hits = len(tokens & body)
        return title_hits * 3 + body_hits

    return sorted(results, key=score, reverse=True)


def _fetch_and_extract(url: str, max_length: int) -> tuple[str | None, str | None]:
    """Fetch a URL and extract clean text content.

    Returns (content, error_message) -- exactly one of the two is set.
    """
    try:
        import trafilatura
    except ImportError:
        return None, "trafilatura package is not installed. Install it with: pip install trafilatura"

    if not _valid_web_url(url):
        return None, "URL must point to a public http:// or https:// host"

    fetch_error: Exception | None = None
    try:
        downloaded = _fetch_with_browser_headers(url)
    except ValueError as e:
        return None, str(e)
    except Exception as e:
        logger.debug("Browser-header fetch failed for %s: %s", url, e)
        downloaded = None
        fetch_error = e

    # Fallback to trafilatura's own fetcher (different session/retry logic)
    if downloaded is None:
        try:
            downloaded = trafilatura.fetch_url(url, config=_get_trafilatura_config())
        except Exception as e:
            logger.error("All fetch methods failed for %s: %s", url, e)
            return None, f"Failed to fetch URL: {e}"

    if downloaded is None:
        # Report the original HTTP error if we have one
        if fetch_error is not None:
            import urllib.error

            if isinstance(fetch_error, urllib.error.HTTPError):
                return None, (
                    f"HTTP {fetch_error.code} fetching {url}. "
                    f"The site may block automated requests."
                )
            return None, f"Could not fetch content from {url} ({fetch_error})"
        return None, f"Could not fetch content from {url}"

    if len(downloaded) > MAX_DECOMPRESSED_BYTES:
        return None, "Page content exceeds the 10 MB safety limit"

    try:
        content = trafilatura.extract(
            downloaded, url=url, output_format="markdown", include_links=True,
            include_comments=False, config=_get_trafilatura_config(),
        )
    except Exception as e:
        logger.error("Failed to extract content from %s: %s", url, e)
        return None, f"Failed to extract content: {e}"

    if not content:
        # trafilatura targets HTML articles and returns nothing for raw text
        # files (e.g. a .py/.md/.json fetched from raw.githubusercontent.com).
        # If the download looks like plain text/code rather than an HTML page,
        # return it directly instead of reporting "no content".
        if _looks_like_plain_text(downloaded):
            content = downloaded
        else:
            return None, f"No meaningful content could be extracted from {url}"

    if len(content) > max_length:
        content = content[:max_length] + "\n\n... (content truncated)"

    return content, None


@tool
def web_search(
    query: str, max_results: int = DEFAULT_RESULTS, fetch_top: int = 0,
    site: str = "", recency: str = "",
) -> str:
    """Search the web for current information using DDGS metasearch.

    Use this to find documentation, look up error messages, check library
    versions, or research implementation approaches. Returns concise
    results with titles, URLs, and relevant snippets.

    Args:
        query: Search query string. Be specific for best results.
        max_results: Number of results to return (1-10, default 5).
        fetch_top: Also fetch and include extracted Markdown (up to 4000
            characters per page) for the top N results (0-3, default 0). Use
            this instead of a follow-up web_read call when snippets alone
            won't be enough detail.
        site: Optional domain to restrict results to, e.g. docs.python.org.
        recency: Optional freshness window: d (day), w (week), m (month), y (year).

    Returns:
        Search results with titles, URLs, and content snippets (plus extracted
        content for the top `fetch_top` results, if requested).
    """
    max_results = max(1, min(max_results, MAX_RESULTS))
    fetch_top = max(0, min(fetch_top, MAX_FETCH_TOP))
    query = query.strip()
    site = site.strip().lower()
    recency = recency.strip().lower()
    if not query:
        return "Error: Search query cannot be empty"
    if site and not re.fullmatch(r"(?:[a-z0-9-]+\.)+[a-z0-9-]{2,63}", site):
        return "Error: site must be a domain such as docs.python.org"
    if recency and recency not in RECENCY_VALUES:
        return "Error: recency must be d, w, m, or y"
    search_query = f"{query} site:{site}" if site else query
    candidate_count = min(MAX_SEARCH_CANDIDATES, max(10, max_results * 2))
    search_kwargs: dict[str, Any] = {"max_results": candidate_count}
    if recency:
        search_kwargs["timelimit"] = recency

    try:
        from ddgs import DDGS
        from ddgs.exceptions import DDGSException
    except ImportError:
        return (
            "Error: ddgs package is not installed. "
            "Install it with: pip install ddgs"
        )

    import random
    import time

    results = None
    last_error: Exception | None = None
    for attempt in range(1, MAX_SEARCH_ATTEMPTS + 1):
        try:
            results = DDGS().text(search_query, **search_kwargs)
            break
        except DDGSException as e:
            # Rate limits and per-engine timeouts are transient -- worth a
            # couple of quick retries before giving up.
            last_error = e
            logger.warning(
                "Web search attempt %d/%d failed: %s", attempt, MAX_SEARCH_ATTEMPTS, e
            )
            if attempt < MAX_SEARCH_ATTEMPTS:
                time.sleep(RETRY_BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0, 0.2))
        except Exception as e:
            logger.error("Web search failed: %s", e)
            return f"Error: Web search failed: {e}"

    if results is None:
        logger.error(
            "Web search failed after %d attempts: %s", MAX_SEARCH_ATTEMPTS, last_error
        )
        return f"Error: Web search failed after {MAX_SEARCH_ATTEMPTS} attempts: {last_error}"

    if not results:
        return f"No results found for: {query}"

    results = _rerank(results, query)
    if site:
        results = [
            result for result in results
            if _valid_web_url(result.get("href", result.get("link", "")))
            and (host := urlsplit(result.get("href", result.get("link", ""))).hostname)
            and (host == site or host.endswith(f".{site}"))
        ]
    results = _dedup_and_diversify(results, max_per_domain=max_results if site else MAX_PER_DOMAIN)
    results = results[:max_results]
    if not results:
        return f"No results found for: {query}"

    fetched: dict[int, tuple[str | None, str | None]] = {}
    if fetch_top:
        with ThreadPoolExecutor(max_workers=min(fetch_top, len(results))) as executor:
            jobs = {
                index: executor.submit(
                    _fetch_and_extract,
                    _canonical_url(result.get("href", result.get("link", ""))),
                    FETCH_TOP_MAX_LENGTH,
                )
                for index, result in enumerate(results[:fetch_top], 1)
            }
            fetched = {index: job.result() for index, job in jobs.items()}

    # Format results for LLM consumption
    lines = [f'Web search results for: "{query}"\n']
    for i, result in enumerate(results, 1):
        title = result.get("title", "No title")
        url = _canonical_url(result.get("href", result.get("link", "")))
        snippet = result.get("body", result.get("snippet", ""))

        lines.append(f"{i}. [{title}]({url})")
        if snippet:
            lines.append(f"   {snippet}")
        if i in fetched:
            content, error = fetched[i]
            if content:
                lines.append(f"   Full content:\n{content}")
            else:
                lines.append(f"   (Could not fetch full content: {error})")
        lines.append("")

    return "\n".join(lines).strip()


@tool
def web_read(url: str, max_length: int = MAX_PAGE_LENGTH) -> str:
    """Read and extract the main content from a web page.

    Fetches the URL and extracts its main content as Markdown, preserving
    headings, code, tables, and links while stripping navigation and
    boilerplate. Does not execute JavaScript or extract PDF content.

    Args:
        url: The URL to read.
        max_length: Maximum characters to return (1000-50000, default 20000).

    Returns:
        Source URL and extracted Markdown, or plain text for raw text/code pages.
    """
    max_length = max(1000, min(max_length, 50_000))

    if not _valid_web_url(url):
        return "Error: URL must point to a public http:// or https:// host"

    content, error = _fetch_and_extract(url, max_length)
    if error:
        return f"Error: {error}"

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
