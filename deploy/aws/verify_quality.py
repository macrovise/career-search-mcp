"""Read-only checks of the full deployed surface; never print personal evidence."""

import asyncio
import json

from fastmcp import Client

WRITES = {
    "search_jobs",
    "save_profile",
    "update_status",
    "import_job_evidence",
    "mark_as_applied",
    "save_application_pack",
}
NEW_READS = {
    "verify_employer_job",
    "get_discovery_changes",
    "get_source_health",
    "get_application_pack",
}


async def main():
    async with Client("http://127.0.0.1:8383/mcp") as client:
        tools = await client.list_tools()
        names = {tool.name for tool in tools}
        assert len(names) == 23 and names >= WRITES | NEW_READS
        assert {tool.name for tool in tools if not tool.annotations.readOnlyHint} == WRITES
        for name, args in [
            ("get_profile", {}),
            ("get_source_health", {}),
            ("get_discovery_changes", {"since": "2026-09-20T00:00:00Z", "limit": 1}),
            ("search_saved_jobs", {"query": "Support", "limit": 1}),
        ]:
            result = await client.call_tool(name, args)
            assert not result.is_error, name
        print(json.dumps({"tools": len(names), "writes": len(WRITES), "read_checks": "passed"}))


if __name__ == "__main__":
    asyncio.run(main())
