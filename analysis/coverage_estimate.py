"""Plan v1.9, D22: the corridor gap for all land pipe, per km, from the main sample and the coverage supplement.

Frames and weights (each frame's pieces stand for its share of the pipe):
  - main: the 3,499 one-km segments with a clean comparison ring (296,191 km), weight per segment = per km;
  - dense: 1 km segments without one (88,868 km), comparison ring as drawn, so conservative;
  - short: pieces of 100 m to 1 km (181,260 km), weight per piece times its length in km.
For each piece, the median of its springs' 0-50 m gap (corridor.py's segment_spring tables), then the weighted median
per frame and for all frames together, with a bootstrap that resamples within each frame's strata.
Writes outputs/results/coverage_estimate/SUMMARY.md and estimates.csv.
Usage: python coverage_estimate.py [--boot 500]
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

P = Path(r"C:\mydrive\Graduate School\Courses\GEOG_392\projects")
R = P / "outputs" / "results"
COLS = ["segment_id", "year", "ring", "index", "diff_all", "diff_same_lc", "stratum", "weight"]


def wmedian(v, w):
    o = np.argsort(v)
    c = np.cumsum(w[o])
    return v[o][np.searchsorted(c, c[-1] / 2)]


def per_piece(path: Path, indices) -> pd.DataFrame:
    parts = []
    for chunk in pd.read_csv(path, usecols=COLS, chunksize=500_000):
        parts.append(chunk[(chunk["ring"] == "0-50 m") & chunk["index"].isin(indices)])
    d = pd.concat(parts)
    return d.groupby(["segment_id", "index", "stratum", "weight"], as_index=False)[["diff_all", "diff_same_lc"]].median()


def main(a):
    rng = np.random.default_rng(392)
    main_ = per_piece(R / "corridor_sample_v1_9springs_pooled" / "segment_spring.csv", a.indices).assign(frame="main", km=1.0)
    supp = per_piece(R / "corridor_supplement_9springs" / "segment_spring.csv", a.indices)
    info = pd.read_csv(P / "outputs" / "zones" / "sample_v2_supplement" / "sample_segments.csv", usecols=["segment_id", "frame", "piece_m"])
    supp = supp.merge(info, on="segment_id", how="left").assign(km=lambda x: x["piece_m"] / 1000).drop(columns="piece_m")
    d = pd.concat([main_, supp], ignore_index=True)
    d["w_km"] = d["weight"] * d["km"]
    d["boot_stratum"] = d["frame"] + "|" + d["stratum"].astype(str)
    rows = []
    for idx in a.indices:
        for frame in ["main", "dense", "short", "all land pipe"]:
            for measure in ("diff_same_lc", "diff_all"):
                p = d[(d["index"] == idx) & ((d["frame"] == frame) | (frame == "all land pipe"))].dropna(subset=[measure])
                v, w = p[measure].to_numpy(float), p["w_km"].to_numpy(float)
                groups = [g.to_numpy() for _, g in p.reset_index(drop=True).groupby("boot_stratum").groups.items()]
                boot = [wmedian(v[i], w[i]) for i in (np.concatenate([rng.choice(g, len(g)) for g in groups]) for _ in range(a.boot))]
                rows.append({"index": idx, "frame": frame, "measure": "same land cover" if measure == "diff_same_lc" else "all ground",
                             "pieces": len(p), "km_represented": w.sum(), "gap": wmedian(v, w),
                             "lo95": np.percentile(boot, 2.5), "hi95": np.percentile(boot, 97.5)})
    t = pd.DataFrame(rows)
    out = R / "coverage_estimate"
    out.mkdir(parents=True, exist_ok=True)
    t.to_csv(out / "estimates.csv", index=False)
    names = {"main": "1 km segments with a clean comparison ring", "dense": "1 km segments in dense areas (ring as drawn)",
             "short": "pieces of 100 m to 1 km", "all land pipe": "all land pipe 100 m or longer"}
    lines = [f"# The corridor gap for all land pipe, per km (plan v1.9, D22; {pd.Timestamp.today():%Y-%m-%d})", "",
             "0-50 m band minus its comparison ring, same land cover, each piece's median over the nine springs, weighted by "
             "the pipe it stands for (km), with a bootstrap within each frame's strata.", "",
             "| Index | Pipe | Pieces measured | km represented | Gap [95% CI] |", "|---|---|---|---|---|"]
    for r in t[t["measure"] == "same land cover"].itertuples():
        lines.append(f"| {r.index} | {names[r.frame]} | {r.pieces:,} | {r.km_represented:,.0f} | {r.gap:+.4f} [{r.lo95:+.4f}, {r.hi95:+.4f}] |")
    lines += ["", "The dense-area segments compare with land beside other corridors, which is less green, so their gap and "
              "the combined gap are conservative (pulled toward zero). km represented are estimates from the sample "
              "weights. First results, not findings."]
    (out / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--indices", nargs="+", default=["NDVI", "NDRE", "NDMI"])
    ap.add_argument("--boot", type=int, default=500)
    main(ap.parse_args())
