"""Coverage supplement (plan v1.9): bring the rest of the land pipe into the statewide estimate.

The main sample (draw_sample.py) represents the 296,191 one-km segments with a clean comparison ring, 50.5% of the pipe.
Two more frames are sampled here, each a stratified random sample (ecoregion x commodity group x diameter class,
in proportion to each stratum's pipe length, at least --min-per-stratum per stratum or all of a smaller one, seed 392),
and measured exactly like the main sample (ten 50 m bands and the 500-1,000 m comparison ring, cleaned the same way):
  - dense: 1 km segments whose comparison ring did not survive the cleaning, because other pipelines lie within 500 m
    of most of it (15.2% of the pipe). Their comparison ring is kept as drawn and flagged: land beside other corridors
    is less green, so their gap is conservative (pulled toward zero);
  - short: pieces from 100 m to 1 km long (32.9% of the pipe, 85% natural gas). A cleaned comparison ring is used when
    at least 8,000 m2 of it survives, otherwise the ring as drawn, flagged.
Weights are per piece (frame pieces in the stratum / pieces drawn); estimates weight each piece by its length too, so
results stay per km of pipe. With the main sample, the estimate then covers all land pipe except pieces under 100 m and
lines offshore or outside the ecoregions, which the coverage table counts.

Writes, in --out: supplement.gpkg (layers segments and rings_b50), sample_segments.csv, ee_upload/<name>_rings.csv and
SAMPLE.md.
Usage: python draw_supplement.py --zones outputs/zones/statewide --lines data/statewide/pipelines_texas_rrc_20261006.gpkg
                                 --out outputs/zones/sample_v2_supplement [--dense 1000] [--short 1500]
"""
import argparse
import datetime as dt
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import shapely

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_zones  # noqa: E402

COLS = ["segment_id", "line_uid", "has_zones", "has_comparison", "ecoregion_code", "ecoregion", "commodity_group",
        "commodity", "service", "diameter_in", "diameter_class", "status", "location_accuracy", "county_fips", "piece_m",
        "dup_geometry"]


def frames(folder: Path):
    dense, short = [], []
    for f in sorted(folder.glob("[0-9][0-9]_*.gpkg")):
        s = pyogrio.read_dataframe(f, layer="segments", columns=COLS)
        s = s[s["dup_geometry"] != True]                              # noqa: E712 (duplicates are measured once, as the other line)
        dense.append(s[s["has_zones"] & ~s["has_comparison"].fillna(False).astype(bool)])
        short.append(s[~s["has_zones"] & s["piece_m"].between(100, 1000, inclusive="left")])
        print(f"  {f.name}: {len(dense[-1]):,} dense segments, {len(short[-1]):,} short pieces", flush=True)
    return pd.concat(dense, ignore_index=True), pd.concat(short, ignore_index=True)


def draw(frame: gpd.GeoDataFrame, size: int, min_per: int, rng) -> gpd.GeoDataFrame:
    frame = frame.assign(stratum=frame["ecoregion_code"].astype(str) + "|" + frame["commodity_group"].astype(str) + "|" +
                         frame["diameter_class"].astype(str))
    km = frame.groupby("stratum")["piece_m"].sum()
    alloc = np.maximum(np.round(km / km.sum() * size), min_per).astype(int)
    out = []
    for st, n in alloc.items():
        g = frame[frame["stratum"] == st]
        take = g.iloc[rng.permutation(len(g))[:min(n, len(g))]].copy()
        take["weight"] = len(g) / len(take)
        out.append(take)
    return gpd.GeoDataFrame(pd.concat(out, ignore_index=True), geometry="geometry", crs=frame.crs)


def main(a):
    rng = np.random.default_rng(a.seed)
    dense, short = frames(a.zones)
    print(f"frames: {len(dense):,} dense segments ({dense['piece_m'].sum() / 1000:,.0f} km), "
          f"{len(short):,} short pieces ({short['piece_m'].sum() / 1000:,.0f} km)", flush=True)
    sd = draw(dense, a.dense, a.min_per_stratum, rng).assign(frame="dense")
    ss = draw(short, a.short, a.min_per_stratum, rng).assign(frame="short")
    seg = gpd.GeoDataFrame(pd.concat([sd, ss], ignore_index=True), geometry="geometry", crs=sd.crs)
    build_zones.RINGS = build_zones.BANDS_50M
    drawn = build_zones.rings_for(seg)
    lines = build_zones.load_lines(a.lines)
    lines = lines[~lines["dup_geometry"]]
    cleaned, summary = build_zones.clean_rings(drawn, lines, workers=a.workers)
    # a comparison ring that the cleaning removed comes back as drawn, flagged
    have = set(cleaned.loc[cleaned["comparison"], "segment_id"])
    back = drawn[drawn["comparison"] & ~drawn["segment_id"].isin(have)].copy()
    back["full_area_m2"], back["kept_share"] = back["area_m2"], 1.0
    cleaned["comparison_clean"] = True
    back["comparison_clean"] = False
    rings = gpd.GeoDataFrame(pd.concat([cleaned, back], ignore_index=True), geometry="geometry", crs=drawn.crs)
    rings = rings.sort_values(["segment_id", "inner_m"], kind="stable")
    seg["comparison_clean"] = seg["segment_id"].isin(have)
    a.out.mkdir(parents=True, exist_ok=True)
    seg.to_file(a.out / "supplement.gpkg", layer="segments", driver="GPKG")
    rings.to_file(a.out / "supplement.gpkg", layer="rings_b50", driver="GPKG")
    seg.drop(columns="geometry").to_csv(a.out / "sample_segments.csv", index=False)
    (a.out / "ee_upload").mkdir(exist_ok=True)
    wkt = shapely.to_wkt(np.asarray(rings.to_crs(4326).geometry.array), rounding_precision=6)
    pd.DataFrame({"zone_id": rings["zone_id"].values, "WKT": wkt}).to_csv(a.out / "ee_upload" / f"{a.name}_rings.csv", index=False)
    lines_md = [f"# Coverage supplement ({dt.date.today()}), seed {a.seed}", "",
                "| Frame | Pieces in the frame | km in the frame | Drawn | Strata | Comparison ring kept as drawn |",
                "|---|---|---|---|---|---|"]
    for name, fr, s in [("dense (no clean comparison ring)", dense, sd), ("short (100 m to 1 km)", short, ss)]:
        flagged = int((~seg.loc[seg["frame"] == s["frame"].iat[0], "comparison_clean"]).sum())
        lines_md.append(f"| {name} | {len(fr):,} | {fr['piece_m'].sum() / 1000:,.0f} | {len(s):,} | {s['stratum'].nunique()} | {flagged:,} |")
    lines_md += ["", f"{len(rings):,} zones written for Earth Engine. Weights are per piece; weight estimates by piece length "
                 "so they stay per km of pipe.", "", "Cleaning summary:", "", summary.round(3).to_string(index=False)]
    (a.out / "SAMPLE.md").write_text("\n".join(lines_md) + "\n", encoding="utf-8")
    print("\n".join(lines_md))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--zones", type=Path, required=True)
    ap.add_argument("--lines", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--dense", type=int, default=1000)
    ap.add_argument("--short", type=int, default=1500)
    ap.add_argument("--min-per-stratum", type=int, default=2)
    ap.add_argument("--seed", type=int, default=392)
    ap.add_argument("--name", default="sample_v2_supp")
    ap.add_argument("--workers", type=int, default=12)
    main(ap.parse_args())
