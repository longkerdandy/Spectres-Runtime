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

### 2.1 The `RecipeSource` abstraction

All recipe data enters through a single `RecipeSource` interface. Each source is
one implementation of the same contract (roughly
`search(constraints) -> list[Recipe]` plus `get(id) -> Recipe`). A source may be
backed by a local dataset, the model itself, a REST API, an Edge-provided store,
or an MCP server — the transport is hidden behind the interface.

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
- `category` / `cuisine` tags
- **structured `ingredients`** — a list of `{name, quantity, unit, role}` where
  `role ∈ {main, aux, seasoning}`. Structured from day one (not a free-text
  blob), which enables portion scaling and downstream filtering.
- `steps` — ordered list
- `servings`, optional `difficulty`, optional `time`
- `source` provenance — which `RecipeSource`, original ref/URL

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
- `knowledge` — the recipe knowledge base in pgvector.
- `db` — `PostgresDb`, for sessions and the Agno User Memory store.
- `dependencies` — a callback that injects the merged household constraints and
  key health snapshot from Profile Management before each run (see §4).
- `tools` — knowledge search, plus Profile Management tools (member detail,
  record measurement).
- `learning` — User Memory enabled for soft preferences.
- `instructions` — ground answers in *retrieved* recipes; adapt to the injected
  profile / household constraints.

**RAG strategy:** agentic search-as-tool — the agent queries the knowledge base
rather than having the entire dataset auto-injected. Per-agent and revisitable.

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
   of the plan and the plan and the
   household constraints intact.

Both operate over the household (§4) and over a **meal plan** that spans days and
meals, rather than a single dish. Further journeys — shopping lists, nutrition
analysis — are natural extensions scheduled per release in the plans.
