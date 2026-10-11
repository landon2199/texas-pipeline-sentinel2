"""Plan D32 (M1): oil and gas wells near every methane plume, from the Railroad Commission's public map service.

Downloads the RRC "Well Locations" layer (RRC_Public_Viewer_Srvs, layer 1) inside small tiles around the plumes of the
three sources (methane_three_sources.py), so only the wells that matter are fetched. Object ids are listed per tile,
then features are fetched in chunks, so the service's record limit doesn't cut anything off.
Writes data/rrc_wells/wells_near_plumes.gpkg (EPSG:4326) with the download date.
Usage: python wells_near_plumes.py [--pad-deg 0.004]
"""
import argparse
import datetime as dt
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

P = Path(r"C:\mydrive\Graduate School\Courses\GEOG_392\projects")
LAYER = "https://gis.rrc.texas.gov/server/rest/services/rrc_public/RRC_Public_Viewer_Srvs/MapServer/1"
TILE = 0.02          # degrees, about 2 km


def call(url, **params):
    data = urllib.parse.urlencode({"f": "json", **params}).encode()
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": "geog392-research"})
            with urllib.request.urlopen(req, timeout=120) as r:
                out = json.loads(r.read())
            if "error" in out:
                raise RuntimeError(out["error"])
            return out
        except Exception:
            if attempt == 3:
                raise
            time.sleep(10 * (attempt + 1))


def main(a):
    R = P / "outputs" / "results" / "methane_three_sources"
    pl = pd.concat([pd.read_csv(R / f, usecols=["lon", "lat"]) for f in
                    ("plumes_carbon_1.csv", "plumes_emit_2.csv", "plumes_mapl_emit,_3.csv", "plumes_mapl_emit,_4.csv")])
    tiles = sorted(set(zip(np.floor(pl["lon"] / TILE).astype(int), np.floor(pl["lat"] / TILE).astype(int))))
    meta = call(LAYER)
    fields = [f["name"] for f in meta.get("fields", []) if f["type"] != "esriFieldTypeGeometry"]
    print(f"{len(pl):,} plumes in {len(tiles):,} tiles; layer '{meta.get('name')}', fields {fields[:12]}", flush=True)
    feats = {}
    for k, (tx, ty) in enumerate(tiles):
        box = f"{tx * TILE - a.pad_deg},{ty * TILE - a.pad_deg},{(tx + 1) * TILE + a.pad_deg},{(ty + 1) * TILE + a.pad_deg}"
        ids = call(f"{LAYER}/query", where="1=1", geometry=box, geometryType="esriGeometryEnvelope", inSR=4326,
                   spatialRel="esriSpatialRelIntersects", returnIdsOnly="true").get("objectIds") or []
        ids = [i for i in ids if i not in feats]
        for c in range(0, len(ids), 500):
            chunk = ids[c:c + 500]
            out = call(f"{LAYER}/query", objectIds=",".join(map(str, chunk)), outFields="*", outSR=4326, returnGeometry="true")
            for f in out.get("features", []):
                g = f.get("geometry") or {}
                if "x" in g:
                    feats[f["attributes"].get(meta.get("objectIdField", "OBJECTID"), len(feats))] = {**f["attributes"], "lon": g["x"], "lat": g["y"]}
        if k % 100 == 0:
            print(f"  tile {k:,}/{len(tiles):,}: {len(feats):,} wells", flush=True)
    w = pd.DataFrame(feats.values())
    out = P / "data" / "rrc_wells"
    out.mkdir(parents=True, exist_ok=True)
    g = gpd.GeoDataFrame(w, geometry=gpd.points_from_xy(w["lon"], w["lat"]), crs=4326)
    g["downloaded"] = dt.date.today().isoformat()
    g.to_file(out / "wells_near_plumes.gpkg", driver="GPKG")
    print(f"wrote {out / 'wells_near_plumes.gpkg'}: {len(g):,} wells")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pad-deg", type=float, default=0.004)
    main(ap.parse_args())
