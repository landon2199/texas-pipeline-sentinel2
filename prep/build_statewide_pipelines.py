"""Merge the Railroad Commission's county pipeline files into one statewide GeoPackage, exactly as published.

Reads every pipeline<FIPS>.zip in the download folder (254 counties, plus pipelineFED.zip for federal offshore waters),
keeps every field as published, adds the source file, and writes one layer in the data's own coordinate system (NAD27).
Nothing is filtered, regrouped or reprojected here: Part 1 projects the lines with NOAA's NADCON5 grids and records
anything it leaves out. Lines whose geometry repeats an earlier one exactly are flagged (dup_geometry), not dropped.

Writes, next to the output: <name>_summary.csv and SOURCES.md, and copies the download manifest.

Usage: python build_statewide_pipelines.py <download folder> <output .gpkg>
"""
import csv
import datetime as dt
import shutil
import sys
import tempfile
import warnings
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio

warnings.filterwarnings("ignore", category=RuntimeWarning)
LAST_YEAR = ("D:/GEOG391_GIS_Day_2025/391 Research Phase 1/391 Research Phase 1.gdb", "pipe235_merge_final_250")
EQUAL_AREA = 6579   # only for the length totals in the summary; Part 1 does the real projection


def read_county(z: Path) -> gpd.GeoDataFrame:
    gdf = pyogrio.read_dataframe(f"/vsizip/{z.as_posix()}")
    gdf["source_file"] = z.name
    return gdf


def main(folder: Path, output: Path):
    zips = sorted(folder.glob("pipeline*.zip"))
    parts, crs = [], set()
    for z in zips:
        g = read_county(z)
        crs.add(g.crs.to_string() if g.crs else "none")
        parts.append(g)
    if len(crs) != 1:
        raise RuntimeError(f"county files use different coordinate systems: {crs}")
    lines = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=parts[0].crs)
    wkb = lines.geometry.to_wkb()
    lines["dup_geometry"] = wkb.duplicated(keep="first")
    empty = lines.geometry.is_empty | lines.geometry.isna()

    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / output.name
        pyogrio.write_dataframe(lines, local, layer="pipelines", driver="GPKG")
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(local, output)

    km = lines.to_crs(EQUAL_AREA).length / 1000
    rows = [("files read", len(zips), ""), ("lines", len(lines), f"{km.sum():,.0f} km"),
            ("exact duplicate geometries (flagged)", int(lines["dup_geometry"].sum()), f"{km[lines['dup_geometry']].sum():,.0f} km"),
            ("empty geometries", int(empty.sum()), ""), ("coordinate system", crs.pop(), "as published")]
    for col in ("CMDTY_DESC", "STATUS_CD"):
        if col in lines:
            for value, n in lines[col].fillna("(blank)").value_counts().items():
                rows.append((f"{col} = {value}", int(n), f"{km[lines[col].fillna('(blank)') == value].sum():,.0f} km"))
    try:
        info = pyogrio.read_info(*LAST_YEAR)
        rows.append(("last year's statewide layer (2025), lines", info["features"], "for comparison"))
    except Exception:
        pass
    summary = output.with_name(output.stem + "_summary.csv")
    with open(summary, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([("what", "count", "note"), *rows])

    manifest = folder / "manifest.csv"
    if manifest.exists():
        shutil.copy(manifest, output.with_name(output.stem + "_manifest.csv"))
        m = pd.read_csv(manifest)
        downloaded = f"{m['downloaded_utc'].min()} to {m['downloaded_utc'].max()} (UTC)"
        size = f"{m['bytes'].sum() / 1e6:,.1f} MB in {len(m)} files"
    else:
        downloaded, size = "unknown", f"{len(zips)} files"
    sources = output.with_name("SOURCES.md")
    sources.write_text(f"""# Statewide pipeline data: where it came from

- **Source:** Railroad Commission of Texas, "Pipeline Layers by County" (ArcView shapefiles, updated twice a week), from
  rrc.texas.gov, Resource Center, Research, Data Sets Available for Download. Files: one `pipeline<county FIPS>.zip` per
  county, plus `pipelineFED.zip` for federal offshore waters.
- **Downloaded:** {downloaded}; {size}. Every file's size and SHA-256 are in `{output.stem}_manifest.csv`.
- **Downloaded with:** `code (do not edit)/prep/download_rrc_pipelines.py`; merged with `prep/build_statewide_pipelines.py`
  on {dt.date.today().isoformat()}.
- **This file:** `{output.name}`, layer `pipelines`: {len(lines):,} lines, every field as published, plus `source_file` and
  `dup_geometry` (True for a line whose geometry exactly repeats an earlier one; flagged, not dropped).
- **Coordinates:** as published, NAD27 latitude and longitude. Part 1 converts them to NAD83(2011) Texas Centric Albers
  (EPSG:6579) with NOAA's NADCON5 grids, installed on 2026-10-07 in PROJ's user folder (PROJ's stated accuracy
  0.35 m). Without the grids, PROJ falls back to a conversion through WGS 84 ("NAD27 to WGS 84 (6)", rated at 9 m),
  which differed from NADCON5 by a median 2.1 m (90th percentile 3.3 m, maximum 4.4 m) at 3,000 pipeline points.
  Each zone build records the conversion it actually used in its `build_*.json`.
- **Counts:** see `{summary.name}`.
- **Cite as:** Railroad Commission of Texas. Pipeline layers by county (digital map data). Accessed {dt.date.today():%B %d, %Y}.
""", encoding="utf-8")
    print(f"wrote {output} ({len(lines):,} lines, {km.sum():,.0f} km), {summary.name}, SOURCES.md")
    for what, n, note in rows[:5]:
        print(f"  {what}: {n:,}" if isinstance(n, int) else f"  {what}: {n}", note)


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
