from fastmcp import Client

from jobsearch_mcp.server import create_server
from jobsearch_mcp.sources.normalize import make_job
from jobsearch_mcp.store import Store


async def test_mcp_workflow(tmp_path):
    store = Store(str(tmp_path / "db"))
    job = store.upsert(
        make_job(
            "himalayas",
            dict(
                title="Support Engineer",
                source_url="https://example.com/jobs/1",
                description="SQL API",
            ),
        )
    )
    async with Client(create_server(store, local_test=True)) as client:
        tools = {t.name: t for t in await client.list_tools()}
        assert {"build_profile", "score_fit", "tailor_resume", "cover_letter_brief"} <= tools.keys()
        assert tools["score_fit"].annotations.readOnlyHint
        assert not tools["search_jobs"].annotations.readOnlyHint
        profile = await client.call_tool("build_profile", {"raw_text": "I used SQL"})
        assert profile.data["reasoning_owner"] == "ChatGPT"
        for name in ["score_fit", "tailor_resume", "cover_letter_brief"]:
            result = await client.call_tool(name, {"job_id": job.id})
            assert not result.is_error
        result = await client.call_tool(
            "update_status",
            {"job_id": job.id, "status": "interesting", "reason": "user selected role"},
        )
        assert result.data["status"] == "interesting"
        result = await client.call_tool(
            "update_status",
            {"job_id": job.id, "status": "nonsense", "reason": "invalid"},
            raise_on_error=False,
        )
        assert result.is_error
