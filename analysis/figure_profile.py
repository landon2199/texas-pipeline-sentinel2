"""Figure: how far from the pipe the effect reaches, ten 50 m bands against the four old rings (plan v1.6, D15).

For each index, the weighted statewide gap in every 50 m band (band minus its own clean 500-1,000 m comparison ring,
like-for-like land cover) with its 95% stratified-bootstrap interval, from analysis/corridor.py on the ten-band
sample. With --rings, the four-ring results for the same spring are drawn behind as grey boxes spanning each ring.

Usage: python figure_profile.py --bands <corridor folder, ten bands> [--rings <corridor folder, four rings>]
                                [--spring 2024] [--indices NDVI NDRE NDMI]
"""
import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

MAROON = "#500000"
plt.rcParams["font.family"] = ["Calibri", "DejaVu Sans"]


def statewide(folder: Path, springs: str, index: str) -> pd.DataFrame:
    r = pd.read_csv(folder / "statewide.csv")
    r = r[(r["springs"].astype(str) == springs) & (r["scope"] == "statewide") & (r["index"] == index)
          & (r["measure"] == "same land cover")].copy()
    r[["inner", "outer"]] = r["ring"].str.replace(" m", "").str.split("-", expand=True).astype(float)
    return r.sort_values("inner")


def main(a):
    fig, axes = plt.subplots(1, len(a.indices), figsize=(3.1 * len(a.indices), 3.0), sharey=False)
    axes = [axes] if len(a.indices) == 1 else list(axes)
    n = None
    for ax, index in zip(axes, a.indices):
        b = statewide(a.bands, "all springs", index)       # the ten-band run holds one spring
        n = int(b["segments"].max())
        if a.rings:
            r = statewide(a.rings, a.spring, index)
            for x in r.itertuples():
                ax.add_patch(Rectangle((x.inner, x.lo95), x.outer - x.inner, x.hi95 - x.lo95, facecolor="#d9d9d9",
                                       edgecolor="none", zorder=1))
                ax.plot([x.inner, x.outer], [x.weighted_median] * 2, color="#7f7f7f", lw=1.2, zorder=2)
        mid = (b["inner"] + b["outer"]) / 2
        ax.errorbar(mid, b["weighted_median"], yerr=[b["weighted_median"] - b["lo95"], b["hi95"] - b["weighted_median"]],
                    fmt="o", color=MAROON, ms=3.5, capsize=2, lw=1, zorder=3)
        ax.axhline(0, color="#444", lw=0.7, ls=(0, (4, 3)), zorder=2.5)
        ax.set_xlim(0, 500)
        ax.set_xticks(range(0, 501, 100))
        ax.set_xlabel("distance from the mapped line (m)", fontsize=9)
        ax.set_title(index, fontsize=11, loc="left")
        ax.tick_params(labelsize=8)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
    axes[0].set_ylabel("band minus comparison ring\n(weighted median, 95% interval)", fontsize=9)
    if a.rings:
        axes[0].plot([], [], "o", color=MAROON, ms=3.5, label="ten 50 m bands")
        axes[0].add_patch(Rectangle((0, 0), 0, 0, facecolor="#d9d9d9", label="four old rings (95% interval)"))
        axes[0].legend(fontsize=8, frameon=False, loc="center right")
    fig.suptitle(f"{a.label or 'Spring ' + a.spring}, {n:,} sampled segments, same land cover: index beside the pipe minus ground "
                 f"500-1,000 m from any pipeline", fontsize=10, x=0.01, ha="left")
    fig.tight_layout()
    out = a.bands / f"figure_profile_{(a.label or a.spring).replace(' ', '_')}.png"
    fig.savefig(out, dpi=200)
    print(f"wrote {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bands", type=Path, required=True)
    ap.add_argument("--rings", type=Path)
    ap.add_argument("--spring", default="2024")
    ap.add_argument("--indices", nargs="+", default=["NDVI", "NDRE", "NDMI"])
    ap.add_argument("--label", help='how to name the springs in the title and file, e.g. "springs 2018-2026"')
    main(ap.parse_args())
