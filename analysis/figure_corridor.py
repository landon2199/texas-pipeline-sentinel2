"""Figure: the corridor effect, from analysis/corridor.py's statewide.csv (one spring or all springs pooled).

Three panels for the 0-50 m ring minus its own clean 500-1,000 m comparison ring, like-for-like land cover, with 95%
stratified-bootstrap intervals: (a) by distance from the pipe, (b) by pipe diameter, (c) by ecoregion.

Usage: python figure_corridor.py --results <corridor output folder> [--index NDVI] [--springs "all springs"]
"""
import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

MAROON = "#500000"
DIAMETERS = ["Under 4.5 in", "4.5-8.6 in", "8.6-12.75 in", "12.75-16 in", "16-24 in", "24-36 in", "Over 36 in"]


def bars(ax, t, labels, title, horizontal=False):
    t = t.set_index("group").reindex(labels).dropna(subset=["weighted_median"])
    y = t["weighted_median"].to_numpy()
    err = [y - t["lo95"].to_numpy(), t["hi95"].to_numpy() - y]
    pos = range(len(t))
    if horizontal:
        ax.barh(pos, y, xerr=err, color=MAROON, alpha=0.85, ecolor="#333", capsize=2)
        ax.set_yticks(list(pos), [f"{g} (n={int(n)})" for g, n in zip(t.index, t["segments"])], fontsize=8)
        ax.axvline(0, color="#888", lw=0.8)
        ax.xaxis.set_major_locator(plt.MaxNLocator(5))          # fewer ticks, so the numbers do not run together
        ax.invert_yaxis()
    else:
        ax.bar(pos, y, yerr=err, color=MAROON, alpha=0.85, ecolor="#333", capsize=2)
        ax.set_xticks(list(pos), list(t.index), rotation=35, ha="right", fontsize=8)
        ax.axhline(0, color="#888", lw=0.8)
    ax.set_title(title, fontsize=10, loc="left")


def main(a):
    r = pd.read_csv(a.results / "statewide.csv")
    r = r[(r["springs"].astype(str) == a.springs) & (r["index"] == a.index) & (r["measure"] == "same land cover")]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.6), gridspec_kw={"width_ratios": [1, 1.3, 1.6]})
    state = r[r["scope"] == "statewide"].rename(columns={"ring": "g"}).assign(group=lambda d: d["g"])
    order = sorted(state["group"].unique(), key=lambda r: int(r.split("-")[0]))      # 4 rings or ten 50 m bands
    bars(axes[0], state, order, "(a) By distance from the pipe")
    zero = r[r["ring"] == "0-50 m"]
    bars(axes[1], zero[zero["scope"] == "diameter_class"], DIAMETERS, "(b) 0-50 m ring, by pipe diameter")
    eco = zero[zero["scope"] == "ecoregion"].sort_values("weighted_median")
    bars(axes[2], eco, list(eco["group"]), "(c) 0-50 m ring, by ecoregion", horizontal=True)
    axes[0].set_ylabel(f"{a.index}: ring minus its comparison ring\n(weighted median, 95% interval)", fontsize=9)
    springs = a.label or a.springs
    fig.suptitle(f"Texas pipelines, {springs}: {a.index} beside the pipe versus ground at least 500 m from any pipeline "
                 f"(same land cover)", fontsize=11, x=0.01, ha="left")
    fig.tight_layout()
    out = a.results / f"figure_{a.index.lower()}_{a.springs.replace(' ', '_')}.png"
    fig.savefig(out, dpi=200)
    print(f"wrote {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--results", type=Path, required=True)
    ap.add_argument("--index", default="NDVI")
    ap.add_argument("--springs", default="all springs", help='"all springs" or one year, e.g. 2025')
    ap.add_argument("--label", help='how to name the springs in the title, e.g. "spring 2025"')
    main(ap.parse_args())
