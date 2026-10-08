"""Run ArcGIS Pro's Optimized Hot Spot Analysis for the MCP server and print a JSON summary as the last line.

Runs only with ArcGIS Pro's Python (arcgispro-py3). Usage: python arcgis_hotspots.py <gpkg> <layer> <field> <out.gdb>
"""
import json
import os
import sys

import arcpy

src, layer, field, gdb = sys.argv[1:5]
arcpy.env.overwriteOutput = True
if not arcpy.Exists(gdb):
    arcpy.management.CreateFileGDB(os.path.dirname(gdb), os.path.basename(gdb))
out = os.path.join(gdb, f"hotspots_{field.lower()}")
arcpy.stats.OptimizedHotSpotAnalysis(os.path.join(src, f"main.{layer}"), out, field)
bins = {}
with arcpy.da.SearchCursor(out, ["Gi_Bin"]) as cursor:
    for (b,) in cursor:
        bins[int(b)] = bins.get(int(b), 0) + 1
print(json.dumps({"output": out, "bins": bins}))
