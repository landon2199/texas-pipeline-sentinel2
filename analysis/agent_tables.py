"""Analysis-ready tables for the agents and the dashboard (the MCP server, the local AI dashboard, Claude and Gemini).

Reads the outputs of Parts 1-3 and writes, in outputs/agent/:
  segments.parquet         one row per sampled segment: published attributes and clean labels, sampling weight and
                           stratum, midpoint (lon, lat), fixed values (elevation, slope, height above drainage, wetness,
                           water share, soil texture), and its typical 0-50 m gaps (median over the measured springs)
  segment_springs.parquet  one row per segment, spring, ring and index (analysis/corridor.py's segment_spring)
  statewide.parquet        weighted statewide and group summaries with 95% intervals (corridor.py's statewide)
  coverage.parquet         Part 1's statewide coverage table: everything kept and left out, with the reason
  spills.parquet           the reported spills matched to a line, with lon and lat
  spill_sites.parquet      every spill site, same-line comparison spot and regional spot
  spill_springs.parquet    per site, spring, circle (50 m, 100 m) and index: the spring value, the median over passes of
                           each circle's mean, rebuilt from the spill rings with their pixel counts
  lst_springs.parquet      per zone and spring: median Landsat surface temperature over passes, all land cover pooled
  drought.parquet          per zone and spring: Palmer Drought Severity Index, SPEI-90 and SPI-90 (gridMET)
  segment_points.gpkg      the segments as midpoints (EPSG:6579) with the gap fields, for ArcGIS hot spots and the map
  band_profile.parquet     the statewide distance profile: weighted gap in every 50 m band (plan v1.6), with intervals
  band_springs.parquet     one row per segment, spring, 50 m band and index (corridor.py on the ten-band sample)
A gap is ring minus the segment's own clean 500-1,000 m comparison ring (negative = less than normal land).

Usage: python agent_tables.py [--corridor outputs/results/corridor_sample_v1_3springs]
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio

sys.path.insert(0, str(Path(__file__).resolve().parent))
from corridor import one_image_per_pass  # noqa: E402

P = Path(r"C:\mydrive\Graduate School\Courses\GEOG_392\projects")
STATS = P / "outputs" / "geog392_zone_stats"
SAMPLE = P / "outputs" / "zones" / "sample_v1"
ZONES = P / "outputs" / "zones" / "statewide"
OUT = P / "outputs" / "agent"
GAP_INDICES = ["NDVI", "NDRE", "NDMI", "BSI", "SAVI", "S2REP", "MNDWI"]
SPILL_INDICES = ["NDVI", "NDMI", "NDRE", "BSI"]
CIRCLES = {50: ["0-25", "25-50"], 100: ["0-25", "25-50", "50-100"]}


def segments_table(corridor: Path) -> pd.DataFrame:
    seg = pyogrio.read_dataframe(SAMPLE / "sample.gpkg", layer="segments")
    mid = seg.geometry.interpolate(0.5, normalized=True)
    ll = mid.to_crs(4326)
    seg["lon"], seg["lat"] = ll.x.round(6), ll.y.round(6)
    seg["x_6579"], seg["y_6579"] = mid.x.round(1), mid.y.round(1)
    ss = pd.read_csv(corridor / "segment_spring.csv")
    zero = ss[ss["ring"] == "0-50 m"]
    gaps = zero.groupby(["segment_id", "index"]).agg(same=("diff_same_lc", "median"), all=("diff_all", "median"),
                                                      springs=("year", "nunique")).reset_index()
    wide = gaps.pivot(index="segment_id", columns="index", values="same").add_suffix("_gap_0_50")
    wide_all = gaps.pivot(index="segment_id", columns="index", values="all").add_suffix("_gap_0_50_all_ground")
    springs = gaps.groupby("segment_id")["springs"].max().rename("springs_measured")
    fixed = pd.read_csv(STATS / "sample_v1_and_spills_v1_fixed.csv")
    fixed = fixed[fixed["zone_id"].str.endswith("_r0-50")].assign(segment_id=lambda d: d["zone_id"].str[:-6])
    fixed = fixed.drop(columns="zone_id").rename(columns=lambda c: c.replace("_mean", "").replace("_mode", ""))
    out = (pd.DataFrame(seg.drop(columns="geometry")).merge(wide, on="segment_id", how="left")
           .merge(wide_all, on="segment_id", how="left").merge(springs, on="segment_id", how="left")
           .merge(fixed, on="segment_id", how="left"))
    out["NDVI_diff_0_50"] = out["NDVI_gap_0_50"]           # the dashboard's colour field, kept under its old name
    return out, mid


def spill_springs_table() -> pd.DataFrame:
    rows = []
    for f in sorted(STATS.glob("spills_v1_per_image_*_10m.csv")):
        d = pd.read_csv(f)
        d[["site_id", "ring"]] = d["zone_id"].str.rsplit("_r", n=1, expand=True)
        d = one_image_per_pass(d, "site_id")                  # one tile image per site and pass, as in corridor.py
        d = d.sort_values(["NDVI_count", "image"], ascending=[False, True], kind="stable").drop_duplicates(
            ["zone_id", "landcover", "date", "orbit"])
        d["year"] = d["date"].str[:4].astype(int)
        for radius, parts in CIRCLES.items():
            c = d[d["ring"].isin(parts)]
            agg = {}
            for i in SPILL_INDICES:
                c = c.assign(**{f"{i}_w": c[f"{i}_mean"] * c[f"{i}_count"]})
            g = c.groupby(["site_id", "year", "date", "orbit"])
            per_pass = pd.DataFrame({i: g[f"{i}_w"].sum() / g[f"{i}_count"].sum() for i in SPILL_INDICES})
            per_pass["pixels"] = g["NDVI_count"].sum()
            per_pass = per_pass[per_pass["pixels"] >= 5]
            yr = per_pass.groupby(level=["site_id", "year"])
            spring = yr[SPILL_INDICES].median()
            spring["passes"], spring["pixels_median"] = yr.size(), yr["pixels"].median()
            spring = spring.reset_index().melt(id_vars=["site_id", "year", "passes", "pixels_median"],
                                               value_vars=SPILL_INDICES, var_name="index", value_name="value")
            spring["radius_m"] = radius
            rows.append(spring)
        print(f"  {f.name}: {d['site_id'].nunique():,} sites")
    return pd.concat(rows, ignore_index=True)


def lst_table() -> pd.DataFrame:
    rows = []
    for f in sorted(STATS.glob("sample_v1_and_spills_v1_lst_*.csv")):
        d = pd.read_csv(f)
        d["unit"] = d["zone_id"].str.rsplit("_r", n=1).str[0]           # the segment or spill site
        d = one_image_per_pass(d, "unit", count="LST_count", pass_key=("date", "path"))
        d = d.sort_values(["LST_count", "image"], ascending=[False, True], kind="stable").drop_duplicates(
            ["zone_id", "landcover", "date"])
        d = d.assign(w=d["LST_mean"] * d["LST_count"])
        g = d.groupby(["zone_id", "date"])[["w", "LST_count"]].sum()
        per = (g["w"] / g["LST_count"]).rename("lst_c").reset_index()
        per = per[g["LST_count"].values >= 5]
        per["year"] = per["date"].str[:4].astype(int)
        y = per.groupby(["zone_id", "year"])["lst_c"].agg(["median", "size"]).reset_index()
        rows.append(y.rename(columns={"median": "lst_c", "size": "passes"}))
    return pd.concat(rows, ignore_index=True)


def main(a):
    OUT.mkdir(parents=True, exist_ok=True)
    seg, mid = segments_table(a.corridor)
    seg.to_parquet(OUT / "segments.parquet", index=False)
    pts = seg[["segment_id", "line_uid", "OPER_NM", "commodity", "commodity_group", "service", "diameter_in", "diameter_class",
               "status", "location_accuracy", "ecoregion", "county_fips", "weight", "springs_measured", "NDVI_diff_0_50",
               "NDRE_gap_0_50", "NDMI_gap_0_50", "BSI_gap_0_50", "lon", "lat"]].copy()
    import geopandas as gpd
    gpd.GeoDataFrame(pts, geometry=mid.values, crs=mid.crs).to_file(OUT / "segment_points.gpkg", layer="segment_points", driver="GPKG")
    print(f"segments: {len(seg):,} ({int(seg['NDVI_gap_0_50'].notna().sum()):,} with an NDVI gap)")

    pd.read_csv(a.corridor / "segment_spring.csv").to_parquet(OUT / "segment_springs.parquet", index=False)
    pd.read_csv(a.corridor / "statewide.csv").to_parquet(OUT / "statewide.parquet", index=False)
    pd.read_csv(ZONES / "coverage_statewide.csv").to_parquet(OUT / "coverage.parquet", index=False)

    sp = pyogrio.read_dataframe(ZONES / "spills_statewide.gpkg", layer="spills_matched")
    ll = sp.geometry.to_crs(4326)
    sp = pd.DataFrame(sp.drop(columns="geometry")).assign(lon=ll.x.round(6).values, lat=ll.y.round(6).values)
    sp["date"] = pd.to_datetime(sp["date"]).dt.date.astype(str)
    sp.to_parquet(OUT / "spills.parquet", index=False)
    sites = pyogrio.read_dataframe(ZONES / "spills_statewide.gpkg", layer="sites")
    ll = sites.geometry.to_crs(4326)
    sites = pd.DataFrame(sites.drop(columns="geometry")).assign(lon=ll.x.round(6).values, lat=ll.y.round(6).values)
    sites["spill_date"] = pd.to_datetime(sites["spill_date"]).dt.date.astype(str)
    sites.to_parquet(OUT / "spill_sites.parquet", index=False)
    print(f"spills: {len(sp)}; sites: {len(sites):,}")

    print("spill springs:")
    spill_springs_table().to_parquet(OUT / "spill_springs.parquet", index=False)
    lst_table().to_parquet(OUT / "lst_springs.parquet", index=False)
    dr = pd.concat([pd.read_csv(f) for f in sorted(STATS.glob("sample_v1_and_spills_v1_drought_*.csv"))], ignore_index=True)
    dr.to_parquet(OUT / "drought.parquet", index=False)
    if (a.bands / "statewide.csv").exists():         # the ten-band design (plan v1.6)
        b = pd.read_csv(a.bands / "statewide.csv")
        b[b["scope"] == "statewide"].to_parquet(OUT / "band_profile.parquet", index=False)
        pd.read_csv(a.bands / "segment_spring.csv").to_parquet(OUT / "band_springs.parquet", index=False)
    for f in sorted(OUT.glob("*.parquet")):
        print(f"  {f.name}: {len(pd.read_parquet(f)):,} rows")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corridor", type=Path, default=P / "outputs" / "results" / "corridor_sample_v1_3springs")
    ap.add_argument("--bands", type=Path, default=P / "outputs" / "results" / "corridor_sample_v1_b50")
    main(ap.parse_args())
