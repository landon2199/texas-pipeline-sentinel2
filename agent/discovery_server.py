"""GEOG 392 pipeline project: the discovery MCP server, for finding data, reports and look-alike places.

It works beside geog392_mcp_server.py (the results). Everything runs on this computer: searches use a local embedding
model (nomic-embed-text through Ollama), the spill narratives were read by a local language model, and the only call
out is Earth Engine, for vegetation_history. Like the results server, every answer can be rechecked with `verify`.

Tools
  search_catalog        find datasets by meaning or words: what we have, where it came from, what it feeds
  describe_dataset      one dataset in full, with what it was made from and what was made from it
  search_spill_reports  search the PHMSA spill narratives by meaning, with filters (cleanup, soil, water, year)
  spill_report          one spill's narrative, the fields the local model read from it, and the quotes behind them
  similar_places        the segments or spill sites whose satellite embedding is closest to a given place
  places_like_spills    every segment ranked by how much its 0-50 m band looks like the spill sites, in one year
  vegetation_history    a live Sentinel-2 record of any spot, segment or spill, spring by spring (Earth Engine)
  verify                recompute the last answer a second, independent way

Run it with the project's Python:  C:\\Users\\Landon\\.geog392\\venv\\Scripts\\python.exe discovery_server.py
"""
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
from mcp.server.mcpserver import MCPServer

PROJECT = Path(os.environ.get("GEOG392_PROJECT", "C:/mydrive/Graduate School/Courses/GEOG_392/projects"))
DISCOVERY = PROJECT / "outputs" / "discovery"
AGENT = PROJECT / "outputs" / "agent"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "extract"))

INSTRUCTIONS = """\
Discovery tools for GEOG 392 Group 10's Texas pipeline project. Use search_catalog and describe_dataset to find what
data exists and where it came from; search_spill_reports and spill_report to read the PHMSA spill narratives (fields
read by a local model, each with a quote; an answer whose quote is not in the narrative is marked unsupported);
similar_places and places_like_spills to find look-alike places with Google's Satellite Embedding; vegetation_history
for a live Sentinel-2 record of any spot. Report what the tools return, say when a field is unsupported, and call
verify after any answer you report. Similarity means "looks alike from space", not "will leak"."""

server = MCPServer(name="geog392-discovery", instructions=INSTRUCTIONS)
LAST: dict = {}
_CACHE: dict = {}


def _ollama() -> str:
    host = os.environ.get("OLLAMA_HOST") or (Path.home() / ".geog392" / "ollama_host.txt").read_text().strip()
    return (host if host.startswith("http") else "http://" + host).rstrip("/")


def _embed_query(text: str) -> np.ndarray:
    req = urllib.request.Request(_ollama() + "/api/embed", headers={"Content-Type": "application/json"},
                                 data=json.dumps({"model": "nomic-embed-text", "input": ["search_query: " + text]}).encode())
    with urllib.request.urlopen(req, timeout=120) as r:
        v = np.array(json.loads(r.read())["embeddings"][0], dtype="float32")
    return v / np.linalg.norm(v)


def _table(name: str) -> pd.DataFrame | None:
    """A discovery or agent table, read once; None when it has not been built yet."""
    if name not in _CACHE:
        path = DISCOVERY / f"{name}.parquet" if (DISCOVERY / f"{name}.parquet").exists() else AGENT / f"{name}.parquet"
        _CACHE[name] = pd.read_parquet(path) if path.exists() else None
    return _CACHE[name]


def _unit(m) -> np.ndarray:
    m = np.vstack(m).astype("float32")
    return m / np.linalg.norm(m, axis=1, keepdims=True)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2}


def _keyword_score(query: str, docs: pd.Series) -> np.ndarray:
    q = _words(query)
    return np.array([len(q & _words(d)) / max(len(q), 1) for d in docs], dtype="float32")


def _rank(query: str, emb: pd.Series, text: pd.Series) -> np.ndarray:
    """Hybrid score: meaning (cosine with the local embedding model) weighted 0.8, shared words 0.2."""
    return 0.8 * (_unit(emb.tolist()) @ _embed_query(query)) + 0.2 * _keyword_score(query, text)


@server.tool()
def search_catalog(query: str, k: int = 8, kind: str = "") -> str:
    """Find datasets in the project catalog by meaning or words, for example 'land surface temperature' or 'where the
    spill locations come from'. kind (optional) narrows it: source data, Earth Engine dataset, zone file, measurement
    table, agent table, discovery table, document."""
    LAST.clear()
    cat = _table("catalog")
    if cat is None:
        return "The catalog is not built yet: run discovery/catalog.py."
    c = cat[cat["kind"] == kind] if kind else cat
    score = _rank(query, c["embedding"], c["title"] + " " + c["description"])
    top = c.assign(score=score).nlargest(int(k), "score")
    LAST.clear()
    LAST.update(tool="search_catalog", query=query, kind=kind, result=list(top["id"]))
    rows = top[["id", "kind", "title", "path", "score"]].assign(score=lambda d: d["score"].round(3))
    return f"Datasets matching '{query}' (best first):\n" + rows.to_csv(index=False) + \
        "\nCall describe_dataset with an id for its description, columns and lineage."


@server.tool()
def describe_dataset(dataset_id: str) -> str:
    """One catalog entry in full: description, where it lives, provider and license, years, size and columns, the script
    that made it, what it was made from (upstream) and what was made from it (downstream)."""
    LAST.clear()
    cat = _table("catalog")
    if cat is None:
        return "The catalog is not built yet: run discovery/catalog.py."
    hit = cat[cat["id"] == dataset_id]
    if hit.empty:
        return f"No dataset '{dataset_id}'. Use search_catalog to find ids."
    e = hit.iloc[0]
    downstream = cat[cat["inputs"].fillna("").str.contains(rf"\b{re.escape(dataset_id)}\b")]["id"].tolist()
    fields = ["title", "kind", "description", "path", "provider", "license", "years", "rows", "bytes", "updated",
              "produced_by", "inputs", "columns"]
    lines = [f"{f}: {e[f]}" for f in fields if f in e and pd.notna(e[f]) and str(e[f]) != ""]
    lines.append(f"made into: {', '.join(downstream) or 'nothing listed'}")
    LAST.clear()
    LAST.update(tool="describe_dataset", dataset_id=dataset_id, result={"downstream": downstream})
    return "\n".join(lines)


def _reports() -> pd.DataFrame | None:
    r = _table("spill_reports")
    if r is not None and "year" not in r:
        r["year"] = pd.to_datetime(r["date"]).dt.year
    return r


@server.tool()
def search_spill_reports(query: str, k: int = 8, how_found: str = "", cleanup: str = "", soil_removed: str = "",
                         reached_water: str = "", since_year: int = 0) -> str:
    """Search the PHMSA narratives of Texas right-of-way spills by meaning, for example 'farmer found oil in a pasture'
    or 'contaminated soil hauled off'. Optional filters: how_found (one of operator patrol or personnel, control room
    or alarm, landowner or public, third party contractor, inspection or testing, unknown), cleanup (one of
    excavated soil, vacuum truck, absorbent,
    booms, burned, soil treated on site, water recovered, repaired or replaced pipe), soil_removed or reached_water
    ('yes', 'no' or 'unknown'), since_year. To count reports with a property (for example how many say soil was
    removed), set that filter and read the first line: "N of 175 reports match the filters". Returns spill IDs where the
    spill is in our study."""
    LAST.clear()
    r = _reports()
    if r is None:
        return "The spill reports are not built yet: run discovery/spill_reports.py."
    keep = pd.Series(True, index=r.index)
    if how_found:
        keep &= r["how_found"].eq(how_found)
    if cleanup:
        keep &= r["cleanup_actions"].fillna("").str.contains(re.escape(cleanup))
    if soil_removed:
        keep &= r["soil_removed"].eq(soil_removed)
    if reached_water:
        keep &= r["reached_water"].eq(reached_water)
    if since_year:
        keep &= r["year"] >= int(since_year)
    c = r[keep]
    if c.empty:
        return "No reports match those filters."
    score = _rank(query, c["embedding"], c["NARRATIVE"].fillna(""))
    top = c.assign(score=score).nlargest(int(k), "score")
    LAST.clear()
    LAST.update(tool="search_spill_reports", query=query, filters=dict(how_found=how_found, cleanup=cleanup,
                                                                      soil_removed=soil_removed,
                                                                      reached_water=reached_water, since_year=since_year),
                result=list(top["REPORT_NUMBER"]))
    out = top.assign(date=lambda d: pd.to_datetime(d["date"]).dt.date, barrels=lambda d: d["UNINTENTIONAL_RELEASE_BBLS"],
                     score=lambda d: d["score"].round(3))
    cols = ["REPORT_NUMBER", "spill_id", "date", "barrels", "summary", "score"]
    filters = {k: v for k, v in dict(how_found=how_found, cleanup=cleanup, soil_removed=soil_removed,
                                     reached_water=reached_water, since_year=since_year).items() if v}
    head = (f"{len(c)} of {len(r)} reports match the filters {filters}" if filters else
            f"No filters: all {len(r)} reports were searched (this is not a count of matches)")
    head = (f"These are PHMSA's {len(r)} right-of-way spill reports in Texas since 2010; {int(r['spill_id'].notna().sum())} "
            f"of them are the spills in our study (since mid-2018, matched to a mapped line). " + head)
    return (f"{head}. The {len(top)} closest in meaning to '{query}', best first:\n" + out[cols].to_csv(index=False)
            + "\nspill_id is blank when the spill is before mid-2018 or not matched to a mapped line. Use spill_report for one.")


@server.tool()
def spill_report(spill_or_report_id: str) -> str:
    """One spill report: the facts, the narrative, the fields the local model read from it, and for each field the
    quote it gave and whether that quote is really in the narrative (unsupported answers are flagged)."""
    LAST.clear()
    r = _reports()
    if r is None:
        return "The spill reports are not built yet: run discovery/spill_reports.py."
    key = str(spill_or_report_id).strip()
    hit = r[(r["spill_id"] == key) | (r["REPORT_NUMBER"].astype(str) == key)]
    if hit.empty:
        return f"No report '{key}'. Use search_spill_reports, or a spill ID such as S024."
    e = hit.iloc[0]
    evidence = json.loads(e["evidence"]) if isinstance(e.get("evidence"), str) else {}
    fields = ["how_found", "cleanup_actions", "soil_removed", "reached_water", "plants_or_crops_mentioned"]
    lines = [f"Report {e['REPORT_NUMBER']}" + (f" (spill {e['spill_id']} in our study)" if pd.notna(e["spill_id"]) else ""),
             f"date {pd.Timestamp(e['date']).date()}, {e['UNINTENTIONAL_RELEASE_BBLS']:,.1f} barrels released, "
             f"{e['RECOVERED_BBLS'] if pd.notna(e['RECOVERED_BBLS']) else 'unknown'} recovered; {e['COMMODITY_RELEASED_TYPE']}; "
             f"cause {e['CAUSE']} ({e['CAUSE_DETAILS']}); operator {e['NAME']}; county {e['ONSHORE_COUNTY_NAME']}",
             f"summary (local model): {e['summary']}", "fields read by the local model:"]
    for f in fields:
        ok = bool(e.get(f + "_supported", True))
        lines.append(f"  {f}: {e[f]}  | quote: \"{evidence.get(f, '')}\"  | {'supported' if ok else 'UNSUPPORTED: the quote is not in the narrative'}")
    lines.append("narrative: " + " ".join(str(e["NARRATIVE"]).split()))
    LAST.clear()
    LAST.update(tool="spill_report", key=key, result={f: bool(e.get(f + "_supported", True)) for f in fields})
    return "\n".join(lines)


def _places() -> pd.DataFrame | None:
    return _table("place_embeddings")


@server.tool()
def similar_places(place_id: str, year: int = 2024, k: int = 10, among: str = "segments") -> str:
    """The places whose Satellite Embedding is closest to a given place in one year (2017-2025). place_id is a segment
    ID (its 0-50 m band) or a spill ID such as S024 (the spill site's 50 m circle). among: 'segments' or 'spill sites'.
    Similar means the place looks alike from space over that year, not that it will leak."""
    LAST.clear()
    p = _places()
    if p is None:
        return "The place embeddings are not built yet: they come from discovery/embeddings.py and place_embeddings.py."
    y = p[p["year"] == int(year)]
    seed = y[(y["place_id"] == place_id) | (y["spill_id"] == place_id)]
    seed = seed[seed["kind"].isin(["segment band", "spill site"])]
    if seed.empty:
        return f"No embedding for '{place_id}' in {year}."
    pool = y[y["kind"] == ("segment band" if among == "segments" else "spill site")]
    pool = pool[pool["place_id"] != seed.iloc[0]["place_id"]]
    sim = _unit(pool["embedding"].tolist()) @ _unit([seed.iloc[0]["embedding"]])[0]
    top = pool.assign(similarity=sim).nlargest(int(k), "similarity")
    LAST.clear()
    LAST.update(tool="similar_places", place_id=place_id, year=int(year), among=among,
                result=list(zip(top["place_id"], top["similarity"].round(6))))
    cols = [c for c in ["place_id", "spill_id", "ecoregion", "commodity", "similarity"] if c in top]
    return (f"The {len(top)} {among} that look most like {place_id} in {year} (cosine similarity of the yearly "
            f"Satellite Embedding; 1 = identical):\n" + top[cols].round({"similarity": 4}).to_csv(index=False))


@server.tool()
def places_like_spills(year: int = 2024, k: int = 25) -> str:
    """Every sampled segment ranked by how much its 0-50 m band looks like the spill sites in one year: its highest
    cosine similarity to any spill site's 50 m circle. A ranking of resemblance to past spill places, not a prediction."""
    LAST.clear()
    p = _places()
    if p is None:
        return "The place embeddings are not built yet: they come from discovery/embeddings.py and place_embeddings.py."
    y = p[p["year"] == int(year)]
    seg, sites = y[y["kind"] == "segment band"], y[y["kind"] == "spill site"]
    if seg.empty or sites.empty:
        return f"No embeddings for {year}."
    s = _unit(seg["embedding"].tolist()) @ _unit(sites["embedding"].tolist()).T
    best = s.argmax(axis=1)
    out = seg.assign(similarity=s.max(axis=1), closest_spill=sites["spill_id"].to_numpy()[best]).nlargest(int(k), "similarity")
    LAST.clear()
    LAST.update(tool="places_like_spills", year=int(year), result=list(zip(out["place_id"], out["similarity"].round(6))))
    cols = [c for c in ["place_id", "ecoregion", "commodity", "closest_spill", "similarity"] if c in out]
    return (f"The {len(out)} of {len(seg):,} segments whose 0-50 m band looks most like a spill site in {year}:\n"
            + out[cols].round({"similarity": 4}).to_csv(index=False))


def _where(place: str) -> tuple[float, float, str]:
    seg, sp = _table("segments"), _table("spills")
    if seg is not None and (seg["segment_id"] == place).any():
        r = seg[seg["segment_id"] == place].iloc[0]
        return float(r["lon"]), float(r["lat"]), f"segment {place} (midpoint)"
    if sp is not None and (sp["spill_id"] == place).any():
        r = sp[sp["spill_id"] == place].iloc[0]
        return float(r["lon"]), float(r["lat"]), f"spill {place}"
    m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*", place)
    if m:
        lat, lon = float(m.group(1)), float(m.group(2))
        return lon, lat, f"point {lat:.5f}, {lon:.5f}"
    raise ValueError("Give a segment ID, a spill ID such as S024, or 'latitude, longitude'.")


def _ee():
    import ee
    if not _CACHE.get("ee"):
        ee.Initialize(project=os.environ.get("EE_PROJECT", "research-476723"))
        _CACHE["ee"] = True
    return ee


def _spring_collections(lon, lat, radius_m, index, years):
    ee = _ee()
    import part2
    region = ee.Geometry.Point(lon, lat).buffer(radius_m)
    return region, {y: part2.spring_images(region, y).select(index) for y in years}


def _history(lon, lat, radius_m, index, years):
    """The project's measure: each clear image's mean over the circle, then the median of those for the spring."""
    ee = _ee()
    region, cols = _spring_collections(lon, lat, radius_m, index, years)
    rows = []
    for y, col in cols.items():
        fc = col.map(lambda img: ee.Feature(None, img.reduceRegion(ee.Reducer.mean(), region, 10)))
        v = [f["properties"][index] for f in fc.getInfo()["features"] if f["properties"].get(index) is not None]
        rows.append({"spring": y, "value": float(np.median(v)) if v else None, "clear_images": len(v)})
    return pd.DataFrame(rows)


def _history_check(lon, lat, radius_m, index, years):
    """The same measure computed inside Earth Engine (its own median), plus a different method for context."""
    ee = _ee()
    region, cols = _spring_collections(lon, lat, radius_m, index, years)
    same, composite = {}, {}
    for y, col in cols.items():
        means = col.map(lambda img: ee.Feature(None, img.reduceRegion(ee.Reducer.mean(), region, 10)))
        same[y] = means.filter(ee.Filter.notNull([index])).aggregate_array(index).reduce(ee.Reducer.median()).getInfo()
        composite[y] = col.median().reduceRegion(ee.Reducer.mean(), region, 10).get(index).getInfo()
    return same, composite


@server.tool()
def vegetation_history(place: str, index: str = "NDVI", radius_m: int = 50, first_spring: int = 2018,
                       last_spring: int = 2026) -> str:
    """A live Sentinel-2 record of any spot, spring by spring (March-April): place is a segment ID, a spill ID such as
    S024, or 'latitude, longitude'. index: NDVI, NDMI, SAVI, NDRE, BSI or MNDWI. Clouds, shadows and water are masked
    exactly as in the statewide runs; each spring's value is the median over its clear images. Uses Earth Engine."""
    LAST.clear()
    if index not in ("NDVI", "NDMI", "SAVI", "NDRE", "BSI", "MNDWI"):
        raise ValueError("index must be NDVI, NDMI, SAVI, NDRE, BSI or MNDWI")
    lon, lat, label = _where(place)
    years = list(range(int(first_spring), int(last_spring) + 1))
    t = _history(lon, lat, int(radius_m), index, years)
    LAST.clear()
    LAST.update(tool="vegetation_history", lon=lon, lat=lat, radius_m=int(radius_m), index=index, years=years,
                result=t.set_index("spring")["value"].to_dict())
    return (f"{index} at {label}, a {radius_m} m circle, spring by spring (median of clear Sentinel-2 images):\n"
            + t.to_csv(index=False, float_format="%.4f"))


@server.tool()
def verify() -> str:
    """Recompute the last answer a second, independent way. search_catalog and search_spill_reports: a words-only
    search, and how many of the top results it shares. spill_report: every quote checked against the narrative again.
    similar_places and places_like_spills: the similarities recomputed with DuckDB's list_cosine_similarity.
    describe_dataset: the downstream list rebuilt from the lineage text. vegetation_history: a median composite per
    spring instead of image by image, which should agree within about 0.03."""
    if not LAST:
        return "Nothing to verify yet: call another tool first."
    tool = LAST["tool"]
    if tool in ("search_catalog", "search_spill_reports"):
        t = _table("catalog") if tool == "search_catalog" else _reports()
        text = t["title"] + " " + t["description"] if tool == "search_catalog" else t["NARRATIVE"].fillna("")
        ids = t["id"] if tool == "search_catalog" else t["REPORT_NUMBER"]
        words = pd.Series(_keyword_score(LAST["query"], text), index=ids.values).nlargest(len(LAST["result"]))
        shared = len(set(words.index) & set(LAST["result"]))
        return (f"CROSS-CHECK: a words-only search shares {shared} of the {len(LAST['result'])} results. Meaning-based "
                "search should find more than shared words do, so this shows overlap, not error.")
    if tool == "spill_report":
        r = _reports()
        e = r[(r["spill_id"] == LAST["key"]) | (r["REPORT_NUMBER"].astype(str) == LAST["key"])].iloc[0]
        ev = json.loads(e["evidence"])
        norm = lambda s: re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()      # noqa: E731
        again = {f: (e[f] in ("unknown", "[\"none stated\"]", "[]", None)) or (bool(norm(ev.get(f, ""))) and norm(ev.get(f, "")) in norm(e["NARRATIVE"]))
                 for f in LAST["result"]}
        same = again == LAST["result"]
        return f"{'AGREES' if same else 'DIFFERS'}: quotes rechecked against the narrative: {again}"
    if tool in ("similar_places", "places_like_spills"):
        import duckdb
        p = _places()
        y = p[p["year"] == LAST["year"]]
        con = duckdb.connect()
        con.register("y", y[["place_id", "spill_id", "kind", "embedding"]])
        if tool == "similar_places":
            seed = y[((y["place_id"] == LAST["place_id"]) | (y["spill_id"] == LAST["place_id"]))
                     & y["kind"].isin(["segment band", "spill site"])].iloc[0]["place_id"]
            kind = "segment band" if LAST["among"] == "segments" else "spill site"
            q = ("SELECT b.place_id, list_cosine_similarity(a.embedding, b.embedding) AS s FROM y a, y b "
                 f"WHERE a.place_id = '{seed}' AND a.kind IN ('segment band', 'spill site') AND b.kind = '{kind}' "
                 f"AND b.place_id <> a.place_id ORDER BY s DESC LIMIT {len(LAST['result'])}")
        else:
            q = ("SELECT a.place_id, max(list_cosine_similarity(a.embedding, b.embedding)) AS s FROM y a, y b "
                 f"WHERE a.kind = 'segment band' AND b.kind = 'spill site' GROUP BY a.place_id ORDER BY s DESC LIMIT {len(LAST['result'])}")
        got = [(pid, round(float(s), 6)) for pid, s in con.execute(q).fetchall()]
        same = [g[0] for g in got] == [r[0] for r in LAST["result"]] and \
            np.allclose([g[1] for g in got], [r[1] for r in LAST["result"]], atol=1e-4)
        return f"{'AGREES' if same else 'DIFFERS'}: DuckDB recomputed the top {len(got)} similarities ({'same order and values' if same else got[:3]})"
    if tool == "describe_dataset":
        cat = _table("catalog")
        again = [i for i, inputs in zip(cat["id"], cat["inputs"].fillna("")) if LAST["dataset_id"] in [s.strip() for s in inputs.split(",")]]
        same = sorted(again) == sorted(LAST["result"]["downstream"])
        return f"{'AGREES' if same else 'DIFFERS'}: downstream rebuilt from the lineage text: {again or 'none'}"
    if tool == "vegetation_history":
        same, composite = _history_check(LAST["lon"], LAST["lat"], LAST["radius_m"], LAST["index"], LAST["years"])
        pairs = [(LAST["result"][y], same[y]) for y in LAST["years"] if LAST["result"].get(y) is not None and same.get(y) is not None]
        ok = bool(pairs) and all(abs(a - b) < 1e-6 for a, b in pairs)
        ctx = [abs(LAST["result"][y] - composite[y]) for y in LAST["years"] if LAST["result"].get(y) is not None and composite.get(y) is not None]
        return (f"{'AGREES' if ok else 'DIFFERS'}: Earth Engine's own median of the same per-image values matches for "
                f"{sum(abs(a - b) < 1e-6 for a, b in pairs)} of {len(pairs)} springs. For context, a different method (one "
                f"median composite per spring) is within {max(ctx):.3f} of these values.")
    return f"verify does not know the tool {tool}."


if __name__ == "__main__":
    server.run()
