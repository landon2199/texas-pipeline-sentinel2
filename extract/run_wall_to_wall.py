"""Wall-to-wall: every pipeline segment's 0-50 m band and comparison ring, from spring median composites (plan 5.4).

The image-by-image sample (run_springs.py) stays the main test; this measures every zone once per spring, cheaply, so
the map can show every pipeline. Zones are the 0-50 m band and the comparison ring (500-1,000 m) of every segment in an
uploaded zone asset. One table export per asset and spring into --drive-folder, logged in jobs_log.csv.

Usage:
  python run_wall_to_wall.py --zones projects/research-476723/assets/geog392/sample_v1 --springs 2024 --name test
  python run_wall_to_wall.py --zones <asset folder> [<asset folder> ...] --springs 2018 ... 2026
"""
import argparse
import datetime as dt
import sys
from pathlib import Path

import ee

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import part2  # noqa: E402
from common.config import DRIVE_FOLDER, EE_PROJECT  # noqa: E402
from run_springs import month_used_hours, read_log, write_log  # noqa: E402

COLUMNS = ["zone_id", "landcover", "spring", "NDVI_mean", "NDMI_mean", "NDVI_count", "NDMI_count"]


def main(a):
    rows = read_log()
    part2.SCALE = 20
    texas = ee.Geometry.Rectangle([-106.7, 25.8, -93.5, 36.6])
    print(f"this month so far: {month_used_hours():,.1f} EECU-hours")
    for folder in a.zones:
        zones = part2.zones_from(folder)[0]
        if a.only_rings:
            zones = zones.filter(ee.Filter.Or(*[ee.Filter.stringEndsWith("zone_id", f"_r{r}") for r in a.only_rings]))
        for spring in a.springs:
            name = f"{a.name or Path(folder).name}_wall_{spring}"
            if name in rows and rows[name]["state"] not in ("FAILED", "CANCELLED"):
                print(f"  {name}: already {rows[name]['state'].lower()}")
                continue
            fc = part2.lean_composite_values(zones, texas, spring)
            task = ee.batch.Export.table.toDrive(collection=fc, description=name, folder=a.drive_folder,
                                                 fileNamePrefix=name, fileFormat="CSV", selectors=COLUMNS)
            task.start()
            rows[name] = {"name": name, "task_id": task.id, "spring": spring, "measure": "wall_to_wall",
                          "zones": Path(folder).name, "submitted": dt.datetime.now().isoformat(timespec="seconds"),
                          "state": "SUBMITTED", "eecu_hours": ""}
            write_log(rows)
            print(f"  submitted {name}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--zones", nargs="+", required=True, help="uploaded zone asset folders")
    ap.add_argument("--springs", nargs="+", type=int, default=list(range(2018, 2027)))
    ap.add_argument("--only-rings", nargs="*", default=["0-50", "500-1000"], help="ring labels to keep (zone_id suffixes)")
    ap.add_argument("--name", help="job name prefix (default: the asset folder name)")
    ap.add_argument("--drive-folder", default=DRIVE_FOLDER)
    ap.add_argument("--project", default=EE_PROJECT)
    a = ap.parse_args()
    ee.Initialize(project=a.project)
    main(a)
