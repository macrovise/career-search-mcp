import pytest
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


async def test_read_only_surface_searches_without_writes(tmp_path, monkeypatch):
    monkeypatch.setenv("CAREER_READ_ONLY", "true")
    store = Store(str(tmp_path / "db"))
    for index, employment_type in enumerate(["permanent", "contract"]):
        store.upsert(
            make_job(
                "himalayas",
                dict(
                    title="Support Engineer",
                    source_id=str(index),
                    source_url=f"https://example.com/jobs/{index}",
                    employment_type=employment_type,
                    description="SQL API",
                ),
            )
        )
    with store.connection() as db:
        before = list(db.iterdump())
    async with Client(create_server(store, local_test=True)) as client:
        tools = {t.name: t for t in await client.list_tools()}
        assert all(tool.annotations.readOnlyHint for tool in tools.values())
        assert {"build_profile", "score_fit", "tailor_resume", "cover_letter_brief"} <= tools.keys()
        assert (
            not {
                "search_jobs",
                "save_profile",
                "update_status",
                "mark_as_applied",
            }
            & tools.keys()
        )
        result = await client.call_tool("search_saved_jobs", {"query": "SUPPORT sql"})
        assert len(result.data["jobs"]) == len(result.data["excluded_jobs"]) == 1
        assert result.data["persisted"] is False
        assert result.data["returned_count"] == 2
        # Removed handlers must be uncallable, not merely hidden from discovery.
        for name, arguments in {
            "search_jobs": {"query": "Support"},
            "save_profile": {"profile": {}},
            "update_status": {"job_id": "x", "status": "applied", "reason": "test"},
            "mark_as_applied": {
                "job_id": "x",
                "confirmation": {
                    "confirmed": True,
                    "recorded_at": "2026-09-19T12:00:00Z",
                    "evidence": "User confirmed submission",
                    "evidence_source": "user_confirmation",
                },
            },
        }.items():
            result = await client.call_tool(name, arguments, raise_on_error=False)
            assert result.is_error
        result = await client.call_tool("search_saved_jobs", {"query": "   "}, raise_on_error=False)
        assert result.is_error
    with store.connection() as db:
        assert list(db.iterdump()) == before


def test_invalid_read_only_setting_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("CAREER_READ_ONLY", "typo")
    with pytest.raises(ValueError, match="CAREER_READ_ONLY"):
        create_server(Store(str(tmp_path / "db")), local_test=True)
