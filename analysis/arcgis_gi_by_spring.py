"""Getis-Ord Gi* hot spot analysis of one corridor variable in each spring, with ArcGIS Pro. Writes each segment's
z-score and bin per spring to gi_by_spring.csv and prints a JSON summary as the last line.

Runs only with ArcGIS Pro's Python (arcgispro-py3); analysis/hot_spots_by_spring.py prepares the input and reads the
result. (Emerging Hot Spot Analysis would be the usual tool, but its space-time cube needs at least 10 time steps,
and there are nine springs.)

Usage: python arcgis_gi_by_spring.py <in.gpkg> <layer> <field> <out folder> [neighbors]
"""
import csv
import json
import os
import sys

import arcpy

src, layer, field, out_dir = sys.argv[1:5]
neighbors = int(sys.argv[5]) if len(sys.argv) > 5 else 8
arcpy.env.overwriteOutput = True
gdb = os.path.join(out_dir, "gi_by_spring.gdb")
if not arcpy.Exists(gdb):
    arcpy.management.CreateFileGDB(out_dir, "gi_by_spring.gdb")
points = os.path.join(gdb, "segment_springs")
arcpy.conversion.ExportFeatures(os.path.join(src, f"main.{layer}"), points)
years = sorted({int(y) for (y,) in arcpy.da.SearchCursor(points, ["year"])})

rows, bins = [], {}
for year in years:
    one = os.path.join(gdb, f"springs_{year}")
    arcpy.analysis.Select(points, one, f"year = {year}")
    out = os.path.join(gdb, f"gi_{year}")
    # each segment against its nearest neighbors, with the false discovery rate correction
    arcpy.stats.HotSpots(one, field, out, "K_NEAREST_NEIGHBORS", "EUCLIDEAN_DISTANCE", "NONE", None, None, None,
                         "APPLY_FDR", neighbors)
    count = {}
    ids = {oid: sid for oid, sid in arcpy.da.SearchCursor(one, ["OID@", "segment_id"])}
    with arcpy.da.SearchCursor(out, ["SOURCE_ID", "GiZScore", "Gi_Bin"]) as cursor:   # the output keeps only the input's ID
        for source, z, b in cursor:
            rows.append((ids[source], year, z, int(b)))
            count[int(b)] = count.get(int(b), 0) + 1
    bins[year] = count

with open(os.path.join(out_dir, "gi_by_spring.csv"), "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["segment_id", "year", "gi_z", "gi_bin"])
    w.writerows(rows)
print(json.dumps({"years": years, "neighbors": neighbors, "bins": bins}))
