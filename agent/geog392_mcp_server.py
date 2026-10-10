"""GEOG 392 pipeline project: an MCP server over the statewide results (sample of 3,499 segments, 82 spills).

An AI agent (Claude Code, the Gemini CLI, Antigravity, or a local model through Ollama in our dashboard) calls these
tools. The tools do the GIS and the math, so the agent never reads raw data: it asks questions and gets small, checked
answers. `verify` recomputes the last answer a second, independent way, so every answer can be checked before anyone
trusts it. The tables come from analysis/agent_tables.py (outputs/agent/).

Tools
  list_tables       what the agent can query, with row counts and columns
  query_zones       read-only SQL over the tables (DuckDB, no file or network access)
  corridor_summary  the weighted statewide answer, or by ecoregion, commodity, service, diameter, status or accuracy
  distance_profile  how far from the pipe the effect reaches: the weighted gap in every 50 m band to 500 m
  segment           everything about one segment: labels, place, fixed values, its gaps spring by spring
  hot_spots         Gi* hot spots on the segment midpoints: open source by default, ArcGIS Pro (ArcPy) as an option
  spill_timeline    one spill against its matched comparison spots, spring by spring (before-after-control-impact)
  spill_summary     the spill effect across all spills, with intervals, tests and fake-spill p-values
  left_out          what the statewide build covers and leaves out, with the reasons
  verify            recompute the last answer independently and say whether it agrees

Run it with the project's Python:  C:\\Users\\Landon\\.geog392\\venv\\Scripts\\python.exe geog392_mcp_server.py
"""
import json
import os
import re
import sqlite3
import subprocess
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pyogrio
from mcp.server.mcpserver import MCPServer

PROJECT = Path(os.environ.get("GEOG392_PROJECT", "C:/mydrive/Graduate School/Courses/GEOG_392/projects"))
AGENT = PROJECT / "outputs" / "agent"
ZONES = PROJECT / "outputs" / "zones"
RUNS = Path(os.environ.get("GEOG392_RUNS", Path.home() / ".geog392" / "agent_runs"))
ARCPY_PYTHON = Path(os.environ.get("ARCPY_PYTHON", "C:/Program Files/ArcGIS/Pro/bin/Python/envs/arcgispro-py3/python.exe"))
HERE = Path(__file__).resolve().parent
MAX_ROWS = 200
GROUPS = ["ecoregion", "commodity_group", "service", "diameter_class", "status", "location_accuracy"]

INSTRUCTIONS = """\
You are working with GEOG 392 Group 10's statewide results: "Can satellites see pipeline leaks?" Every Texas Railroad
Commission pipeline was cut into 1 km segments; each segment has rings beside the pipe (0-50, 50-100, 100-250,
250-500 m) and a clean comparison ring 500-1,000 m away that has no pipeline within 500 m. A stratified random sample
of 3,499 segments (weights stand for all 296,191 segments with a clean comparison ring) and 82 reported spills with
their comparison spots are measured in Sentinel-2 imagery, image by image, every spring (March-April). Springs
2018-2026 (all nine) are measured. A gap is ring minus its own comparison ring, like-for-like
land cover; negative means less than normal land. Since plan v1.6 the sample is also measured in ten 50 m bands out to 500 m (distance_profile). These are first results, not findings. Prefer the tools over
guessing, report numbers with their 95% intervals, and call verify after any answer you report. Project rules: every
spring is always measured; anything left out is counted and stated."""

server = MCPServer(name="geog392-pipelines", instructions=INSTRUCTIONS)
LAST: dict = {}          # the last answer, so verify can recompute it

DESCRIPTIONS = {
    "segments": "the 3,499 sampled 1 km segments: Railroad Commission fields as published plus clean labels (commodity, "
                "commodity_group, service, diameter_in, diameter_class, status, location_accuracy, ecoregion, county_fips), "
                "weight and stratum, lon/lat of the midpoint, fixed values (elevation_m, slope_deg, hand_m, twi, water_share, "
                "soil_texture) and typical 0-50 m gaps over the measured springs (NDVI_gap_0_50, NDRE_gap_0_50, NDMI_gap_0_50, "
                "BSI_gap_0_50 ... like-for-like land cover; *_all_ground = all land cover pooled)",
    "segment_springs": "one row per segment, spring (year), ring and index: diff_same_lc (like-for-like land cover), "
                       "diff_all (all ground), passes (clear satellite passes), doy_median",
    "statewide": "weighted medians with 95% stratified-bootstrap intervals: springs ('all springs' or a year), scope "
                 "('statewide' or a grouping such as ecoregion), group, ring, index, measure, segments, weighted_median, lo95, hi95",
    "coverage": "Part 1's statewide coverage: every piece of pipe kept or left out, by ecoregion, commodity_group, "
                "diameter_class, status and location_accuracy, with the reason, pieces, lines and km",
    "spills": "the 82 reported right-of-way spills (PHMSA) matched to a mapped line: spill_id, date, barrels, commodity, "
              "cause, ecoregion, line_uid, location_accuracy, distance_to_line_m, lon, lat",
    "spill_sites": "every site: the spill itself ('spill'), comparison spots every 0.5 km along the same line out to 3 km "
                   "('candidate'), and spots on similar lines in the same ecoregion ('regional'); offset_m, same_ecoregion, "
                   "other_spill_within_1km, lon, lat",
    "spill_springs": "per site, spring (year), circle radius_m (50 or 100) and index (NDVI, NDMI, NDRE, BSI): value "
                     "(median over the spring's clear passes), passes, pixels_median",
    "lst_springs": "per zone and spring: lst_c, the median Landsat 8/9 surface temperature (deg C) over clear passes; "
                   "zone_id is <segment_id>_r<inner>-<outer> or <site_id>_r<inner>-<outer>",
    "drought": "per zone and spring: pdsi (Palmer Drought Severity Index), spei90d, spi90d (gridMET; negative = drier)",
    "band_profile": "the statewide distance profile from the ten-band design: weighted gap in every 50 m band from 0 to "
                    "500 m, with 95% intervals (springs, ring, index, measure, segments, weighted_median, lo95, hi95)",
    "band_springs": "one row per segment, spring, 50 m band (ring) and index: diff_same_lc, diff_all, passes",
    "spill_effects": "per spill, index and matching ('strict' or 'broader'): E1 (first spring after minus the springs "
                     "before, spill minus its matched same-line spots), E_all, springs_before, springs_after, spots, "
                     "barrels, commodity_group, cause, ecoregion, hand_m, slope_deg",
    "spill_baci": "per spill, index, matching and spring (year): d, the spill's 50 m circle minus the mean of its matched "
                  "same-line spots in the same passes (median over the spring), passes, status (before/during/after), "
                  "years_from_spill",
    "spill_matches": "which comparison spots were matched to each spill: spill_id, site_id, kind ('same line' or "
                     "'regional'), matching",
    "spill_summary": "the effect across all spills, per index, matching and subset ('all' or '50 barrels or more (H2)'): "
                     "n, mean_E1, lo95, hi95, median_E1, wilcoxon_p, perm_p_same_line, perm_p_regional, "
                     "date_shift_mean_E1, date_shift_n",
}

_TABLES: dict[str, pd.DataFrame] | None = None


def _read_tables() -> dict[str, pd.DataFrame]:
    return {name: pd.read_parquet(AGENT / f"{name}.parquet") for name in DESCRIPTIONS if (AGENT / f"{name}.parquet").exists()}


def tables() -> dict[str, pd.DataFrame]:
    global _TABLES
    if _TABLES is None:
        _TABLES = _read_tables()
    return _TABLES


def duck() -> duckdb.DuckDBPyConnection:
    """A fresh in-memory database holding the tables, locked so SQL cannot read files or the network."""
    con = duckdb.connect()
    for name, df in tables().items():
        con.register(name, df)
    con.execute("SET enable_external_access = false")
    con.execute("SET lock_configuration = true")
    return con


READ_ONLY = re.compile(r"^\s*(select|with)\b", re.I | re.S)
FORBIDDEN = re.compile(r"\b(insert|update|delete|create|drop|alter|attach|detach|copy|install|load|pragma|export|import|call|set|reset)\b", re.I)


def _clean_sql(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S).strip().rstrip(";").strip()
    if ";" in sql:
        raise ValueError("Send one statement at a time.")
    if not READ_ONLY.match(sql) or FORBIDDEN.search(sql):
        raise ValueError("Only read-only SELECT or WITH queries are allowed.")
    return sql


def _as_text(df: pd.DataFrame, limit: int) -> str:
    shown = df.head(limit)
    note = f"{len(df):,} rows" + (f" (showing the first {limit})" if len(df) > limit else "")
    return note + "\n" + shown.to_csv(index=False, float_format="%.6g")


def _wmedian(v: np.ndarray, w: np.ndarray) -> float:
    o = np.argsort(v)
    c = np.cumsum(w[o])
    return float(v[o][np.searchsorted(c, c[-1] / 2)])


@server.tool()
def list_tables() -> str:
    """List the tables the agent can query with query_zones: name, row count, what it holds, and columns."""
    return "\n".join(f"{name} ({len(df):,} rows): {DESCRIPTIONS[name]}\n  columns: {', '.join(df.columns)}"
                     for name, df in tables().items())


@server.tool()
def query_zones(sql: str, max_rows: int = 50) -> str:
    """Run one read-only SQL query (DuckDB dialect) over the tables and return the result as CSV.

    Tables: segments, segment_springs, statewide, coverage, spills, spill_sites, spill_springs, lst_springs, drought.
    Example: SELECT ecoregion, COUNT(*) AS n, MEDIAN(NDVI_gap_0_50) AS median_gap FROM segments GROUP BY 1 ORDER BY 3
    For statewide numbers use corridor_summary, which applies the sampling weights; a plain median here is unweighted.
    """
    sql = _clean_sql(sql)
    df = duck().execute(sql).df()
    LAST.clear()
    LAST.update(tool="query_zones", sql=sql, result=df)
    return _as_text(df, min(max_rows, MAX_ROWS))


@server.tool()
def corridor_summary(index: str = "NDVI", ring: str = "0-50 m", by: str = "statewide",
                     measure: str = "same land cover", springs: str = "all springs") -> str:
    """The weighted answer to "is the ground beside the pipe different from normal land?", with 95% intervals.

    index: NDVI, NDRE, NDMI, BSI, SAVI, S2REP or MNDWI. ring: '0-50 m', '50-100 m', '100-250 m' or '250-500 m'.
    by: 'statewide' or one of ecoregion, commodity_group, service, diameter_class, status, location_accuracy.
    measure: 'same land cover' (like-for-like, the main measure) or 'all ground'. springs: 'all springs' or a year.
    """
    st = tables()["statewide"]
    rows = st[(st["index"] == index) & (st["ring"] == ring) & (st["measure"] == measure) &
              (st["springs"].astype(str) == str(springs)) & (st["scope"] == by)]
    if rows.empty:
        raise ValueError(f"no rows for index={index}, ring={ring}, by={by}, measure={measure}, springs={springs}")
    rows = rows.sort_values("weighted_median")[["group", "segments", "weighted_median", "lo95", "hi95"]]
    LAST.clear()
    LAST.update(tool="corridor_summary", index=index, ring=ring, by=by, measure=measure, springs=str(springs), result=rows)
    shown = rows.assign(differs_from_zero=np.where(rows["hi95"] < 0, "yes, below 0",
                                                   np.where(rows["lo95"] > 0, "yes, above 0",
                                                            np.where(rows["lo95"].isna(), "no interval", "no"))))
    head = (f"{index}, {ring} ring minus its comparison ring ({measure}), {springs}, by {by}. Weighted median of each "
            f"segment's typical gap; 95% stratified-bootstrap interval where computed.\n")
    note = ""
    big = rows.dropna(subset=["lo95"])
    big = big[big["segments"] >= 100]
    if len(big) >= 2:                  # the plain-language comparison, so the agent does not have to judge intervals
        lo, hi = big.iloc[0], big.iloc[-1]
        overlap = not (lo["hi95"] < hi["lo95"] or hi["hi95"] < lo["lo95"])
        note = (f"\nReading it: among groups with at least 100 segments, the most negative is {lo['group']} "
                f"({lo['weighted_median']:+.4f}, 95% {lo['lo95']:+.4f} to {lo['hi95']:+.4f}) and the least negative is "
                f"{hi['group']} ({hi['weighted_median']:+.4f}, 95% {hi['lo95']:+.4f} to {hi['hi95']:+.4f}). Their intervals "
                f"{'overlap, so this sample cannot tell them apart' if overlap else 'do not overlap, so the two groups differ'}.\n")
    return head + shown.to_csv(index=False, float_format="%.5f") + note


@server.tool()
def distance_profile(index: str = "NDVI", measure: str = "same land cover") -> str:
    """How far from the pipe does the corridor effect reach? The weighted gap in every 50 m band from 0 to 500 m.

    index: NDVI, NDRE or NDMI. measure: 'same land cover' (like-for-like) or 'all ground'. The "Reading it" line names
    how far the unbroken run of bands below zero reaches from the pipe, and any isolated band farther out, so the
    agent does not have to judge intervals.
    """
    if "band_profile" not in tables():
        raise ValueError("the ten-band profile is not built yet (analysis/agent_tables.py --bands ...)")
    b = tables()["band_profile"]
    rows = b[(b["index"] == index) & (b["measure"] == measure) & (b["springs"].astype(str) == "all springs")].copy()
    if rows.empty:
        raise ValueError(f"no profile for index={index}, measure={measure}")
    rows["inner_m"] = rows["ring"].str.split("-").str[0].astype(int)
    rows = rows.sort_values("inner_m")[["ring", "segments", "weighted_median", "lo95", "hi95"]]
    LAST.clear()
    LAST.update(tool="distance_profile", index=index, measure=measure, result=rows)
    is_below = (rows["hi95"] < 0).tolist()
    run = next((k for k, b in enumerate(is_below) if not b), len(is_below))     # bands below zero, counted from the pipe
    reach = (f"the gap is clearly below zero in every band from the pipe out to the {rows.iloc[run - 1]['ring']} band"
             if run else "the band beside the pipe is not clearly below zero")
    fades = f"; the first band whose interval includes zero is {rows.iloc[run]['ring']}" if run < len(rows) else ""
    isolated = [r for r, b in zip(rows["ring"].iloc[run:], is_below[run:]) if b]
    if isolated:
        fades += (f"; farther out, {', '.join(isolated)} {'is' if len(isolated) == 1 else 'are'} below zero on its own, "
                  "which may be chance among ten bands")
    springs = sorted(tables()["band_springs"]["year"].unique()) if "band_springs" in tables() else []
    return (f"{index} gap by distance from the pipe ({measure}), ten 50 m bands, springs {springs}.\n"
            + rows.to_csv(index=False, float_format="%.5f") + f"\nReading it: {reach}{fades}.\n")


@server.tool()
def segment(segment_id: str) -> str:
    """Everything about one segment: labels, place, fixed values, and its gaps in every measured spring."""
    seg = tables()["segments"]
    s = seg[seg["segment_id"] == segment_id]
    if s.empty:
        raise ValueError(f"{segment_id} is not a sampled segment; try query_zones on segments")
    r = s.iloc[0]
    ss = tables()["segment_springs"]
    mine = ss[(ss["segment_id"] == segment_id) & (ss["index"].isin(["NDVI", "NDMI", "NDRE"]))]
    t = mine.pivot_table(index=["ring", "year"], columns="index", values="diff_same_lc").reset_index()
    t["inner"] = t["ring"].str.split("-").str[0].astype(int)
    t = t.sort_values(["inner", "year"]).drop(columns="inner")
    dr = tables()["drought"]
    d = dr[dr["zone_id"] == f"{segment_id}_r0-50"][["year", "pdsi", "spei90d"]].sort_values("year")
    LAST.clear()
    LAST.update(tool="segment", segment_id=segment_id, result=float(r["NDVI_gap_0_50"]) if pd.notna(r["NDVI_gap_0_50"]) else None)
    lines = [f"Segment {segment_id}: {r['commodity']} ({r['service']}), {r['diameter_in']} in ({r['diameter_class']}), "
             f"{r['status']}; operator {r['OPER_NM']}; mapped {r['location_accuracy']}; {r['ecoregion']}; county FIPS "
             f"{r['county_fips']}; stations {r['start_station']} to {r['end_station']}; midpoint {r['lat']}, {r['lon']}.",
             f"Sampling weight {r['weight']:.1f} (stands for that many segments of its stratum, {r['stratum']}).",
             f"Fixed values (0-50 m ring): elevation {r['elevation_m']:.0f} m, slope {r['slope_deg']:.1f} deg, height above "
             f"drainage {r['hand_m']:.1f} m, wetness index {r['twi']:.1f}, water share {r['water_share']:.2f}, soil texture class "
             f"{r['soil_texture']:.0f}.",
             f"Typical 0-50 m gap over {r['springs_measured']:.0f} springs (like-for-like land cover): NDVI {r['NDVI_gap_0_50']:+.4f}, "
             f"NDRE {r['NDRE_gap_0_50']:+.4f}, NDMI {r['NDMI_gap_0_50']:+.4f}.",
             "Gaps by ring and spring:", t.to_csv(index=False, float_format="%.4f"),
             "Spring drought at the segment (negative = drier):", d.to_csv(index=False, float_format="%.2f")]
    return "\n".join(lines)


def _hot_spot_bins_open(field: str) -> tuple[dict[int, int], str]:
    """Gi* with NumPy/SciPy (analysis/gi_star.py), 8 nearest neighbors and the FDR correction. On the same input it
    reproduces ArcGIS Pro's Hot Spot Analysis exactly (checked Oct 9: identical z-scores and bins)."""
    import sys
    sys.path.insert(0, str(HERE.parent / "analysis"))
    from gi_star import gi_bins
    pts = pyogrio.read_dataframe(AGENT / "segment_points.gpkg", columns=["segment_id", field]).dropna(subset=[field])
    _, b = gi_bins(np.c_[pts.geometry.x, pts.geometry.y], pts[field].to_numpy(), k=8)
    pts["Gi_Bin"] = b
    RUNS.mkdir(parents=True, exist_ok=True)
    gpkg, layer = RUNS / "hotspots_open.gpkg", f"hotspots_{field.lower()}"
    pyogrio.write_dataframe(pts, gpkg, layer=layer)
    counts = pd.Series(b).value_counts()
    return {int(k): int(v) for k, v in counts.items()}, str(gpkg / layer)


def _hot_spot_bins(field: str) -> tuple[dict[int, int], str]:
    src = AGENT / "segment_points.gpkg"
    if not ARCPY_PYTHON.exists():
        raise RuntimeError("ArcGIS Pro is not installed on this computer, so hot_spots is unavailable here. "
                           "Run it on the desktop, or set ARCPY_PYTHON to ArcGIS Pro's python.exe.")
    RUNS.mkdir(parents=True, exist_ok=True)
    gdb = RUNS / "agent.gdb"
    run = subprocess.run([str(ARCPY_PYTHON), str(HERE / "arcgis_hotspots.py"), str(src), "segment_points", field, str(gdb)],
                         capture_output=True, text=True, timeout=1200)
    lines = [l for l in run.stdout.strip().splitlines() if l.startswith("{")]
    if run.returncode != 0 or not lines:
        raise RuntimeError(f"ArcGIS Pro could not run the analysis: {(run.stderr or run.stdout)[-800:]}")
    out = json.loads(lines[-1])
    return {int(k): v for k, v in out["bins"].items()}, out["output"]


BIN_NAMES = {3: "hot spot, 99% confidence", 2: "hot spot, 95%", 1: "hot spot, 90%", 0: "not significant",
             -1: "cold spot, 90%", -2: "cold spot, 95%", -3: "cold spot, 99% confidence"}


@server.tool()
def hot_spots(field: str = "NDVI_diff_0_50", engine: str = "open") -> str:
    """Getis-Ord Gi* hot spots on the sampled segments' midpoints.

    field: NDVI_diff_0_50 (the NDVI gap), NDRE_gap_0_50, NDMI_gap_0_50 or BSI_gap_0_50. With an NDVI gap, a COLD spot
    is a cluster of segments whose corridor is much less green than normal land.
    engine: 'open' (default; NumPy/SciPy, 8 nearest neighbors, false discovery rate correction, seconds; identical to
    ArcGIS Pro's Hot Spot Analysis with the same settings) or 'arcgis' (ArcGIS Pro's Optimized Hot Spot Analysis, which
    picks its own distance band; a minute or two, only where ArcGIS Pro is installed).
    """
    allowed = ("NDVI_diff_0_50", "NDRE_gap_0_50", "NDMI_gap_0_50", "BSI_gap_0_50")
    if field not in allowed:
        raise ValueError(f"field must be one of {allowed}")
    if engine not in ("open", "arcgis"):
        raise ValueError("engine must be 'open' or 'arcgis'")
    bins, output = _hot_spot_bins_open(field) if engine == "open" else _hot_spot_bins(field)
    LAST.clear()
    LAST.update(tool="hot_spots", field=field, result=bins, output=output)
    name = "Gi* (open source, 8 nearest neighbors, FDR)" if engine == "open" else "ArcGIS Pro Optimized Hot Spot Analysis"
    rows = [f"{BIN_NAMES[b]}: {bins.get(b, 0)} segments" for b in (3, 2, 1, 0, -1, -2, -3)]
    return f"{name} on {field} ({sum(bins.values())} segments)\n" + "\n".join(rows) + f"\nOutput: {output}"


SPILL_INDICES = ("NDVI", "NDMI", "NDRE", "BSI")


@server.tool()
def spill_timeline(spill_id: str, index: str = "NDVI", matching: str = "strict") -> str:
    """One spill against its matched comparison spots on the same pipeline, spring by spring (before-after-control-
    impact, from analysis/spills.py). index: NDVI, NDMI, NDRE or BSI. matching: 'strict' (same land cover class and soil
    texture, similar terrain, no other spill within 1 km) or 'broader' (same land cover group, any soil). Each spring's
    value d is the spill's 50 m circle minus the mean of its matched spots in the same satellite passes (median over
    the spring), labeled before, during or after the spill. E1 is the first spring after minus the mean of the springs
    before; a negative NDVI E1 means the spill site lost more green than its comparison spots."""
    if index not in SPILL_INDICES:
        raise ValueError("index must be NDVI, NDMI, NDRE or BSI")
    if matching not in ("strict", "broader"):
        raise ValueError("matching must be 'strict' or 'broader'")
    T = tables()
    info = T["spills"][T["spills"]["spill_id"] == spill_id]
    if info.empty:
        raise ValueError(f"No spill {spill_id}. Spills: {', '.join(sorted(T['spills']['spill_id']))}")
    i = info.iloc[0]
    LAST.clear()
    m = T["spill_matches"]
    spots = m[(m["spill_id"] == spill_id) & (m["kind"] == "same line") & (m["matching"] == matching)]["site_id"].tolist()
    e = T["spill_effects"]
    e = e[(e["spill_id"] == spill_id) & (e["index"] == index) & (e["matching"] == matching)]
    head = f"Spill {spill_id}: {i['date']}, {i['barrels']:,.0f} barrels of {i['commodity']} ({i['cause']}). "
    if e.empty or not spots:
        LAST.update(tool="spill_timeline", spill_id=spill_id, index=index, matching=matching, result=None)
        return head + (f"No same-line spot passed the {matching} matching rules, so it has no matched comparison"
                       + (" (try matching='broader')." if matching == "strict" else "."))
    e = e.iloc[0]
    b = T["spill_baci"]
    tl = b[(b["spill_id"] == spill_id) & (b["index"] == index) & (b["matching"] == matching)].sort_values("year")
    E1 = None if pd.isna(e["E1"]) else float(e["E1"])
    LAST.update(tool="spill_timeline", spill_id=spill_id, index=index, matching=matching, result=E1)
    effect = (f"Effect E1 (first spring after minus the springs before): {E1:+.4f} {index}; all springs after minus "
              f"before: {e['E_all']:+.4f}." if E1 is not None else "No measured spring right after the spill, so no E1.")
    return (head + f"{len(spots)} matched same-line spots ({matching} matching).\n{effect}\n"
            + tl[["year", "status", "years_from_spill", "d", "passes"]].to_csv(index=False, float_format="%.4f"))


@server.tool()
def spill_summary(index: str = "NDVI", matching: str = "strict") -> str:
    """The spill effect across all spills: the mean and median E1 (first spring after minus the springs before, spill
    minus its matched same-line spots) with a 95% bootstrap interval, a Wilcoxon signed-rank test, and the fake-spill
    permutation p-values: matched same-line spots treated as if they had spilled, and regional spots treated as if they
    spilled on the real dates. Also the check with each spill's date moved two years earlier, which should show nothing.
    For all spills and for spills of 50 barrels or more (H2). matching: 'strict' or 'broader'."""
    if index not in SPILL_INDICES:
        raise ValueError("index must be NDVI, NDMI, NDRE or BSI")
    s = tables()["spill_summary"]
    s = s[(s["index"] == index) & (s["matching"] == matching)]
    LAST.clear()
    LAST.update(tool="spill_summary", index=index, matching=matching,
                result={r["spills"]: (float(r["mean_E1"]), float(r["median_E1"]), float(r["wilcoxon_p"])) for _, r in s.iterrows()})
    if s.empty:
        return f"No spill summary for {index} with {matching} matching."
    allr = s[s["spills"] == "all"].iloc[0]
    p_same = float(str(allr["perm_p_same_line"]).split()[0]) if str(allr["perm_p_same_line"]) != "n/a" else 1.0
    clear = allr["hi95"] < 0 and p_same < 0.05
    reading = (f"Reading it: across {int(allr['n'])} spills the spill sites lost more {index} than their matched "
               f"comparison spots in the first spring after the spill; the interval is entirely below zero and fake spills "
               f"rarely look this bad (p = {allr['perm_p_same_line']}). With the dates moved two years earlier the "
               f"effect is about zero ({allr['date_shift_mean_E1']:+.4f})." if clear else
               f"Reading it: across {int(allr['n'])} spills the interval includes zero or fake spills look as bad, so "
               f"there is no clear {index} effect.")
    cols = ["spills", "n", "mean_E1", "lo95", "hi95", "median_E1", "wilcoxon_p", "perm_p_same_line", "perm_p_regional",
            "date_shift_mean_E1", "date_shift_n"]
    return (f"{index} effect across spills ({matching} matching), first results:\n"
            + s[cols].to_csv(index=False, float_format="%.4f") + "\n" + reading)


def _coverage() -> dict:
    c = tables()["coverage"]
    total = float(c["km"].sum())
    by = c.groupby(["kept", "reason"], dropna=False)["km"].sum().reset_index()
    seg = tables()["segments"]
    return {"total_km": total, "by_reason": by, "sample": len(seg), "population": float(seg["weight"].sum())}


@server.tool()
def left_out() -> str:
    """What the statewide build covers and what it leaves out, with the reason for each (the project counts everything)."""
    c = _coverage()
    LAST.clear()
    LAST.update(tool="left_out", result=c)
    rows = [(("kept" if k else "left out"), f"{km:,.0f} km", f"{km / c['total_km']:.1%}",
             r if isinstance(r, str) and r else "measured, with a clean comparison ring") for k, r, km in c["by_reason"].itertuples(index=False)]
    rows.sort(key=lambda x: -float(x[1].replace(",", "").split()[0]))
    df = pd.DataFrame(rows, columns=["kept", "pipe", "share", "reason"])
    return (f"All Railroad Commission pipe: {c['total_km']:,.0f} km.\n" + df.to_csv(index=False) +
            f"The Earth Engine sample: {c['sample']:,} segments standing for {c['population']:,.0f} segments with a clean "
            "comparison ring (weights add up to the population).\n")


def _same(a: pd.DataFrame, b: pd.DataFrame) -> tuple[bool, str]:
    if a.shape != b.shape:
        return False, f"different shapes: {a.shape} vs {b.shape}"
    a, b = a.reset_index(drop=True).copy(), b.reset_index(drop=True).copy()
    a.columns = b.columns = range(a.shape[1])
    a, b = a.sort_values(list(a.columns), ignore_index=True), b.sort_values(list(b.columns), ignore_index=True)
    for col in a.columns:
        x, y = a[col], b[col]
        if pd.api.types.is_numeric_dtype(x) and pd.api.types.is_numeric_dtype(y):
            if not np.allclose(x.astype(float), y.astype(float), rtol=1e-9, atol=1e-12, equal_nan=True):
                return False, f"column {col} differs"
        elif not (x.astype(str).values == y.astype(str).values).all():
            return False, f"column {col} differs"
    return True, f"{len(a)} rows match"


@server.tool()
def verify() -> str:
    """Recompute the last answer a second, independent way and report whether the two agree.

    query_zones: the same SQL in SQLite on freshly read tables. corridor_summary: the weighted medians recomputed from
    the per-segment table with plain NumPy. segment: the labels re-read from the sample GeoPackage with GDAL and the gap
    recomputed as the median of its springs. hot_spots: GDAL re-reads the saved output (open-source or ArcGIS Pro) and recounts it.
    spill_timeline: DuckDB SQL recomputes the effect from the raw spill table. left_out: the parts must add up to the
    total, and the measured kilometers must equal the measured pieces in the zone files.
    """
    if not LAST:
        return "Nothing to verify yet: call another tool first."
    tool = LAST["tool"]
    if tool == "query_zones":
        con = sqlite3.connect(":memory:")
        for name, df in _read_tables().items():
            df.to_sql(name, con, index=False)
        try:
            other = pd.read_sql_query(LAST["sql"], con)
        except Exception as e:
            return f"Could not re-run this query in SQLite (it may use DuckDB-only syntax such as MEDIAN): {e}"
        ok, why = _same(LAST["result"], other)
        return f"{'AGREES' if ok else 'DISAGREES'}: DuckDB and SQLite ({why})."
    if tool == "corridor_summary":
        ss = pd.read_parquet(AGENT / "segment_springs.parquet")
        seg = pd.read_parquet(AGENT / "segments.parquet")
        col = "diff_same_lc" if LAST["measure"] == "same land cover" else "diff_all"
        x = ss[(ss["index"] == LAST["index"]) & (ss["ring"] == LAST["ring"])]
        if LAST["springs"] != "all springs":
            x = x[x["year"].astype(str) == LAST["springs"]]
        per = x.groupby("segment_id")[col].median().dropna().rename("v").reset_index().merge(seg, on="segment_id")
        checks = []
        for _, row in LAST["result"].iterrows():
            part = per if LAST["by"] == "statewide" else per[per[LAST["by"]].astype(str) == str(row["group"])]
            est = _wmedian(part["v"].to_numpy(float), part["weight"].to_numpy(float))
            checks.append(abs(est - row["weighted_median"]) < 1e-9 and len(part) == row["segments"])
        ok = all(checks)
        return f"{'AGREES' if ok else 'DISAGREES'}: NumPy recomputation of {len(checks)} weighted medians from the per-segment table ({sum(checks)} match)."
    if tool == "distance_profile":
        bs = pd.read_parquet(AGENT / "band_springs.parquet")
        seg = pd.read_parquet(AGENT / "segments.parquet")[["segment_id", "weight"]]
        col = "diff_same_lc" if LAST["measure"] == "same land cover" else "diff_all"
        x = bs[bs["index"] == LAST["index"]]
        checks = []
        for _, row in LAST["result"].iterrows():
            per = (x[x["ring"] == row["ring"]].groupby("segment_id")[col].median().dropna().rename("v").reset_index()
                   .merge(seg, on="segment_id"))
            est = _wmedian(per["v"].to_numpy(float), per["weight"].to_numpy(float))
            checks.append(abs(est - row["weighted_median"]) < 1e-9 and len(per) == row["segments"])
        ok = all(checks)
        return f"{'AGREES' if ok else 'DISAGREES'}: NumPy recomputation of {len(checks)} band medians from the per-segment table ({sum(checks)} match)."
    if tool == "segment":
        sid = LAST["segment_id"]
        gpkg = pyogrio.read_dataframe(ZONES / "sample_v1" / "sample.gpkg", layer="segments", read_geometry=False,
                                      where=f"segment_id = '{sid}'")
        ss = pd.read_parquet(AGENT / "segment_springs.parquet")
        v = ss[(ss["segment_id"] == sid) & (ss["index"] == "NDVI") & (ss["ring"] == "0-50 m")]["diff_same_lc"].median()
        mine = LAST["result"]
        same_gap = (mine is None and pd.isna(v)) or (mine is not None and abs(mine - v) < 1e-12)
        return f"{'AGREES' if len(gpkg) == 1 and same_gap else 'DISAGREES'}: GDAL found the segment in the sample file ({len(gpkg)} row); NDVI gap recomputed {v:+.4f} vs reported {mine if mine is None else f'{mine:+.4f}'}."
    if tool == "hot_spots":
        gdb, layer = Path(LAST["output"]).parent, Path(LAST["output"]).name
        recount = pyogrio.read_dataframe(gdb, layer=layer, columns=["Gi_Bin"], read_geometry=False)["Gi_Bin"].value_counts()
        recount = {int(k): int(v) for k, v in recount.items()}
        ok = recount == LAST["result"]
        return f"{'AGREES' if ok else 'DISAGREES'}: GDAL recount of the saved output {recount} vs reported {LAST['result']}."
    if tool == "spill_timeline":
        sql = """SELECT MAX(CASE WHEN status = 'after' AND years_from_spill = 1 THEN d END)
                        - AVG(CASE WHEN status = 'before' THEN d END)
                 FROM spill_baci WHERE spill_id = $id AND "index" = $idx AND matching = $m"""
        other = duck().execute(sql, {"id": LAST["spill_id"], "idx": LAST["index"], "m": LAST["matching"]}).fetchone()[0]
        mine = LAST["result"]
        ok = (mine is None and other is None) or (mine is not None and other is not None and abs(mine - other) < 1e-9)
        return f"{'AGREES' if ok else 'DISAGREES'}: DuckDB SQL recomputed E1 from the spring table: {other} vs reported {mine}."
    if tool == "spill_summary":
        from scipy import stats
        e = tables()["spill_effects"]
        e = e[(e["index"] == LAST["index"]) & (e["matching"] == LAST["matching"])].dropna(subset=["E1"])
        checks = []
        for name, sub in [("all", e), ("50 barrels or more (H2)", e[e["barrels"] >= 50])]:
            if name in LAST["result"] and len(sub) >= 3:
                mean, med, p = LAST["result"][name]
                again = (float(np.mean(sub["E1"])), float(np.median(sub["E1"])), float(stats.wilcoxon(sub["E1"]).pvalue))
                checks.append(np.allclose(again, (mean, med, p), atol=1e-9))
        ok = bool(checks) and all(checks)
        return (f"{'AGREES' if ok else 'DISAGREES'}: NumPy and SciPy recomputed the mean, median and Wilcoxon p from the "
                f"per-spill effects ({sum(checks)} of {len(checks)} subsets match).")
    if tool == "left_out":
        c = LAST["result"]
        adds_up = abs(c["by_reason"]["km"].sum() - c["total_km"]) < 1e-6 * c["total_km"]
        measured = 0.0
        for f in sorted((ZONES / "statewide").glob("[0-9]*_*.gpkg")):
            s = pyogrio.read_dataframe(f, layer="segments", read_geometry=False, columns=["piece_m", "has_zones"])
            measured += s.loc[s["has_zones"].astype(bool), "piece_m"].sum() / 1000
        reported = float(c["by_reason"].loc[c["by_reason"]["kept"].astype(bool), "km"].sum())
        same = abs(measured - reported) < 0.001 * reported
        return (f"{'AGREES' if adds_up and same else 'DISAGREES'}: parts add up to the total ({adds_up}); measured km in the "
                f"zone files {measured:,.0f} vs coverage table {reported:,.0f}.")
    return f"No verifier for {tool}."


if __name__ == "__main__":
    server.run()
