"""Gap 1: does the corridor gap survive without man-made features next to the pipe?

Reads the man-made share of every zone (extract/man_made.py: NLCD 2021 impervious surface and its descriptor for roads,
developed land and buildings, and well pads and other energy sites; Dynamic World built-up probability) and the
per-segment, per-spring 0-50 m gap from the agent tables. A segment is clean when its 0-50 m band has no NLCD road,
developed or energy pixel, under 1% impervious surface and a Dynamic World built-up probability under 0.1. The gap is
the same estimator throughout: each segment's median over its springs, then the weighted median across segments with a
stratified bootstrap (corridor.py's design weights). It is reported for all segments, clean segments, and by the amount
of man-made cover in the band; and the same for the comparison ring, since man-made ground there would shrink the gap.

Writes outputs/results/man_made_check/SUMMARY.md and segments.csv.
Usage: python man_made_check.py [--index NDVI] [--boot 500]
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

P = Path(r"C:\mydrive\Graduate School\Courses\GEOG_392\projects")
MM = P / "outputs" / "geog392_zone_stats" / "sample_v1_b50_and_spills_v1_man_made.csv"


def wmedian(v, w):
    o = np.argsort(v)
    c = np.cumsum(w[o])
    return v[o][np.searchsorted(c, c[-1] / 2)]


def estimate(d: pd.DataFrame, rng, boot: int):
    v, w = d["gap"].to_numpy(), d["weight"].to_numpy()
    est = wmedian(v, w)
    groups = [g.index.to_numpy() for _, g in d.reset_index(drop=True).groupby("stratum")]
    vals = []
    for _ in range(boot):
        idx = np.concatenate([rng.choice(g, len(g)) for g in groups])
        vals.append(wmedian(v[idx], w[idx]))
    return est, np.percentile(vals, 2.5), np.percentile(vals, 97.5), len(d), w.sum()


def main(a):
    rng = np.random.default_rng(392)
    mm = pd.read_csv(MM)
    mm = mm[~mm["zone_id"].str.startswith("S")].copy()            # sample zones only (spill zones start with S)
    mm[["segment_id", "ring"]] = mm["zone_id"].str.rsplit("_r", n=1, expand=True)
    mm["man_made"] = mm[["road", "developed", "energy"]].sum(axis=1)
    band, ring = mm[mm["ring"] == "0-50"].set_index("segment_id"), mm[mm["ring"] == "500-1000"].set_index("segment_id")
    s = pd.read_parquet(P / "outputs" / "agent" / "segment_springs.parquet",
                        columns=["segment_id", "year", "ring", "index", "diff_same_lc", "stratum", "weight"])
    s = s[(s["index"] == a.index) & (s["ring"] == "0-50 m")].dropna(subset=["diff_same_lc"])
    seg = s.groupby("segment_id").agg(gap=("diff_same_lc", "median"), stratum=("stratum", "first"), weight=("weight", "first"))
    seg = seg.join(band[["man_made", "impervious_pct", "dw_built", "energy", "road", "lc_changed"]]).join(
        ring[["man_made", "impervious_pct"]].rename(columns=lambda c: "ring_" + c))
    seg["clean"] = (seg["man_made"] == 0) & (seg["impervious_pct"] < 1) & (seg["dw_built"] < 0.1)
    seg["clean_both"] = seg["clean"] & (seg["ring_man_made"] < 0.01)
    a.out.mkdir(parents=True, exist_ok=True)
    seg.to_csv(a.out / "segments.csv")
    rows = [("all segments", seg), ("clean 0-50 m band", seg[seg["clean"]]),
            ("clean band and clean comparison ring", seg[seg["clean_both"]]),
            ("band with any man-made cover", seg[~seg["clean"]])]
    share = pd.cut(seg["man_made"], [-1e-9, 0, 0.05, 0.2, 1], labels=["none", "up to 5%", "5-20%", "over 20%"])
    rows += [(f"man-made cover in the band: {k}", g) for k, g in seg.groupby(share, observed=True)]
    tot_w = seg["weight"].sum()
    lines = [f"# Does the corridor gap survive without man-made features? 0-50 m {a.index} ({pd.Timestamp.today():%Y-%m-%d})", "",
             "Man-made cover: NLCD 2021 roads, developed land, buildings, well pads and other energy sites, plus "
             "Dynamic World built-up. Same estimator for every row: each segment's median over its springs, then the "
             "weighted median with a stratified bootstrap.", "",
             "| Segments | Gap [95% CI] | Segments | Share of the weighted network |", "|---|---|---|---|"]
    for name, d in rows:
        if len(d) < 30:
            continue
        est, lo, hi, n, w = estimate(d, rng, a.boot)
        lines.append(f"| {name} | {est:+.4f} [{lo:+.4f}, {hi:+.4f}] | {n:,} | {w / tot_w:.0%} |")
    lines += ["", f"Well pads or other energy sites in the 0-50 m band: {(seg['energy'] > 0).mean():.0%} of sampled segments; "
              f"roads: {(seg['road'] > 0).mean():.0%}. NLCD land cover changed (2001-2021) somewhere in the band: "
              f"{(seg['lc_changed'] > 0).mean():.0%}.", "",
              "If the clean rows match the all-segments row, man-made features next to the pipe do not explain the gap. "
              "First results, not findings."]
    (a.out / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--index", default="NDVI")
    ap.add_argument("--boot", type=int, default=500)
    ap.add_argument("--out", type=Path, default=P / "outputs" / "results" / "man_made_check")
    main(ap.parse_args())
