"""Gaps 10 and 11: how sure are the spill results? Clustering, several indices, and the smallest effect we could see.

From each spill's E1 (analysis/spills.py, effects.csv), across spills only:
  - the mean E1 with the plain bootstrap over spills and with a region-block bootstrap that resamples whole ecoregions,
    since spills cluster (the Permian) and nearby spills may share weather and land;
  - the Wilcoxon p-values of the four indices with the Holm correction for testing four indices at once;
  - the minimum detectable effect: the smallest mean E1 a paired test of this many spills would find 80% of the time at
    alpha 0.05 (two-sided), from the spread of the effects.
Writes outputs/results/spill_robustness/SUMMARY.md.
Usage: python spill_robustness.py [--folder spills_9springs]
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

P = Path(r"C:\mydrive\Graduate School\Courses\GEOG_392\projects")
INDICES = ["NDVI", "NDRE", "NDMI", "BSI"]


def holm(p: np.ndarray) -> np.ndarray:
    order = np.argsort(p)
    adj = np.empty_like(p)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, (len(p) - rank) * p[i])
        adj[i] = min(running, 1.0)
    return adj


def main(a):
    rng = np.random.default_rng(392)
    e = pd.read_csv(P / "outputs" / "results" / a.folder / "effects.csv").dropna(subset=["E1"])
    rows = []
    for i in INDICES:
        d = e[e["index"] == i]
        x = d["E1"].to_numpy()
        plain = x[rng.integers(0, len(x), (4000, len(x)))].mean(axis=1)
        groups = [g["E1"].to_numpy() for _, g in d.groupby("ecoregion")]
        block = [np.concatenate([groups[j] for j in rng.integers(0, len(groups), len(groups))]).mean() for _ in range(4000)]
        sd = x.std(ddof=1)
        mde = (stats.norm.ppf(0.975) + stats.norm.ppf(0.8)) * sd / np.sqrt(len(x))
        rows.append({"index": i, "n": len(x), "regions": len(groups), "mean": x.mean(),
                     "plain_lo": np.percentile(plain, 2.5), "plain_hi": np.percentile(plain, 97.5),
                     "block_lo": np.percentile(block, 2.5), "block_hi": np.percentile(block, 97.5),
                     "p": stats.wilcoxon(x).pvalue, "mde": mde})
    t = pd.DataFrame(rows)
    t["p_holm"] = holm(t["p"].to_numpy())
    lines = [f"# Spill results: clustering, several indices, detectable size ({a.folder}, {pd.Timestamp.today():%Y-%m-%d})", "",
             "Across spills only. The region-block interval resamples whole ecoregions; Holm adjusts the Wilcoxon p-values "
             "for testing four indices; the minimum detectable effect (MDE) is for 80% power at alpha 0.05.", "",
             "| Index | Spills (ecoregions) | Mean E1 | 95% CI, spills | 95% CI, ecoregion blocks | Wilcoxon p | Holm p | MDE |",
             "|---|---|---|---|---|---|---|---|"]
    for r in t.itertuples():
        lines.append(f"| {r.index} | {r.n} ({r.regions}) | {r.mean:+.3f} | [{r.plain_lo:+.3f}, {r.plain_hi:+.3f}] | "
                     f"[{r.block_lo:+.3f}, {r.block_hi:+.3f}] | {r.p:.4f} | {r.p_holm:.4f} | {r.mde:.3f} |")
    lines += ["", "An index whose |mean E1| is below its MDE could have a real effect this many spills can't show. "
              "First results, not findings."]
    out = P / "outputs" / "results" / "spill_robustness"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"SUMMARY_{a.folder}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--folder", default="spills_9springs")
    main(ap.parse_args())
