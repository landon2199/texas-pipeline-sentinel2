"""The side-by-side check of stations.py in ArcGIS Pro: Create Routes, then Locate Features Along Routes.

Builds M-aware routes from the segments of every route with a spill (route ID line_uid, measures from start_m and
end_m, so the routes carry exactly the measures stations.py uses), locates each spill on its own route within 100 m,
and compares ArcGIS's measure and offset with stations.py's. Writes outputs/zones/statewide/stations_arcgis.csv and
prints a JSON summary as the last line.

Runs only with ArcGIS Pro's Python:
  "C:/Program Files/ArcGIS/Pro/bin/Python/envs/arcgispro-py3/python.exe" arcgis_stations_check.py
(run stations.py first; it writes stations_check.gpkg)
"""
import csv
import json
import os

import arcpy

S = r"C:\mydrive\Graduate School\Courses\GEOG_392\projects\outputs\zones\statewide"
arcpy.env.overwriteOutput = True
gdb = os.path.join(S, "stations_check.gdb")
if not arcpy.Exists(gdb):
    arcpy.management.CreateFileGDB(S, "stations_check.gdb")
src = os.path.join(S, "stations_check.gpkg")
routes = os.path.join(gdb, "routes")
arcpy.lr.CreateRoutes(os.path.join(src, "main.route_segments"), "line_uid", routes, "TWO_FIELDS",
                      from_measure_field="start_m", to_measure_field="end_m")
table = os.path.join(gdb, "spill_events")
arcpy.lr.LocateFeaturesAlongRoutes(os.path.join(src, "main.spills"), routes, "line_uid", "100 Meters", table,
                                   "rid POINT meas", "ALL", "DISTANCE", "ZERO", "FIELDS", "M_DIRECTON")
arc = {}
for spill, own, rid, meas, dist in arcpy.da.SearchCursor(table, ["spill_id", "line_uid", "rid", "meas", "Distance"]):
    if rid == own and (spill not in arc or abs(dist) < abs(arc[spill][1])):
        arc[spill] = (meas, dist)

rows, diffs = [], []
with open(os.path.join(S, "spill_stations.csv"), newline="", encoding="utf-8") as fh:
    for r in csv.DictReader(fh):
        m, d = arc.get(r["spill_id"], (None, None))
        diff = abs(m - float(r["measure_m"])) if m is not None else None
        if diff is not None and r["measure_along"] == "whole line":
            diffs.append(diff)
        rows.append({"spill_id": r["spill_id"], "route": r["route"], "measure_along": r["measure_along"],
                     "measure_m_open": r["measure_m"], "measure_m_arcgis": m, "abs_diff_m": diff,
                     "offset_m_open": r["offset_m"], "offset_m_arcgis": abs(d) if d is not None else None})
with open(os.path.join(S, "stations_arcgis.csv"), "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
diffs.sort()
print(json.dumps({"spills": len(rows), "located_by_arcgis": len(arc), "whole_line_compared": len(diffs),
                  "median_abs_diff_m": diffs[len(diffs) // 2] if diffs else None, "max_abs_diff_m": diffs[-1] if diffs else None}))
