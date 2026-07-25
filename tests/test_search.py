"""Tavily-first web search with a DuckDuckGo fallback."""

from __future__ import annotations

import jarvis.tools.web as web
from jarvis.config import SearchConfig
from jarvis.tools.web import SearchError, WebSearchTool


def test_provider_order_prefers_tavily_when_a_key_is_present():
    with_key = WebSearchTool(SearchConfig(tavily_api_key="secret"))
    without_key = WebSearchTool(SearchConfig())
    assert with_key._order() == ["tavily", "duckduckgo"]
    assert without_key._order() == ["duckduckgo"]


def test_provider_can_be_pinned():
    pinned = WebSearchTool(SearchConfig(provider="duckduckgo", tavily_api_key="secret"))
    assert pinned._order() == ["duckduckgo"]


def test_tavily_result_is_used(monkeypatch):
    monkeypatch.setattr(web, "tavily_search", lambda *a, **k: "1. Result\n   https://example.com")
    tool = WebSearchTool(SearchConfig(tavily_api_key="secret"))
    output = tool.run("notion ai")
    assert "Tavily" in output and "example.com" in output


def test_falls_back_to_duckduckgo_when_tavily_fails(monkeypatch):
    def broken(*_args, **_kwargs):
        raise SearchError("rate limit")

    monkeypatch.setattr(web, "tavily_search", broken)
    monkeypatch.setattr(web, "duckduckgo_search", lambda *a, **k: "1. Backup result")
    tool = WebSearchTool(SearchConfig(tavily_api_key="secret"))
    output = tool.run("notion ai")
    assert "DuckDuckGo" in output and "Backup result" in output


def test_all_providers_failing_is_reported(monkeypatch):
    def broken(*_args, **_kwargs):
        raise SearchError("down")

    monkeypatch.setattr(web, "tavily_search", broken)
    monkeypatch.setattr(web, "duckduckgo_search", broken)
    tool = WebSearchTool(SearchConfig(tavily_api_key="secret"))
    assert tool.run("anything").startswith("Search failed")
