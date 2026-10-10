"""ArcGIS Pro's Forest-based and Boosted Classification and Regression on gap_drivers.py's table, for the side-by-side.

Runs only with ArcGIS Pro's Python (arcgispro-py3); gap_drivers.py --arcgis prepares the input and reads the result.
Prints a JSON summary (validation R², top variables by importance) as the last line.
Usage: python arcgis_forest.py <in.gpkg> <out folder>
"""
import json
import os
import re
import sys

import arcpy

src, out_dir = sys.argv[1:3]
arcpy.env.overwriteOutput = True
gdb = os.path.join(out_dir, "gap_drivers.gdb")
if not arcpy.Exists(gdb):
    arcpy.management.CreateFileGDB(out_dir, "gap_drivers.gdb")
pts = os.path.join(gdb, "segments")
arcpy.conversion.ExportFeatures(os.path.join(src, "main.segments"), pts)
fields = {f.name.lower(): f for f in arcpy.ListFields(pts)}
cats = ["commodity_group", "service", "status", "location_accuracy", "soil_texture"]
nums = ["diameter_in", "impervious_pct", "road", "developed", "energy", "dw_built", "lc_changed", "slope_deg_mean",
        "hand_m_mean", "twi_mean", "elevation_m_mean"] + [n for n in fields if n.startswith("nlcd_")]
nums = [n for n in nums if n in fields]
vals = list(zip(*arcpy.da.SearchCursor(pts, [fields[n].name for n in nums])))
dropped = []
for n, v in zip(list(nums), vals):                 # the tool refuses fields that are nearly constant (ERROR 110180)
    v = [x for x in v if x is not None]
    if not v or max(v.count(x) for x in set(v)) / len(v) > 0.9:
        nums.remove(n)
        dropped.append(n)
expl = [[fields[n].name, "false"] for n in nums] + [[fields[c].name, "true"] for c in cats if c in fields]
imp = os.path.join(gdb, "importance")
res = arcpy.stats.Forest(prediction_type="TRAIN", in_features=pts, variable_predict=fields["gap"].name,
                         explanatory_variables=expl, output_importance_table=imp, number_of_trees=500,
                         minimum_leaf_size=5, sample_size=100, percentage_for_training=10)
msgs = res.getMessages()
r2 = re.findall(r"R-Squared\s+([-\d.]+)", msgs)
rows = sorted(arcpy.da.SearchCursor(imp, ["VARIABLES", "PERCENTAGE"]), key=lambda r: -r[1])
print(json.dumps({"trees": 500, "validation_r2": r2[-1] if r2 else None, "top": [r[0] for r in rows[:6]], "dropped": dropped,
                  "importance": {r[0]: round(r[1], 4) for r in rows}}))
