"""Send a zone file to Earth Engine as table assets, in pieces, with no manual upload and no Cloud Storage.

Earth Engine's own uploaders need either the Code Editor (by hand) or Cloud Storage (a billing account). This script
instead builds the features on our side in pieces small enough for one request (under 10 MB), and asks Earth Engine to
save each piece as a table asset with Export.table.toAsset. Part 2 then reads all the pieces of a region as one
collection. Pieces that already exist are skipped, so the script can be run again after an interruption.

Usage: python ee_upload.py <zones .csv with zone_id,WKT> <asset folder name> [--project research-476723]
                           [--max-pieces N] [--wait]
"""
import argparse
import json
import sys
import time
from pathlib import Path

import ee
import pandas as pd
import shapely
import shapely.geometry

LIMIT_BYTES = 4_000_000      # Earth Engine's request limit is 10 MB, and its encoding adds overhead


def asset_root(project: str) -> str:
    return f"projects/{project}/assets/geog392"


def ensure_folder(path: str):
    try:
        ee.data.getAsset(path)
    except ee.EEException:
        ee.data.createAsset({"type": "FOLDER"}, path)


def pieces(df: pd.DataFrame):
    """Yield lists of GeoJSON features whose JSON stays under LIMIT_BYTES."""
    batch, size = [], 0
    for zone_id, wkt in zip(df["zone_id"], df["WKT"]):
        # mapping() keeps the CSV's 6-decimal coordinates short; GEOS's GeoJSON writer would expand them to 17 digits.
        geom = shapely.geometry.mapping(shapely.from_wkt(wkt))
        feat = {"type": "Feature", "geometry": geom, "properties": {"zone_id": zone_id}}
        n = len(json.dumps(feat))
        if batch and size + n > LIMIT_BYTES:
            yield batch
            batch, size = [], 0
        batch.append(feat)
        size += n
    if batch:
        yield batch


def main(a):
    ee.Initialize(project=a.project)
    root = asset_root(a.project)
    ensure_folder(root)
    folder = f"{root}/{a.name}"
    ensure_folder(folder)
    df = pd.read_csv(a.csv)
    started = []
    for i, batch in enumerate(pieces(df)):
        if a.max_pieces is not None and i >= a.max_pieces:
            break
        asset = f"{folder}/part_{i:04d}"
        try:
            ee.data.getAsset(asset)
            print(f"  {asset} exists, skipped")
            continue
        except ee.EEException:
            pass
        fc = ee.FeatureCollection({"type": "FeatureCollection", "features": batch})
        task = ee.batch.Export.table.toAsset(collection=fc, description=f"{a.name}_part_{i:04d}"[:100], assetId=asset)
        task.start()
        started.append((asset, task, len(batch)))
        print(f"  started {asset}: {len(batch):,} zones", flush=True)
    print(f"{len(started)} upload tasks started for {len(df):,} zones in {folder}")
    if a.wait:
        failed = 0
        while started:
            time.sleep(15)
            for item in list(started):
                asset, task, n = item
                try:
                    status = task.status()
                except Exception as e:      # Earth Engine sometimes answers a status check with a passing error (a 403
                    print(f"  status check failed for {asset}, retrying: {type(e).__name__}", flush=True)  # on Oct 7)
                    continue
                state = status["state"]
                if state in ("COMPLETED", "FAILED", "CANCELLED"):
                    extra = "" if state == "COMPLETED" else f": {status.get('error_message', '')}"
                    print(f"  {asset}: {state}{extra}", flush=True)
                    failed += state != "COMPLETED"
                    started.remove(item)
        if failed:
            raise SystemExit(f"{failed} upload piece(s) did not complete; rerun to retry them (finished pieces are skipped)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("csv", type=Path)
    ap.add_argument("name", help="asset folder under projects/<project>/assets/geog392/")
    ap.add_argument("--project", default="research-476723")
    ap.add_argument("--max-pieces", type=int)
    ap.add_argument("--wait", action="store_true")
    main(ap.parse_args())
