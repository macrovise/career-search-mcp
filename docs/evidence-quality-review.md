# Evidence quality review and release

Three independent reviewers tested the initial patch and the port onto the newer
career-quality-packs feature source. The fixes address:

- Requirement headings after benefits no longer suppress genuine skills or discovery.
- Generic discovery matching stays independent from candidate-evidence section filtering.
- URL masking preserves adjacent Markdown text and original source offsets.
- HTML block boundaries survive normalisation for section-aware evidence filtering.
- Fit evidence, structured requirements and keyword coverage use the same candidate mask.
- Structured evidence quotes retain literal source text; URLs cannot create capabilities.
- Partial compound requirements remain partial; alternatives are sent for review without
  inventing conjunctive gaps. This is conservative vocabulary-based evidence, not NLP.
- Writing briefs include British English, concise letters and preservation of metrics.
- Explicitly preferred hybrid roles remain reviewable.

Validation: 179 tests pass; Ruff lint and formatting checks pass. Twelve new regression
cases cover the review findings and original writing/hybrid requirements.

Source base: cba311da45eb9014fbe6ef4ff7141c7414b945cc on feat/career-quality-packs.
This preserves application packs, requirement extraction and CV variants absent from
the older main checkout. The existing host's installed revision must still be checked.

Deployment is not completed: this session has no authenticated SSH/AWS administrative
route or concrete target hostname. GitHub CI's VM-install job tests an ephemeral runner;
it is not a production deployment. Before release, inspect the existing server revision,
preserve its live configuration, snapshot its authoritative SQLite database consistently,
deploy the compatible patch, and verify tool discovery, the read-only evidence chain,
application-pack availability and unchanged application history. Do not run the fresh-host
installer over an existing installation or create a second authoritative database.
