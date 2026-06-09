# Recipe Agent — Architecture & Design

**Status:** living design. Version-independent. This document captures the durable
architecture, domain model, and design decisions of the recipe agent. The fact
layer — the ingestion pipeline, the recipe knowledge base, and the agent's core
composition — is implemented (see §7 for the module map); personalization (§4) and
the multi-day meal-plan journeys (§6) remain forward-looking. Per-release work
breakdowns are tracked separately under `docs/plans/` and are treated as disposable
history, not a dependency of this doc.

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

The first concrete ingester, **`HowToCookIngester`**, composes each `Recipe` from a
vendored snapshot: a structured catalog (`catalog/recipes.jsonl`) for the typed
fields and the matching Markdown (`dishes/<ref>`) for the embedded `content`, with
the upstream contributor footer stripped. Every ingester carries a stable `name`,
recorded as `provenance.source`.

Ingestion runs as a one-shot batch command, **`recipe-ingest`**
(`recipe_agent/ingestion/__main__.py`). The write is a **full update** every run:
each recipe is upserted under a stable `name` (`Recipe.id`), so a re-run re-embeds
the corpus over itself in place — **idempotent**, no duplicate vectors. Agno's
`contents_db` tracks what was written; per-recipe change detection is deliberately
skipped because the upstream releases rarely.

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

### 2.3 Knowledge base storage

The knowledge base is an Agno `Knowledge` handle over Postgres + pgvector. The
wiring separates **mechanism from identity**:

- **Mechanism** lives in the shared `storage/` layer: `build_db` (the single shared
  `PostgresDb`) and a generic `build_knowledge(...)` factory parameterized by table
  name, display name, and search type — no domain knowledge.
- **Identity** is owned by the agent: `recipe_agent/knowledge.py` pins the `recipes`
  table and the AgentOS-facing name, wrapping the generic factory as
  `build_recipe_knowledge`. Each knowledge domain is **physically isolated** in its
  own table.

Storage decisions the recipe base commits to:

- **One embedder, one vector space.** Ingest (passages) and search (queries) share
  the same configured embedder, so stored and query vectors are comparable. The
  embedding model is a data contract — changing it requires a full re-embed.
- **Vector-only search.** Postgres full-text search cannot tokenize Chinese, so
  hybrid/keyword search is deferred; retrieval is pure vector similarity.
- **Exact KNN, no ANN index.** At the corpus's ~1-2k recipes, exact nearest-neighbor
  is fine; an approximate index is unnecessary.
- **Pinned `public` schema.** Both the vector store and the shared `PostgresDb` live
  in `public` (not pgvector's `ai` default), so the Runtime's tables share one
  namespace.

---

## 3. Domain Model: `Recipe`

The internal model every source normalizes into. Core fields:

- `id`, `name`
- `description` and `images` — a human-readable summary and cover/display
  images. `description` is **Markdown**; `images` are runtime-resolvable
  references (local path or served URL), populated at ingestion rather than the
  upstream address.
- `category` tags
- **structured `ingredients`** — a list of `{name, optional}` where `optional`
  flags an ingredient the cook may leave out. A clean structured name list (not a
  free-text blob) enables downstream filtering ("用到豆瓣酱吗", "纯素"). Amounts are
  deliberately **not** structured: quantities stay in the `content` body for the cook
  to read and balance, so there is no `quantity`/`unit` field.
- `content` — **Markdown**, the recipe's full human-readable body (title, intro,
  ingredient/quantity sections, steps), source boilerplate (e.g. contributor footers)
  stripped. Kept whole rather than split into a `steps` list because nothing consumes
  it one line at a time, and because **this body is the text embedded for retrieval** —
  the structured fields above ride alongside as filter/display metadata.
- `difficulty` (ordinal 1-5) — optional.
- `provenance` — which source (ingester) the recipe was normalized from, plus the
  original ref/URL within that source.

**Free-text fields hold Markdown by contract** (`description`, `content`): sources
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

The agent is thin — it composes the layers above.

**Wired today (`build_recipe_agent`):**

- `model` — the hosted chat model, configured via env (currently **DeepSeek-V4-Flash**
  through SiliconFlow); provider-agnostic, since id / base-URL / key are all config.
  v0.4 uses a mid-tier model because the current task (grounded recipe Q&A) is
  composition-heavy rather than reasoning-heavy; the full household profile with
  health-constraint reasoning (design §4) is expected to need a stronger tier
  (DeepSeek-V4-Pro or equivalent) when it lands.
- `knowledge` — the recipe knowledge base in pgvector (§2.3), written by the
  ingestion layer (§2.1). Agno's agentic search-as-tool is on by default.
- `db` — the shared `PostgresDb` (§2.3); today it backs conversation history, later
  the User Memory store and other roles.
- `instructions` + history — env-driven (`RECIPE_AGENT_*`); the last
  `num_history_runs` turns are replayed into context. Telemetry is off.

**Planned (per §4):**

- `dependencies` — a callback injecting the merged household constraints and key
  health snapshot from Profile Management before each run.
- `tools` — Profile Management tools (member detail, record measurement) alongside
  the built-in knowledge search.
- `learning` — User Memory enabled for soft preferences.

The agent and its knowledge base are both registered with AgentOS (`app.py`) so the
control plane can manage them.

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
analysis — are natural extensions deferred for now.

---

## 7. Code Structure

The implementation keeps shared infrastructure and agent-private logic separate:

| Path | Responsibility |
|---|---|
| `config.py` | Shared `Settings` (database, embedder, chat) + builders `build_embedder` / `build_chat_model`. |
| `storage/` | Shared persistence: `build_db` (the one `PostgresDb`) and the generic `build_knowledge` factory. No domain identity. |
| `app.py` | AgentOS wiring — registers agents and knowledge bases; `app_factory` is the ASGI entry point. |
| `recipe_agent/agent.py` | `build_recipe_agent` — composes the agent from `Settings` (§5). |
| `recipe_agent/config.py` | `RecipeAgentSettings` — agent-private env config (`RECIPE_AGENT_` prefix). |
| `recipe_agent/knowledge.py` | Recipe knowledge identity: the `recipes` table + `build_recipe_knowledge` (§2.3). |
| `recipe_agent/ingestion/` | `RecipeIngester` interface, `HowToCookIngester`, `RecipeSink`, and the `recipe-ingest` entry (§2.1). |
| `recipe_agent/models/` | The `Recipe` aggregate with `Ingredient` and `RecipeProvenance` (§3). |

**Config layering.** Shared infrastructure config lives in the root `Settings`;
each agent's private settings live next to it (`RecipeAgentSettings`) and compose in
as a nested field, so adding an agent never touches the shared class. Secrets
(`*_api_key`) are `SecretStr`, sourced only from the environment or a git-ignored
`.env`.
