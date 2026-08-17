from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
from collections.abc import Callable
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from pydantic import BaseModel, Field

from coco_code.tools.base import Tool, ToolResult

_SEARCH_URL = "https://html.duckduckgo.com/html/"
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_REDIRECTS = 5
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0 Safari/537.36 CoCo-Code/0.2"
)
_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/json,text/plain;q=0.9,*/*;q=0.1",
    "Accept-Language": "en-US,en;q=0.8",
}
_BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "br", "dd", "div", "dl",
    "dt", "figcaption", "figure", "footer", "h1", "h2", "h3", "h4",
    "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p",
    "pre", "section", "table", "tbody", "td", "tfoot", "th", "thead",
    "tr", "ul",
}
_SKIP_TAGS = {"script", "style", "noscript", "svg", "template"}


class WebSearchParams(BaseModel):
    query: str = Field(min_length=1, max_length=500, description="Web search query")
    max_results: int = Field(default=5, ge=1, le=10)
    timeout: int = Field(default=20, ge=5, le=60, description="Request timeout in seconds")


class WebFetchParams(BaseModel):
    url: str = Field(description="Public HTTP or HTTPS URL to read")
    max_chars: int = Field(default=12000, ge=1000, le=50000)
    timeout: int = Field(default=30, ge=5, le=60, description="Request timeout in seconds")


class _SearchParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._field: str | None = None
        self._field_depth = 0
        self._parts: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if self._field is not None:
            self._field_depth += 1
            return

        attr_map = dict(attrs)
        classes = set((attr_map.get("class") or "").split())
        is_title = bool({"result__a", "result-link"} & classes)
        is_snippet = bool({"result__snippet", "result-snippet"} & classes)

        if is_title and tag == "a":
            self._finish_current()
            self._current = {
                "title": "",
                "url": _unwrap_search_url(attr_map.get("href") or ""),
                "snippet": "",
            }
            self._start_capture("title")
        elif is_snippet and self._current is not None:
            self._start_capture("snippet")

    def handle_endtag(self, _tag: str) -> None:
        if self._field is None:
            return
        self._field_depth -= 1
        if self._field_depth > 0:
            return
        value = _clean_text(" ".join(self._parts))
        if self._current is not None:
            self._current[self._field] = value
        self._field = None
        self._parts = []

    def handle_data(self, data: str) -> None:
        if self._field is not None:
            self._parts.append(data)

    def finish(self) -> list[dict[str, str]]:
        self._finish_current()
        seen: set[str] = set()
        unique: list[dict[str, str]] = []
        for result in self.results:
            url = result["url"]
            if url in seen:
                continue
            seen.add(url)
            unique.append(result)
        return unique

    def _start_capture(self, field: str) -> None:
        self._field = field
        self._field_depth = 1
        self._parts = []

    def _finish_current(self) -> None:
        if not self._current:
            return
        if self._current["title"] and _is_http_url(self._current["url"]):
            self.results.append(self._current)
        self._current = None


class _ReadableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.focused_parts: list[str] = []
        self.title_parts: list[str] = []
        self._skip_depth = 0
        self._title_depth = 0
        self._focus_depth = 0
        self._focus_seen = False

    def handle_starttag(
        self, tag: str, _attrs: list[tuple[str, str | None]]
    ) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._title_depth += 1
        if tag in {"main", "article"}:
            self._focus_depth += 1
            self._focus_seen = True
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
            if self._focus_depth:
                self.focused_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "title" and self._title_depth:
            self._title_depth -= 1
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
            if self._focus_depth:
                self.focused_parts.append("\n")
        if tag in {"main", "article"} and self._focus_depth:
            self._focus_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        self.parts.append(data)
        if self._focus_depth:
            self.focused_parts.append(data)
        if self._title_depth:
            self.title_parts.append(data)


class WebSearch(Tool):
    name = "WebSearch"
    description = (
        "Search the public web for current information. Returns result titles, "
        "URLs, and snippets. Use WebFetch to read a selected result."
    )
    params_model = WebSearchParams
    category = "read"
    is_concurrency_safe = True

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def execute(self, params: WebSearchParams) -> ToolResult:
        try:
            async with httpx.AsyncClient(
                headers=_HEADERS,
                timeout=params.timeout,
                transport=self._transport,
            ) as client:
                response = await client.get(
                    _SEARCH_URL,
                    params={"q": params.query, "kl": "wt-wt"},
                    follow_redirects=True,
                )
                response.raise_for_status()
        except httpx.TimeoutException:
            return ToolResult(output="Web search timed out.", is_error=True)
        except httpx.HTTPError as exc:
            return ToolResult(output=f"Web search failed: {exc}", is_error=True)

        parser = _SearchParser()
        parser.feed(response.text)
        parser.close()
        results = parser.finish()[:params.max_results]
        if not results:
            return ToolResult(
                output="Web search returned no parseable results. Try a different query.",
                is_error=True,
            )

        lines = [f"Search results for: {params.query}"]
        for index, result in enumerate(results, 1):
            lines.extend([
                "",
                f"{index}. {result['title']}",
                f"   URL: {result['url']}",
            ])
            if result["snippet"]:
                lines.append(f"   Snippet: {result['snippet']}")
        return ToolResult(output="\n".join(lines))


class WebFetch(Tool):
    name = "WebFetch"
    description = (
        "Fetch a public HTTP or HTTPS page and extract readable text. "
        "Use it to inspect sources returned by WebSearch."
    )
    params_model = WebFetchParams
    category = "read"
    is_concurrency_safe = True

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def execute(self, params: WebFetchParams) -> ToolResult:
        current_url = params.url
        try:
            async with httpx.AsyncClient(
                headers=_HEADERS,
                timeout=params.timeout,
                transport=self._transport,
            ) as client:
                for _ in range(_MAX_REDIRECTS + 1):
                    await _ensure_public_url(current_url)
                    async with client.stream(
                        "GET", current_url, follow_redirects=False
                    ) as response:
                        if response.is_redirect:
                            location = response.headers.get("location")
                            if not location:
                                return ToolResult(
                                    output="Web fetch received a redirect without a location.",
                                    is_error=True,
                                )
                            current_url = urljoin(str(response.url), location)
                            continue

                        response.raise_for_status()
                        body, download_truncated = await _read_limited(response)
                        content_type = response.headers.get(
                            "content-type", ""
                        ).lower()
                        final_url = str(response.url)
                        break
                else:
                    return ToolResult(
                        output=f"Web fetch exceeded {_MAX_REDIRECTS} redirects.",
                        is_error=True,
                    )
        except ValueError as exc:
            return ToolResult(output=f"Web fetch blocked: {exc}", is_error=True)
        except httpx.TimeoutException:
            return ToolResult(output="Web fetch timed out.", is_error=True)
        except httpx.HTTPError as exc:
            return ToolResult(output=f"Web fetch failed: {exc}", is_error=True)

        charset = response.charset_encoding or "utf-8"
        try:
            text = body.decode(charset, errors="replace")
        except LookupError:
            text = body.decode("utf-8", errors="replace")
        title = ""
        if "html" in content_type:
            title, text = _extract_readable_html(text)
        elif "json" in content_type:
            try:
                text = json.dumps(
                    json.loads(text), ensure_ascii=False, indent=2
                )
            except json.JSONDecodeError:
                pass
        elif not (
            content_type.startswith("text/")
            or "xml" in content_type
            or not content_type
        ):
            return ToolResult(
                output=f"Unsupported web content type: {content_type}",
                is_error=True,
            )

        text = text[:params.max_chars]
        output = [f"URL: {final_url}"]
        if title:
            output.append(f"Title: {title}")
        output.extend(["", text or "(page contained no readable text)"])
        if download_truncated or len(text) >= params.max_chars:
            output.append("\n[content truncated]")
        return ToolResult(output="\n".join(output))


async def _read_limited(
    response: httpx.Response,
) -> tuple[bytes, bool]:
    body = bytearray()
    truncated = False
    async for chunk in response.aiter_bytes():
        remaining = _MAX_RESPONSE_BYTES - len(body)
        if remaining <= 0:
            truncated = True
            break
        body.extend(chunk[:remaining])
        if len(chunk) > remaining:
            truncated = True
            break
    return bytes(body), truncated


async def _ensure_public_url(
    url: str,
    resolver: Callable[..., Any] = socket.getaddrinfo,
) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("only HTTP and HTTPS URLs are allowed")
    if not parsed.hostname:
        raise ValueError("URL has no hostname")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("credentials in URLs are not allowed")

    try:
        addresses = [ipaddress.ip_address(parsed.hostname)]
    except ValueError:
        try:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            records = await asyncio.to_thread(
                resolver, parsed.hostname, port, type=socket.SOCK_STREAM
            )
        except (OSError, ValueError) as exc:
            raise ValueError(f"hostname could not be resolved: {exc}") from exc
        addresses = list({ipaddress.ip_address(record[4][0]) for record in records})

    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("local, private, or reserved network addresses are not allowed")


def _extract_readable_html(source: str) -> tuple[str, str]:
    parser = _ReadableHTMLParser()
    parser.feed(source)
    parser.close()
    title = _clean_text(" ".join(parser.title_parts))
    parts = parser.focused_parts if parser._focus_seen else parser.parts
    lines = []
    for line in "".join(parts).splitlines():
        clean = _clean_text(line)
        if clean and (not lines or lines[-1] != clean):
            lines.append(clean)
    return title, "\n".join(lines)


def _unwrap_search_url(url: str) -> str:
    if url.startswith("//"):
        url = f"https:{url}"
    elif url.startswith("/"):
        url = urljoin("https://duckduckgo.com", url)
    parsed = urlsplit(url)
    if parsed.hostname and parsed.hostname.endswith("duckduckgo.com"):
        target = parse_qs(parsed.query).get("uddg")
        if target:
            return target[0]
    return url


def _is_http_url(url: str) -> bool:
    return urlsplit(url).scheme in {"http", "https"}


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
