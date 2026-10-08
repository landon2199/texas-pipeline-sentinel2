"""Part 2 in one command: submit every Earth Engine job for the statewide sample and the spill zones, spring by spring,
inside a compute budget, and keep a log of every job (analysis plan v1.5, Section 5.6).

For each spring it submits, as table exports to the Drive folder --drive-folder (Earth Engine finds a Drive folder by
name anywhere in Drive, so keep exactly one folder with this name, in projects/outputs):
  - the sample's image-by-image values on the 20 m grid (corridor zones),
  - the spill zones' image-by-image values on the 10 m grid,
  - Landsat surface temperature for both (30 m),
  - the spring drought index for both;
and once, the fixed values (terrain, drainage, soil, water share) for both.
Jobs already in the log as submitted or done are not submitted again, so the command can be rerun after a stop.

The budget guard: before each spring, it adds up this calendar month's batch compute (from Earth Engine's own task
records) plus the estimated cost of the spring's jobs, and stops if that would pass --budget. The quota resets on the
first of the month (Pacific time), so rerun it then to continue. Online use (the Code Editor, interactive checks) also
counts against the quota but is not listed, so keep a margin.

Usage:
  python run_springs.py --sample <asset folder> --spills <asset folder> --springs 2025 2024 ... [--budget 140]
  python run_springs.py --status        (refresh the log: state and EECU-hours of every job)
"""
import argparse
import csv
import datetime as dt
import sys
from pathlib import Path

import ee

sys.path.insert(0, str(Path(__file__).resolve().parent))
import part2  # noqa: E402
from run_part2 import columns, region_geometry  # noqa: E402

LOG = Path(__file__).resolve().parent / "jobs_log.csv"
FIELDS = ["name", "task_id", "spring", "measure", "zones", "submitted", "state", "eecu_hours"]
# EECU-hours per spring, measured on spring 2025 (Oct 7): sample_v1 15.8, spills_v1 at 10 m 13.0, temperature 3.8
EST = {"sample_per_image": 16.0, "spills_per_image": 13.0, "lst": 3.8, "drought": 0.1, "fixed": 0.9}


def read_log():
    if not LOG.exists():
        return {}
    with LOG.open(newline="", encoding="utf-8") as fh:
        return {r["name"]: r for r in csv.DictReader(fh)}


def write_log(rows):
    with LOG.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(sorted(rows.values(), key=lambda r: r["submitted"]))


def month_used_hours() -> float:
    start = dt.date.today().replace(day=1).isoformat()
    return sum(float(op.get("metadata", {}).get("batchEecuUsageSeconds", 0)) / 3600
               for op in ee.data.listOperations() if op.get("metadata", {}).get("createTime", "") >= start)


def zones_of(folder):
    return part2.zones_from(folder)[0]


def submit(rows, name, fc, mode, spring, measure, zones_name, folder):
    if name in rows and rows[name]["state"] not in ("FAILED", "CANCELLED"):
        print(f"  {name}: already {rows[name]['state'].lower()}, skipped")
        return
    task = ee.batch.Export.table.toDrive(collection=fc, description=name, folder=folder, fileNamePrefix=name,
                                         fileFormat="CSV", selectors=columns(mode))
    task.start()
    rows[name] = {"name": name, "task_id": task.id, "spring": spring, "measure": measure, "zones": zones_name,
                  "submitted": dt.datetime.now().isoformat(timespec="seconds"), "state": "SUBMITTED", "eecu_hours": ""}
    write_log(rows)
    print(f"  submitted {name}")


def refresh(rows):
    """Bring every logged job's state and compute up to date from Earth Engine's task records."""
    ops = {op["name"].rsplit("/", 1)[-1]: op for op in ee.data.listOperations()}
    for r in rows.values():
        op = ops.get(r["task_id"])
        if op:
            m = op.get("metadata", {})
            r["state"] = m.get("state", r["state"])
            r["eecu_hours"] = f"{float(m.get('batchEecuUsageSeconds', 0)) / 3600:.2f}"
    write_log(rows)
    return rows


def status():
    rows = refresh(read_log())
    done = [r for r in rows.values() if r["eecu_hours"]]
    for r in sorted(rows.values(), key=lambda r: r["submitted"]):
        print(f"{r['name']:58} {r['state']:10} {r['eecu_hours'] or '-':>7} EECU-h")
    print(f"total so far: {sum(float(r['eecu_hours']) for r in done):,.1f} EECU-hours; this month (all tasks): "
          f"{month_used_hours():,.1f} (quota: Community tier 150, Contributor tier 1,000)")


def main(a):
    rows = refresh(read_log()) if LOG.exists() else {}
    texas = region_geometry("Texas")
    box = texas.bounds(100)
    sample, spills = zones_of(a.sample), zones_of(a.spills)
    s_name, p_name = Path(a.sample).name, Path(a.spills).name
    both = sample.merge(spills)

    if f"{s_name}_and_{p_name}_fixed" not in rows or rows[f"{s_name}_and_{p_name}_fixed"]["state"] in ("FAILED", "CANCELLED"):
        submit(rows, f"{s_name}_and_{p_name}_fixed", part2.fixed_values(both, None, None, None), "fixed", "", "fixed",
               f"{s_name}_and_{p_name}", a.drive_folder)

    def pending_hours():
        """Estimated cost of jobs in the log that have not finished yet (their compute isn't counted by Earth Engine yet)."""
        est = {"per_image": None, "lst": EST["lst"], "drought": EST["drought"], "fixed": EST["fixed"]}
        total = 0.0
        for r in rows.values():
            if r["state"] in ("SUBMITTED", "PENDING", "READY", "RUNNING"):
                total += (EST["sample_per_image"] if r["zones"] == s_name else EST["spills_per_image"]) \
                    if r["measure"] == "per_image" else est.get(r["measure"], 1.0)
        return total

    for spring in a.springs:
        need = EST["sample_per_image"] + EST["spills_per_image"] + EST["lst"] + EST["drought"]
        used = month_used_hours() + pending_hours()
        if used + need > a.budget:
            print(f"spring {spring}: stopping. This month's batch use is {used:,.1f} EECU-hours; this spring needs about "
                  f"{need:,.0f}, which would pass the budget of {a.budget:,.0f}. Rerun after the quota resets on the 1st.")
            break
        print(f"spring {spring} (this month, spent plus queued: {used:,.1f} EECU-hours):")
        part2.SCALE, part2.TILE_SCALE = 20, 1
        submit(rows, f"{s_name}_per_image_{spring}", part2.per_image_values(sample, box, spring, None), "per_image",
               spring, "per_image", s_name, a.drive_folder)
        part2.SCALE = 10
        submit(rows, f"{p_name}_per_image_{spring}_10m", part2.per_image_values(spills, box, spring, None), "per_image",
               spring, "per_image", p_name, a.drive_folder)
        part2.SCALE = 20
        submit(rows, f"{s_name}_and_{p_name}_lst_{spring}", part2.lst_values(both, box, spring, None), "lst",
               spring, "lst", f"{s_name}_and_{p_name}", a.drive_folder)
        submit(rows, f"{s_name}_and_{p_name}_drought_{spring}", part2.drought_values(both, box, spring), "drought",
               spring, "drought", f"{s_name}_and_{p_name}", a.drive_folder)
    print(f"log: {LOG}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sample", help="asset folder of the sample's rings, e.g. projects/research-476723/assets/geog392/sample_v1")
    ap.add_argument("--spills", help="asset folder of the spill zones")
    ap.add_argument("--springs", nargs="+", type=int, default=[2025, 2024, 2023, 2022, 2021, 2020, 2019, 2018, 2026])
    ap.add_argument("--budget", type=float, default=140, help="EECU-hours this month not to pass (Community tier: 150)")
    ap.add_argument("--drive-folder", default="geog392_zone_stats")
    ap.add_argument("--project", default="research-476723")
    ap.add_argument("--status", action="store_true", help="refresh the job log and stop")
    a = ap.parse_args()
    ee.Initialize(project=a.project)
    if a.status:
        status()
    elif not (a.sample and a.spills):
        ap.error("--sample and --spills are needed to submit jobs")
    else:
        main(a)
