"""Discovery, places: Google's Satellite Embedding for every segment and spill site, so agents can find look-alikes.

Satellite Embedding V1 (Earth Engine GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL; Brown et al. 2025) summarizes a year of
satellite observations of every 10 m pixel as 64 numbers. Places with similar numbers look alike over the year: land
cover, moisture, texture, how they change with the seasons. For each year 2017-2025 this exports the mean embedding of
  - every sampled segment's 0-50 m band (10 m grid) and its 500-1,000 m comparison ring (30 m grid), and
  - every spill site and comparison spot: the 0-25 and 25-50 m rings (10 m grid), joined in Part 3 by pixel count.
The tables go to the Drive folder geog392_zone_stats as embeddings_<year>_<which>.csv. Jobs are logged in
discovery_jobs.csv beside this script (not in extract/jobs_log.csv, so the spring runs are tracked on their own).

Usage: python embeddings.py [--years 2017 2018 ...] [--status]
"""
import argparse
import csv
import datetime as dt
import sys
from pathlib import Path

import ee

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "extract"))
import part2  # noqa: E402

ROOT = "projects/research-476723/assets/geog392"
LOG = Path(__file__).resolve().parent / "discovery_jobs.csv"
FIELDS = ["name", "task_id", "year", "zones", "submitted", "state", "eecu_hours"]
BANDS = [f"A{k:02d}" for k in range(64)]
SETS = {  # name: (asset folder, zone_id endings, grid in meters)
    "sample_row": ("sample_v1_b50", ["_r0-50"], 10),
    "sample_comparison": ("sample_v1_b50", ["_r500-1000"], 30),
    "spill_sites": ("spills_v1", ["_r0-25", "_r25-50"], 10),
}


def read_log():
    return {r["name"]: r for r in csv.DictReader(LOG.open(newline="", encoding="utf-8"))} if LOG.exists() else {}


def write_log(rows):
    with LOG.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(sorted(rows.values(), key=lambda r: r["submitted"]))


def refresh(rows):
    ops = {op["name"].rsplit("/", 1)[-1]: op.get("metadata", {}) for op in ee.data.listOperations()}
    for r in rows.values():
        m = ops.get(r["task_id"])
        if m:
            r["state"] = m.get("state", r["state"])
            r["eecu_hours"] = f"{float(m.get('batchEecuUsageSeconds', 0)) / 3600:.2f}"
    write_log(rows)
    return rows


def zones(folder, endings):
    fc = part2.zones_from(f"{ROOT}/{folder}")[0]
    keep = ee.Filter.Or(*[ee.Filter.stringEndsWith("zone_id", e) for e in endings]) if len(endings) > 1 else \
        ee.Filter.stringEndsWith("zone_id", endings[0])
    return fc.filter(keep).select(["zone_id"])


def main(a):
    rows = refresh(read_log())
    if a.status:
        for r in rows.values():
            print(f"{r['name']:40} {r['state']:10} {r['eecu_hours'] or '-':>6} EECU-h")
        return
    col = ee.ImageCollection("GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL")
    for year in a.years:
        img = col.filterDate(f"{year}-01-01", f"{year + 1}-01-01").mosaic().select(BANDS)
        img = img.addBands(img.select("A00").mask().rename("pixels"))          # pixel count: the sum of the mask
        for which, (folder, endings, scale) in SETS.items():
            name = f"embeddings_{year}_{which}"
            if name in rows and rows[name]["state"] not in ("FAILED", "CANCELLED"):
                print(f"  {name}: already {rows[name]['state'].lower()}, skipped")
                continue
            means = img.select(BANDS).reduceRegions(collection=zones(folder, endings), reducer=ee.Reducer.mean(),
                                                    scale=scale, tileScale=2)
            counted = img.select("pixels").reduceRegions(collection=means, reducer=ee.Reducer.sum().setOutputs(["pixels"]),
                                                         scale=scale, tileScale=2)
            task = ee.batch.Export.table.toDrive(collection=counted, description=name, folder=a.drive_folder,
                                                 fileNamePrefix=name, fileFormat="CSV", selectors=["zone_id"] + BANDS + ["pixels"])
            task.start()
            rows[name] = {"name": name, "task_id": task.id, "year": year, "zones": which,
                          "submitted": dt.datetime.now().isoformat(timespec="seconds"), "state": "SUBMITTED", "eecu_hours": ""}
            write_log(rows)
            print(f"  submitted {name}")
    print(f"log: {LOG}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--years", nargs="+", type=int, default=list(range(2017, 2026)))
    ap.add_argument("--drive-folder", default="geog392_zone_stats")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    ee.Initialize(project="research-476723")
    main(a)
