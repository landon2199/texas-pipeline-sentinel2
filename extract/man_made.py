"""Man-made features in every zone (gap 1 of the Oct 9 gap scan), one Earth Engine table export.

For each zone of the sample (ten 50 m bands and the comparison ring) and of the spills, the share of the zone that is:
  - impervious surface (NLCD 2021, percent), and by the NLCD impervious descriptor: roads (classes 20-23), other
    developed land and Microsoft buildings (24-26), and well pads, wind turbines and other energy sites (27-29);
  - built-up or bare in Dynamic World (Google's deep-learning land cover from Sentinel-2): the mean of the spring
    (March-April) median probabilities, 2018-2026;
  - land cover that changed at least once in NLCD's 2001-2021 change record.
Written as <zones...>_man_made.csv to --drive-folder and logged in jobs_log.csv. analysis/man_made_check.py uses it.

Usage: python man_made.py [--zones projects/research-476723/assets/geog392/sample_v1_b50 .../spills_v1]
"""
import argparse
import datetime as dt
import sys
from pathlib import Path

import ee

sys.path.insert(0, str(Path(__file__).resolve().parent))
import part2  # noqa: E402
from run_springs import read_log, write_log  # noqa: E402

BANDS = ["impervious_pct", "road", "developed", "energy", "lc_changed", "dw_built", "dw_bare"]


def layers() -> ee.Image:
    nlcd = ee.ImageCollection("USGS/NLCD_RELEASES/2021_REL/NLCD").first()
    d = nlcd.select("impervious_descriptor")
    texas = ee.Geometry.Rectangle([-106.7, 25.8, -93.5, 36.6])
    dw = ee.ImageCollection([
        ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1").filterBounds(texas).filterDate(f"{y}-03-01", f"{y}-05-01")
        .select(["built", "bare"]).median() for y in range(2018, 2027)]).mean()
    return ee.Image.cat([
        nlcd.select("impervious").rename("impervious_pct"),
        d.gte(20).And(d.lte(23)).rename("road"),
        d.gte(24).And(d.lte(26)).rename("developed"),
        d.gte(27).And(d.lte(29)).rename("energy"),
        nlcd.select("science_products_land_cover_change_count").unmask(0).gt(0).rename("lc_changed"),
        dw.select("built").rename("dw_built"),
        dw.select("bare").rename("dw_bare"),
    ]).toFloat()


def main(a):
    zones = ee.FeatureCollection([part2.zones_from(z)[0] for z in a.zones]).flatten()
    out = layers().reduceRegions(collection=zones, reducer=ee.Reducer.mean(), scale=10, crs="EPSG:3083", tileScale=4)
    name = "_and_".join(Path(z).name for z in a.zones) + "_man_made"
    rows = read_log()
    if name in rows and rows[name]["state"] not in ("FAILED", "CANCELLED"):
        print(f"{name}: already {rows[name]['state'].lower()}")
        return
    task = ee.batch.Export.table.toDrive(collection=out, description=name, folder=a.drive_folder, fileNamePrefix=name,
                                         fileFormat="CSV", selectors=["zone_id"] + BANDS)
    task.start()
    rows[name] = {"name": name, "task_id": task.id, "spring": "", "measure": "man_made", "zones": name,
                  "submitted": dt.datetime.now().isoformat(timespec="seconds"), "state": "SUBMITTED", "eecu_hours": ""}
    write_log(rows)
    print(f"submitted {name}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--zones", nargs="+", default=["projects/research-476723/assets/geog392/sample_v1_b50",
                                                   "projects/research-476723/assets/geog392/spills_v1"])
    ap.add_argument("--drive-folder", default="geog392_zone_stats")
    ap.add_argument("--project", default="research-476723")
    a = ap.parse_args()
    ee.Initialize(project=a.project)
    main(a)
