"""Check the deployed HTTP service without writes or contacting any job provider."""

import asyncio
import json

from fastmcp import Client

EXPECTED_TOOLS = {
    "assess_job_evidence",
    "prepare_handoff",
    "build_profile",
    "cover_letter_brief",
    "get_job_detail",
    "get_job_history",
    "get_my_jobs",
    "get_profile",
    "score_fit",
    "search_saved_jobs",
    "search_live_jobs",
    "tailor_resume",
}


async def main():
    async with Client("http://127.0.0.1:8383/mcp") as client:
        tools = await client.list_tools()
        if {tool.name for tool in tools} != EXPECTED_TOOLS:
            raise RuntimeError("The server does not expose the expected read-only tools.")
        if any(not tool.annotations or not tool.annotations.readOnlyHint for tool in tools):
            raise RuntimeError("A tool is missing its read-only annotation.")
        profile = await client.call_tool("get_profile", {})
        results = await client.call_tool(
            "search_saved_jobs", {"query": "Support", "limit": 3, "offset": 0}
        )
        if profile.is_error or results.is_error:
            raise RuntimeError("A read-only MCP request failed.")
        # Do not print profile or job data to deployment/CI logs.
        print(
            json.dumps({"read_only_tools": len(tools), "profile_read": True, "search_read": True})
        )


if __name__ == "__main__":
    asyncio.run(main())
