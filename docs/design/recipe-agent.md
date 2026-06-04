# Recipe Agent — Architecture & Design

**Status:** design stage. Version-independent. This document captures the durable
architecture, domain model, and design decisions of the recipe agent. The
per-release *work breakdown* lives in the version plans under
[`docs/plans/`](../plans/), starting with
[`v0.2-recipe-agent-skeleton.md`](../plans/v0.2-recipe-agent-skeleton.md).

It is a component-level design under the Runtime-wide architecture in
[`Agents.md`](../../Agents.md); concepts referenced here (AgentOS, User Memory
store, Knowledge/RAG, Hooks, Postgres+pgvector) are defined there.

---

## 1. Facts vs. Capability

Two concerns are kept separate:

| Layer | Owned by | Responsibility |
|---|---|---|
| **Fact layer** | Knowledge base (recipe data in pgvector) | Authoritative recipe data — ingredients, quantities, steps. |
| **Capability layer** | The LLM | Composition, adaptation, explanation, planning over *retrieved* recipes. |

The model **processes** recipes; it does not **recall** them. Generation is
always grounded in retrieved data, never in the model's parametric memory. Where
the model's own knowledge is used as a *source* (Phase B, §2.2), its output is
captured as candidate facts and normalized into the Fact layer — never trusted as
authoritative and never a substitute for retrieval. The same rule applies to
nutrition: any nutrition reasoning is grounded in a nutrition-facts source (see
§4), never estimated from the model's parametric memory.

---

## 2. Data-Source Strategy

### 2.1 Ingestion, not a query abstraction

Recipe data enters through an **ingestion layer** and is read back through Agno's
native knowledge search — there is no custom query interface or `RecipeSource`.

Two pieces (`recipe_agent/ingestion/`):

- **`RecipeIngester`** — one implementation per *origin*. It owns the origin's
  transport (a vendored local snapshot, a REST API, the model itself) and
  `ingest()`s a stream of normalized `Recipe` objects. A source may thus be
  backed by a local dataset, the model, a REST API, or an MCP server — the
  transport is hidden behind this interface.
- **`RecipeSink`** — the shared write endpoint. It consumes any ingester's recipe
  stream and persists each into the knowledge base (Postgres + pgvector).
  Persistence (chunk, embed, upsert) is identical across origins, so it lives here
  once rather than in each ingester.

At query time the agent does **not** call a custom store: it searches the
knowledge base through Agno's built-in agentic RAG (`search_knowledge_base`, on by
default when `knowledge` is attached). A parallel typed query interface would
duplicate that. A typed read of structured `Recipe` objects is introduced only if
non-LLM logic (e.g. portion scaling) later needs it — as an internal helper or an
Agno `knowledge_retriever` hook, never an agent-facing tool. (See §5.)

### 2.2 Phased rollout

| Phase | Source | Status |
|---|---|---|
| **A** | **HowToCook** (`Anduin2017/HowToCook`) | First source. Public domain, human-curated templated Markdown. Vendored as a pinned snapshot of the raw `dishes/` tree. |
| **B** | **LLM-intrinsic recipes** | Fallback/augmentation only; never trusted as authoritative; passed through the same normalization. |
| **C** | **Xiachufang / Meishijie / Douguo** (large Chinese recipe platforms) etc. | Deferred until scale is a real bottleneck and compliance is cleared. |

---

## 3. Domain Model: `Recipe`

The internal model every source normalizes into. Core fields:

- `id`, `name`, `aliases`
- `description` and `images` — a human-readable summary and cover/display
  images. `description` is **Markdown**; `images` are runtime-resolvable
  references (local path or served URL), populated at ingestion rather than the
  upstream address.
- `category` tags
- **structured `ingredients`** — a list of `{name, optional}` where `optional`
  flags an ingredient the cook may leave out. A clean structured name list (not a
  free-text blob) enables downstream filtering ("用到豆瓣酱吗", "纯素"). Amounts are
  deliberately **not** structured: quantities stay in the steps body for the cook to
  read and balance, so there is no `quantity`/`unit` field.
- `steps` — **Markdown**, keeping the source's structure (phase headings,
  ordering, emphasis) rather than a split list, since nothing consumes steps one
  at a time.
- `difficulty` (ordinal 1-5), `time` (hours) — both optional.
- `provenance` — which source (ingester) the recipe was normalized from, plus the
  original ref/URL within that source.

**Free-text fields hold Markdown by contract** (`description`, `steps`): sources
that are not natively Markdown are converted during normalization, so consumers
always render one format.

---

## 4. Personalization Model

The agent personalizes from two sources with different ownership:

| Source | Holds | Consumed via |
|---|---|---|
| **Profile Management** (Runtime-level component) | Structured per-user / household facts — dietary restrictions, `dietary_style`, chronic conditions and long-term health goals (key-value); body metrics such as weight / blood glucose (time-series) | `dependencies` injection + function tools |
| **User Memory** (Agno, per-user) | Unstructured soft preferences and observations — "likes spicy", "found the braised pork too sweet" | Agno Learning Machine |

Profile Management is a **Runtime-level shared component**, not recipe-private —
future agents (health, shopping) consume the same user / household data. Its full
design lives in its own component doc,
[`user-profile-management.md`](./user-profile-management.md). The points the
recipe agent relies on:

- **Two data shapes.** Key-value current-state facts (dietary restrictions,
  chronic conditions, long-term goals) are exact-recall and fully injected.
  Time-series metrics (weight, blood glucose) are append-only and injected only as
  a *latest value + short trend summary* — never the full series (same "keep
  context small" rule as RAG).
- **Household-first.** Modeled around `User` + `Household` (membership). A cooking
  session is for the table: the agent receives the **merged constraints** of the
  eating members (union of dietary restrictions, per-member health targets), not a
  single user's profile.
- **Integration (service + injection + tools).** Profile Management is a
  framework-neutral service. Must-have constraints are injected deterministically
  via a `dependencies` callback resolved before each run; on-demand member detail
  and writes (e.g. record a measurement) are exposed as **function tools**. An
  Agno custom-store adapter is an optional future compatibility layer, not the
  primary interface.
- **Writes.** Safety-relevant fields use explicit / confirmed writes. Automatic
  extraction from conversation is deferred; when added, it lands as a post-hook
  calling the service.

Nutrition reasoning (matching dishes to health targets / conditions) is a
**capability-layer** concern grounded in a nutrition-facts source (future), per
§1.

---

## 5. Agent Composition & RAG

The agent is thin — it composes the layers above:

- `model` — a domestic provider (DeepSeek / Zhipu / Qwen / Moonshot), per
  `Agents.md`, configured via env.
- `knowledge` — the recipe knowledge base in pgvector, written by the ingestion
  layer (§2.1).
- `db` — `PostgresDb`, for sessions and the Agno User Memory store.
- `dependencies` — a callback that injects the merged household constraints and
  key health snapshot from Profile Management before each run (see §4).
- `tools` — Agno's built-in knowledge search (`search_knowledge_base`), plus
  Profile Management tools (member detail, record measurement).
- `learning` — User Memory enabled for soft preferences.
- `instructions` — ground answers in *retrieved* recipes; adapt to the injected
  profile / household constraints.

**RAG strategy:** Agno's native agentic search-as-tool — the agent calls
`search_knowledge_base` to query the knowledge base on demand rather than having
the entire dataset auto-injected. No custom retrieval store is built; retrieval
grounds generation (the agent adapts retrieved recipes), it is not exact
constraint lookup.

---

## 6. User Journeys

The agent is designed around **meal planning for a household**, not one-off dish
lookups. The two primary interactions:

1. **Generate a plan from household preferences** — e.g. "Plan next week's family
   dinners." The agent produces a multi-day **meal plan** grounded in retrieved
   recipes, honoring the household's **merged constraints** (dietary restrictions,
   dietary styles, health targets) and balancing variety across the week.
2. **Adjust an existing plan conversationally** — e.g. "The kid wants steak —
   change tonight's plan." The agent revises an already-generated plan *in place*:
   swap or add dishes for a specific day or member request, while keeping the rest
   of the plan and the household constraints intact.

Both operate over the household (§4) and over a **meal plan** that spans days and
meals, rather than a single dish. Further journeys — shopping lists, nutrition
analysis — are natural extensions scheduled per release in the plans.
