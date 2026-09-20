# Shared application register

The AWS SQLite store is the authoritative submission register. Both agents read
`application_tracking` from existing detail, assessment, search and fit responses.
`submission_status=submitted` means recorded submission evidence exists. `unknown`
means no submission is recorded; it never means the user definitely has not applied.
Seen/discovered/prepared records are not submission evidence.

## Mark as applied

Trevor can tell Codex: **“Mark [company + exact role/link] as applied.”** This is a
confirmation that he has already submitted, not permission to submit an application.
Codex resolves the exact vacancy, imports its portable evidence if unsaved, and uses
the existing authenticated SSH administrator route. It asks for a role identifier
only when the match is ambiguous. Unknown submission time stays null.

```sh
career-admin --database PRIVATE_DATABASE mark-as-applied \
  --job-id SAVED_ID --confirmed \
  --evidence 'Trevor explicitly confirmed submission in this conversation'
```

Optional `--submitted-at` requires an ISO timestamp with a timezone. Read the job
back after writing and confirm the persisted status/evidence to Trevor. Do not print
secrets or transfer CVs. Repeating the action does not create duplicate submission
events or reset a later interview/offer stage.

The full MCP also exposes `mark_as_applied` as an explicitly annotated write tool.
It is removed in `CAREER_READ_ONLY=true`. The current ChatGPT connection remains
read-only: neither agent can claim to have marked a role through that connection.
When asked there, preserve the exact role reference/portable handoff and direct Trevor
to the Codex write route. There is no hidden automatic ChatGPT-to-admin bridge.

## Import existing applications

First inventory existing application records, separating confirmed submissions from
watchlist, drafts and uncertain records. Import confirmed records with an exact vacancy
URL, genuine source receipt time and submission evidence; never manufacture timestamps.
If the exact vacancy identity is missing, retain the record as unresolved for review.

`career-admin --database PRIVATE_DATABASE import-applications --file PRIVATE_JSON`
accepts `{"schema_version":1,"records":[{"evidence":ExternalJobEvidence,
"submission":Submission}]}` (up to 100 records). `Submission` requires `confirmed:true`,
`recorded_at`, nonempty `evidence`, and `evidence_source` (`user_confirmation` or
`confirmation_record`); `submitted_at` may be null. The server sets the actual recording
time. Validate all records first, then apply idempotent per-record transactions. A batch
is not all-or-nothing: inspect the error and retry remaining records safely.

`migrate-submissions` preserves existing applied/awaiting-response/interview/offer
lifecycle history as legacy submission evidence, including when the current stage is
now rejected/closed. It does not infer submission from closed/dismissed alone and does
not invent the actual submission date. Back up before migration or import.

## Filtering and identity

Submitted vacancies appear in `excluded_jobs` with an explicit already-submitted reason.
They remain available through detail and tracking reads. Discovery never resets their
submission record, even if the workflow status later changes. Previously surfaced roles
without submission evidence can still be prepared provisionally.

Existing conservative identity matching uses provider IDs and canonical vacancy URLs,
including employer application URLs. Cross-source records sharing the same employer
requisition are excluded consistently. A same-title role with a different requisition
is not automatically suppressed. When providers expose unrelated redirect URLs and no
shared identity, the agents must resolve the employer requisition; fuzzy title matching
is deliberately insufficient. Missing linkage is an uncertainty, not proof of newness.

The register does not monitor email or detect submissions outside tracked evidence.
Application receipt emails can be imported after explicit review but are not assumed
to cover every application.

Unlinked confirmed applications are retained separately using `import-application-review`.
Assessing or reading a role at the same named company exposes these as
`unresolved_same_company_records` and a reconciliation concern, never a company-wide
exclusion. Different company spellings still require agent review against the Library.
