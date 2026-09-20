# Evidence quality and shared application packs

Career keeps the canonical records and drafts; ChatGPT reasons over evidence and authors
application text. All independent job connectors remain discovery sources. Neither agent
submits an application, uploads a CV, or contacts an employer.

## Shared agent workflow

1. Read `get_profile`, `get_source_health` and `get_discovery_changes(since=last successful run)`.
   The change feed covers watcher observations, not every independent connector. Keep a
   successful-run watermark; do not advance it on a partial failure.
2. Search available independent connectors concurrently where possible, alongside Career's
   `search_live_jobs`. Disclose missing/failed sources. A zero-result response is not failure.
   Cached health is not fresh successful retrieval. Do not run the same source twice merely
   because both its standalone connector and Career adapter exist.
3. Assess each candidate with `assess_job_evidence`; preserve source receipt time and actual
   HTTP code when exposed. Independently check role, remote scope, employment and salary.
   Seen previously is not applied. Check exact saved application history before shortlisting.
4. For supported employer links, call `verify_employer_job` after saving the candidate.
   Supported exact public ATS records are Lever, Ashby and Greenhouse. This is a read-only
   API check, not an arbitrary page scraper. Compare employer/requisition identity before
   importing the returned evidence. An absent record does not automatically close a job.
5. Save shortlisted evidence with `import_job_evidence`; use its stable saved ID across both
   agents. Prefer direct employer/ATS evidence over aggregator fields while preserving
   disagreements and all source provenance.
6. Call `score_fit`, `tailor_resume` and `cover_letter_brief` for shortlisted roles in BOTH
   agents. Explain essential/desirable/unknown requirements, quoted CV support, transferable
   evidence, gaps and uncertainties. Keyword coverage is secondary and is not an employer
   ATS score or hiring probability. Do not invent experience or answer unresolved questions.
7. Read `get_application_pack`. Reuse current drafts; review stale evidence before revision.
   ChatGPT authors the summary, CV bullet edits, cover letter and screening answers, then
   calls `save_application_pack` with `expected_revision=0` for a new pack or the last read
   revision for an update. Conflict means re-read and reconcile, never overwrite blindly.
8. Call `show_application_tracker` with saved IDs to render submission buttons. Rendering
   and draft saving never mark a role applied. The confirmed button records a past submission
   through `mark_as_applied`; it does not send an application.

## Output for each qualifying role

Use a plain role/company heading, a short verdict and a five-row evidence table:

| Required field | Content |
|---|---|
| HTTP Status | Actual plugin/MCP retrieval outcome and exposed HTTP code, otherwise code unavailable. Employer API status is separate. |
| Eligibility / Compatibility | Remote/location restrictions, UK work authorization, residence uncertainty, salary/employment and future Algeria compatibility. |
| Estimated CV keyword coverage | Matched/detected terms, selected CV, limitations; not an employer ATS score. |
| Fetched_at | Exact source or caller-observed response timestamp and its basis, never report generation time. |
| Source | All relevant provider links and employer corroboration with provenance. |

Follow with specific fit evidence, missing requirements/concerns, application draft and
remaining questions. Include the tracker card. Finish with one compact source-health line.
Avoid numbered administrative sections. Re-surface a seen role only for meaningful new
information or pending user action, never merely because its fetch timestamp changed.

## Storage and interface

Application packs are immutable SQLite revisions linked to canonical jobs. Each stores
its author, CV variant, authored text, unanswered screening questions, evidence references,
save time and evidence fingerprints. Optimistic revisions protect concurrent agent writes.
Staleness reports evidence changes; it is not a verdict about draft quality. The service
validates structure, not the truth of arbitrary text supplied by ChatGPT.

The watcher persists new/materially-changed observations and sanitized source health.
Polling timestamps and lifecycle-only changes are not new discoveries. A first observation
establishes a baseline; it cannot reconstruct historical changes before this release.

The full interface adds five tools: `verify_employer_job`, `get_discovery_changes`,
`get_source_health`, `get_application_pack` (reads), and `save_application_pack` (write).
Full mode has 23 tools, including six writes; read-only mode has 17 tools. SQLite migrations
are additive. No new database service, paid reasoning worker or external LLM dependency is
introduced. Refresh the existing ChatGPT Career connection after deploying tool changes.
Test actual tool execution and draft write/read-back in each target agent; metadata discovery
alone is insufficient. Scheduled execution requires its own unattended test.
