"""Rebuild a sample's rings as ten equal 50 m bands out to 500 m, plus the 500-1,000 m comparison ring (plan v1.6).

Landon asked why the rings widened from 50 m to 250 m. The rings test of 2026-10-07 showed that ten 50 m bands cost the
same compute, place the edge of the corridor effect (it ends near 50 m), and give identical 0-50 and 50-100 m rings, so
the plan's main test is unchanged. The four rings of v1.5 can still be rebuilt from the bands (analysis/corridor.py
--pool). The bands are built and cleaned exactly as build_zones.py does (NADCON5 grids, flat ends, ground closer to any
pipeline than a band's inner edge removed, under 8,000 m2 dropped). The segments and their weights do not change.

Writes, in the sample folder: layer rings_b50 in sample.gpkg, cleaning_b50.csv, and ee_upload/<name>_rings.csv.

Usage: python sample_bands.py --sample <sample folder> --lines <statewide pipelines .gpkg> [--name sample_v1_b50]
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio
import shapely

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_zones  # noqa: E402


def main(a):
    seg = pyogrio.read_dataframe(a.sample / "sample.gpkg", layer="segments")
    print(f"{len(seg):,} sample segments; {len(build_zones.BANDS_50M)} bands each", flush=True)
    build_zones.RINGS = build_zones.BANDS_50M
    rings = build_zones.rings_for(seg)
    lines = build_zones.load_lines(a.lines)
    lines = lines[~lines["dup_geometry"]]
    print("projection:", build_zones.projection_note(), flush=True)
    rings, summary = build_zones.clean_rings(rings, lines, workers=a.workers)
    rings = rings.sort_values(["segment_id", "inner_m"], kind="stable")
    summary.to_csv(a.sample / "cleaning_b50.csv", index=False)
    print(summary.round(3).to_string(index=False))
    rings.to_file(a.sample / "sample.gpkg", layer="rings_b50", driver="GPKG")
    (a.sample / "ee_upload").mkdir(exist_ok=True)
    wkt = shapely.to_wkt(np.asarray(rings.to_crs(4326).geometry.array), rounding_precision=6)
    out = a.sample / "ee_upload" / f"{a.name}_rings.csv"
    pd.DataFrame({"zone_id": rings["zone_id"].values, "WKT": wkt}).to_csv(out, index=False)
    print(f"wrote {len(rings):,} rings for {rings['segment_id'].nunique():,} segments -> {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sample", type=Path, required=True)
    ap.add_argument("--lines", type=Path, required=True)
    ap.add_argument("--name", default="sample_v1_b50")
    ap.add_argument("--workers", type=int, default=12)
    main(ap.parse_args())
