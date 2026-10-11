"""Plan D30: measure the 2010+ spill sites in Landsat (springs 2008-2026) and their fixed values, in Earth Engine.

One table export per spring (image-by-image values of the five Landsat indices for every spill-site ring, by land cover)
and one export of the fixed values (terrain, drainage, soil) for matching, into --drive-folder, logged in jobs_log.csv.
Usage: python run_landsat_spills.py [--zones projects/research-476723/assets/geog392/spills_2010] [--springs 2008 ... 2026]
"""
import argparse
import datetime as dt
import sys
from pathlib import Path

import ee

sys.path.insert(0, str(Path(__file__).resolve().parent))
import part2  # noqa: E402
from run_springs import month_used_hours, read_log, write_log  # noqa: E402

COLUMNS = (["zone_id", "landcover", "date", "image", "orbit", "tile", "spacecraft", "sun_zenith"]
           + [f"{i}_{s}" for i in part2.LANDSAT_INDICES for s in ("mean", "count")])
FIXED = ["zone_id"] + [f"{f}_mean" for f in part2.FIXED if f != "soil_texture"] + ["soil_texture_mode"]


def submit(rows, name, fc, selectors, spring, measure, zones, folder):
    if name in rows and rows[name]["state"] not in ("FAILED", "CANCELLED"):
        print(f"  {name}: already {rows[name]['state'].lower()}")
        return
    task = ee.batch.Export.table.toDrive(collection=fc, description=name, folder=folder, fileNamePrefix=name,
                                         fileFormat="CSV", selectors=selectors)
    task.start()
    rows[name] = {"name": name, "task_id": task.id, "spring": spring, "measure": measure, "zones": zones,
                  "submitted": dt.datetime.now().isoformat(timespec="seconds"), "state": "SUBMITTED", "eecu_hours": ""}
    write_log(rows)
    print(f"  submitted {name}")


def main(a):
    rows = read_log()
    print(f"this month so far: {month_used_hours():,.1f} EECU-hours")
    zones = part2.zones_from(a.zones)[0]
    texas = ee.Geometry.Rectangle([-106.7, 25.8, -93.5, 36.6])
    zname = Path(a.zones).name
    submit(rows, f"{zname}_fixed", part2.fixed_values(zones), FIXED, "", "fixed", zname, a.drive_folder)
    for spring in a.springs:
        submit(rows, f"{zname}_landsat_per_image_{spring}", part2.landsat_sr_values(zones, texas, spring), COLUMNS, spring,
               "landsat_per_image", zname, a.drive_folder)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--zones", default="projects/research-476723/assets/geog392/spills_2010")
    ap.add_argument("--springs", nargs="+", type=int, default=list(range(2008, 2027)))
    ap.add_argument("--drive-folder", default="geog392_zone_stats")
    ap.add_argument("--project", default="research-476723")
    a = ap.parse_args()
    ee.Initialize(project=a.project)
    main(a)
