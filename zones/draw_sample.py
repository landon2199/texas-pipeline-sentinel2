"""Draw the statewide sample of segments that Part 2 measures every spring (analysis plan v1.5, Section 4).

Earth Engine's free tier can't measure all ~440,000 segments for nine springs, so Part 2 measures a stratified random
sample, and every sampled segment carries a weight so statewide results stay unbiased:
  - population: every 1 km segment that has a clean comparison ring (build_zones.py), in every ecoregion;
  - strata: ecoregion x commodity group x diameter class;
  - allocation: in proportion to each stratum's size (segments, so pipe length), with at least --min-per-stratum
    segments from every stratum (all of them when it has fewer), so rare kinds of pipe are never left out;
  - lines mapped within 50 ft (the Railroad Commission's quality code E) are drawn at --e-boost times the rate of
    the others, because their rings sit where the pipe really is; within a stratum, each group is a simple random
    sample, so the weight (segments in the group / segments drawn) is exact.
The seed is fixed, so the same inputs always give the same sample.

Writes, in --out: sample_segments.csv (one row per sampled segment, with its stratum and weight), sample.gpkg (layers
segments and rings, for ArcGIS), ee_upload/<name>_rings.csv (zone_id and WKT for ee_upload.py) and SAMPLE.md.

Usage: python draw_sample.py --zones <statewide zones folder> --out <folder> [--size 3500] [--min-per-stratum 3]
                             [--e-boost 2] [--seed 392] [--name sample_v1]
"""
import argparse
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio
import shapely

COLS = ["segment_id", "line_uid", "has_comparison", "ecoregion_code", "ecoregion", "commodity_group", "commodity",
        "service", "diameter_in", "diameter_class", "status", "location_accuracy", "county_fips", "piece_m"]
E_LABEL = "Within 50 ft"


def md(df: pd.DataFrame) -> str:
    """A small Markdown table, without extra packages."""
    df = df.reset_index()
    rows = [list(map(str, df.columns)), ["---"] * len(df.columns)]
    rows += [[f"{v:,}" if isinstance(v, (int, np.integer)) else str(v) for v in r] for r in df.itertuples(index=False)]
    return "\n".join("| " + " | ".join(r) + " |" for r in rows)


def region_files(folder: Path):
    return sorted(p for p in folder.glob("[0-9]*_*.gpkg"))


def allocate(sizes: pd.Series, total: int, minimum: int) -> pd.Series:
    """Proportional allocation with a floor, scaled so the parts add up to `total` (never more than a stratum has)."""
    floor = np.minimum(sizes, minimum)
    if floor.sum() >= total:
        return floor
    lo, hi = 0.0, float(total) * 4
    for _ in range(100):
        s = (lo + hi) / 2
        n = np.maximum(floor, np.minimum(sizes, np.round(s * sizes / sizes.sum())))
        lo, hi = (s, hi) if n.sum() < total else (lo, s)
    return np.maximum(floor, np.minimum(sizes, np.round(hi * sizes / sizes.sum()))).astype(int)


def split(n: int, n_e: int, n_o: int, boost: float):
    """Share a stratum's n draws between its E lines and the rest, E counted `boost` times. When both groups exist and
    n >= 2, each gets at least one draw, so every segment has a chance of being drawn and the weights are unbiased."""
    if n_e == 0:
        return 0, min(n, n_o)
    if n_o == 0:
        return min(n, n_e), 0
    k_e = round(n * n_e * boost / (n_e * boost + n_o))
    k_e = min(max(k_e, 1), n_e, max(n - 1, 0))
    k_o = min(n - k_e, n_o)
    return min(n - k_o, n_e), k_o                     # if one group runs short, the other takes the rest


def main(a):
    files = region_files(a.zones)
    pop = []
    for f in files:
        seg = pyogrio.read_dataframe(f, layer="segments", read_geometry=False, columns=COLS)
        seg = seg[seg["has_comparison"].astype(bool)].copy()
        seg["region_file"] = f.name
        pop.append(seg)
    pop = pd.concat(pop, ignore_index=True)
    pop["e_line"] = pop["location_accuracy"] == E_LABEL
    pop["stratum"] = pop["ecoregion_code"].astype(str) + " | " + pop["commodity_group"] + " | " + pop["diameter_class"]
    pop["group"] = pop["stratum"] + " | " + np.where(pop["e_line"], "E", "other")

    # strata get their share of the sample with E lines counted e_boost times
    weight = pop["e_line"].map({True: a.e_boost, False: 1.0})
    n_h = allocate(weight.groupby(pop["stratum"]).sum(), a.size, a.min_per_stratum)
    n_h = np.minimum(n_h, pop.groupby("stratum").size()).astype(int)

    rng = np.random.default_rng(a.seed)
    picked = []
    for stratum, grp in pop.groupby("stratum", sort=True):
        n = int(n_h[stratum])
        e, other = grp[grp["e_line"]], grp[~grp["e_line"]]
        n_e, n_o = split(n, len(e), len(other), a.e_boost)
        for part, k in ((e, n_e), (other, n_o)):
            if k:
                take = part.iloc[np.sort(rng.choice(len(part), k, replace=False))].copy()
                take["group_size"], take["group_drawn"] = len(part), k
                take["weight"] = len(part) / k
                picked.append(take)
    sample = pd.concat(picked, ignore_index=True)

    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "ee_upload").mkdir(exist_ok=True)
    sample.to_csv(a.out / "sample_segments.csv", index=False)

    segs, rings = [], []
    for f, ids in sample.groupby("region_file")["segment_id"]:
        where = "segment_id IN (" + ",".join(f"'{i}'" for i in ids) + ")"
        segs.append(pyogrio.read_dataframe(a.zones / f, layer="segments", where=where))
        rings.append(pyogrio.read_dataframe(a.zones / f, layer="rings", where=where))
    segs, rings = pd.concat(segs, ignore_index=True), pd.concat(rings, ignore_index=True)
    segs = segs.merge(sample[["segment_id", "stratum", "e_line", "weight"]], on="segment_id")
    rings = rings.sort_values(["segment_id", "inner_m"], kind="stable")
    gpkg = a.out / "sample.gpkg"
    gpkg.unlink(missing_ok=True)
    segs.to_file(gpkg, layer="segments", driver="GPKG")
    rings.to_file(gpkg, layer="rings", driver="GPKG")
    wkt = shapely.to_wkt(np.asarray(rings.to_crs(4326).geometry.array), rounding_precision=6)
    pd.DataFrame({"zone_id": rings["zone_id"].values, "WKT": wkt}).to_csv(a.out / "ee_upload" / f"{a.name}_rings.csv", index=False)

    by = lambda c: sample.groupby(c).agg(segments=("segment_id", "size"), weighted=("weight", "sum")).round(0).astype(int)
    lines = [f"# Statewide sample `{a.name}`", "",
             f"Drawn {dt.date.today().isoformat()} by `zones/draw_sample.py` (seed {a.seed}) from the zones in `{a.zones.name}`.", "",
             f"- Population: {len(pop):,} segments with a clean comparison ring, in {pop['ecoregion'].nunique()} ecoregions.",
             f"- Sample: {len(sample):,} segments ({len(rings):,} rings) in {sample['stratum'].nunique()} strata "
             f"(ecoregion x commodity group x diameter class), at least {a.min_per_stratum} per stratum or all it has.",
             f"- Lines mapped within 50 ft: {int(sample['e_line'].sum()):,} sampled, drawn at {a.e_boost:g} times the rate of the others.",
             f"- Weights: each segment stands for `weight` segments of its group; they add up to {sample['weight'].sum():,.0f}.", "",
             "## By ecoregion", "", md(by("ecoregion")), "",
             "## By commodity group", "", md(by("commodity_group")), "",
             "## By diameter class", "", md(by("diameter_class")), "",
             "## By mapped location accuracy", "", md(by("location_accuracy")), ""]
    (a.out / "SAMPLE.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:9]))
    print(f"wrote {a.out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--zones", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--size", type=int, default=3500)
    ap.add_argument("--min-per-stratum", type=int, default=3)
    ap.add_argument("--e-boost", type=float, default=2.0)
    ap.add_argument("--seed", type=int, default=392)
    ap.add_argument("--name", default="sample_v1")
    main(ap.parse_args())
