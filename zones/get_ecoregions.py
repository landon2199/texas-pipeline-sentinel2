"""Save the EPA Level III ecoregions that cover Texas, from Earth Engine's built-in copy, as a GeoPackage.

Part 1 needs the ecoregion boundaries on our side to cut pipelines where they cross from one ecoregion to another.
Pulling them once from Earth Engine (EPA/Ecoregions/2013/L3) means Part 1 and Part 2 use exactly the same map, and
teammates running Part 1 never need Earth Engine. Polygons are clipped to Texas plus 2 km, so lines on the state line
keep their ecoregion.

Usage: python get_ecoregions.py <output .gpkg> [--project research-476723]
"""
import argparse
import datetime as dt
from pathlib import Path

import ee
import geopandas as gpd

ASSET = "EPA/Ecoregions/2013/L3"


def main(out: Path, project: str):
    ee.Initialize(project=project)
    texas = ee.FeatureCollection("TIGER/2018/States").filter(ee.Filter.eq("NAME", "Texas")).geometry().buffer(2000, 100)
    eco = (ee.FeatureCollection(ASSET).filterBounds(texas)
           .map(lambda f: f.intersection(texas, 1).set("area_km2", f.intersection(texas, 1).area(1).divide(1e6))))
    gdf = ee.data.computeFeatures({"expression": eco, "fileFormat": "GEOPANDAS_GEODATAFRAME"})
    gdf = gpd.GeoDataFrame(gdf, geometry="geometry", crs="EPSG:4326")
    # One feature per ecoregion: dissolve any pieces Earth Engine returns separately.
    keep = [c for c in ("us_l3code", "us_l3name", "na_l3code", "na_l3name", "na_l2name", "na_l1name") if c in gdf.columns]
    gdf = gdf[keep + ["geometry"]].dissolve(by=["us_l3code", "us_l3name"], aggfunc="first", as_index=False)
    gdf["us_l3code"] = gdf["us_l3code"].astype(str)
    gdf = gdf.sort_values("us_l3code").reset_index(drop=True)
    gdf["source"] = f"Earth Engine {ASSET}, accessed {dt.date.today().isoformat()}"
    out.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(out, layer="ecoregions", driver="GPKG")
    area = gdf.to_crs(6579).area / 1e6
    for (_, r), a in zip(gdf.iterrows(), area):
        print(f"  {r['us_l3code']:>3}  {r['us_l3name']:<32} {a:>10,.0f} km2 in Texas")
    print(f"wrote {out}: {len(gdf)} ecoregions")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--project", default="research-476723")
    a = ap.parse_args()
    main(a.out, a.project)
