"""Web search and page fetching.

Search goes through **Tavily** when an API key is available — it is built for
LLM agents and returns clean, ranked content plus an optional synthesised
answer. DuckDuckGo remains the keyless fallback, so search keeps working with
no configuration at all.

Provider selection (``search.provider``):

* ``auto``       — Tavily if a key is set, otherwise DuckDuckGo (default);
* ``tavily``     — Tavily only;
* ``duckduckgo`` — DuckDuckGo only.
"""

from __future__ import annotations

import html
import re

import requests

from .base import Tool

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)
_TAVILY_SEARCH_URL = "https://api.tavily.com/search"
_TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"
_DDG_URL = "https://html.duckduckgo.com/html/"


class SearchError(RuntimeError):
    """Raised when a search provider fails and a fallback should be tried."""


# ----------------------------------------------------------------------
# Providers
# ----------------------------------------------------------------------
def tavily_search(
    query: str,
    api_key: str,
    max_results: int = 5,
    depth: str = "basic",
    include_answer: bool = True,
    timeout: int = 30,
) -> str:
    """Search with Tavily and return a compact, model-friendly digest."""

    if not api_key:
        raise SearchError("no Tavily API key")

    payload = {
        "query": query,
        "max_results": max(1, min(int(max_results), 20)),
        "search_depth": "advanced" if depth == "advanced" else "basic",
        "include_answer": bool(include_answer),
    }
    try:
        response = requests.post(
            _TAVILY_SEARCH_URL,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise SearchError(f"Tavily request failed: {exc}") from exc

    if response.status_code == 401:
        raise SearchError("Tavily rejected the API key (401).")
    if response.status_code == 429:
        raise SearchError("Tavily rate limit reached (429).")
    if response.status_code >= 400:
        raise SearchError(f"Tavily returned HTTP {response.status_code}.")

    try:
        data = response.json()
    except ValueError as exc:
        raise SearchError("Tavily returned an unreadable response.") from exc

    lines: list[str] = []
    answer = (data.get("answer") or "").strip()
    if answer:
        lines.append(f"Answer: {answer}\n")

    results = data.get("results") or []
    if not results and not answer:
        raise SearchError("Tavily returned no results.")

    for index, item in enumerate(results, start=1):
        title = (item.get("title") or "").strip()
        url = (item.get("url") or "").strip()
        content = " ".join((item.get("content") or "").split())[:600]
        lines.append(f"{index}. {title}\n   {url}\n   {content}")

    return "\n".join(lines).strip()


def duckduckgo_search(query: str, max_results: int = 5, timeout: int = 20) -> str:
    """Keyless fallback search."""

    try:  # the maintained library, when installed
        from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            hits = list(ddgs.text(query, max_results=max_results))
        if hits:
            return "\n".join(
                f"{i}. {h.get('title', '')}\n   {h.get('href', '')}\n   {h.get('body', '')[:400]}"
                for i, h in enumerate(hits, start=1)
            )
    except ImportError:
        pass
    except Exception:  # noqa: BLE001 - fall back to scraping
        pass

    try:
        response = requests.post(
            _DDG_URL,
            data={"q": query},
            headers={"User-Agent": _USER_AGENT},
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise SearchError(f"DuckDuckGo request failed: {exc}") from exc

    pattern = re.compile(
        r'<a[^>]*class="result__a"[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>',
        re.DOTALL,
    )
    lines = []
    for index, match in enumerate(pattern.finditer(response.text), start=1):
        title = html.unescape(re.sub(r"<[^>]+>", "", match.group("title"))).strip()
        lines.append(f"{index}. {title}\n   {html.unescape(match.group('url'))}")
        if index >= max_results:
            break

    if not lines:
        raise SearchError("DuckDuckGo returned no results.")
    return "\n".join(lines)


# ----------------------------------------------------------------------
# Tools
# ----------------------------------------------------------------------
class WebSearchTool(Tool):
    name = "web_search"
    description = (
        "Search the internet for current information and return ranked results "
        "with short summaries. Use it whenever the answer may have changed "
        "recently or is not part of your knowledge."
    )
    category = "web"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for."},
            "max_results": {
                "type": "integer",
                "description": "How many results to return (default from config).",
            },
            "depth": {
                "type": "string",
                "enum": ["basic", "advanced"],
                "description": "Tavily only: 'advanced' digs deeper but is slower.",
            },
        },
        "required": ["query"],
    }

    def __init__(self, search_config=None):
        from ..config import SearchConfig

        self.config = search_config or SearchConfig()

    def _order(self) -> list[str]:
        provider = (self.config.provider or "auto").lower()
        if provider == "tavily":
            return ["tavily"]
        if provider in {"duckduckgo", "ddg"}:
            return ["duckduckgo"]
        return ["tavily", "duckduckgo"] if self.config.tavily_api_key else ["duckduckgo"]

    def run(self, query: str, max_results: int | None = None, depth: str | None = None) -> str:
        limit = int(max_results or self.config.max_results)
        errors: list[str] = []

        for provider in self._order():
            try:
                if provider == "tavily":
                    result = tavily_search(
                        query,
                        api_key=self.config.tavily_api_key,
                        max_results=limit,
                        depth=depth or self.config.depth,
                        include_answer=self.config.include_answer,
                    )
                    return f"Search results (Tavily) for '{query}':\n\n{result}"
                result = duckduckgo_search(query, max_results=limit)
                prefix = "Search results (DuckDuckGo)"
                if errors:
                    prefix += " — Tavily unavailable"
                return f"{prefix} for '{query}':\n\n{result}"
            except SearchError as exc:
                errors.append(f"{provider}: {exc}")

        return "Search failed. " + "; ".join(errors)


class WebFetchTool(Tool):
    name = "web_fetch"
    description = (
        "Download a web page and return its readable text. Use after web_search "
        "when you need the full content of a specific page."
    )
    category = "web"
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The page URL."},
            "max_chars": {
                "type": "integer",
                "description": "Maximum characters to return (default 6000).",
                "default": 6000,
            },
        },
        "required": ["url"],
    }

    def __init__(self, search_config=None):
        from ..config import SearchConfig

        self.config = search_config or SearchConfig()

    # -- extraction ----------------------------------------------------
    def _tavily_extract(self, url: str, timeout: int = 30) -> str:
        if not self.config.tavily_api_key:
            raise SearchError("no Tavily API key")
        response = requests.post(
            _TAVILY_EXTRACT_URL,
            json={"urls": [url]},
            headers={"Authorization": f"Bearer {self.config.tavily_api_key}"},
            timeout=timeout,
        )
        if response.status_code >= 400:
            raise SearchError(f"Tavily extract returned HTTP {response.status_code}")
        results = (response.json() or {}).get("results") or []
        if not results:
            raise SearchError("Tavily extract returned nothing")
        return (results[0].get("raw_content") or "").strip()

    @staticmethod
    def _plain_fetch(url: str, timeout: int = 25) -> str:
        response = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=timeout)
        response.raise_for_status()
        markup = response.text

        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(markup, "html.parser")
            for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
                tag.decompose()
            text = soup.get_text(separator="\n")
        except ImportError:
            text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", markup, flags=re.DOTALL | re.I)
            text = html.unescape(re.sub(r"<[^>]+>", " ", text))

        return "\n".join(line.strip() for line in text.splitlines() if line.strip())

    def run(self, url: str, max_chars: int = 6000) -> str:
        text = ""
        try:
            text = self._tavily_extract(url)
        except (SearchError, requests.RequestException, ValueError):
            text = ""

        if not text:
            try:
                text = self._plain_fetch(url)
            except requests.RequestException as exc:
                return f"Error fetching {url}: {exc}"

        if not text:
            return f"No readable text found at {url}."
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n...[truncated at {max_chars} chars]"
        return f"Content of {url}:\n\n{text}"
