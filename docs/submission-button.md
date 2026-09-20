# Mark as submitted

`show_application_tracker(job_ids)` renders a small interactive card in compatible
ChatGPT clients. It accepts only persisted IDs and reads the authoritative shared
application register. It does not save anything merely by rendering.

Both agents should finish each prepared shortlist with this tool. First persist
external or temporary results with `import_job_evidence` and retain the returned
canonical IDs. Continue to provide the evidence tables and full application drafts
in the conversation; the card supplements that output.

The user clicks **Mark as submitted**, then **Yes, I have submitted it**. The card
calls the existing `mark_as_applied` tool and reads the saved job back before showing
**Submitted ✓**. It never opens an employer form or sends an application. A repeated
confirmation is idempotent. The submission time remains unknown; the confirmation
time is recorded separately. ChatGPT's normal tool approval controls still apply.

The card uses the MCP Apps host bridge and has no credentials, external scripts,
network requests or browser storage. Job titles are inserted as text, not HTML.
Read-only mode disables the button and removes the underlying write handler.
If the host cannot render interactive cards, the same action remains available by
saying “Mark this role as submitted” in the conversation.

The interface adds one read tool: full mode has 18 tools (13 read and 5 write).
Scheduled execution does not imply a human clicked a confirmation: scheduled agents
must never infer submission from a prepared application or rendered card.
