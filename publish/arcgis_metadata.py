"""Optional, with ArcGIS Pro: translate the ISO 19139 metadata from catalog.py to ISO 19115-3 and check that Pro opens
the GeoParquet layers. Writes outputs/publish/metadata/<layer>_iso19115-3.xml and prints a JSON summary.

Runs only with ArcGIS Pro's Python:
  "C:/Program Files/ArcGIS/Pro/bin/Python/envs/arcgispro-py3/python.exe" arcgis_metadata.py
"""
import glob
import json
import os

import arcpy
from arcpy import metadata as md

O = r"C:\mydrive\Graduate School\Courses\GEOG_392\projects\outputs\publish"
out = {"pro_version": arcpy.GetInstallInfo()["Version"], "metadata": {}, "geoparquet": {}}
for x in sorted(glob.glob(os.path.join(O, "metadata", "*.xml"))):
    if x.endswith("_iso19115-3.xml"):
        continue
    name = os.path.basename(x)[:-4]
    m = md.Metadata()
    m.importMetadata(x, "ISO19139")
    dst = os.path.join(O, "metadata", f"{name}_iso19115-3.xml")
    m.exportMetadata(dst, "ISO19115_3")
    out["metadata"][name] = {"title": m.title, "iso19115_3": os.path.exists(dst)}
for f in sorted(glob.glob(os.path.join(O, "data", "*.parquet"))):
    try:
        out["geoparquet"][os.path.basename(f)] = int(arcpy.management.GetCount(f)[0])
    except Exception as e:  # older Pro releases do not read Parquet
        out["geoparquet"][os.path.basename(f)] = f"not opened: {str(e).splitlines()[0][:80]}"
print(json.dumps(out))
