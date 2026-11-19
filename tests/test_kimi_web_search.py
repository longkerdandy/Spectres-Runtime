"""Unit tests for the Kimi web search Toolkit."""

import json
from typing import Any, Literal, cast

import httpx
import pytest

from spectres.tools.kimi_web_search import MAX_OUTPUT_CHARACTERS, MAX_RESULTS, KimiWebSearchTools

pytestmark = pytest.mark.unit

TEST_BASE_URL = "https://kimi.example.com/search"
TEST_API_KEY = "test-secret-key"
SearchMode = Literal["sync", "async"]


@pytest.fixture
def tools() -> KimiWebSearchTools:
    """Create a Toolkit pointed at a synthetic endpoint."""
    return KimiWebSearchTools(api_key=TEST_API_KEY, base_url=TEST_BASE_URL)


def _install_mock_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler: Any,
) -> dict[str, list[int | None]]:
    timeouts: dict[str, list[int | None]] = {"sync": [], "async": []}
    transport = httpx.MockTransport(handler)
    client_class = httpx.Client
    async_client_class = httpx.AsyncClient

    def client_factory(*args: Any, **kwargs: Any) -> httpx.Client:
        timeouts["sync"].append(cast(int | None, kwargs.get("timeout")))
        return client_class(*args, transport=transport, **kwargs)

    def async_client_factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        timeouts["async"].append(cast(int | None, kwargs.get("timeout")))
        return async_client_class(*args, transport=transport, **kwargs)

    monkeypatch.setattr("spectres.tools.kimi_web_search.httpx.Client", client_factory)
    monkeypatch.setattr("spectres.tools.kimi_web_search.httpx.AsyncClient", async_client_factory)
    return timeouts


async def _call_search(tools: KimiWebSearchTools, mode: SearchMode, query: str) -> str:
    functions = tools.get_functions() if mode == "sync" else tools.get_async_functions()
    entrypoint = functions["web_search_using_kimi"].entrypoint
    assert entrypoint is not None
    result = entrypoint(query)
    if mode == "sync":
        return cast(str, result)
    return cast(str, await result)


def test_agno_function_schema_and_registration(tools: KimiWebSearchTools) -> None:
    """Both Agno surfaces expose one query-only function with usage guidance."""
    assert tools.name == "kimi_web_search"
    assert list(tools.get_functions()) == ["web_search_using_kimi"]
    assert list(tools.get_async_functions()) == ["web_search_using_kimi"]

    for function in (tools.get_functions()["web_search_using_kimi"], tools.get_async_functions()["web_search_using_kimi"]):
        function.process_entrypoint()
        assert function.parameters == {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "(str) The web search query."}},
            "required": ["query"],
        }
        assert function.description is not None
        description = function.description.lower()
        assert "summaries rather than full pages" in description
        assert "read_url" in description
        assert "cite" in description


@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_search_request_and_response_shaping(
    monkeypatch: pytest.MonkeyPatch,
    tools: KimiWebSearchTools,
    mode: SearchMode,
) -> None:
    """The registered entrypoint sends the confirmed request and whitelists results."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == TEST_BASE_URL
        assert request.headers["Authorization"] == f"Bearer {TEST_API_KEY}"
        assert request.headers["Content-Type"] == "application/json"
        assert json.loads(request.content) == {"text_query": "中文 search", "search_mode": "links"}
        return httpx.Response(
            200,
            json={
                "search_results": [
                    {
                        "title": "结果",
                        "url": "https://example.com/article",
                        "snippet": "摘要",
                        "date": "2026-11-12",
                        "site_name": "Example",
                        "content": "full upstream content must not be exposed",
                        "icon": "https://example.com/icon.png",
                        "mime": "text/html",
                    }
                ],
                "ignored": "upstream metadata",
            },
        )

    timeouts = _install_mock_transport(monkeypatch, handler)
    output = await _call_search(tools, mode, "  中文 search  ")

    assert "中文" in output
    assert json.loads(output) == {
        "query": "中文 search",
        "results": [
            {
                "title": "结果",
                "url": "https://example.com/article",
                "snippet": "摘要",
                "date": "2026-11-12",
                "site_name": "Example",
            }
        ],
        "truncated": False,
    }
    assert timeouts[mode] == [15]


@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_empty_results_are_successful(
    monkeypatch: pytest.MonkeyPatch,
    tools: KimiWebSearchTools,
    mode: SearchMode,
) -> None:
    """An empty search_results array is a valid empty response."""
    _install_mock_transport(monkeypatch, lambda request: httpx.Response(200, json={"search_results": []}))

    output = json.loads(await _call_search(tools, mode, "query"))

    assert output == {"query": "query", "results": [], "truncated": False}


@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_blank_query_makes_no_request(
    monkeypatch: pytest.MonkeyPatch,
    tools: KimiWebSearchTools,
    mode: SearchMode,
) -> None:
    """Blank input returns a controlled error without network activity."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("A blank query must not make an HTTP request")

    _install_mock_transport(monkeypatch, handler)

    output = json.loads(await _call_search(tools, mode, "  \t "))

    assert output["query"] == ""
    assert output["results"] == []
    assert output["error"]["type"] == "invalid_query"


@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_result_count_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
    tools: KimiWebSearchTools,
    mode: SearchMode,
) -> None:
    """No more than ten results are returned and truncation is reported."""
    results = [{"title": f"Result {index}", "url": f"https://example.com/{index}", "snippet": "summary"} for index in range(MAX_RESULTS + 2)]
    _install_mock_transport(monkeypatch, lambda request: httpx.Response(200, json={"search_results": results}))

    output = json.loads(await _call_search(tools, mode, "bounded"))

    assert len(output["results"]) == MAX_RESULTS
    assert output["results"][-1]["url"] == "https://example.com/9"
    assert output["truncated"] is True


@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_oversized_snippet_is_shortened_without_dropping_only_result(
    monkeypatch: pytest.MonkeyPatch,
    tools: KimiWebSearchTools,
    mode: SearchMode,
) -> None:
    """A single oversized result remains present as bounded valid JSON."""
    results = [{"title": "Result", "url": "https://example.com/0", "snippet": "x" * 30_000}]
    _install_mock_transport(monkeypatch, lambda request: httpx.Response(200, json={"search_results": results}))

    serialized = await _call_search(tools, mode, "bounded")
    output = json.loads(serialized)

    assert len(serialized) <= MAX_OUTPUT_CHARACTERS
    assert len(output["results"]) == 1
    assert output["results"][0]["url"] == "https://example.com/0"
    assert 0 < len(output["results"][0]["snippet"]) < 30_000
    assert output["truncated"] is True


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize(
    ("body", "content_type"),
    [
        ("not-json", "text/plain"),
        ("{}", "application/json"),
        ('{"search_results": {}}', "application/json"),
        ('{"search_results": [{"url": 123}]}', "application/json"),
    ],
)
async def test_malformed_success_responses_are_controlled(
    monkeypatch: pytest.MonkeyPatch,
    tools: KimiWebSearchTools,
    mode: SearchMode,
    body: str,
    content_type: str,
) -> None:
    """Malformed JSON and schemas return the same safe invalid-response error."""
    _install_mock_transport(
        monkeypatch,
        lambda request: httpx.Response(200, text=body, headers={"Content-Type": content_type}),
    )

    output = json.loads(await _call_search(tools, mode, "query"))

    assert output == {
        "query": "query",
        "results": [],
        "error": {"type": "invalid_response", "message": "Kimi web search returned an invalid response."},
    }


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize(
    ("status", "error_type"),
    [(401, "authentication"), (403, "authentication"), (429, "rate_limit"), (500, "http"), (201, "http")],
)
async def test_http_failures_are_mapped_without_response_body_leaks(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tools: KimiWebSearchTools,
    mode: SearchMode,
    status: int,
    error_type: str,
) -> None:
    """HTTP errors preserve only their category and status, never the body."""
    _install_mock_transport(monkeypatch, lambda request: httpx.Response(status, text=f"secret response: {TEST_API_KEY}"))

    serialized = await _call_search(tools, mode, "query")
    output = json.loads(serialized)

    assert output["results"] == []
    assert output["error"]["type"] == error_type
    assert output["error"]["status"] == status
    assert TEST_API_KEY not in serialized
    assert "secret response" not in serialized
    assert TEST_API_KEY not in caplog.text
    assert "secret response" not in caplog.text


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize(
    ("exception_class", "error_type"),
    [(httpx.ReadTimeout, "timeout"), (httpx.ConnectError, "network")],
)
async def test_transport_failures_are_mapped_without_credential_leaks(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tools: KimiWebSearchTools,
    mode: SearchMode,
    exception_class: type[httpx.RequestError],
    error_type: str,
) -> None:
    """Timeout and network errors do not expose exception credential text."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise exception_class(f"synthetic failure containing {TEST_API_KEY}", request=request)

    _install_mock_transport(monkeypatch, handler)

    serialized = await _call_search(tools, mode, "query")
    output = json.loads(serialized)

    assert output["error"]["type"] == error_type
    assert "status" not in output["error"]
    assert TEST_API_KEY not in serialized
    assert TEST_API_KEY not in caplog.text
