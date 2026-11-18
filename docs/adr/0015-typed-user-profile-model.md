# ADR 0015: Typed User Profile Model with Multi-Source Updates

- **Status**: Proposed
- **Date**: 2026-11-18
- **Deciders**: Project owner + architecture discussion

## Context

User Profile is intended to be a core Spectres capability and a point of
differentiation from other AI assistants. It must support more than a small set of
Agent memories or a generic collection of profile key-value pairs.

Profile data has three sources:

- **Manual**: values entered explicitly by the user through a UI.
- **Device**: values measured or collected by physical devices and delivered
  directly or through a provider cloud.
- **Agent**: values extracted, summarized, or inferred by an Agent from
  conversations or other information.

Source is not a useful top-level boundary for the logical profile. The same field
may accept contributions from all three sources. For example, a weight may come
from a manual entry, a scale, or an explicit measurement reported in conversation.
These entry points do not require persisted update-attribution metadata.

Fields also have different retention requirements. Current personal attributes
and interaction settings need only their latest values. Interest preferences form
an evolving collection of current entries rather than one value or document per
user. Health measurements, daily summaries, sleep, and workouts require history.
Treating all profile data as current key-value pairs loses these collection and
temporal semantics.

Agno 3.1.2 provides `LearningMachine` and `UserProfileStore`. They are useful
potential extraction and Agent-learning primitives, but their default profile is a
generic structured object stored as JSON content in `agno_learnings`. That model
does not provide the field-specific persistence, history, correction, and
validation behavior required here. Agno's authentication User Directory is a
separate, deliberately small identity roster and is not a general profile store.

Runtime already has Core-owned `health_*` tables keyed around provider-separated
current and historical records. Those tables are a starting point, not an
unchangeable boundary. Health data belongs inside the UserProfile logical model,
and the existing schema may be migrated to support unified current values and
multi-source updates.

The project has decided to keep PostgreSQL as the authoritative profile store.
The next step is to define a deliberately typed logical model without introducing
a universal attribute engine, a generic resolver framework, or another database.
How each field is later exposed to Agents through prompt context or Tools is a
separate design topic.

## Decision

### 1. Use PostgreSQL as the sole authoritative profile store

Keep all authoritative Runtime-owned UserProfile data in PostgreSQL. Do not add a
document, graph, time-series, vector, or cache database for this model.

Use ordinary typed relational columns for predefined profile values and PostgreSQL
JSONB only for bounded metadata or genuinely provider-specific details. Continue
using the existing Runtime connection pool, Core Alembic migrations, and explicit
`user_id` ownership predicates.

Logto remains authoritative for account identity, email, roles, and tokens. Agno
continues to own its framework tables, including authentication, sessions, and any
learning records explicitly enabled in the future. Runtime must access Agno tables
only through Agno APIs. Neither system becomes the generic store for the typed
Runtime UserProfile described here.

A future derived semantic index, cache, or high-density time-series store requires
a separate decision and must not silently become another authoritative profile
store.

### 2. Partition the logical model by data type and use, not source

The UserProfile logical model is:

```text
UserProfile
├── Basic Information        Current personal attributes and interaction settings
├── Preferences              Current categorized likes and dislikes
└── Health
    ├── Health Context       Current height, demographic context, and goals
    ├── Daily Summaries      Historical daily health metrics
    ├── Body Measurements    Historical weight and body-composition records
    ├── Sleep Sessions       Historical sleep events
    └── Workouts             Historical workout summaries
```

Manual, Device, and Agent are update entry points, not source classifications
stored on records. They are not separate profile sections and do not have separate
canonical copies of the same field.

An Agent contribution uses the same typed table and domain service as a UI or
device contribution for that data type. If no predefined table and field exist for
an Agent-produced value, that value does not enter the authoritative UserProfile.
Adding a new data type requires an explicit schema, validation, ownership, and
service decision rather than insertion into a catch-all JSON profile.

### 3. Use closed, predefined table schemas

Each profile table has a known purpose, typed value columns, a retention policy,
and dedicated processing code. Do not create a universal `profile_facts`,
`profile_attributes`, `profile_records`, or `profile_observations` table that
accepts arbitrary keys and values.

Do not introduce a generic attribute-definition registry, source-resolution
framework, or dynamic field-definition control plane. Different data types are
expected to need different validation, normalization, conflict, correction, and
query behavior, and that behavior should remain visible in ordinary domain code.

The initial target table set is:

| Table | Cardinality and retention | Purpose |
|-------|---------------------------|---------|
| `profile_basic` | One current row per user; no revision history initially | Preferred name, birth date, sex, broad textual location, timezone, biography, language, response detail, and measurement units |
| `profile_preferences` | Multiple current rows per user; one row per category and normalized subject; no revision history initially | Interest likes and dislikes for bounded categories, with optional notes |
| `health_profile` | One current row per user | Height, birth year, sex, and current health/activity goals |
| `health_daily_summaries` | One correctable row per user and local health day | Daily activity, heart-rate, SpO2, and sleep metrics |
| `health_body_measurements` | Historical correctable measurements | Weight, BMI, and body composition with explicit availability |
| `health_sleep_sessions` | Historical correctable events | Sleep intervals, stages, and related metrics |
| `health_workouts` | Historical correctable events | Workout intervals and summary metrics |

The exact constraints and any remaining fields are implementation-contract details
to be refined in the corresponding milestone. The table names describe the logical
target; a migration need not rename existing tables merely for naming consistency.

Singleton interaction settings belong in `profile_basic`, not in
`profile_preferences`. Their fixed fields, defaults, and validation rules differ
from an open-ended collection of interests.

Each `profile_preferences` row represents one independent preference statement:

```text
id                  UUID primary key
user_id             String(128), verified owner
category            String(32), bounded allowlist
subject             String(200), display value
normalized_subject  String(200), internal normalization for deduplication
sentiment           String(16), like or dislike
note                Text, optional Agent- or user-supplied context
created_at          DateTime(timezone=True)
updated_at          DateTime(timezone=True)
```

The initial categories are `food`, `book`, `entertainment`, `game`, `music`,
`movie`, and `tv_show`. There is no `other` category. Adding a category requires
an explicit implementation decision rather than arbitrary Agent input.

`normalized_subject` performs only basic normalization such as trimming and case
folding. A global catalog of works, artists, foods, or other entities is not part
of the initial model. Enforce uniqueness on `(user_id, category,
normalized_subject)` and index `(user_id, category, updated_at)` for bounded
category reads.

`note` preserves nuance for one subject; it is not a whole-category biography.
This preference-specific schema is not a generic fact table because every column
has defined preference semantics and arbitrary keys, values, and categories are
rejected.

Current weight is queried from body-measurement history rather than duplicated as
an independently editable field in `health_profile`. Ingestion checkpoints and
synchronization run state are operational data, not UserProfile values.

### 4. Do not persist update provenance initially

Keep only `created_at` and `updated_at` as common Runtime row timestamps. Do not
add generic update-attribution fields or per-field source metadata.

Domain services still decide which entry point may update each field, but Runtime
does not record which UI, device, or Agent performed an update.

### 5. Keep domain history separate from row metadata

Historical measurement and event tables store typed business values and the domain
timestamps needed to describe each measurement or event. Those timestamps are part
of the health data itself, not generic update-attribution metadata.

Current-value tables retain only currently accepted typed values. Overwriting or
deleting such a value does not imply that an older value can be restored. A later
resynchronization or new contribution may repopulate it according to that field's
rules.

### 6. Make latest-only versus historical retention an explicit table property

`profile_basic` and `health_profile` represent singleton current state. Their
services update only the supplied fields and preserve unrelated current fields.
They do not retain a revision history unless a later requirement explicitly adds
one.

`profile_preferences` is a current collection, not a singleton settings row.
Services add, update, or delete individual entries without rewriting unrelated
entries or an entire category. Entries have no revision history initially;
deleting an entry removes it rather than retaining an inactive preference.

`health_daily_summaries` retains one correctable row per user and local health day.
A repeated or corrected report updates the existing day rather than creating a
second canonical day. Missing values remain distinct from genuine zero activity.

Body measurements, sleep sessions, and workouts retain history. They use stable
record identities for idempotent replays and corrections, exclude tombstoned
provider records from ordinary reads, and preserve explicit measurement/event
times separately from synchronization time.

### 7. Handle multi-source updates in dedicated domain services

Every source calls the service that owns the target data type:

```text
Web UI             -> Profile or Health domain service
Device adapter     -> Health domain service
Agent extraction   -> Profile or Health domain service
```

No source writes another domain's tables directly. An Agent must not issue SQL or
write a parallel generic health/profile object.

The initial `profile_basic` contributors are the Web UI for explicit manual input
and Agent extraction for explicit conversational input. Both call the Profile
domain service, which is the sole database writer. Device adapters cannot update
`profile_basic`.

Web UI preference operations and Agent preference Tools call the same
`PreferenceService`, which is the sole preference database writer. Before writing,
an Agent searches the owner's existing entries in the relevant category and then
creates, updates, or deletes one or more independent entries. It must not replace
the owner's whole preference document or issue SQL. Tool schemas never accept a
user id; ownership comes only from verified run context.

Update rules are intentionally specific and may be hard-coded. Examples:

- A preferred-name update is accepted from the UI or from an explicit Agent
  extraction such as a user asking to be addressed differently. A device cannot
  update it, and an unrelated newer name mention does not automatically replace
  an existing setting.
- A birth date can be accepted from the UI or an explicit conversation. Conflicting
  or uncertain Agent output must not silently overwrite an existing value.
- An explicit user statement of a like or dislike may directly create or update a
  preference entry. A recommendation request or an inference from a single action
  is not itself an authoritative preference.
- A refinement updates the existing entry for the same category and subject. An
  explicit reversal changes its `sentiment`; it does not create a competing row.
- A statement that the user no longer likes a subject deletes that preference
  rather than assuming a dislike. A separate explicit dislike changes the
  sentiment to `dislike`.
- A correction of the subject updates the existing entry rather than leaving two
  contradictory rows. Agent-generated notes summarize explicitly supplied
  information and must not invent additional interests.
- A weight row can represent a manual measurement, a device measurement, or an
  explicit user-reported measurement extracted by an Agent. An Agent inference
  that the user may have gained weight is not a measurement and cannot be stored
  as one.
- Multiple device reports for the same daily metric are not summed automatically.
  The daily-health service defines each metric's update and correction behavior in
  dedicated code.

These examples establish the style of the rules, not a universal precedence
algorithm. The exact field/update-entry-point matrix remains part of the
implementation contracts. Update rules cannot depend on knowing which entry point
wrote the existing value because that attribution is not persisted.

### 8. Integrate the existing health schema into UserProfile

The target logical model has one current health context per user and one canonical
daily summary per user and day. This changes the current provider-separated
direction:

- Migrate `health_profiles` from one current row per `(user_id, provider)` toward
  one `health_profile` row per `user_id`.
- Migrate `health_daily_summaries` from one row per `(user_id, provider, day)`
  toward one row per `(user_id, day)`, with metric-specific update rules.
- Keep stable external record identities on body measurements, sleep sessions, and
  workouts so historical replays, corrections, tombstones, and duplicate
  investigation remain possible. These integration keys do not record who updated
  a profile field.
- Do not automatically sum or merge overlapping device histories. Any future
  cross-device deduplication requires data-type-specific logic.
- Preserve the existing Mi Fitness adapter boundary: the Extension maps provider
  data and calls Core contracts; Core health/profile services do not import
  Extension code.

Before changing the existing schema, an implementation milestone must define a
reviewed data-migration procedure for current provider-separated rows, including
conflict handling when two providers already supplied different values. This ADR
does not authorize destructive deletion of existing provider contributions during
that migration.

### 9. Keep ownership, privacy, and Agent usage explicit

Every profile row remains private to its verified Runtime `user_id`. UI requests,
device synchronization, scheduled runs, and Agent calls derive ownership from
verified request or run context, never from payloads or LLM arguments.

Current-value and historical responses expose typed allowlisted fields. Raw
provider payloads, internal integration identifiers, and credentials are not
exposed by default. Sensitive values must not be logged.

Users can list preferences by category and create, edit, or delete individual
entries through owner-scoped Profile APIs. These operations use the same
`PreferenceService` as Agent Tools so users can inspect and correct Agent-maintained
preferences.

Recommendation flows read a bounded set of entries for the relevant owner and
category, including positive and negative sentiments and their notes. `updated_at`
may provide recency context but does not create a universal newest-preference-wins
rule. Category summaries for prompts are derived from these entries rather than
stored as a second authoritative representation. The initial model requires
neither a vector store nor a dedicated recommendation engine.

The later Agent-usage design may hard-code which small fields enter ordinary prompt
context and which require read-only Tools. It need not introduce a dynamic usage
policy engine. That design, including remaining update-confirmation rules and
sensitive-field access, is explicitly deferred and does not change the storage
decisions here.

## Alternatives Considered

- **Use Agno `UserProfileStore` as the complete canonical profile**: minimizes
  initial Runtime code but stores heterogeneous data as generic learning content
  and lacks the required typed history, validation, and correction behavior.
  Rejected as the canonical model; Agno extraction remains reusable.
- **Partition the profile into Manual, Device, and Agent stores**: separates update
  entry points but splits the same semantic field across isolated sections and
  complicates coherent current values. Rejected.
- **Build a universal attribute/record/resolver framework**: supports dynamic
  fields but hides data-type-specific behavior behind abstractions and adds more
  infrastructure than the product currently needs. Rejected.
- **Store the complete profile as one JSON document**: simplifies document reads
  but weakens typed constraints, historical queries, and reviewed migrations.
  Rejected.
- **Store one preference summary or JSON document per user or category**: makes
  Agent rewrites easy but loses independent correction, deletion, deduplication,
  and bounded category-item reads. It also risks dropping unrelated entries when
  Agent output replaces a whole summary. Rejected as authoritative storage;
  derived summaries remain valid.
- **Introduce a document, graph, vector, or dedicated time-series database now**:
  adds operational and consistency costs without a demonstrated requirement.
  Rejected. Future derived indexes require a separate decision.
- **Keep provider-separated current profiles and daily summaries as the final
  model**: preserves the existing schema but leaves multiple current values for
  the same logical user field and keeps provider as a top-level partition. Not
  adopted for the target model; stable external record identity remains on
  historical records for synchronization.
- **Add a generic Agent observation store for all otherwise unmodeled data**:
  provides an easy persistence path but recreates an unbounded catch-all beside
  the typed model. Rejected. New authoritative data types require explicit
  schemas and services.

## Consequences

- Runtime owns a cohesive UserProfile model while retaining separate, focused
  tables and services for different data types.
- UI, device, and Agent writers can contribute to the same field without creating
  source-specific canonical copies.
- Developers must write explicit validation and update code when adding a profile
  field. This is an intentional cost, not an extensibility failure.
- Interest preferences support independent Agent and user corrections, negative
  preferences, and category-scoped recommendations without whole-document rewrites.
- Preference updates require careful existing-entry lookup and normalization to
  reduce duplicates. Basic string normalization cannot resolve every alias or
  ambiguous subject.
- Current-value overwrites and preference-entry deletion discard the previous
  current state by design. Fields or entries requiring history must use an
  explicitly historical model instead.
- Runtime cannot report which UI, device, or Agent last changed a value. Adding
  update attribution later requires a separate decision and schema migration.
- Existing provider-separated health profiles and daily summaries require a
  reviewed migration and explicit handling of already conflicting values.
- Latest body measurements are queries over history rather than a second editable
  current-weight store.
- Agent extraction does not receive blanket write access to the profile. Each
  typed service determines whether a proposed contribution is valid.
- The ADR establishes a target model only. It does not itself migrate health data,
  enable Agno `LearningMachine`, add Agent Tools, change prompt context, or define
  the final field/update-entry-point matrix.

## Open Questions for Refinement

1. What are the exact initial fields for `profile_basic` and each health table?
2. Which sources may update each non-preference field, and what confirmation or
   conflict rule applies to each update?
3. Should broad textual location and home location remain separate fields?
4. How should Agents resolve aliases and ambiguous preference subjects without a
   global entity catalog?
5. What update rules should each daily health metric use when multiple devices
   report the same day?
6. How should existing provider-separated current and daily rows be migrated when
   their values conflict?
7. Which remaining Agent extractions require confirmation, and which should stay
   transient conversation output rather than authoritative profile data?

## References

- ADR 0009: Identity Provider — Logto OSS Self-Hosted
- ADR 0013: Mi Health as Built-in Extensions
- `docs/plan/v0.7.4-personal-health-data.md`
- `docs/plan/v0.7.7-profile-and-health-api.md` (`in review`)
- `docs/architecture/system-architecture.md`
- `src/spectres/health/models.py`
- `src/spectres/health/ingestion.py`
- `src/spectres/health/queries.py`
- Agno 3.1.2 `agno/learn/schemas.py` and `agno/learn/stores/user_profile.py`
