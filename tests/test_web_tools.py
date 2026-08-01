from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from coco_code.tools import create_default_registry
from coco_code.tools.web import (
    WebFetch,
    WebFetchParams,
    WebSearch,
    WebSearchParams,
    _ensure_public_url,
    _extract_readable_html,
)


@pytest.mark.asyncio
async def test_web_search_parses_results_and_unwraps_urls() -> None:
    html = """
    <div class="result">
      <h2><a class="result__a"
        href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fdocs">
        Example Documentation
      </a></h2>
      <a class="result__snippet">Current API documentation.</a>
    </div>
    """

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["q"] == "example API"
        return httpx.Response(200, text=html, request=request)

    tool = WebSearch(transport=httpx.MockTransport(handler))
    result = await tool.execute(
        WebSearchParams(query="example API", max_results=3)
    )

    assert not result.is_error
    assert "Example Documentation" in result.output
    assert "https://example.com/docs" in result.output
    assert "Current API documentation." in result.output


@pytest.mark.asyncio
async def test_web_fetch_extracts_text(monkeypatch: pytest.MonkeyPatch) -> None:
    html = """
    <html><head><title>Example Page</title><style>hidden</style></head>
    <body><main><h1>Heading</h1><p>Hello <b>world</b>.</p></main>
    <script>ignored()</script></body></html>
    """

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=html,
            headers={"content-type": "text/html; charset=utf-8"},
            request=request,
        )

    monkeypatch.setattr(
        "coco_code.tools.web._ensure_public_url", AsyncMock()
    )
    tool = WebFetch(transport=httpx.MockTransport(handler))
    result = await tool.execute(WebFetchParams(url="https://example.com"))

    assert not result.is_error
    assert "Title: Example Page" in result.output
    assert "Heading" in result.output
    assert "Hello world." in result.output
    assert "ignored()" not in result.output
    assert "hidden" not in result.output


@pytest.mark.asyncio
async def test_web_fetch_validates_every_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checked: list[str] = []

    async def validate(url: str) -> None:
        checked.append(url)
        if "127.0.0.1" in url:
            raise ValueError("private address")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"location": "http://127.0.0.1/admin"},
            request=request,
        )

    monkeypatch.setattr("coco_code.tools.web._ensure_public_url", validate)
    tool = WebFetch(transport=httpx.MockTransport(handler))
    result = await tool.execute(WebFetchParams(url="https://example.com"))

    assert result.is_error
    assert checked == [
        "https://example.com",
        "http://127.0.0.1/admin",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1/admin",
        "http://10.0.0.1/",
        "http://[::1]/",
    ],
)
async def test_web_fetch_blocks_non_public_urls(url: str) -> None:
    with pytest.raises(ValueError):
        await _ensure_public_url(url)


def test_html_extraction_omits_active_content() -> None:
    title, text = _extract_readable_html(
        "<title>Docs</title><nav>Navigation</nav>"
        "<main><p>Visible</p><script>secret()</script></main>"
    )
    assert title == "Docs"
    assert "Visible" in text
    assert "Navigation" not in text
    assert "secret" not in text


def test_default_registry_exposes_web_tools_immediately() -> None:
    registry = create_default_registry()
    names = {schema["name"] for schema in registry.get_all_schemas()}
    assert {"WebSearch", "WebFetch"} <= names
