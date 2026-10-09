"""Plan 7.4: every clear Sentinel-2 image from a year before to a year after each reported spill.

The springs (run_springs.py) measure every zone in March and April only. This add-on follows each spill through the
seasons around it, to show when greenness fell and whether it came back. It measures the 50 m circle (the 0-25 and
25-50 m rings, the circle spills.py uses) of every site of the spill: the spill itself, its same-line spots and its
regional spots, on the 10 m grid. The outer spill rings (50-200 m) stay in the springs.

One table export per spill, named <zones>_series_<spill>, into --drive-folder, logged in jobs_log.csv with the springs.
Jobs already logged as submitted or done are skipped, so it can be rerun. Before each job it adds this month's batch
compute to the estimate for the jobs still queued and stops at --budget (Contributor tier: 1,000 EECU-hours a month).

Usage:
  python run_spill_series.py --spills projects/research-476723/assets/geog392/spills_v1 [--only S024 S045] [--days 365]
  python run_spill_series.py --status
"""
import argparse
import datetime as dt
import sys
from pathlib import Path

import ee
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import part2  # noqa: E402
from run_springs import LOG, month_used_hours, read_log, refresh, status, submit  # noqa: E402

SPILLS = Path(r"C:\mydrive\Graduate School\Courses\GEOG_392\projects\outputs\agent\spills.parquet")
QUEUED = ("SUBMITTED", "PENDING", "READY", "RUNNING")


def main(a):
    rows = refresh(read_log()) if LOG.exists() else {}
    spills = pd.read_parquet(SPILLS, columns=["spill_id", "date"]).sort_values("date")
    if a.only:
        spills = spills[spills["spill_id"].isin(a.only)]
    zones_name = Path(a.spills).name
    circle = ee.Filter.Or(ee.Filter.stringEndsWith("zone_id", "_r0-25"), ee.Filter.stringEndsWith("zone_id", "_r25-50"))
    zones = part2.zones_from(a.spills)[0].filter(circle)
    part2.SCALE = 10
    today = dt.date.today()
    used = month_used_hours()
    queued = a.est * sum(r["measure"] == "series" and r["state"] in QUEUED for r in rows.values())
    print(f"this month so far: {used:,.1f} EECU-hours; series jobs still queued: about {queued:,.1f}")
    for s in spills.itertuples():
        name = f"{zones_name}_series_{s.spill_id}"
        if name in rows and rows[name]["state"] not in ("FAILED", "CANCELLED"):
            continue
        if used + queued + a.est > a.budget:
            print(f"stopping before {s.spill_id}: about {used + queued:,.1f} EECU-hours used or queued, budget {a.budget:,.0f}")
            break
        day = pd.Timestamp(s.date).date()
        start, end = day - dt.timedelta(days=a.days), min(day + dt.timedelta(days=a.days + 1), today)
        mine = zones.filter(ee.Filter.stringStartsWith("zone_id", f"{s.spill_id}_"))
        fc = part2.per_image_between(mine, mine.geometry(1), start.isoformat(), end.isoformat(), None)
        submit(rows, name, fc, "per_image", f"{s.date} ({start} to {end})", "series", zones_name, a.drive_folder)
        queued += a.est
    print(f"log: {LOG}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--spills", default="projects/research-476723/assets/geog392/spills_v1", help="asset folder of the spill zones")
    ap.add_argument("--only", nargs="+", help="spill IDs to submit (default: every matched spill)")
    ap.add_argument("--days", type=int, default=365, help="days before and after each spill")
    ap.add_argument("--est", type=float, default=1.0, help="estimated EECU-hours per spill, for the budget guard")
    ap.add_argument("--budget", type=float, default=900, help="EECU-hours this month not to pass")
    ap.add_argument("--drive-folder", default="geog392_zone_stats")
    ap.add_argument("--project", default="research-476723")
    ap.add_argument("--status", action="store_true", help="refresh the job log and stop")
    a = ap.parse_args()
    ee.Initialize(project=a.project)
    status() if a.status else main(a)
