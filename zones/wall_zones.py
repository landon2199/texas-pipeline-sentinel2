"""Zones for the wall-to-wall map: the 0-50 m band and the comparison ring of every statewide segment, for upload.

Reads each region's upload table (ee_upload/<region>_rings.csv, written by build_zones.py: zone_id and WKT) and keeps
only the 0-50 m band and the 500-1,000 m comparison ring, which is what extract/run_wall_to_wall.py measures. Segments
without a clean comparison ring keep only their band here; the coverage supplement (draw_supplement.py) samples them.

Usage: python wall_zones.py --zones outputs/zones/statewide [--out outputs/zones/statewide/ee_upload_wall]
"""
import argparse
from pathlib import Path

import pandas as pd

KEEP = ("_r0-50", "_r500-1000")


def main(a):
    a.out.mkdir(parents=True, exist_ok=True)
    total = 0
    for f in sorted((a.zones / "ee_upload").glob("[0-9][0-9]_*_rings.csv")):
        out = a.out / f.name.replace("_rings.csv", "_wall.csv")
        n = 0
        with out.open("w", encoding="utf-8", newline="") as fh:
            for i, chunk in enumerate(pd.read_csv(f, chunksize=200_000)):
                keep = chunk[chunk["zone_id"].str.endswith(KEEP)]
                keep.to_csv(fh, index=False, header=(i == 0))
                n += len(keep)
        total += n
        print(f"{out.name}: {n:,} zones ({out.stat().st_size / 1e6:,.0f} MB)", flush=True)
    print(f"total: {total:,} zones")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--zones", type=Path, required=True)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    a.out = a.out or a.zones / "ee_upload_wall"
    main(a)
