"""Read-only external discovery through an actual MCP HTTP client.

Discovery persists job listings on the server; no profile, application or message writes.
"""

import argparse
import asyncio
import json

from fastmcp import Client


async def run(url: str):
    async with Client(url, timeout=120) as client:
        names = [tool.name for tool in await client.list_tools()]
        assert {"build_profile", "score_fit", "tailor_resume", "cover_letter_brief"} <= set(names)
        result = await client.call_tool("search_jobs", {"query": "Technical Support Engineer"})
        assert not result.is_error
        data = result.data
        print(
            json.dumps(
                {
                    "tools": names,
                    "source_status": data["source_status"],
                    "jobs": len(data["jobs"]),
                    "excluded": len(data["excluded_jobs"]),
                },
                indent=2,
            )
        )
        if not data["jobs"]:
            raise RuntimeError("No job available for evidence-tool verification")
        job = data["jobs"][0]
        for name in ["score_fit", "tailor_resume", "cover_letter_brief"]:
            result = await client.call_tool(name, {"job_id": job["id"]})
            assert not result.is_error
            assert result.data["reasoning_owner"] == "ChatGPT"
        print(
            json.dumps(
                {
                    "evidence_tools": "passed",
                    "sample": {
                        k: job[k] for k in ["title", "company", "source_url", "remote_scope"]
                    },
                    "chatgpt_connection_verified": False,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    asyncio.run(run(parser.parse_args().url))
