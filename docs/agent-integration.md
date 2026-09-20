# Shared Career agent contract v1

Career Search complements the existing job plugins. The Worldwide Support Role Scan
Agent and Support Application Agent both discover, assess, and prepare suitable
unsubmitted roles for human review. ChatGPT interprets evidence and writes; the MCP
never calls another LLM, submits an application or sends a message.

## Every role, from every source

Include these five labels even in needs-verification and excluded-result sections:

| Label | Required evidence |
|---|---|
| HTTP Status | Outcome of the source plugin/MCP fetch (SUCCESS, FAILED, or NOT_CALLED/UNAVAILABLE), plus the actual transport HTTP code when exposed. Otherwise say HTTP code unavailable. Successful zero-result calls remain SUCCESS. Never infer 200 from tool success. |
| Eligibility/Compatibility | Separate current work authorisation, employer hiring rules, remote working location, salary, employment, role fit and unknowns. Check Algeria as a future destination separately from UK work authorisation. |
| ATS Score | Label as estimated CV keyword coverage; show CV variant, matched/detected counts and method. Never call it an employer ATS score or hiring probability. Use unavailable when CV/JD evidence cannot support computation. |
| Fetched_at | Actual source retrieval timestamp with timezone; retain per-source timestamps. Never substitute posting time, report time or reassessment time. |
| Source | Every contributing provider/plugin, retrieval method, original listing and application URLs. |

The user-facing HTTP Status row is assembled from the caller's source tool-call receipt.
The deployed `http_status.checks` field describes URL checks and must not be relabelled
as connector transport evidence. Keep any employer-page checks separate. A successful
Career Search assessment is not proof of a successful originating provider fetch.
Preserve both transport and tool/application outcomes when they differ, and distinguish
failed attempts from a successful retry.

MCP responses expose `http_status`, `eligibility_compatibility`, `ats_score`, `fetched_at`,
and `source`. `score_fit`, search, detail, saved jobs and writing briefs share this contract.
The estimated score uses the public vocabulary and formula in `reporting.TERMS`:
100 * evidenced matched terms / detected vocabulary terms in the supplied description.
It does not interpret negation, required/desirable wording, seniority, years, or PDF layout.
It cannot override exclusions or country restrictions. Missing evidence is not inability.
The canonical profile is the union of facts; score a particular application with
`cv_variant="technical_support"` or `"customer_support"`. The server validates literal
quotes against each CV. It returns evidence briefs, not edited PDF files.

## Plugin cooperation and handoff

1. Discover available tools on each run. Call Career Search `get_profile`; use
   `search_live_jobs` for a new provider fetch and `search_saved_jobs` for stored jobs.
2. Retain the existing Indeed, Jobicy, FoundRole, WhatJobs, ai.jobs, Curaiz, Monster,
   joblet.ai and other configured plugin passes plus the web/employer/ATS gap search.
   Do not silently replace these with the MCP's five configured providers.
3. For a plugin result, supply its canonical facts, original provider identity, actual
   timestamp and full description to `assess_job_evidence(evidence, cv_variant)`.
   It does not contact the plugin, fetch arbitrary URLs, send CVs to providers or write.
   Caller-supplied HTTP observations remain explicitly caller-reported.
4. Use `get_job_detail`, `score_fit`, `tailor_resume(job_id, cv_variant)` and
   `cover_letter_brief` on the returned ID. Read the full description before ranking.
5. Use `prepare_handoff(job_id)` to export every source snapshot. The envelope carries
   stable URL/requisition evidence, a handoff key and any existing saved ID. The key is
   a reference, not proof of deduplication or persistence. Live IDs expire after 15 minutes and are lost on server restart.
   Preserve the exported envelope, not just its live ID. If a follow-up reports an expired
   or unavailable result, re-assess the preserved evidence once and use the exact new ID,
   keeping original source timestamps. If that retry fails, report UNAVAILABLE and retain
   the envelope for later; do not loop or claim persistence. A new live search is needed
   only when fresh provider evidence is required or no preserved snapshot is available.
6. Compare both the canonical Library seen-role registry and saved MCP records. An absent
   MCP record alone does not prove a role is unseen. Do not reset dismissed/applied states.
7. Persist only through an actually available, authorised write route. Confirm its result.
   Where Library writes are absent, include the portable envelope in the run output and
   mark PERSISTENCE_PENDING. Do not claim that the other agent or the MCP has received it.

Keep source audit labels DIRECT_CONNECTOR, DIRECT_SITE_OR_ATS, WEB_INDEXED,
ACCESS_LIMITED and UNAVAILABLE. Distinguish disabled, failed and zero-result providers.
Scout remains blocked until its OAuth callback is accepted. It must not be claimed searched.
A plugin outage does not justify inventing results or falling back silently to stale data.

## Retrieval timestamps from direct plugins

Some direct plugins omit a retrieval timestamp. A caller may measure UTC request start
and response receipt around a **new** awaited connector call, using a reliable runtime
clock. Its measured response-received time is the snapshot's `fetched_at`; explicitly
label it **caller-observed retrieval completion**. Provider backend fetch/cache time
remains unknown. Never stamp an old result with the current/report-generation time.
Keep `retrieval_method` within its schema enum; preserve timestamp basis and measurement
metadata alongside the evidence in the report or portable handoff envelope. Reassessment
must retain the measured retrieval time. Without a reliable observation or source time,
report UNAVAILABLE rather than inventing one.

## Shared role presentation and tool execution

Both agents use the same readable role layout: company/title with a link, a short
verdict, fit and gaps, and a separate evidence table for every reported role:

| Required field | Result |
| --- | --- |
| HTTP Status | Source plugin/MCP fetch outcome and observed transport code, or HTTP code unavailable |
| Eligibility / Compatibility | Employment, salary, remote scope and unresolved country restrictions |
| ATS Score — estimated CV keyword coverage | Value, matched/detected counts, CV variant and limitations |
| Fetched_at | Original source or caller-observed response receipt time, with timezone |
| Source | Provider, retrieval method and original listing link |

Do not compress these rows into prose. Keyword coverage is not an employer ATS
score or an overall suitability rating; incidental terms in links can affect it.
Review the full description for actual requirements and gaps.

Both agents actually call `score_fit`, `tailor_resume`, and `cover_letter_brief`
for substantively assessed surfaced roles, including Worldwide Scan. Clearly excluded
discovery noise can be logged without preparation calls. A tool's presence is not
evidence it executed; report failures honestly. Use portable evidence for handoff.

For suitable roles, deliver a fuller verdict explaining why to pursue or hold, matched
requirements with CV evidence, required versus desirable gaps, experience/seniority,
salary, country/remote eligibility, phone/on-call/weekend burden, freshness, uncertainties
and the next step. Prepare actual review-ready drafts: CV variant, truthful rewritten
summary/bullets, a tailored cover letter, answers to known form questions and missing
information. Do not invent employer questions, experience or personal answers. Neither
agent submits, uploads CVs, enters external forms, or contacts employers.

Previously seen does not mean applied. Relevant previously surfaced roles remain
eligible for preparation unless submission is confirmed or another exclusion applies.
Check shared application history and reuse existing drafts. Suppress confirmed submitted
requisitions from discovery/preparation, including later application stages; retain them
for tracking. If history is unavailable, label submission status unknown and preparation
provisional. Draft generation alone must not change application lifecycle state.

Run independent accessible connector searches concurrently after any prerequisites.
Dependent detail retrieval and assessment follow their inputs. Report each provider
as successful, zero results, unavailable, blocked, or failed. Preserve existing plugins
alongside Career Search; never claim a connector ran merely because its adapter exists.
No CV uploads or employer messages are needed for this workflow.

## Controlled write access

The deployed read-only MCP exposes 12 tools. `import_job_evidence`, `save_profile`,
`search_jobs` and `update_status` are absent and uncallable. Never relabel writes as reads.
The full interface exposes 17 tools for a separately authorised write-capable client.

An authenticated administrator can use the existing SSH route, without enabling public
ports or changing the read-only tunnel:

```sh
career-admin --database PRIVATE_DATABASE save-profile --file PRIVATE_PROFILE.json
career-admin --database PRIVATE_DATABASE import-handoff --file PRIVATE_HANDOFF.json
career-admin --database PRIVATE_DATABASE update-status --job-id ID --status review --reason 'User selected role'
```

Run as the service owner, transfer private inputs over verified SSH, use mode 0600, and
back up the database before profile updates. Do not commit profiles or evidence dumps.
Import validates all input records before writing; individual upserts are atomic and
idempotent, not a promised all-or-nothing batch. Existing lifecycle/history survives imports.
Older source snapshots cannot overwrite newer snapshots from the same provider identity.

This administrative route is implemented; it is not an unattended ChatGPT-to-AWS bridge.
Automatic Library/MCP synchronisation requires a verified authorised writer. Current
instructions must explicitly report a missing write capability rather than bypass it.

## Shared submitted-application check

Use `application_tracking` from Career Search as the shared recorded submission check.
See [application register](application-register.md) for the Mark as applied action,
confirmed imports and exact read-only limitations. A Library seen record alone never
means applied. Reconcile confirmed Library submissions through the authenticated admin
route; until reconciled, either source confirming submission suppresses new preparation.
