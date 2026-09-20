from fastmcp import Client

from jobsearch_mcp.server import create_server
from jobsearch_mcp.sources.normalize import make_job
from jobsearch_mcp.store import Store


async def test_tracker_is_read_only_and_uses_saved_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("CAREER_READ_ONLY", "false")
    store = Store(str(tmp_path / "jobs.db"))
    job = store.upsert(
        make_job(
            "himalayas",
            {
                "title": "Support Engineer",
                "company": "Example",
                "source_url": "https://example.com/jobs/1",
            },
        )
    )
    async with Client(create_server(store, local_test=True)) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        tracker = tools["show_application_tracker"]
        assert tracker.annotations.readOnlyHint
        uri = tracker.meta["ui"]["resourceUri"]
        resources = await client.read_resource(uri)
        assert "Mark as submitted" in resources[0].text
        assert "event.source !== window.parent" in resources[0].text
        with store.connection() as db:
            before = list(db.iterdump())
        result = await client.call_tool("show_application_tracker", {"job_ids": [job.id, job.id]})
        assert result.data["writes_enabled"]
        assert len(result.data["jobs"]) == 1
        assert result.data["jobs"][0]["id"] == job.id
        assert result.data["jobs"][0]["application_tracking"]["submission_status"] == "unknown"
        for ids in [[], ["live:missing"], ["missing"], [job.id] * 21]:
            failed = await client.call_tool(
                "show_application_tracker", {"job_ids": ids}, raise_on_error=False
            )
            assert failed.is_error
        with store.connection() as db:
            assert list(db.iterdump()) == before


async def test_read_only_tracker_disables_submission(tmp_path, monkeypatch):
    monkeypatch.setenv("CAREER_READ_ONLY", "true")
    store = Store(str(tmp_path / "jobs.db"))
    job = store.upsert(
        make_job(
            "himalayas", {"title": "Support Engineer", "source_url": "https://example.com/jobs/2"}
        )
    )
    async with Client(create_server(store, local_test=True)) as client:
        result = await client.call_tool("show_application_tracker", {"job_ids": [job.id]})
        assert not result.data["writes_enabled"]
        assert "mark_as_applied" not in {t.name for t in await client.list_tools()}
