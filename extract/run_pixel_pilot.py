"""Plan D31, step 1: every pixel of the sample's 0-50 m band, springs 2018-2026, for the finer-than-1-km baseline.

Three kinds of export, all into --drive-folder and logged in jobs_log.csv:
  sample_v1_pixels_ndvi_10m          every 10 m pixel (NDVI's native size) in the 0-50 m band of the 3,499 sample
                                     segments: its location, NLCD class and spring median NDVI for each of the nine springs;
  sample_v1_pixels_ndre_ndmi_20m     the same for NDRE and NDMI at their native 20 m (no false detail from resampling);
  sample_v1_comparison_composite_Y   each segment's comparison ring (500-1,000 m), spring median composite, mean and
                                     pixel count by land cover (NDVI, NDMI, NDRE), one export per spring.
Masked pixels are written as -9 (no clear image that spring). Usage: python run_pixel_pilot.py
"""
import argparse
import datetime as dt
import sys
from pathlib import Path

import ee

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import part2  # noqa: E402
from common.config import DRIVE_FOLDER, EE_ASSETS, EE_PROJECT  # noqa: E402
from run_springs import month_used_hours, read_log, write_log  # noqa: E402

SPRINGS = list(range(2018, 2027))


def submit(rows, name, fc, selectors, folder, measure):
    if name in rows and rows[name]["state"] not in ("FAILED", "CANCELLED"):
        print(f"  {name}: already {rows[name]['state'].lower()}")
        return
    task = ee.batch.Export.table.toDrive(collection=fc, description=name, folder=folder, fileNamePrefix=name,
                                         fileFormat="CSV", selectors=selectors)
    task.start()
    rows[name] = {"name": name, "task_id": task.id, "spring": "2018-2026", "measure": measure, "zones": "sample_v1_b50",
                  "submitted": dt.datetime.now().isoformat(timespec="seconds"), "state": "SUBMITTED", "eecu_hours": ""}
    write_log(rows)
    print(f"  submitted {name}")


def stack(region, index):
    return ee.Image.cat([part2.spring_images(region, y).select(index).median().rename(f"{index}_{y}") for y in SPRINGS])


def main(a):
    rows = read_log()
    print(f"this month so far: {month_used_hours():,.1f} EECU-hours")
    zones = part2.zones_from(a.zones)[0]
    band = zones.filter(ee.Filter.stringEndsWith("zone_id", "_r0-50"))
    comp = zones.filter(ee.Filter.stringEndsWith("zone_id", "_r500-1000"))
    texas = ee.Geometry.Rectangle([-106.7, 25.8, -93.5, 36.6])
    lc = part2.nlcd().rename("landcover")
    ndvi = stack(texas, "NDVI").unmask(-9).addBands(lc)
    s10 = ndvi.sampleRegions(collection=band, properties=["zone_id"], scale=10, geometries=True, tileScale=8)
    submit(rows, "sample_v1_pixels_ndvi_10m", s10, ["zone_id", "landcover"] + [f"NDVI_{y}" for y in SPRINGS] + [".geo"],
           a.drive_folder, "pixel_pilot_10m")
    red = stack(texas, "NDRE").addBands(stack(texas, "NDMI")).unmask(-9).addBands(lc)
    s20 = red.sampleRegions(collection=band, properties=["zone_id"], scale=20, geometries=True, tileScale=8)
    submit(rows, "sample_v1_pixels_ndre_ndmi_20m", s20,
           ["zone_id", "landcover"] + [f"{i}_{y}" for i in ("NDRE", "NDMI") for y in SPRINGS] + [".geo"], a.drive_folder,
           "pixel_pilot_20m")
    cols = ["zone_id", "landcover", "spring"] + [f"{i}_{s}" for i in ("NDVI", "NDMI", "NDRE") for s in ("mean", "count")]
    for y in SPRINGS:
        fc = part2.lean_composite_values(comp, texas, y, bands=("NDVI", "NDMI", "NDRE"))
        submit(rows, f"sample_v1_comparison_composite_{y}", fc, cols, a.drive_folder, "comparison_composite")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--zones", default=f"{EE_ASSETS}/sample_v1_b50")
    ap.add_argument("--drive-folder", default=DRIVE_FOLDER)
    ap.add_argument("--project", default=EE_PROJECT)
    a = ap.parse_args()
    ee.Initialize(project=a.project)
    main(a)
