"""Local GeoAI dashboard: an ArcGIS map with an "ask the map" agent, at http://localhost:8392 (statewide results).

The browser shows the statewide sample's segments (coloured by the 0-50 m NDVI gap) and the reported spills, over
OpenStreetMap, Esri World Imagery or USGS NAIP aerial photos. A question goes to a manager agent: a local model in Ollama (qwen2.5:14b by
default) that plans the work and calls the project's MCP tools (geog392_mcp_server.py). After every data tool the app
itself calls `verify`, so each answer arrives with an independent check the model cannot skip. Nothing leaves this
computer: the model, the tools and the data all run locally.

Run with the project's Python:
    C:\\Users\\Landon\\.geog392\\venv\\Scripts\\python.exe ai_dashboard.py

Settings (environment variables): GEOAI_MODEL (default qwen2.5:14b), OLLAMA_URL (default: Ollama's own OLLAMA_HOST
setting, else http://127.0.0.1:11434),
GEOAI_HOST (default 127.0.0.1, this computer only; set it to the desktop's Tailscale address to open the app from a
laptop), GEOAI_PORT (default 8392), GEOG392_PROJECT (the projects folder), ARCPY_PYTHON (ArcGIS Pro's python.exe).
"""
import asyncio
import contextlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import geopandas as gpd
import pandas as pd
import uvicorn
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

HERE = Path(__file__).resolve().parent
PROJECT = Path(os.environ.get("GEOG392_PROJECT", "C:/mydrive/Graduate School/Courses/GEOG_392/projects"))
def _ollama_url() -> str:
    """Where the local model server answers: OLLAMA_URL, else Ollama's own OLLAMA_HOST setting, else this computer."""
    if os.environ.get("OLLAMA_URL"):
        return os.environ["OLLAMA_URL"].rstrip("/")
    host = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434").replace("0.0.0.0", "127.0.0.1")
    host = host if host.startswith("http") else "http://" + host
    return (host if host.count(":") >= 2 else host + ":11434").rstrip("/")


OLLAMA = _ollama_url()
MODEL = os.environ.get("GEOAI_MODEL", "qwen2.5:14b")
HOST = os.environ.get("GEOAI_HOST", "127.0.0.1")
PORT = int(os.environ.get("GEOAI_PORT", "8392"))
MAX_STEPS = 8
CHECKED = {"query_zones", "spill_timeline", "left_out", "hot_spots", "corridor_summary", "segment", "distance_profile"}

SYSTEM = """You are the manager agent for GEOG 392 Group 10's pipeline project: "Can satellites see pipeline leaks?"
You answer questions about the statewide results by calling tools. Every Texas pipeline was cut into 1 km segments; a
stratified sample of 3,499 segments (weighted to stand for 296,191) and 82 reported spills are measured in Sentinel-2
imagery every spring. Springs 2023-2025 are measured so far. A gap is the 0-50 m ring beside the pipe minus the same
segment's clean comparison ring 500-1,000 m away (like-for-like land cover): negative means less green than normal land.

Rules:
- Always answer in English.
- Every number in your answer must come from a tool result in this conversation. Never guess or invent numbers.
- For statewide or group answers ("which pipeline types...", "by ecoregion"), call corridor_summary: it applies the
  sampling weights and gives 95% intervals. Its 'by' can be statewide, ecoregion, commodity_group, service,
  diameter_class, status or location_accuracy.
- For one segment, call segment with its ID (IDs look like 001-000025-35-0-8). For lists and rankings of segments, use
  query_zones on the segments table (columns NDVI_gap_0_50, commodity_group, diameter_in, ecoregion, ...); call
  list_tables first if you need column names.
- distance_profile answers how far from the pipe the effect reaches (ten 50 m bands out to 500 m); repeat its
  "Reading it" line.
- spill_timeline shows one spill (IDs look like S006) against its comparison spots spring by spring.
- hot_spots finds clusters of high or low NDVI_diff_0_50 with ArcGIS Pro (it takes a minute or two).
- left_out answers what the statewide build covers and leaves out.
- The app checks every data answer independently; you do not need to call verify.
- Read significance from the tool, not from your own judgment: corridor_summary says for each group whether it
  differs from zero, and its "Reading it" line says whether the strongest and weakest groups differ. Repeat that line's
  conclusion; never say groups do not differ when it says their intervals do not overlap.
- Answer in two to five short, plain sentences, with the 95% interval when there is one. Say these are first results
  from three springs, not findings. When the user should look at something on the map, name the segment IDs or spill IDs."""

STATE: dict = {}
LOCK = asyncio.Lock()          # one question at a time: verify always checks the call just made


def _layers() -> dict[str, str]:
    agent = PROJECT / "outputs" / "agent"            # built by analysis/agent_tables.py
    seg = gpd.read_file(agent / "segment_points.gpkg", layer="segment_points").to_crs(4326)
    seg = seg[["segment_id", "commodity", "service", "diameter_in", "OPER_NM", "status", "location_accuracy", "ecoregion",
               "springs_measured", "NDVI_diff_0_50", "NDRE_gap_0_50", "NDMI_gap_0_50", "geometry"]]
    sp = pd.read_parquet(agent / "spills.parquet")
    spills = gpd.GeoDataFrame(sp[["spill_id", "date", "barrels", "commodity", "cause", "ecoregion", "location_accuracy"]],
                              geometry=gpd.points_from_xy(sp["lon"], sp["lat"]), crs=4326)
    STATE["known"] = {"segments": set(seg["segment_id"]), "spills": set(spills["spill_id"])}   # only real IDs get highlighted
    return {"segments": seg.to_json(drop_id=True), "spills": spills.to_json(drop_id=True)}


def _as_ollama_tool(tool) -> dict:
    schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None) or {"type": "object", "properties": {}}
    return {"type": "function", "function": {"name": tool.name, "description": tool.description or "", "parameters": schema}}


def _ollama_chat(messages: list, tools: list) -> dict:
    body = json.dumps({"model": MODEL, "messages": messages, "tools": tools, "stream": False,
                       "options": {"temperature": 0, "num_ctx": 16384}}).encode()
    req = urllib.request.Request(f"{OLLAMA}/api/chat", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.loads(r.read())


async def _call(name: str, args: dict) -> tuple[str, bool]:
    result = await STATE["session"].call_tool(name, args)
    text = "\n".join(getattr(c, "text", "") for c in result.content)
    return text, bool(getattr(result, "isError", False))


SEGMENT_ID = re.compile(r"\b\d{3}-\d{6}-\d{2}-\d{1,3}-\d{1,4}\b")      # county-line-ecoregion-part-piece
SPILL_ID = re.compile(r"\bS\d{3}\b")


async def ask(question: str) -> dict:
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}]
    steps, started = [], time.time()
    for _ in range(MAX_STEPS):
        reply = await asyncio.to_thread(_ollama_chat, messages, STATE["tools"])
        msg = reply.get("message", {})
        messages.append(msg)
        calls = msg.get("tool_calls") or []
        if not calls:
            answer = msg.get("content", "").strip()
            break
        for call in calls:
            name = call.get("function", {}).get("name", "")
            args = call.get("function", {}).get("arguments") or {}
            if isinstance(args, str):
                args = json.loads(args or "{}")
            t0 = time.time()
            text, is_error = await _call(name, args)
            check = None
            if name in CHECKED and not is_error:
                check, _ = await _call("verify", {})
            steps.append({"tool": name, "args": args, "seconds": round(time.time() - t0, 1),
                          "error": is_error, "result": text[:4000], "check": check})
            messages.append({"role": "tool", "content": text[:6000], "tool_name": name})
    else:
        answer = "I stopped after too many steps without a final answer. Try a more specific question."
    letters = [c for c in answer if c.isalpha()]
    if letters and sum(c.isascii() for c in letters) / len(letters) < 0.9:      # the model drifted out of English
        messages.append({"role": "user", "content": "Rewrite your last answer in plain English, keeping every number."})
        answer = (await asyncio.to_thread(_ollama_chat, messages, [])).get("message", {}).get("content", answer).strip()
    seen = answer + "\n" + "\n".join(s["result"] for s in steps)
    return {"answer": answer, "steps": steps, "model": MODEL, "seconds": round(time.time() - started, 1),
            "highlight": {"segments": sorted(set(SEGMENT_ID.findall(seen)) & STATE["known"]["segments"])[:300],
                          "spills": sorted(set(SPILL_ID.findall(seen)) & STATE["known"]["spills"])}}


async def page(request: Request):
    return FileResponse(HERE / "static" / "index.html")


async def layer(request: Request):
    name = request.path_params["name"]
    if name not in STATE["layers"]:
        return Response(status_code=404)
    return Response(STATE["layers"][name], media_type="application/geo+json")


async def status(request: Request):
    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=5) as r:
            models = [m["name"] for m in json.loads(r.read()).get("models", [])]
        ollama = MODEL in models
    except (urllib.error.URLError, OSError):
        ollama = False
    return JSONResponse({"model": MODEL, "model_ready": ollama, "tools": [t["function"]["name"] for t in STATE["tools"]]})


async def ask_route(request: Request):
    body = await request.json()
    question = (body.get("question") or "").strip()
    if not question:
        return JSONResponse({"error": "Type a question first."}, status_code=400)
    async with LOCK:
        try:
            return JSONResponse(await ask(question))
        except (urllib.error.URLError, OSError) as e:
            return JSONResponse({"error": f"Could not reach the local model at {OLLAMA} ({e}). Is Ollama running?"}, status_code=503)


@contextlib.asynccontextmanager
async def lifespan(app):
    STATE["layers"] = _layers()
    async with contextlib.AsyncExitStack() as stack:
        params = StdioServerParameters(command=sys.executable, args=[str(HERE / "geog392_mcp_server.py")])
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        tools = (await session.list_tools()).tools
        STATE.update(session=session, tools=[_as_ollama_tool(t) for t in tools if t.name != "verify"])
        print(f"GeoAI dashboard: http://{HOST}:{PORT}  (model {MODEL}; tools: {', '.join(t.name for t in tools)})", flush=True)
        yield


app = Starlette(routes=[Route("/", page), Route("/api/status", status), Route("/api/layers/{name}.geojson", layer),
                        Route("/api/ask", ask_route, methods=["POST"])], lifespan=lifespan)

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
