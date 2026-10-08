"""Pipeline Discovery Lab: an ArcGIS map with an "ask the map" agent over two MCP servers, at http://localhost:8392.

The browser shows the statewide sample's segments (coloured by the 0-50 m NDVI gap) and the reported spills, over
OpenStreetMap, Esri World Imagery or USGS NAIP aerial photos. A question goes to a manager agent: a local model in
Ollama (qwen2.5:14b by default) that plans the work and calls tools on two MCP servers:
  results    geog392_mcp_server.py   the statewide results (corridor, distance profile, segments, hot spots, spills)
  discovery  discovery_server.py     the data catalog, the spill narratives, look-alike places, live vegetation history
After every data tool the app itself calls that server's `verify`, so each step arrives with an independent check the
model cannot skip. Every number in the written answer is then checked against the tool results; a number no tool gave
is flagged. "Export brief" writes a short Markdown report of the answer, its evidence and its checks. Nothing leaves
this computer except Earth Engine calls for vegetation_history: the model, the tools and the data all run locally.

Run with the project's Python (or double-click start_dashboard.bat):
    C:\\Users\\Landon\\.geog392\\venv\\Scripts\\python.exe ai_dashboard.py

Settings (environment variables): GEOAI_MODEL (default qwen2.5:14b), OLLAMA_URL (default: Ollama's own OLLAMA_HOST
setting, else http://127.0.0.1:11434), GEOAI_HOST (default 127.0.0.1, this computer only), GEOAI_PORT (default 8392),
GEOG392_PROJECT (the projects folder), ARCPY_PYTHON (ArcGIS Pro's python.exe).
"""
import asyncio
import contextlib
import io
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
SERVERS = {"results": HERE / "geog392_mcp_server.py", "discovery": HERE / "discovery_server.py"}


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
NOT_CHECKED = {"list_tables"}                 # every other tool is verified after each call

SYSTEM = """You are the manager agent of the Pipeline Discovery Lab, GEOG 392 Group 10's project "Can satellites see
pipeline leaks?" You answer by calling tools on two servers: the results and the discovery tools. Every Texas pipeline
was cut into 1 km segments; a stratified sample of 3,499 segments (weighted to stand for 296,191) and 82 reported
spills are measured in Sentinel-2 imagery every spring. A gap is a band beside the pipe minus the same segment's clean
comparison ring 500-1,000 m away (like-for-like land cover): negative means less green than normal land.

Rules:
- Always answer in English.
- Every number in your answer must come from a tool result in this conversation. Never guess or invent numbers; the app
  checks every number you write against the tool results and flags any that no tool gave.
- Statewide or group answers: corridor_summary (by statewide, ecoregion, commodity_group, service, diameter_class,
  status or location_accuracy), with its 95% interval and its "Reading it" line. How far from the pipe: distance_profile.
- One segment: segment (IDs look like 001-000025-35-0-8). Lists and rankings: query_zones (call list_tables first if
  you need column names). One spill against its comparison spots: spill_timeline (IDs look like S006).
- What data exists, where it came from, what it feeds: search_catalog, then describe_dataset.
- The spill narratives: search_spill_reports, then spill_report for one. Use its filters for facts (how_found,
  cleanup, soil_removed, reached_water, since_year) and the query for meaning. Its first line says how many reports match
  the filters, or that all were searched; the reports listed are the closest in meaning, not a count. Say when a field
  is marked unsupported.
- Never answer from memory: every answer starts with at least one tool call.
- Look-alike places: similar_places and places_like_spills (Google's Satellite Embedding). Similar means looks alike from
  space, never that a place will leak.
- A live record of any spot: vegetation_history (place = a segment ID, a spill ID or 'latitude, longitude'); call it at
  most once per question.
- Clusters: hot_spots (ArcGIS Pro; a minute or two). Coverage: left_out.
- The app checks every tool answer independently; you do not need to call verify.
- Read significance from the tools, not your own judgment; repeat their "Reading it" lines.
- Answer in two to five short, plain sentences. These are first results, not findings. Name the segment IDs or spill IDs
  the user should look at on the map."""

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


async def _call(server: str, name: str, args: dict) -> tuple[str, bool]:
    result = await STATE["sessions"][server].call_tool(name, args)
    text = "\n".join(getattr(c, "text", "") for c in result.content)
    return text, bool(getattr(result, "isError", False))


SEGMENT_ID = re.compile(r"\b\d{3}-\d{6}-\d{2}-\d{1,3}-\d{1,4}\b")      # county-line-ecoregion-part-piece
SPILL_ID = re.compile(r"\bS\d{3}\b")
NUMBER = re.compile(r"(?<![\w.])[-+−]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?%?")


def _numbers(text: str) -> list[str]:
    text = SEGMENT_ID.sub(" ", SPILL_ID.sub(" ", text))
    return [m.group(0) for m in NUMBER.finditer(text)]


def _value(token: str) -> float:
    return float(token.replace("−", "-").replace(",", "").rstrip("%"))


def number_check(answer: str, evidence: list[str]) -> dict:
    """Every number in the answer must match a number in the tool results at the precision it is written (a percent may
    match a fraction). Small counting words like 'two' are not numbers here; years and IDs are skipped."""
    found = [_value(t) for e in evidence for t in _numbers(e)]
    checked, unsupported = 0, []
    for token in _numbers(answer):
        x = _value(token)
        if token.isdigit() and 2000 <= x <= 2030:            # a year
            continue
        mantissa = token.rstrip("%").lower().split("e")[0]
        decimals = len(mantissa.split(".")[1]) if "." in mantissa else 0
        if "e" in token.lower():                              # 3.9e-04: the precision of the written value
            decimals += -int(token.lower().split("e")[1])
        tol = 0.5 * 10 ** -decimals + 1e-12
        candidates = found + ([y * 100 for y in found] if token.endswith("%") else [])
        checked += 1
        if not any(abs(x - y) <= tol or abs(abs(x) - abs(y)) <= tol for y in candidates):
            unsupported.append(token)
    return {"checked": checked, "unsupported": unsupported}


def _chart(step: dict) -> dict | None:
    """A vegetation history comes back as a small table: draw it."""
    if step["tool"] != "vegetation_history" or step["error"]:
        return None
    try:
        lines = step["result"].splitlines()
        t = pd.read_csv(io.StringIO("\n".join(lines[1:])))
        t = t.dropna(subset=["value"])
        return {"title": lines[0].rstrip(":"), "x": t["spring"].astype(int).tolist(), "y": t["value"].round(4).tolist(),
                "n": t["clear_images"].tolist()}
    except Exception:
        return None


async def ask(question: str) -> dict:
    STATE["nudged"] = False
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}]
    steps, started = [], time.time()
    for _ in range(MAX_STEPS):
        reply = await asyncio.to_thread(_ollama_chat, messages, STATE["tools"])
        msg = reply.get("message", {})
        messages.append(msg)
        calls = msg.get("tool_calls") or []
        if not calls and not steps and not STATE.get("nudged"):
            # no answer from memory: send the model back once to use the tools
            STATE["nudged"] = True
            messages.append({"role": "user", "content": "Answer only from the project's tools: call the tool that fits "
                             "(search_catalog for questions about data, corridor_summary for results, search_spill_reports "
                             "for spill reports), then answer from its result."})
            continue
        if not calls:
            answer = msg.get("content", "").strip()
            if not steps:
                answer = ("I could not answer this from the project's tools. Try naming what you want: a dataset, a "
                          "segment, a spill or a result.")
            break
        for call in calls:
            name = call.get("function", {}).get("name", "")
            args = call.get("function", {}).get("arguments") or {}
            if isinstance(args, str):
                args = json.loads(args or "{}")
            server = STATE["route"].get(name)
            t0 = time.time()
            if server is None:
                text, is_error = f"There is no tool named {name}.", True
            else:
                text, is_error = await _call(server, name, args)
            check = None
            if server and name not in NOT_CHECKED and not is_error:
                check, _ = await _call(server, "verify", {})
            steps.append({"tool": name, "server": server, "args": args, "seconds": round(time.time() - t0, 1),
                          "error": is_error, "result": text[:4000], "check": check})
            messages.append({"role": "tool", "content": text[:6000], "tool_name": name})
    else:
        answer = "I stopped after too many steps without a final answer. Try a more specific question."
    letters = [c for c in answer if c.isalpha()]
    if letters and sum(c.isascii() for c in letters) / len(letters) < 0.9:      # the model drifted out of English
        messages.append({"role": "user", "content": "Rewrite your last answer in plain English, keeping every number."})
        answer = (await asyncio.to_thread(_ollama_chat, messages, [])).get("message", {}).get("content", answer).strip()
    evidence = [s["result"] for s in steps] + [question, SYSTEM]
    numbers = number_check(answer, evidence)
    rewritten = False
    if numbers["unsupported"] and steps:
        # self-correction: name the numbers no tool gave, and let the model rewrite once
        messages.append({"role": "user", "content": f"These numbers in your answer did not come from any tool result: "
                         f"{', '.join(numbers['unsupported'])}. Rewrite the answer using only numbers from the tool results."})
        fixed = (await asyncio.to_thread(_ollama_chat, messages, [])).get("message", {}).get("content", "").strip()
        again = number_check(fixed, evidence)
        if fixed and len(again["unsupported"]) < len(numbers["unsupported"]):
            answer, numbers, rewritten = fixed, again, True
    seen = answer + "\n" + "\n".join(s["result"] for s in steps)
    out = {"question": question, "answer": answer, "steps": steps, "model": MODEL, "seconds": round(time.time() - started, 1),
           "numbers": {**numbers, "rewritten": rewritten},
           "charts": [c for c in (_chart(s) for s in steps) if c],
           "highlight": {"segments": sorted(set(SEGMENT_ID.findall(seen)) & STATE["known"]["segments"])[:300],
                         "spills": sorted(set(SPILL_ID.findall(seen)) & STATE["known"]["spills"])}}
    STATE["last"] = out
    return out


BRIEF = """Write the summary paragraph of a short research brief (3 to 5 plain sentences) answering the question below,
using only the answer and tool results given. Every number you write must appear in them. Say these are first results,
not findings.

Question: {question}
Answer: {answer}
Tool results:
{evidence}"""


async def brief() -> str:
    """A Markdown brief of the last answer: a summary paragraph written by the local model (number-checked), then the
    answer, every tool call with its independent check, and the number check."""
    last = STATE.get("last")
    if not last:
        raise ValueError("Ask a question first.")
    evidence = "\n\n".join(f"[{s['tool']}]\n{s['result'][:2500]}" for s in last["steps"])
    prompt = BRIEF.format(question=last["question"], answer=last["answer"], evidence=evidence)
    msg = (await asyncio.to_thread(_ollama_chat, [{"role": "user", "content": prompt}], [])).get("message", {})
    summary = msg.get("content", "").strip()
    sources = [s["result"] for s in last["steps"]] + [last["question"], last["answer"]]
    nc = number_check(summary, sources)
    if nc["unsupported"]:
        retry = [{"role": "user", "content": prompt}, msg,
                 {"role": "user", "content": f"These numbers did not come from the answer or the tool results: "
                  f"{', '.join(nc['unsupported'])}. Rewrite the paragraph using only numbers that appear in them."}]
        fixed = (await asyncio.to_thread(_ollama_chat, retry, [])).get("message", {}).get("content", "").strip()
        again = number_check(fixed, sources)
        if fixed and len(again["unsupported"]) < len(nc["unsupported"]):
            summary, nc = fixed, {**again, "rewritten": True}
    lines = [f"# {last['question']}", "", f"*Pipeline Discovery Lab, GEOG 392 Group 10 · {time.strftime('%B %d, %Y %H:%M')} · "
             f"local model {MODEL}*", "", "## Summary", "", summary, "",
             f"Number check: {nc['checked']} numbers, " + ("all found in the tool results" if not nc["unsupported"] else
                                                           f"NOT found in any tool result: {', '.join(nc['unsupported'])}")
             + (" (after one rewrite)." if nc.get("rewritten") else "."),
             "", "## The agent's answer", "", last["answer"], "", "## Evidence: every tool call and its independent check", ""]
    for k, s in enumerate(last["steps"], 1):
        lines += [f"### {k}. `{s['tool']}` ({s['server']} server, {s['seconds']} s)", "",
                  f"Arguments: `{json.dumps(s['args'])}`", "", "```", s["result"][:3000], "```", "",
                  f"Check: {s['check'] or 'not checked'}", ""]
    lines += ["---", "These are first results, not findings. Every number above came from a project tool; the tools and "
              "data run on this computer."]
    return "\n".join(lines)


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
    return JSONResponse({"model": MODEL, "model_ready": ollama, "tools": [t["function"]["name"] for t in STATE["tools"]],
                         "servers": {k: sum(1 for v in STATE["route"].values() if v == k) for k in STATE["sessions"]}})


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


async def brief_route(request: Request):
    async with LOCK:
        try:
            md = await brief()
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
    return Response(md, media_type="text/markdown",
                    headers={"Content-Disposition": f'attachment; filename="discovery_brief_{time.strftime("%Y%m%d_%H%M")}.md"'})


@contextlib.asynccontextmanager
async def lifespan(app):
    STATE["layers"] = _layers()
    async with contextlib.AsyncExitStack() as stack:
        STATE.update(sessions={}, route={}, tools=[])
        for name, path in SERVERS.items():
            params = StdioServerParameters(command=sys.executable, args=[str(path)])
            read, write = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            STATE["sessions"][name] = session
            for t in (await session.list_tools()).tools:
                if t.name != "verify":
                    STATE["route"][t.name] = name
                    STATE["tools"].append(_as_ollama_tool(t))
        print(f"Pipeline Discovery Lab: http://{HOST}:{PORT}  (model {MODEL}; "
              + "; ".join(f"{k}: {sum(1 for v in STATE['route'].values() if v == k)} tools" for k in STATE["sessions"]) + ")",
              flush=True)
        yield


app = Starlette(routes=[Route("/", page), Route("/api/status", status), Route("/api/layers/{name}.geojson", layer),
                        Route("/api/ask", ask_route, methods=["POST"]), Route("/api/brief", brief_route, methods=["POST"])],
                lifespan=lifespan)

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
