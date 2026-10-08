"""Play the agent: start the MCP server over stdio, call every tool once, and verify each answer.

Usage: python try_tools.py [--skip-hot-spots]
"""
import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = Path(__file__).resolve().parent / "geog392_mcp_server.py"


async def main(skip_hot_spots: bool):
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()
            tools = await s.list_tools()
            print("tools:", [t.name for t in tools.tools])

            async def call(name, args=None, verify=True):
                res = await s.call_tool(name, args or {})
                text = res.content[0].text if res.content else ""
                print(f"\n=== {name} {args or ''}\n{text[:900]}")
                if verify:
                    v = await s.call_tool("verify", {})
                    print("verify ->", v.content[0].text)

            await call("list_tables", verify=False)
            await call("query_zones", {"sql": "SELECT ecoregion, COUNT(*) AS n FROM segments GROUP BY 1 ORDER BY 2 DESC"})
            await call("corridor_summary", {"index": "NDVI", "ring": "0-50 m", "by": "diameter_class"})
            await call("segment", {"segment_id": "001-000025-35-0-8"})
            await call("distance_profile", {"index": "NDVI"})
            await call("spill_timeline", {"spill_id": "S006", "index": "NDVI", "radius_m": 50})
            await call("left_out")
            if not skip_hot_spots:
                await call("hot_spots", {"field": "NDVI_diff_0_50"})


if __name__ == "__main__":
    asyncio.run(main("--skip-hot-spots" in sys.argv))
