# Pipeline Discovery Lab: agents over the statewide results and the project's data

Two Model Context Protocol (MCP) servers let AI agents work with the project. The **results** server
(`geog392_mcp_server.py`) answers from the statewide results. The **discovery** server (`discovery_server.py`) finds
data, reads the spill narratives and finds look-alike places. The agent asks questions and calls tools, and the tools do
the GIS and the math, so the agent never reads raw data. Every answer can be re-checked with `verify`, which recomputes
it a second, independent way, and the dashboard checks every number in the agent's written answer against the tool
results. The models, tools and data run on this computer.

**The data.** A stratified sample of 3,499 one-kilometer pipeline segments, weighted to stand for the 296,191 segments
that have a clean comparison ring, and 82 reported spills with their comparison spots. They are measured in Sentinel-2
imagery image by image, and all nine springs, 2018–2026, are measured. The tables come from `analysis/agent_tables.py` and live in
`outputs/agent/` (Parquet, plus a points GeoPackage for ArcGIS). These are first results, not findings.

## Results tools (`geog392_mcp_server.py`)

| Tool | What it does | How `verify` checks it |
|---|---|---|
| `list_tables` | The tables, with row counts and columns | |
| `query_zones` | One read-only SQL query (DuckDB) over the tables, returned as CSV | The same SQL in SQLite on freshly read tables |
| `corridor_summary` | The weighted answer statewide or by ecoregion, commodity, service, diameter, status or accuracy, with 95% intervals and a plain "Reading it" line that says which groups differ | NumPy recomputes every weighted median from the per-segment table |
| `distance_profile` | How far from the pipe the effect reaches: the weighted gap in each 50 m band to 500 m, with a plain reading | NumPy recomputes every band's weighted median |
| `segment` | One segment: labels, place, fixed values, its gaps by ring and spring, spring drought | GDAL re-reads it from the sample file; the gap is recomputed from its springs |
| `hot_spots` | ArcGIS Pro's Optimized Hot Spot Analysis (Getis-Ord Gi*) on the segment midpoints | GDAL re-reads ArcGIS Pro's output and recounts it |
| `spill_timeline` | One spill against its matched same-line comparison spots, spring by spring, with its before-and-after effect (`analysis/spills.py`) | DuckDB SQL recomputes the effect from the spring table |
| `spill_summary` | The spill effect across all spills: mean and median with a bootstrap interval, a Wilcoxon test, fake-spill permutation p-values and the date-shift check | NumPy and SciPy recompute the mean, median and test from the per-spill effects |
| `left_out` | What the statewide build covers and leaves out, with reasons | The parts must add up; measured km must match the zone files |
| `verify` | Recomputes the last answer and says whether it agrees | |

## Discovery tools (`discovery_server.py`)

| Tool | What it does | How `verify` checks it |
|---|---|---|
| `search_catalog` | Finds datasets by meaning or words in the project catalog (`discovery/catalog.py`) | A words-only search, and how many results it shares |
| `describe_dataset` | One dataset: description, provider, license, size, columns, and its lineage (made from, made into) | The downstream list rebuilt from the lineage text |
| `search_spill_reports` | Searches the PHMSA spill narratives by meaning, with filters for cleanup, soil removed, water reached and year | A words-only search, and how many results it shares |
| `spill_report` | One report: facts, narrative, and the fields a local model read from it, each with its quote | Every quote is checked against the narrative again |
| `similar_places` | The segments or spill sites whose Satellite Embedding is closest to a given place in one year | DuckDB's `list_cosine_similarity` recomputes the ranking |
| `places_like_spills` | Every segment ranked by how much its 0-50 m band looks like the spill sites | DuckDB recomputes the ranking |
| `vegetation_history` | A live Sentinel-2 record of any spot, spring by spring, masked exactly as in the statewide runs (Earth Engine) | Earth Engine recomputes the spring medians from the same images |
| `verify` | Recomputes the last answer and says whether it agrees | |

The discovery data: `discovery/catalog.py` (every dataset, with lineage), `discovery/spill_reports.py` (the narratives
read by `qwen2.5:14b`, each answer with a quote that must appear in the narrative), `discovery/embeddings.py` and
`discovery/place_embeddings.py` (Google's Satellite Embedding V1 for every segment and spill site, 2017-2025). Searches
use `nomic-embed-text` through Ollama.

## Design

- **The science stays deterministic.** Agents are not deterministic, so they never compute results themselves. They
  call tested tools that give the same answer every time.
- **Prepare the database; do not feed data to the model.** The tables sit in an in-memory database. The model sends
  SQL and gets back only the rows it asked for, which saves tokens and keeps the data out of the model.
- **Let the tools judge significance.** A small local model misread 95% intervals in testing, so `corridor_summary`
  states plainly whether groups differ.
- **Use GIS tools for the analysis.** Hot spots come from ArcGIS Pro, not from the model.
- **A correctness step.** `verify` recomputes every answer with different software.
- **Generated text is checked too.** Every number in the agent's answer, and in an exported brief, must match a number
  a tool returned, at the precision written; the dashboard flags any that does not. The narrative reader must quote
  the report for every answer, and an answer whose quote is not in the report is marked unsupported.
- **Measured, not assumed.** `evaluate_agents.py` asks a bank of questions whose right answers are computed straight
  from the tables and scores each model on tool choice, answer and number check.
- **Locked down.** SQL is read-only, one statement at a time, and DuckDB's file and network access is off. ArcGIS Pro
  writes only to `C:\Users\Landon\.geog392\agent_runs`.

## The same servers, any AI

| AI | How it is connected | Status (Oct 7, 2026) |
|---|---|---|
| Claude Code | `claude mcp add --scope user geog392-pipelines -- <python> <server>` (and `geog392-discovery`) | both connected |
| Gemini CLI (Google) | `gemini mcp add -s user geog392-pipelines <python> <server>`; settings in `~/.gemini/settings.json` | added. Run `gemini` in a folder, choose **Trust folder** and sign in with your Google account |
| Antigravity (Google) | `~/.gemini/config/mcp_config.json` | written. Antigravity reads it once installed on this PC |
| Local dashboard (Ollama) | `ai_dashboard.py` starts the server itself | working: 3 to 16 s per answer, every data answer checked |

`<python>` is `C:/Users/Landon/.geog392/venv/Scripts/python.exe` and `<server>` is this folder's
`geog392_mcp_server.py` or `discovery_server.py`. Questions to try: *Does the corridor effect depend on pipe diameter? Which ecoregions show the
biggest NDVI gap? Tell me about segment 001-000025-35-0-8. What does the statewide build leave out?*

Run the tests, which play the agent, call every tool and verify each answer:

```
C:\Users\Landon\.geog392\venv\Scripts\python.exe try_tools.py
C:\Users\Landon\.geog392\venv\Scripts\python.exe try_discovery.py --live
```

## The dashboard

`ai_dashboard.py` serves an ArcGIS map with an "ask the map" panel at http://localhost:8392:
- **The map:** the sampled segments, colored by their 0–50 m NDVI gap, and the spills.
- **Basemaps:** OpenStreetMap or Esri World Imagery (the switch at the bottom right).
- **Aerial photos:** USGS NAIP at about 0.6 m, in the layer list at the top right.

A question goes to a manager agent, a local model in Ollama (`qwen2.5:14b`), which calls the tools on both servers.
After every tool the app runs that server's `verify` itself and shows "checked ✓", then checks every number in the
answer against the tool results. The map highlights the segments and spills named in the answer, a vegetation history
draws as a chart, and **Export brief** saves a Markdown report: a summary written by the local model (number-checked),
the answer, and every tool call with its check. Only `vegetation_history` calls out, to Earth Engine; everything else
stays on this computer.

```
C:\Users\Landon\.geog392\venv\Scripts\python.exe ai_dashboard.py
```

Or double-click `start_dashboard.bat`: a window opens and runs the dashboard, and the page opens in your browser. The
dashboard is a small local web server, so the page works only while it runs. It uses no CPU while idle and does work
only when someone asks a question. Close the window to stop it.

On Landon's PC, Ollama listens on the desktop's Tailscale address, which is kept outside this repository in
`~/.geog392/ollama_host.txt`; `start_dashboard.bat` reads it. Elsewhere, set `OLLAMA_HOST` to your Ollama address.

Other settings: `GEOAI_MODEL`, `OLLAMA_URL`, `GEOAI_HOST` and `GEOAI_PORT`.

From a laptop, there are three ways:
- **Remote Desktop:** connect to this PC and open the app there.
- **Over Tailscale:** start the app with `GEOAI_HOST` set to the desktop's Tailscale address and open that address
  on port 8392 on the laptop.
- **On the laptop itself:** copy the project folder and this environment to the laptop.

## Requirements

- The project environment (`C:\Users\Landon\.geog392\venv`) with `mcp` (2.x), `duckdb` and `pyarrow`.
- ArcGIS Pro 3.7, for `hot_spots`.
- Rebuild the tables after new springs: `python ../analysis/agent_tables.py --corridor <corridor output folder>`.
