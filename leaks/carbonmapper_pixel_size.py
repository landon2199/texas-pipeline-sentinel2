"""Plan D32: each Carbon Mapper plume's real pixel size, read from its own image file.

The catalog's 'gsd' field is filled only for Tanager-1, but every plume links to its concentration GeoTIFF (con_tif),
whose header holds the pixel size of that flight or overpass (airborne AVIRIS-3 about 2.6 m, AVIRIS-NG and GAO about
5 m, Tanager-1 30 m, EMIT about 57 m; airborne values change with flight altitude). Only the header is read (HTTP range
requests through GDAL), several at a time. Writes data/carbonmapper/plume_pixel_size.csv.
Usage: python carbonmapper_pixel_size.py [--workers 8]
"""
import argparse
import json
import math
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import rasterio

P = Path(r"C:\mydrive\Graduate School\Courses\GEOG_392\projects")
API = "https://api.carbonmapper.org/api/v1/catalog/plumes/annotated"


def catalog() -> pd.DataFrame:
    rows, offset = [], 0
    while True:
        q = urllib.parse.urlencode([("bbox", -106.7), ("bbox", 25.8), ("bbox", -93.5), ("bbox", 36.6),
                                    ("plume_gas", "CH4"), ("limit", 1000), ("offset", offset)])
        with urllib.request.urlopen(f"{API}?{q}", timeout=120) as r:
            items = json.load(r)["items"]
        rows += [{"plume_id": it["plume_id"], "instrument": it.get("instrument"), "gsd_catalog_m": it.get("gsd"),
                  "scene_id": it.get("scene_id"), "con_tif": it.get("con_tif") or it.get("plume_tif")} for it in items]
        if len(items) < 1000:
            return pd.DataFrame(rows).drop_duplicates("plume_id")
        offset += 1000
        time.sleep(0.5)


def pixel_m(url):
    if not url:
        return None
    for attempt in range(3):
        try:
            with rasterio.Env(GDAL_HTTP_TIMEOUT="60", GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
                with rasterio.open(f"/vsicurl/{url}") as src:
                    rx, ry = src.res
                    if src.crs and src.crs.is_geographic:
                        lat = (src.bounds.top + src.bounds.bottom) / 2
                        rx, ry = rx * 111320 * math.cos(math.radians(lat)), ry * 110540
                    return round((rx + ry) / 2, 2)
        except Exception:
            time.sleep(5 * (attempt + 1))
    return None


def main(a):
    c = catalog()
    texas = pd.read_csv(P / "outputs" / "results" / "methane_plumes" / "plumes.csv", usecols=["plume_id"])
    c = c[c["plume_id"].isin(texas["plume_id"])]
    print(f"{len(c):,} Texas plumes; reading pixel sizes...", flush=True)
    with ThreadPoolExecutor(a.workers) as ex:
        c["pixel_m"] = list(ex.map(pixel_m, c["con_tif"]))
    out = P / "data" / "carbonmapper" / "plume_pixel_size.csv"
    c.drop(columns="con_tif").to_csv(out, index=False)
    print(f"wrote {out}; missing {c['pixel_m'].isna().sum()}")
    print(c.groupby("instrument")["pixel_m"].describe()[["count", "min", "50%", "max"]].round(1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--workers", type=int, default=8)
    main(ap.parse_args())
