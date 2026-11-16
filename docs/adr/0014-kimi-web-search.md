# ADR 0014: Configurable Kimi Web Search with Tavily Alternative

- **Status**: Accepted
- **Date**: 2026-11-12
- **Updated**: 2026-11-16
- **Deciders**: Project owner + architecture discussion
- **Amends**: ADR 0006 backend selection; its Tavily integration remains a selectable alternative

## Context

ADR 0006 adopted Agno's `TavilyTools` after unreliable meta-search experiments.
That integration provides agent-oriented search results and remains useful, but
Runtime now also has access to Kimi's authenticated web-search API. The Kimi
endpoint returns source titles, URLs, and snippets, matching Runtime's existing
search-plus-page-read model without importing Kimi Code or sharing its OAuth
credentials.

The search backend must be selectable through explicit Runtime configuration.
Registering both backends would expose duplicate capabilities with different
function names and make backend selection dependent on model behavior. Implicit
selection based on which credentials happen to be present would also make a
missing or unintended credential change the effective backend selector.

## Decision

Implement a custom Agno `KimiWebSearchTools` Toolkit and select exactly one
optional web-search backend through `WEB_SEARCH_BACKEND`:

1. `WEB_SEARCH_BACKEND=kimi` is the default. Register only Kimi when
   `KIMI_WEB_SEARCH_API_KEY` is non-blank.
2. `WEB_SEARCH_BACKEND=tavily` selects the existing Tavily Toolkit at
   `search_depth="basic"` when `TAVILY_API_KEY` is configured.
3. If the selected backend has no credential, register no web-search Toolkit.
   Never register or fall back to an unselected backend, even when its credential
   is present.

The setting is a typed enum-like configuration value so future backends require
an explicit allowed-value extension and a corresponding registration branch.
Kimi and Tavily have independent configuration sections. The committed examples
leave Tavily commented out because Kimi is the default selection.

`KIMI_WEB_SEARCH_BASE_URL` defaults to
`https://api.kimi.com/coding/v1/search` and may select another compatible
endpoint. Calculator, Shell, and `WebsiteTools.read_url` registration remain
unchanged. Kimi returns summaries; full-page reads continue through `read_url`.

The Toolkit exposes one public function, `web_search_using_kimi`, with one
required `query: str` argument in both synchronous and asynchronous Agno
registration. It sends a bearer-authenticated POST containing `text_query` and
`search_mode: "links"`, uses per-call HTTP clients with a 15-second timeout,
and does not retry automatically.

Successful responses are validated and restricted to title, URL, snippet, date,
and site name. Output is UTF-8 JSON with at most ten results and 20,000
serialized characters; truncation preserves valid JSON and shortens oversized
snippets. HTTP, authentication, rate-limit, timeout, network, and malformed
response failures return controlled JSON errors. Credentials and upstream error
bodies are not included in tool errors or logs.

This decision adds no OAuth login or token refresh, provider-native search,
custom AG-UI events, page fetching, caching, retry, rate-limiting, automatic
provider fallback, or per-user credential mechanism.

## Alternatives Considered

- **Retain Tavily as the only backend**: preserves the existing implementation
  but does not make the available Kimi API accessible. Rejected.
- **Replace Tavily with Kimi**: simplifies the dependency and configuration
  surface but removes a working alternative for installations that explicitly
  select Tavily. Rejected.
- **Select implicitly from available credentials**: provides automatic fallback
  but makes configuration order and unrelated credentials control behavior.
  Rejected in favor of explicit selection.
- **Register Kimi and Tavily together**: allows the model to choose per query
  but creates ambiguous backend selection and duplicate search capabilities.
  Rejected.
- **Import Kimi Code or reuse its OAuth files**: couples Runtime to another
  application's internals and credential lifecycle. Rejected.
- **Use provider-native model search**: would make availability and behavior
  model-specific and would not implement the confirmed Kimi endpoint contract.
  Not adopted.

## Consequences

- Kimi is the default search backend without removing Tavily, `tavily-python`,
  or existing Tavily credentials.
- Selecting Tavily requires `WEB_SEARCH_BACKEND=tavily` and its own credential.
  Merely configuring `TAVILY_API_KEY` no longer activates Tavily.
- Runtime owns a small HTTP and response-shaping implementation with sync/async
  unit coverage rather than depending on a Kimi SDK.
- Search credentials remain process-wide optional configuration. A missing
  credential for the selected backend means no search Toolkit, while Runtime and
  page reading still start normally.
- Adding another backend requires extending `WEB_SEARCH_BACKEND`'s typed values,
  adding an isolated Toolkit and credential section, and covering the selection
  matrix. No dispatch registry is introduced.
- Tool results are bounded and credential-safe; source citation remains the
  model's responsibility, guided by the function docstring.
- ADR 0006 remains the historical record for choosing Tavily over meta-search
  and other alternatives. Its backend preference is amended: Tavily is now an
  explicitly selectable alternative rather than the sole official search API.

## References

- ADR 0006: Web Search Tool — from ddgs Meta-Search to Tavily
- `src/spectres/tools/kimi_web_search.py`
- `src/spectres/tools/builtin.py`
- `docs/plan/v0.7.3-kimi-web-search.md`
