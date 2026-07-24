"""Internet access tools: web search and page fetching."""

from __future__ import annotations

import re
from html import unescape
from typing import Any

import requests

from .base import Tool

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)


class WebSearchTool(Tool):
    name = "web_search"
    description = (
        "Search the web and return a list of results (title, URL, snippet). "
        "Use this to find current information before answering."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query."},
            "max_results": {
                "type": "integer",
                "description": "How many results to return (default 5).",
                "default": 5,
            },
        },
        "required": ["query"],
    }

    def run(self, query: str, max_results: int = 5) -> str:
        results = self._search_duckduckgo_lib(query, max_results)
        if results is None:
            results = self._search_html_fallback(query, max_results)
        if not results:
            return f"No results found for '{query}'."

        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r['title']}\n   {r['url']}\n   {r['snippet']}")
        return "\n".join(lines)

    @staticmethod
    def _search_duckduckgo_lib(query: str, max_results: int) -> list[dict[str, str]] | None:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return None
        try:
            with DDGS() as ddgs:
                hits = list(ddgs.text(query, max_results=max_results))
        except Exception:  # noqa: BLE001 - fall back to raw HTTP
            return None
        return [
            {
                "title": h.get("title", ""),
                "url": h.get("href", ""),
                "snippet": h.get("body", ""),
            }
            for h in hits
        ]

    @staticmethod
    def _search_html_fallback(query: str, max_results: int) -> list[dict[str, str]]:
        try:
            resp = requests.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query},
                headers={"User-Agent": _USER_AGENT},
                timeout=20,
            )
            resp.raise_for_status()
        except requests.RequestException:
            return []

        pattern = re.compile(
            r'<a[^>]+class="result__a"[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>',
            re.DOTALL,
        )
        results: list[dict[str, str]] = []
        for match in pattern.finditer(resp.text):
            title = unescape(re.sub(r"<[^>]+>", "", match.group("title"))).strip()
            results.append({"title": title, "url": match.group("url"), "snippet": ""})
            if len(results) >= max_results:
                break
        return results


class WebFetchTool(Tool):
    name = "web_fetch"
    description = (
        "Fetch a web page by URL and return its readable text content. "
        "Use after web_search to read a specific page."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The URL to fetch."},
            "max_chars": {
                "type": "integer",
                "description": "Truncate the extracted text to this many characters (default 6000).",
                "default": 6000,
            },
        },
        "required": ["url"],
    }

    def run(self, url: str, max_chars: int = 6000) -> str:
        try:
            resp = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as exc:
            return f"Error fetching {url}: {exc}"

        text = self._extract_text(resp.text)
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n...[truncated at {max_chars} chars]"
        return f"# Content of {url}\n\n{text}"

    @staticmethod
    def _extract_text(html: str) -> str:
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
                tag.decompose()
            text = soup.get_text("\n")
        except ImportError:
            text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", html)
            text = re.sub(r"(?s)<[^>]+>", "", text)
            text = unescape(text)

        lines = [line.strip() for line in text.splitlines()]
        return "\n".join(line for line in lines if line)
