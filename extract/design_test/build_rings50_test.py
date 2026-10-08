"""Rings test (2026-10-07): ten equal 50 m bands out to 500 m, plus the 500-1,000 m comparison ring, on 500 segments.

Landon asked why the rings widen from 50 m to 250 m ("how can I go from 50 to 500 and call it even"). Equal bands give
a sharper distance profile, and the current four rings can be rebuilt from them by pooling means with pixel counts.
This draws 500 random segments from the statewide sample (seed 392), builds and cleans the new bands with exactly the
same rules as zones/build_zones.py (NADCON5 grids, flat ends, ground closer to any pipeline than a band's inner edge
removed, under 8,000 m2 dropped), and writes the upload CSV for zones/ee_upload.py.

Usage: python build_rings50_test.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio
import shapely

P = Path(r"C:\mydrive\Graduate School\Courses\GEOG_392\projects")
sys.path.insert(0, str(P / "code (do not edit)" / "zones"))
import build_zones  # noqa: E402

BANDS = [(i, i + 50) for i in range(0, 500, 50)] + [(500, 1000)]
OUT = P / "outputs" / "tests" / "rings50_test_2026-10-07"
N = 500

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    sample = pd.read_csv(P / "outputs" / "zones" / "sample_v1" / "sample_segments.csv")
    pick = sample.sample(n=N, random_state=392)
    pick.to_csv(OUT / "test_segments.csv", index=False)
    where = "segment_id IN (" + ",".join(f"'{i}'" for i in pick["segment_id"]) + ")"
    seg = pyogrio.read_dataframe(P / "outputs" / "zones" / "sample_v1" / "sample.gpkg", layer="segments", where=where)
    print(f"{len(seg)} segments; building {len(BANDS)} bands each", flush=True)

    build_zones.RINGS = BANDS                          # same builder, new bands (the last is still the comparison ring)
    rings = build_zones.rings_for(seg)
    lines = build_zones.load_lines(P / "data" / "statewide" / "pipelines_texas_rrc_20261006.gpkg")
    lines = lines[~lines["dup_geometry"]]
    print("projection:", build_zones.projection_note(), flush=True)
    rings, summary = build_zones.clean_rings(rings, lines, workers=12)
    rings = rings.sort_values(["segment_id", "inner_m"], kind="stable")
    summary.to_csv(OUT / "cleaning.csv", index=False)
    print(summary.round(3).to_string(index=False))

    rings.to_file(OUT / "rings50_test.gpkg", layer="rings", driver="GPKG")
    wkt = shapely.to_wkt(np.asarray(rings.to_crs(4326).geometry.array), rounding_precision=6)
    pd.DataFrame({"zone_id": rings["zone_id"].values, "WKT": wkt}).to_csv(OUT / "rings50_test_upload.csv", index=False)
    print(f"wrote {len(rings):,} rings for {rings['segment_id'].nunique()} segments -> {OUT}")
