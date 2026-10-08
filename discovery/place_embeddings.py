"""Discovery, places: join Earth Engine's Satellite Embedding exports into one table the discovery server searches.

Reads embeddings_<year>_<which>.csv from outputs/geog392_zone_stats (discovery/embeddings.py) and writes
outputs/discovery/place_embeddings.parquet, one row per place and year:
  kind "segment band"        a sampled segment's 0-50 m band            (place_id = segment_id)
  kind "segment comparison"  its 500-1,000 m comparison ring            (place_id = segment_id)
  kind "spill site"          a spill's 50 m circle                      (place_id = site_id, with spill_id)
  kind "comparison spot"     a same-line or regional spot's 50 m circle (place_id = site_id, with spill_id)
A 50 m circle is its 0-25 and 25-50 m rings joined by pixel count. The embedding is the zone's mean of the 64 values;
the server normalizes it before comparing places.

Usage: python place_embeddings.py
"""
import re
from pathlib import Path

import numpy as np
import pandas as pd

P = Path(r"C:\mydrive\Graduate School\Courses\GEOG_392\projects")
STATS = P / "outputs" / "geog392_zone_stats"
OUT = P / "outputs" / "discovery" / "place_embeddings.parquet"
BANDS = [f"A{k:02d}" for k in range(64)]


def main():
    seg = pd.read_parquet(P / "outputs" / "agent" / "segments.parquet")[["segment_id", "ecoregion", "commodity"]]
    sites = pd.read_parquet(P / "outputs" / "agent" / "spill_sites.parquet")[["site_id", "spill_id", "site", "site_ecoregion"]]
    parts = []
    for f in sorted(STATS.glob("embeddings_*_*.csv")):
        year, which = re.fullmatch(r"embeddings_(\d{4})_(\w+)\.csv", f.name).groups()
        d = pd.read_csv(f).dropna(subset=BANDS)
        d = d[d["pixels"] > 0]
        if which in ("sample_row", "sample_comparison"):
            d["place_id"] = d["zone_id"].str.rsplit("_r", n=1).str[0]
            d = d.merge(seg, left_on="place_id", right_on="segment_id", how="left").drop(columns="segment_id")
            d["kind"], d["spill_id"] = ("segment band" if which == "sample_row" else "segment comparison"), None
        else:                                   # join each site's two rings into its 50 m circle, by pixel count
            d["place_id"] = d["zone_id"].str.rsplit("_r", n=1).str[0]
            w = d[BANDS].mul(d["pixels"], axis=0)
            g = pd.concat([w, d[["pixels"]], d[["place_id"]]], axis=1).groupby("place_id")
            d = (g[BANDS].sum().div(g["pixels"].sum(), axis=0)).assign(pixels=g["pixels"].sum()).reset_index()
            d = d.merge(sites, left_on="place_id", right_on="site_id", how="left").drop(columns="site_id")
            d["kind"] = np.where(d["site"] == "spill", "spill site", "comparison spot")
            d = d.rename(columns={"site_ecoregion": "ecoregion"}).drop(columns="site")
        d["year"] = int(year)
        d["embedding"] = d[BANDS].to_numpy(dtype="float32").tolist()
        parts.append(d[["place_id", "kind", "year", "spill_id", "ecoregion"] + (["commodity"] if "commodity" in d else [])
                       + ["pixels", "embedding"]])
        print(f"  {f.name}: {len(d):,} places")
    if not parts:
        raise SystemExit(f"no embedding exports in {STATS} yet")
    out = pd.concat(parts, ignore_index=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT, index=False)
    print(f"wrote {OUT}: {len(out):,} rows, {out['year'].nunique()} years ({', '.join(f'{k} {v:,}' for k, v in out['kind'].value_counts().items())})")


if __name__ == "__main__":
    main()
