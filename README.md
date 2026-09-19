# Career Search MCP

A personal job-search evidence service for ChatGPT, forked from
[TadMSTR/jobsearch-mcp](https://github.com/TadMSTR/jobsearch-mcp).
ChatGPT does the reasoning and writing. This server discovers jobs, records provenance,
deduplicates listings, prepares evidence, and tracks the application lifecycle.
It never calls an LLM, submits an application, or sends a message.

## Start locally

Python 3.11+ is required. From the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
CAREER_AUTH_MODE=local .venv/bin/career-search-mcp
```

This starts Streamable HTTP at `http://127.0.0.1:8383/mcp`. Local mode refuses a
non-loopback bind. It is for trusted local clients only; do not expose it through
a generic public tunnel. The default mode is OAuth and fails closed without configuration.

In another terminal, exercise the real local HTTP transport:

```sh
.venv/bin/python scripts/smoke_mcp.py http://127.0.0.1:8383/mcp
```

Run the watcher once, or leave it running with its six-hour interval:

```sh
.venv/bin/career-watcher --once
.venv/bin/career-watcher
```

The watcher stores discoveries and marks explicitly scheduled follow-ups due.
It never marks a job applied, infers rejection from a missing search result, or sends email.
It runs only while this process is running; no background system service is installed automatically.

## ChatGPT Pro read-only access

ChatGPT Pro supports custom MCP apps with read/fetch permissions in Developer Mode;
write-capable MCP access is currently limited to Business, Enterprise, and Edu. For Pro,
run the MCP server with `CAREER_READ_ONLY=true` and keep the watcher running locally as a
separate process. ChatGPT can then use `search_saved_jobs` to read the watcher’s saved
results without starting a live search or changing stored data. The four evidence and
writing-preparation tools remain available. Profile saving and lifecycle changes are not
available through the Pro connection. This reflects current OpenAI documentation; it does
not confirm tunnel access or a working ChatGPT connection for any particular account. See
[the tunnel and Pro setup guide](docs/deployment.md).

No tunnel, API key, Adzuna account, subscription change, or deployment is provisioned
automatically. Optional Adzuna credentials require registration with the
[Adzuna developer site](https://developer.adzuna.com/signup); setup details are in the
deployment guide.

## Development checks

```sh
.venv/bin/pytest -q
.venv/bin/ruff check src tests scripts
.venv/bin/ruff format --check src tests scripts
.venv/bin/python -m pip check
```

Mocked source tests require no credentials. The smoke script performs live public
searches and writes job listings to the configured local database, but sends no résumé.
Failures from individual providers appear explicitly in `source_status`.

## Architecture and documentation

- [Architecture, schema, matching, lifecycle, and source precedence](docs/architecture.md)
- [Secure deployment, configuration, and ChatGPT connection](docs/deployment.md)
- [Source status and verification limits](docs/verification.md)
- [Security policy](SECURITY.md)

SQLite with WAL is the only datastore. MCP and one watcher share a local persistent
volume. No Postgres, Qdrant, Valkey, Ollama, Anthropic, Firecrawl, SMTP, or scraping
service is required. This is a single-user, single-host deployment, not a distributed service.

## Upstream maintenance

The repository retains upstream history and MIT attribution. Use separate remotes:

```sh
git remote -v
git fetch upstream
git log --oneline HEAD..upstream/main
# Review individual fixes before selectively applying them:
git cherry-pick <reviewed-commit>
```

`origin` points to `macrovise/career-search-mcp`; `upstream` points to
`TadMSTR/jobsearch-mcp`. The custom branch is `feat/career-search-chatgpt`.
Do not blindly merge upstream's former Claude, identity-header, or scraping paths.
The previous implementation and tests remain recoverable in Git history.
