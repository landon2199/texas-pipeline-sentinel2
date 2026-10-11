"""Plan v1.10, D27: group comparisons of the corridor gap, as measured and at the statewide mix of pipe sizes.

Bigger pipes have wider clearings, and the 0-50 m band is the same width for every pipe, so a group full of big pipes
shows a larger gap even if each pipe is cleared the same way. For every group (ecoregion, commodity, service, status,
mapped accuracy) this reports:
  - as measured: the weighted median of each segment's gap (median over the nine springs), as in corridor.py;
  - at the statewide size mix: the weighted median within each of three size classes (under 8.6 in, 8.6-16 in, over
    16 in), averaged with the classes' statewide km shares (direct standardization). A class with fewer than 15
    segments in the group leaves the standardized value empty.
Intervals: 500 bootstrap draws, segments resampled within the sample's strata (the same draws for both columns).
Writes outputs/results/size_standardized/: estimates.csv and SUMMARY.md.
Usage: python size_standardized.py [--ring "0-50 m"] [--indices NDVI NDRE NDMI] [--boot 500]
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.codes import DIAMETER_CLASSES  # noqa: E402
from common.config import CORRIDOR, R  # noqa: E402
from common.gaps import piece_gaps  # noqa: E402
from common.stats import bootstrap, strata_groups, wmedian  # noqa: E402

SRC = CORRIDOR / "segment_spring.csv"
OUT = R / "size_standardized"
SCOPES = ["ecoregion", "commodity_group", "service", "status", "location_accuracy"]
CLASSES = ["under 8.6 in", "8.6-16 in", "over 16 in"]
# the seven diameter classes in the three size classes ('Not recorded' is in none)
SIZE = dict(zip(DIAMETER_CLASSES, [CLASSES[0]] * 2 + [CLASSES[1]] * 2 + [CLASSES[2]] * 3))
MIN_CELL = 15


def estimates(v, w, size, share):
    raw = wmedian(v, w)
    cells = []
    for k, cls in enumerate(CLASSES):
        m = size == k
        if m.sum() < MIN_CELL:
            return raw, np.nan
        cells.append(share[cls] * wmedian(v[m], w[m]))
    return raw, float(np.sum(cells))


def main(a):
    rng = np.random.default_rng(392)
    seg = piece_gaps(SRC, ["segment_id", "index", "stratum", "weight", "diameter_class"] + SCOPES, a.ring, a.indices,
                     ["diff_same_lc"]).rename(columns={"diff_same_lc": "gap"})
    seg["size"] = seg["diameter_class"].map(SIZE)
    seg = seg.dropna(subset=["size", "gap"])           # 'Not recorded' diameters can't be standardized
    rows = []
    for idx, s in seg.groupby("index"):
        share = s.groupby("size")["weight"].sum() / s["weight"].sum()
        for scope in SCOPES:
            for group, g in s.groupby(scope):
                v, w = g["gap"].to_numpy(float), g["weight"].to_numpy(float)
                size = g["size"].map({c: k for k, c in enumerate(CLASSES)}).to_numpy()
                raw, std = estimates(v, w, size, share)
                draws = np.array(bootstrap(lambda i: estimates(v[i], w[i], size[i], share),
                                           strata_groups(g["stratum"], sort=False), a.boot, rng))
                ci = np.nanpercentile(draws, [2.5, 97.5], axis=0) if len(draws) else np.full((2, 2), np.nan)
                rows.append({"index": idx, "scope": scope, "group": group, "segments": len(g),
                             "share_over_16in": float(w[size == 2].sum() / w.sum()),
                             "as_measured": raw, "as_measured_lo95": ci[0, 0], "as_measured_hi95": ci[1, 0],
                             "size_standardized": std, "std_lo95": ci[0, 1] if np.isfinite(std) else np.nan,
                             "std_hi95": ci[1, 1] if np.isfinite(std) else np.nan})
    t = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    t.to_csv(OUT / "estimates.csv", index=False)
    share = seg[seg["index"] == a.indices[0]].groupby("size")["weight"].sum()
    share = (share / share.sum()).reindex(CLASSES)
    names = {"ecoregion": "Ecoregion", "commodity_group": "Commodity", "service": "Service", "status": "Status",
             "location_accuracy": "Mapped accuracy"}
    lines = [f"# Group comparisons at the statewide mix of pipe sizes (plan D27; {pd.Timestamp.today():%Y-%m-%d})", "",
             f"{a.ring} gap, same land cover, each segment's median over the nine springs. Bigger pipes have wider clearings, "
             "and the band is the same width for every pipe, so groups are also compared at the statewide size mix: "
             + ", ".join(f"{c} {share[c]:.0%}" for c in CLASSES) + " of the pipe km. 95% intervals from 500 stratified "
             "bootstrap draws.", ""]
    for idx in a.indices:
        lines += [f"## {idx}", "", "| Group | Segments | Share over 16 in | As measured [95% CI] | At statewide size mix [95% CI] | Change |",
                  "|---|---|---|---|---|---|"]
        for scope in SCOPES:
            part = t[(t["index"] == idx) & (t["scope"] == scope)].sort_values("as_measured")
            for r in part.itertuples():
                std = (f"{r.size_standardized:+.4f} [{r.std_lo95:+.4f}, {r.std_hi95:+.4f}]" if np.isfinite(r.size_standardized)
                       else "too few segments in a size class")
                ch = f"{r.size_standardized - r.as_measured:+.4f}" if np.isfinite(r.size_standardized) else "-"
                lines.append(f"| {names[scope]}: {r.group} | {r.segments:,} | {r.share_over_16in:.0%} | "
                             f"{r.as_measured:+.4f} [{r.as_measured_lo95:+.4f}, {r.as_measured_hi95:+.4f}] | {std} | {ch} |")
        lines.append("")
    lines += ["Read the standardized column when comparing groups: it removes the part of a difference that comes only from "
              "one group having more big (wider-cleared) pipes. The statewide estimate and the spill tests don't need this "
              "(spills are compared with spots on the same line). First results, not findings."]
    (OUT / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:4] + [l for l in lines if l.startswith("| Service") or l.startswith("| Commodity")]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ring", default="0-50 m")
    ap.add_argument("--indices", nargs="+", default=["NDVI", "NDRE", "NDMI"])
    ap.add_argument("--boot", type=int, default=500)
    main(ap.parse_args())
