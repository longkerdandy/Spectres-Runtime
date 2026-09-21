# ADR 0006: Web Search Tool — from ddgs Meta-Search to Tavily

- **Status**: Accepted
- **Date**: 2026-09-21
- **Deciders**: Project owner + architecture discussion

## Context

The Team Leader Agent needs web search to answer time-sensitive questions and
to ground its replies in citable sources. The requirements for the single-user
MVP:

- Free tier covers personal-assistant volume (well under 1,000 searches/month).
- Works reliably from the owner's residential network in China.
- Agent-friendly output: clean text the LLM can consume directly, not raw HTML.
- No API key preferred, but reliability takes precedence.

### Attempt 1 — ddgs meta-search (Agno `WebSearchTools`)

We first integrated Agno's `WebSearchTools`, built on the `ddgs` meta-search
library. `ddgs` requires no API key: it simulates browser requests against the
free consumer-facing web search pages of multiple engines (Google, Bing via
DuckDuckGo/Yahoo, Brave, Mojeek, Startpage, Wikipedia, Grokipedia), parses the
HTML, and merges results from several backends in parallel. We paired it with
`WebsiteTools` (`read_url`) so the agent can fetch full page content after
searching.

We then pinned the backend list to `startpage,duckduckgo,brave,mojeek` (four
independent data sources, excluding the rate-limited Google direct path and
the AI-generated Grokipedia) and made it configurable via `SEARCH_BACKEND`.

### Measured reality

Live tests from the owner's machine (each engine queried individually, Chinese
and English queries) showed the meta-search approach is not reliable enough:

| Engine | Result |
|--------|--------|
| Brave | Only consistently successful engine (all queries) |
| DuckDuckGo | Intermittent — often blocked with HTTP 202 anti-bot challenge |
| Startpage | Always failed — proof-of-work challenge (`sp_pow`) blocks scrapers |
| Mojeek | Always failed — HTTP 200 but no parseable results |
| Google | Always failed — HTTP 429 rate-limit / verification page |
| Yahoo | Worked for the Chinese query only |
| Wikipedia / Grokipedia | No useful results for general queries |

In practice the "meta-search" degraded to "Brave plus luck". Scraped HTML
search is fragile by nature: engines change markup, impose proof-of-work, or
rate-limit at will. An official API is required.

### Attempt 2 — official search APIs: Tavily vs Brave

Both candidates offer roughly 1,000 free searches/month:

- **Tavily**: 1,000 free credits/month, no credit card, monthly reset. Purpose
  -built for LLM agents: one call returns an AI-generated answer plus
  pre-extracted clean page content per result. Pricing beyond free tier:
  ~$8/1k (pay-as-you-go).
- **Brave Search API**: $5 free credit/month (≈1,000 searches) with an
  attribution requirement. Independent index (not Google/Bing). Returns
  classic SERP structures (title/URL/snippet); full page content still needs a
  separate fetch. Cheaper at volume ($5/1k). Higher rate limits.

## Decision

Adopt **Tavily** as the web search backend for the Team Leader Agent, via
Agno's `TavilyTools`:

- `TAVILY_API_KEY` configured through the typed settings (`.env`).
- `search_depth` explicitly set to `basic` (1 credit/search). Agno's default
  is `advanced` at 2 credits/search, which would silently halve the free tier
  to 500 searches/month.
- `WebsiteTools` (`read_url`) stays registered as the fallback for full-page
  reads when Tavily's extracted content is insufficient.

Rationale:

1. **Agent-native output**: extracted content plus a direct answer in one call
   — fewer tool round-trips, fewer tokens, better grounded replies.
2. **Free tier fits MVP volume** with zero billing friction (no credit card,
   no attribution obligation).
3. **Reliability**: official API with a contract, replacing measured-unreliable
   HTML scraping.
4. **Reversibility**: the tool registry isolates the choice; swapping backends
   later is a localized change.

## Alternatives Considered

- **Keep ddgs meta-search** (`WebSearchTools`): zero cost and no key, but the
  measured success rate from the owner's network makes it unsuitable as the
  primary path. Rejected.
- **Brave Search API** (`BraveSearchTools`): independent index and cheaper at
  volume, but SERP-only output requires an extra fetch per result, the free
  credit carries an attribution requirement, and sign-up historically requires
  a card on file. Remains the leading fallback if search volume grows past
  Tavily's free tier or if result quality disappoints.
- **Exa**: strong agent-oriented semantic search, but no meaningful advantage
  over Tavily for our use case and a similar price class. Not adopted.
- **Baidu / other scraping-based tools**: same fragility class as ddgs.
  Rejected.
- **Domestic (China) search APIs** (Zhipu BigModel, Volcengine Doubao
  Search): see the dedicated subsection below — a deliberate future option,
  not a current rejection.

### Future option — domestic search APIs via a custom Agno Toolkit

If Tavily's free tier becomes insufficient (volume growth, automation
triggers per ADR 0003, or multi-user use), two mainland-China search APIs are
attractive: domestic-network friendly (no cross-border latency or blocking),
RMB billing at very low per-call prices, and strong Chinese-language
coverage. Neither has an Agno built-in toolkit, so adoption means writing a
small custom Toolkit (an HTTP call wrapped as Agno tool functions).

- **Zhipu BigModel — Search Tool Service**
  ([pricing](https://docs.bigmodel.cn/cn/guide/start/pricing#%E6%90%9C%E7%B4%A2%E5%B7%A5%E5%85%B7%E6%9C%8D%E5%8A%A1)):
  per-call billing, no subscription: Search-Std ¥0.01/call, Search-Pro
  ¥0.03/call, Search-Pro-Sogou ¥0.05/call, Search-Pro-Quark ¥0.05/call.
  1,000 searches/month costs ¥10 on Search-Std — cheaper than Brave ($5/1k)
  and far cheaper than pay-as-you-go Tavily ($8/1k).
- **Volcengine Doubao Search** (豆包搜索, formerly 联网搜索/融合信息搜索)
  ([product intro](https://docs.volcengine.com/docs/Networkedsearch/Onlinesearchproductintroduction?lang=zh),
  [billing](https://docs.volcengine.com/docs/Networkedsearch/Onlinesearchproductbilling?lang=zh)):
  built for LLM consumption — returns titles, length-controllable summaries,
  publish time, full page text (txt/markdown), site authority scores, and
  query-relevance rerank scores; supports domain/time filtering and
  ICP-filed-site restriction. Monthly plans from ¥5.9 (1,000 calls, 50/day
  cap) or ¥9.9 (2,000 calls, 100/day cap); pay-as-you-go ¥0.020/call.

Not adopted now because Tavily's free tier covers MVP volume at zero cost
and zero development effort. Revisit when monthly searches exceed ~1,000 or
when Chinese-result quality becomes the bottleneck; Doubao Search's
full-text (markdown) output is the closest match to Tavily's agent-native
shape.

## Consequences

- Runtime now requires `TAVILY_API_KEY` in `.env`; without it the search tool
  fails fast at startup (Agno raises on a missing key).
- `tavily-python` becomes a dependency; `ddgs` and `beautifulsoup4` may be
  removed if `WebSearchTools` is dropped (kept only if we retain a scraping
  fallback).
- `SEARCH_BACKEND` and the ddgs backend experiments are superseded by this
  decision; the configuration surface shifts to Tavily parameters
  (`search_depth`, `max_results`).
- At MVP scale (<1,000 basic searches/month) cost stays at $0. If volume
  grows, revisit Brave Search API, a paid Tavily plan, or a custom Toolkit
  over a domestic search API (see "Future option" above).
