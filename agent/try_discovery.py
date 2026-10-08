"""Play the agent on the discovery server: call each tool once over stdio and verify each answer.

Usage: python try_discovery.py [--live]      (--live also runs vegetation_history, which calls Earth Engine)
"""
import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = Path(__file__).resolve().parent / "discovery_server.py"


async def main(live: bool):
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()
            print("tools:", [t.name for t in (await s.list_tools()).tools])

            async def call(name, args=None):
                res = await s.call_tool(name, args or {})
                text = res.content[0].text if res.content else ""
                print(f"\n=== {name} {args or ''}\n{text[:1200]}")
                v = await s.call_tool("verify", {})
                print("verify ->", v.content[0].text)

            await call("search_catalog", {"query": "land surface temperature for each zone", "k": 5})
            await call("describe_dataset", {"dataset_id": "phmsa_accidents"})
            await call("search_spill_reports", {"query": "a farmer found crude oil in his pasture", "k": 5})
            await call("search_spill_reports", {"query": "contaminated soil was excavated and hauled away", "k": 5,
                                                "soil_removed": "yes"})
            await call("spill_report", {"spill_or_report_id": "S024"})
            await call("similar_places", {"place_id": "S024", "year": 2024, "k": 5})
            await call("similar_places", {"place_id": "147-000014-32-0-1", "year": 2024, "k": 5})
            await call("places_like_spills", {"year": 2024, "k": 10})
            if live:
                await call("vegetation_history", {"place": "S024", "index": "NDVI", "first_spring": 2019, "last_spring": 2025})


if __name__ == "__main__":
    asyncio.run(main("--live" in sys.argv))
