"""Part 3, plan 9: where does the corridor gap cluster, does it hold every spring, and is it changing? 2018-2026.

For every sampled segment and spring, the 0-50 m gap (ring minus its comparison ring, like-for-like land cover, from
the agent tables) goes to ArcGIS Pro's Hot Spot Analysis (Getis-Ord Gi*, each segment's nearest neighbors, false
discovery rate correction), once per spring (analysis/arcgis_gi_by_spring.py). Then, per segment:
  - how many of the nine springs it is a significant cold spot (95%) and how many a hot spot. Negative gaps mean
    less green next to the pipe, so cold spots are where pipelines thin the vegetation most;
  - its 2018-2026 trend: Mann-Kendall (Kendall's tau of the gap on the year) with the Theil-Sen slope, and the
    Benjamini-Hochberg correction across segments.
The sample is stratified: the map shows where effects cluster among sampled segments; the statewide trend line uses
the sample weights.

Writes, in --out: input.gpkg, gi_by_spring.gdb and .csv, segments.csv, figure_hot_spots_<index>.png and SUMMARY.md.
Usage: python hot_spots_by_spring.py [--index NDVI] [--neighbors 8] [--out outputs/results/hot_spots_by_spring]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.config import AGENT, ARCPY_PYTHON, CORRIDOR, ECOREGIONS, R  # noqa: E402

HERE = Path(__file__).resolve().parent
CLASSES = [("cold spot in 7-9 springs", "#08306b"), ("cold spot in 4-6", "#2171b5"), ("cold spot in 1-3", "#9ecae1"),
           ("hot spot in 1-3", "#fcbba1"), ("hot spot in 4-6", "#ef3b2c"), ("hot spot in 7-9 springs", "#67000d")]


def build_input(index: str, out: Path):
    s = pd.read_parquet(AGENT / "segment_springs.parquet",
                        columns=["segment_id", "year", "ring", "index", "diff_same_lc", "weight"])
    s = s[(s["index"] == index) & (s["ring"] == "0-50 m")].dropna(subset=["diff_same_lc"]).rename(columns={"diff_same_lc": "gap"})
    pts = gpd.read_file(AGENT / "segment_points.gpkg", columns=["segment_id", "ecoregion", "diameter_class"])
    d = pts.merge(s[["segment_id", "year", "gap"]], on="segment_id")
    path = out / "input.gpkg"
    d.to_file(path, layer="segment_springs", driver="GPKG")
    print(f"input: {d['segment_id'].nunique():,} segments, {len(d):,} segment-springs")
    return path, s, pts


def classify(n_cold: int, n_hot: int) -> str:
    if n_cold == 0 and n_hot == 0:
        return "never"
    kind, n = ("cold", n_cold) if n_cold >= n_hot else ("hot", n_hot)
    return f"{kind} spot in " + ("7-9 springs" if n >= 7 else "4-6" if n >= 4 else "1-3")


def trends(s: pd.DataFrame) -> pd.DataFrame:
    out = []
    for sid, g in s.groupby("segment_id"):
        if g["year"].nunique() < 6:
            continue
        tau, p = stats.kendalltau(g["year"], g["gap"])
        out.append({"segment_id": sid, "tau": tau, "p": p, "slope_per_year": stats.theilslopes(g["gap"], g["year"])[0]})
    t = pd.DataFrame(out)
    t["p_fdr"] = stats.false_discovery_control(t["p"].fillna(1))
    return t


def figure(res: gpd.GeoDataFrame, index: str, path: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    eco = gpd.read_file(ECOREGIONS).to_crs(res.crs)
    fig, ax = plt.subplots(figsize=(6.5, 6.2), dpi=200)
    eco.boundary.plot(ax=ax, color="#9a9a9a", linewidth=0.4)
    never = res[res["class"] == "never"]
    never.plot(ax=ax, color="#dedede", markersize=2, label=f"never a hot or cold spot ({len(never):,})")
    for name, color in CLASSES:
        g = res[res["class"] == name]
        if len(g):
            g.plot(ax=ax, color=color, markersize=6 if "7-9" in name or "4-6" in name else 3, label=f"{name} ({len(g):,})")
    ax.set_axis_off()
    ax.set_title(f"Where the 0-50 m {index} gap clusters, springs 2018-2026 (Gi*, ArcGIS Pro)\n"
                 "cold spot = the strip next to the pipe is less green than nearby land", fontsize=9, loc="left")
    ax.legend(frameon=False, fontsize=6.5, loc="lower left", markerscale=1.6)
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)


def main(a):
    a.out.mkdir(parents=True, exist_ok=True)
    src, s, pts = build_input(a.index, a.out)
    run = subprocess.run([str(ARCPY_PYTHON), str(HERE / "arcgis_gi_by_spring.py"), str(src), "segment_springs", "gap",
                          str(a.out), str(a.neighbors)], capture_output=True, text=True, timeout=3600)
    last = [l for l in run.stdout.strip().splitlines() if l.startswith("{")]
    if run.returncode or not last:
        raise SystemExit(f"ArcGIS step failed:\n{run.stdout[-3000:]}\n{run.stderr[-3000:]}")
    info = json.loads(last[-1])
    gi = pd.read_csv(a.out / "gi_by_spring.csv")
    per = gi.groupby("segment_id").agg(cold=("gi_bin", lambda b: int((b <= -2).sum())), hot=("gi_bin", lambda b: int((b >= 2).sum())))
    per["class"] = [classify(c, h) for c, h in zip(per["cold"], per["hot"])]
    t = trends(s)
    seg = per.join(t.set_index("segment_id")).reset_index()
    seg.to_csv(a.out / "segments.csv", index=False)
    res = pts.merge(seg, on="segment_id")
    figure(res, a.index, a.out / f"figure_hot_spots_{a.index}.png")

    # the statewide trend uses the headline estimate (corridor.py's weighted median for each spring), not a mean
    c = pd.read_csv(a.corridor / "statewide.csv")
    c = c[(c["scope"] == "statewide") & (c["ring"] == "0-50 m") & (c["index"] == a.index) &
          (c["measure"] == "same land cover") & c["springs"].astype(str).str.fullmatch(r"\d{4}")]
    yearly = c.set_index(c["springs"].astype(int))["weighted_median"].sort_index()
    tau, p = stats.kendalltau(yearly.index, yearly.values)
    slope = stats.theilslopes(yearly.values, yearly.index)[0]
    down = int(((seg["p_fdr"] < 0.05) & (seg["tau"] < 0)).sum())
    up = int(((seg["p_fdr"] < 0.05) & (seg["tau"] > 0)).sum())
    counts = seg["class"].value_counts()
    eco = res.assign(strong_cold=res["class"].isin(["cold spot in 7-9 springs", "cold spot in 4-6"]),
                     strong_hot=res["class"].isin(["hot spot in 7-9 springs", "hot spot in 4-6"]))
    by_eco = eco.groupby("ecoregion").agg(segments=("segment_id", "size"), cold=("strong_cold", "sum"), hot=("strong_hot", "sum"))
    by_eco = by_eco.sort_values("cold", ascending=False)
    lines = [f"# Hot spots of the 0-50 m {a.index} gap, spring by spring, 2018-2026", "",
             f"{len(seg):,} sampled segments; Gi* in each of {len(info['years'])} springs with {info['neighbors']} "
             "nearest neighbors and the false discovery rate correction, in ArcGIS Pro. A segment counts as a cold "
             "(hot) spot in a spring at 95% or more.", "",
             "| Class | Segments |", "|---|---|"] + [f"| {k} | {counts.get(k, 0):,} |" for k, _ in CLASSES] + \
            [f"| never | {counts.get('never', 0):,} |", "",
             "| Ecoregion | Segments | Cold spot in 4+ springs | Hot spot in 4+ springs |", "|---|---|---|---|"] + \
            [f"| {e} | {r.segments:,} | {r.cold:,} ({r.cold / r.segments:.0%}) | {r.hot:,} |" for e, r in by_eco.iterrows()] + \
            ["", "**Trend, 2018-2026.** The statewide gap by spring (weighted median, as in the corridor results): " +
             ", ".join(f"{y} {v:+.4f}" for y, v in yearly.items()) +
             f". Mann-Kendall tau {tau:+.2f} (p = {p:.2f}), Theil-Sen slope {slope:+.5f} a year.",
             f"Segments with a significant trend after the Benjamini-Hochberg correction: {down:,} toward less green next "
             f"to the pipe, {up:,} toward more, of {len(seg):,}.",
             "", "Emerging Hot Spot Analysis would be the usual tool, but its space-time cube needs at least 10 time "
             "steps and there are nine springs. First results, not findings."]
    (a.out / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--index", default="NDVI")
    ap.add_argument("--neighbors", type=int, default=8)
    ap.add_argument("--corridor", type=Path, default=CORRIDOR,
                    help="corridor results folder, for the statewide gap of each spring")
    ap.add_argument("--out", type=Path, default=R / "hot_spots_by_spring")
    main(ap.parse_args())
