# Career Search MCP contributor guidance

Fork of TadMSTR/jobsearch-mcp, customised for one user's ChatGPT workflow.
Read README.md and docs/architecture.md before changing the implementation.

- ChatGPT is the only reasoning layer. Never add internal LLM, auto-apply, scraping,
  or messaging calls. Keep build_profile, score_fit, tailor_resume, cover_letter_brief.
- Preferences are not candidate experience. Every verified skill needs résumé evidence.
- Preserve URL/DNS/redirect protections, owner-bound OAuth, no-secret logging and
  non-root/capability-free containers. Local mode must remain loopback-only.
- Preserve provenance, lifecycle audit history and atomic deduplication transactions.
- Sources can fail independently. Never turn an access failure into an empty success.
- Add regression tests for meaningful behavior, then run pytest and Ruff checks.
- Branch before edits; keep upstream remote and make focused commits.
- Do not commit personal profiles, databases, tokens, environment files or live response dumps.
