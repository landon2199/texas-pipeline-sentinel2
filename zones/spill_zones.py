"""Part 1, spills: zones at every reported spill, its candidate comparison spots, and a regional baseline pool.

Analysis plan, Sections 7.1-7.2. For each spill this:
  1. matches it to the nearest mapped line within 100 m and records the distance and that line's location accuracy;
  2. draws distance rings around the spill point (0-25, 25-50, 50-100, 100-200 m) and the 50 m and 100 m circles.
     Only the rings go to Earth Engine: each circle is exactly the rings inside it (50 m = 0-25 + 25-50 m), so Part 3
     rebuilds its mean from the rings' means and pixel counts, which saves about a quarter of the spill compute. The
     circles stay in the GeoPackage for maps;
  3. places candidate comparison spots on the same line every 0.5 km, out to 3 km each way, with the same zones;
  4. draws a pool of regional baseline spots: random points on other lines in the same ecoregion with the same
     commodity group and diameter class.
Rules that need only geometry are applied here as labels (same ecoregion; no other reported spill within 1 km). The
rules that need land cover, soil and terrain are applied after Part 2 measures them; nothing is dropped here.

Usage: python spill_zones.py --spills <spills .gpkg> --lines <statewide .gpkg> --ecoregions <.gpkg> --out <.gpkg>
                             [--only "Central Great Plains"] [--pool 50]
"""
import argparse
import shutil
import sys
import tempfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.ops import linemerge

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_zones import EQUAL_AREA, load_lines, projection_note  # noqa: E402

MATCH_M = 100
STEP_M, REACH_M = 500, 3000
SPILL_FREE_M = 1000
RINGS = [(0, 25), (25, 50), (50, 100), (100, 200)]
CIRCLES = [50, 100]
SEED = 392


def zones_at(sites: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Rings and circles around every site point."""
    pts = np.asarray(sites.geometry.array)
    out = []
    for inner, outer in RINGS:
        geom = shapely.buffer(pts, outer)
        if inner:
            geom = shapely.difference(geom, shapely.buffer(pts, inner))
        out.append(pd.DataFrame({"site_id": sites["site_id"].values, "zone_type": "ring", "inner_m": inner,
                                 "outer_m": outer, "geometry": geom}))
    for r in CIRCLES:
        out.append(pd.DataFrame({"site_id": sites["site_id"].values, "zone_type": "circle", "inner_m": 0,
                                 "outer_m": r, "geometry": shapely.buffer(pts, r)}))
    z = gpd.GeoDataFrame(pd.concat(out, ignore_index=True), geometry="geometry", crs=sites.crs)
    z.insert(0, "zone_id", z["site_id"] + np.where(z["zone_type"] == "ring", "_r" + z["inner_m"].astype(str) + "-", "_c")
             + z["outer_m"].astype(str))
    return z.merge(sites.drop(columns="geometry"), on="site_id", how="left")


def main(a):
    print("projection:", projection_note(), flush=True)
    lines = load_lines(a.lines)
    lines = lines[~lines["dup_geometry"]].reset_index(drop=True)
    eco = gpd.read_file(a.ecoregions).to_crs(EQUAL_AREA)[["us_l3code", "us_l3name", "geometry"]]
    spills = gpd.read_file(a.spills).to_crs(EQUAL_AREA)
    spills = gpd.sjoin(spills.drop(columns=[c for c in ("ecoregion",) if c in spills]), eco, how="left",
                       predicate="within").drop(columns="index_right").rename(columns={"us_l3name": "ecoregion",
                                                                                       "us_l3code": "ecoregion_code"})
    if a.only:
        spills = spills[spills["ecoregion"].isin(a.only)]
    near = gpd.sjoin_nearest(spills, lines[["line_uid", "location_accuracy", "commodity_group", "diameter_class", "geometry"]],
                             max_distance=MATCH_M, distance_col="distance_to_line_m")
    near = near.sort_values("distance_to_line_m").drop_duplicates("spill_id").drop(columns="index_right")
    unmatched = spills[~spills["spill_id"].isin(near["spill_id"])]
    all_spills = gpd.read_file(a.spills).to_crs(EQUAL_AREA)

    sites, rng = [], np.random.default_rng(SEED)
    line_geom = lines.set_index("line_uid").geometry
    for s in near.itertuples():
        base = {"spill_id": s.spill_id, "spill_date": s.date, "barrels": s.barrels, "ecoregion": s.ecoregion,
                "ecoregion_code": s.ecoregion_code, "line_uid": s.line_uid, "spill_distance_to_line_m": round(s.distance_to_line_m, 1),
                "line_location_accuracy": s.location_accuracy}
        sites.append({**base, "site_id": f"{s.spill_id}_spill", "site": "spill", "offset_m": 0, "geometry": s.geometry})
        line = line_geom.loc[s.line_uid]
        line = linemerge(line) if line.geom_type == "MultiLineString" else line
        if line.geom_type == "MultiLineString":                         # still in pieces: use the piece nearest the spill
            line = min(line.geoms, key=lambda g: g.distance(s.geometry))
        at = line.project(s.geometry)
        for step in range(STEP_M, REACH_M + 1, STEP_M):
            for side, d in (("up", at - step), ("down", at + step)):
                if 0 <= d <= line.length:
                    sites.append({**base, "site_id": f"{s.spill_id}_{side}_{step:04d}", "site": "candidate",
                                  "offset_m": step if side == "down" else -step, "geometry": line.interpolate(d)})
        # Regional baseline pool: other lines in the same ecoregion, same commodity group and diameter class.
        region = eco.loc[eco["us_l3name"] == s.ecoregion, "geometry"]
        if region.empty:
            continue
        pool = lines[(lines["commodity_group"] == s.commodity_group) & (lines["diameter_class"] == s.diameter_class)
                     & (lines["line_uid"] != s.line_uid)]
        pool = pool.iloc[pool.sindex.query(region.iloc[0], predicate="intersects")]
        if pool.empty:
            continue
        picks = pool.sample(n=min(a.pool, len(pool)), random_state=int(rng.integers(1e9)))
        for i, p in enumerate(picks.itertuples()):
            part = shapely.intersection(p.geometry, region.iloc[0])
            if part.is_empty or part.length < 1:
                continue
            sites.append({**base, "site_id": f"{s.spill_id}_regional_{i:03d}", "site": "regional", "offset_m": np.nan,
                          "regional_line_uid": p.line_uid,
                          "geometry": shapely.line_interpolate_point(part, rng.uniform(0, part.length))})
    sites = gpd.GeoDataFrame(sites, geometry="geometry", crs=EQUAL_AREA)

    # Geometry-only rules, as labels: same ecoregion as the spill; no other reported spill within 1 km.
    sites = gpd.sjoin(sites, eco.rename(columns={"us_l3name": "site_ecoregion"})[["site_ecoregion", "geometry"]],
                      how="left", predicate="within").drop(columns="index_right")
    sites["same_ecoregion"] = sites["site_ecoregion"] == sites["ecoregion"]
    others = all_spills[["spill_id", "geometry"]].rename(columns={"spill_id": "other_spill"})
    close = gpd.sjoin(sites[["site_id", "spill_id", "geometry"]], others.set_geometry(others.buffer(SPILL_FREE_M)),
                      how="inner", predicate="within")
    close = close[close["other_spill"] != close["spill_id"]]
    sites["other_spill_within_1km"] = sites["site_id"].isin(close["site_id"])
    zones = zones_at(sites)

    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / a.out.name
        near.to_file(local, layer="spills_matched", driver="GPKG")
        if len(unmatched):
            unmatched.to_file(local, layer="spills_unmatched", driver="GPKG")
        sites.to_file(local, layer="sites", driver="GPKG")
        zones.to_file(local, layer="zones", driver="GPKG")
        csv = Path(tmp) / (a.out.stem + "_zones.csv")
        ee_zones = zones[zones["zone_type"] == "ring"].sort_values(["site_id", "inner_m"], kind="stable")
        pd.DataFrame({"zone_id": ee_zones["zone_id"].values, "WKT": shapely.to_wkt(
            np.asarray(ee_zones.to_crs(4326).geometry.array), rounding_precision=6)}).to_csv(csv, index=False)
        a.out.parent.mkdir(parents=True, exist_ok=True)
        (a.out.parent / "ee_upload").mkdir(exist_ok=True)
        shutil.copy(local, a.out)
        shutil.copy(csv, a.out.parent / "ee_upload" / csv.name)
    counts = sites["site"].value_counts().to_dict()
    print(f"spills: {len(near)} matched within {MATCH_M} m, {len(unmatched)} not matched; sites {counts}; "
          f"{len(zones):,} zones -> {a.out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--spills", type=Path, required=True)
    ap.add_argument("--lines", type=Path, required=True)
    ap.add_argument("--ecoregions", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--pool", type=int, default=50, help="regional baseline candidates per spill")
    main(ap.parse_args())
