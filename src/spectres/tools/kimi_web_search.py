"""Kimi web search Toolkit for Agno agents."""

import json
import logging
from typing import Any

import httpx
from agno.tools.toolkit import Toolkit
from pydantic import BaseModel, ConfigDict, ValidationError

logger = logging.getLogger(__name__)

DEFAULT_KIMI_WEB_SEARCH_BASE_URL = "https://api.kimi.com/coding/v1/search"
MAX_RESULTS = 10
MAX_OUTPUT_CHARACTERS = 20_000


class _KimiSearchResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str | None = None
    url: str | None = None
    snippet: str | None = None
    date: str | None = None
    site_name: str | None = None


class _KimiSearchResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    search_results: list[_KimiSearchResult]


class KimiWebSearchTools(Toolkit):
    """Search the web through Kimi's authenticated search API."""

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_KIMI_WEB_SEARCH_BASE_URL,
        timeout: int = 15,
    ) -> None:
        """Initialize the Toolkit with its credential, endpoint, and HTTP timeout."""
        self.api_key = api_key
        self.base_url = base_url
        super().__init__(
            name="kimi_web_search",
            tools=[self.web_search_using_kimi],
            async_tools=[(self._web_search_using_kimi_async, "web_search_using_kimi")],
            timeout=timeout,
        )

    def web_search_using_kimi(self, query: str) -> str:
        """Search the web for current information using Kimi.

        Results contain titles, URLs, and summaries rather than full pages. Cite
        source URLs in the answer, and use read_url when full page content is
        required.

        Args:
            query (str): The web search query.

        Returns:
            str: A JSON object containing bounded search results or a safe error.
        """
        normalized_query = query.strip()
        if not normalized_query:
            return _error_response(normalized_query, "invalid_query", "Search query must not be blank.")
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(self.base_url, **self._request_arguments(normalized_query))
        except httpx.TimeoutException:
            logger.warning("Kimi web search request timed out")
            return _error_response(normalized_query, "timeout", "Kimi web search timed out.")
        except httpx.RequestError as exc:
            logger.warning("Kimi web search network failure: %s", type(exc).__name__)
            return _error_response(normalized_query, "network", "Kimi web search could not reach the service.")
        return self._process_response(normalized_query, response)

    async def _web_search_using_kimi_async(self, query: str) -> str:
        """Search the web for current information using Kimi.

        Results contain titles, URLs, and summaries rather than full pages. Cite
        source URLs in the answer, and use read_url when full page content is
        required.

        Args:
            query (str): The web search query.

        Returns:
            str: A JSON object containing bounded search results or a safe error.
        """
        normalized_query = query.strip()
        if not normalized_query:
            return _error_response(normalized_query, "invalid_query", "Search query must not be blank.")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(self.base_url, **self._request_arguments(normalized_query))
        except httpx.TimeoutException:
            logger.warning("Kimi web search request timed out")
            return _error_response(normalized_query, "timeout", "Kimi web search timed out.")
        except httpx.RequestError as exc:
            logger.warning("Kimi web search network failure: %s", type(exc).__name__)
            return _error_response(normalized_query, "network", "Kimi web search could not reach the service.")
        return self._process_response(normalized_query, response)

    def _request_arguments(self, query: str) -> dict[str, Any]:
        return {
            "headers": {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            "json": {"text_query": query, "search_mode": "links"},
        }

    def _process_response(self, query: str, response: httpx.Response) -> str:
        if response.status_code != 200:
            logger.warning("Kimi web search request failed with HTTP %s", response.status_code)
            if response.status_code in {401, 403}:
                return _error_response(query, "authentication", "Kimi web search authentication failed.", response.status_code)
            if response.status_code == 429:
                return _error_response(query, "rate_limit", "Kimi web search rate limit reached.", response.status_code)
            return _error_response(query, "http", "Kimi web search returned an HTTP error.", response.status_code)
        try:
            parsed = _KimiSearchResponse.model_validate_json(response.content)
        except ValidationError:
            logger.warning("Kimi web search returned an invalid success response")
            return _error_response(query, "invalid_response", "Kimi web search returned an invalid response.")
        return _success_response(query, parsed.search_results)


def _success_response(query: str, upstream_results: list[_KimiSearchResult]) -> str:
    results: list[dict[str, str]] = []
    for result in upstream_results[:MAX_RESULTS]:
        shaped = {
            "title": result.title or "",
            "url": result.url or "",
            "snippet": result.snippet or "",
        }
        if result.date is not None:
            shaped["date"] = result.date
        if result.site_name is not None:
            shaped["site_name"] = result.site_name
        results.append(shaped)

    payload: dict[str, Any] = {"query": query, "results": results, "truncated": len(upstream_results) > MAX_RESULTS}
    while True:
        serialized = _serialize(payload)
        overflow = len(serialized) - MAX_OUTPUT_CHARACTERS
        if overflow <= 0:
            return serialized
        payload["truncated"] = True
        if _shorten_longest_field(results, ("snippet",), overflow + 1):
            continue
        if len(results) > 1:
            results.pop()
            continue
        if _shorten_longest_field(results, ("title", "url", "date", "site_name"), overflow + 1):
            continue
        current_query = payload["query"]
        payload["query"] = current_query[: max(0, len(current_query) - overflow - 1)]


def _shorten_longest_field(results: list[dict[str, str]], fields: tuple[str, ...], characters: int) -> bool:
    candidates = [(len(result[field]), result, field) for result in results for field in fields if result.get(field)]
    if not candidates:
        return False
    length, result, field = max(candidates, key=lambda candidate: candidate[0])
    result[field] = result[field][: max(0, length - characters)]
    return True


def _error_response(query: str, error_type: str, message: str, status: int | None = None) -> str:
    error: dict[str, Any] = {"type": error_type, "message": message}
    if status is not None:
        error["status"] = status
    return _serialize({"query": query, "results": [], "error": error})


def _serialize(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)
