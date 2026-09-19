# Architecture and evidence contract

## Main workflow

`server.main` loads environment configuration, builds OAuth validation, opens `Store`,
and registers the MCP interface. `search_jobs` calls `CareerService.discover`, which
queries adapters, reports provider failures, normalizes records, persists deduplicated
jobs, and attaches deterministic fit evidence. `job_watcher` uses the same service.
`search_saved_jobs` searches persisted SQLite records by title, company, or description;
it does not contact job sources or write to the database. `search_live_jobs` calls the
currently configured, enabled adapters at request time, bypasses the SQLite source-response
cache, combines duplicates in memory, and does not persist results. All configured enabled
sources are used by default; an optional `sources` filter can narrow that set, but cannot
enable a disabled provider such as Scout or Adzuna. The watcher and `search_jobs` caching
and persistence behavior are unchanged.

Each live-search response includes provider `source_status` with `fetched_at`,
`cached: false`, and any failures, plus `total_count`, `returned_count`, `truncated`, and
`limit`. A request-time fetch does not guarantee a complete inventory: providers can cap,
delay, or fail to return listings. Read-only means no persistent writes here; live search
still contacts external services and needs network access.

Both live search and watcher discovery apply the same literal query filter to every
provider before deduplication. Query terms must occur as whole words (or simple plurals)
in the title or description. Role searches also require title evidence: for example,
`Technical Support Engineer` requires `support` and `engineer` in the title, while
`technical` may appear in the description. This rejects incidental mentions of another
team in an unrelated job description. Skill-only queries still search descriptions.
This conservative filter can miss synonyms; it does not claim semantic matching.

Each returned record includes `query_evidence` with matched title/description terms and
the required title terms. Each provider reports `retrieved_count`, `query_filtered_count`,
and its accepted `count`; zero accepted results are distinct from a provider failure.
Live results containing every query term in the title appear first, then remaining
matches, ordered by posting date within each group. Filtering happens before the response
limit. Previously saved jobs and their lifecycle states are not removed by this filter.

Live result IDs start with `live:` and remain in process memory for 15 minutes, up to 500
listings. `get_job_detail`, `score_fit`, `tailor_resume`, and `cover_letter_brief` accept
these IDs. When a result matches a saved job, it also returns the raw `saved_job_id`;
`get_job_history(live_id)` can return that job's stored history. For an unmatched live job,
it returns an empty history. A server restart, expiry, or eviction removes the temporary
result, so run the search again to use it.

### ChatGPT Pro read-only mode

OpenAI currently documents Pro access to custom MCP apps with read/fetch permissions in
Developer Mode. Write-capable MCP access is limited to Business, Enterprise, and Edu.
Secure MCP Tunnel does not change those plan permissions. See the current
[OpenAI Help Center plan guidance](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt).

Set `CAREER_READ_ONLY=true` on the MCP server used by Pro. The server removes and rejects
`search_jobs`, `save_profile`, and `update_status`. The read-only
`search_saved_jobs(query, status, limit, offset)` tool searches only watcher-collected
records and returns `jobs`, `excluded_jobs`, and pagination/coverage evidence. The
read-only `search_live_jobs(query, sources, limit)` tool instead retrieves current results
from configured enabled providers without persistence. The watcher continues to perform
source discovery and persistence as a separate local process; the ChatGPT MCP request does
not change watcher records. The default `CAREER_READ_ONLY=false` preserves the existing
interface for an authorized deployment with write access.

The four ChatGPT reasoning tools remain available: `build_profile`, `score_fit`,
`tailor_resume`, and `cover_letter_brief`. They prepare or retrieve evidence for ChatGPT
and do not call an external LLM. In Pro read-only mode, ChatGPT cannot save a reviewed
profile or change a job's lifecycle through this MCP. If a saved résumé profile is needed,
stop the tunnel and initialize it through a trusted loopback-only client, then restart
the MCP server with `CAREER_READ_ONLY=true` before reconnecting the tunnel.

SQLite transactions cover identity lookup, merge, provenance, and persistence.
WAL plus a busy timeout supports one MCP process and one watcher on the same local
filesystem. State updates and evidence updates cannot overwrite one another.
Do not put the database on NFS or run multiple replicas with separate volumes.
Use SQLite's backup API for consistent backups rather than copying a live database file.

### Why not Postgres + pgvector / Qdrant / Valkey?

The customised design does not create embeddings or call a model. Explainable keyword
and evidence matching needs no vector database, so Qdrant and Ollama add no value here.
Postgres + pgvector is a sensible later replacement if semantic retrieval and multiple
users become necessary: it can hold vectors alongside profiles, jobs and provenance,
without Qdrant. That requires choosing an embedding model and measuring retrieval quality;
there is deliberately no untested pretend semantic score in this version.

Valkey is unnecessary: `search_jobs` and the watcher keep source-response caching in SQLite
with expiration. Broad Remotive, Jobicy and WWR feeds share one cache across target queries
for six hours; Himalayas and Adzuna query caches last one hour. `search_live_jobs` bypasses
this cache and holds its results only in the bounded in-memory window described above. The
watcher minimum interval is six hours. A cache is a bounded first-page/feed snapshot, not a
claim of full market coverage. Avoid concurrent cold-cache discovery from multiple
processes: they may each fetch once. For a larger deployment, move leases/caching and
persistent data to Postgres.

## Canonical job schema

The authoritative validated schema is `models.Job`:

| Field | Meaning |
|---|---|
| id | Stable canonical ID for a saved job; live results instead use temporary `live:` IDs |
| title, company, location | Source-disclosed identifying text |
| remote_scope | worldwide, uk, emea, europe, restricted, remote_unspecified, onsite, hybrid, unknown |
| salary_min, salary_max, currency | Numeric source evidence, nullable |
| salary_period, salary_is_predicted, salary_text | Preserve units, estimates and unparsed source salary |
| employment_type | permanent, full_time, part_time, contract, temporary, internship, unknown |
| posted_at | UTC timestamp, nullable when unparseable/absent |
| sources | Source name, source ID, source URL, application URL, fetch time and field snapshot |
| source_url, application_url | Listing and original application links; never automatically opened/submitted |
| description, skills | Source text and declared tags; tags are not candidate skills |
| country_restrictions | Disclosed restrictions; absence is not verified work authorization |
| eligibility | Explainable eligibility uncertainty |
| match_evidence | Matched/missing evidence, concerns, exclusions and reasons |
| status | Persistent user-controlled application lifecycle |
| first_seen, last_seen | Discovery timestamps |
| follow_up_at | Optional explicit timezone-aware reminder due date |
| conflicts | Disagreements retained across sources |

Provider HTML is reduced to plain text. Content is untrusted evidence, never instructions.
Salary amounts are never merged across currencies or periods. Unknown annual units and
non-GBP pay require review; no fabricated exchange rate is used.

## Deduplication and precedence

Identity matches use source-native ID, normalized listing/application URLs (tracking
parameters removed, requisition parameters retained), then exact company + title +
location + employment type + posting date. Different requisitions within one source
are not merged by the fallback fingerprint. Missing location/date prevents that fallback.
No fuzzy title-only merge is used. Some duplicates will remain when evidence is insufficient;
that is safer than losing separate applications. Conflicting aliases are flagged for review.

Field precedence is deterministic: Himalayas, Scout, Adzuna, Jobicy, Remotive, WWR;
newer evidence wins within a source. This is an explicit convenience rule, not a claim
that aggregators are authoritative. All snapshots and conflicting location/salary/type
values remain visible so ChatGPT can prefer the employer's evidence during review.
Salary amount, currency, period and predicted flag are selected as one source bundle.
Rediscovery preserves lifecycle, follow-up date and audit history.

## Canonical profile and explainable matching

Initial preferences target Support Engineer, Technical Support Engineer, Customer Engineer,
Application Support, Product Support, and Customer Support Engineer. Worldwide remote
is strongest; UK/EMEA/Europe remote is acceptable pending exact country and authorization
checks. Annual disclosed GBP below £40,000 is excluded when even the upper bound is below
that threshold. Undisclosed pay remains in review. Contract and temporary roles, hybrid
and onsite roles are excluded. Salary estimates never trigger salary exclusion.

Positive terms: technical troubleshooting, APIs, HTTP, JSON, SQL, SaaS, engineering
escalation, Python, Postman, Datadog. Inbound phone support is a concern. Posting age and
unknown dates are explicit concerns. Deterministic matching is not exhaustive NLP:
ChatGPT must review the full supplied description and distinguish required from optional
skills, negation, time-zone requirements, and legal eligibility.

Preferences are not résumé claims. `verified_skills` requires literal quotes from
`resume_text`; `experience_evidence` must also cite it. No name, contact information,
work authorization, achievements, or actual skills are invented. Profile country and
work authorization begin unknown and must be supplied by the user.

## Four reasoning-layer tools

- `build_profile(raw_text)`: returns a schema, raw evidence and draft preferences for
  ChatGPT to extract facts and ask about ambiguity. Does not save.
- `score_fit(job_id)`: returns matched requirements with job/résumé quotes, skills not
  evidenced, remote eligibility, salary evidence, concerns, exclusion reasons and positive
  evidence. No opaque score or external LLM call.
- `tailor_resume(job_id)`: returns the job/profile, fit evidence and output
  contract for ChatGPT to propose summary/skills/experience changes with citations.
- `cover_letter_brief(job_id)`: returns evidence and an output contract covering opening
  angle, requirements, supporting experience, gaps and questions. ChatGPT writes the brief.

`save_profile` is an explicit write; the four reasoning tools never alter the saved résumé.
All are published with MCP annotations and, in OAuth mode, security scheme metadata.
The full interface has 13 tools, while `CAREER_READ_ONLY=true` exposes 10 read-only tools.
`search_jobs` is accurately marked as a write because discoveries are persisted.
`search_saved_jobs` is read-only: query matching is limited to stored title/company/
description text, applies optional status and pagination, and returns an explicit
"saved listings only" coverage statement. It does not refresh listings or update stored
fit evidence. `search_live_jobs` is also read-only, but it contacts enabled providers and
returns temporary live results without writing to the database or source cache.

## Lifecycle

`discovered`, `interesting`, `review`, `dismissed`, `application_prepared`, `applied`,
`awaiting_response`, `follow_up_due`, `recruiter_screen`, `interview`,
`technical_interview`, `final_stage`, `rejected`, `withdrawn`, `offer`, `closed`.

User-directed transitions are allowed between these states to accommodate corrections
and different employer processes. Every transition stores old/new states, time and reason.
The only automatic transition is applied/awaiting_response -> follow_up_due when the
user-specified follow-up time passes. Terminal states are never advanced automatically.
A missing listing is not proof that a role has closed.

## Response sizes

Search results contain a 1,500-character description preview and compact provenance links.
`description_truncated` makes that limit visible. For a saved job, `get_job_detail` returns
the complete stored description and source snapshots; for a live ID, it returns the
temporary result while that result remains in memory. Evidence tools return source
references rather than duplicating every raw snapshot in each fit assessment.

## Scout integration boundary

The opt-in Scout adapter is a schema-validating transport scaffold, not a proven live
provider integration. It requires an independently approved token and an operator-supplied
JSON argument template matching the live `scout_discover` schema. It replaces only the
`{query}` placeholder, rejects external JSON Schema references, and never calls `scout_score`.
Recognized structured JSON result fields are normalized; unrecognized formats fail explicitly.
Default configuration leaves it disabled. Do not copy ChatGPT-managed tokens into the watcher.
