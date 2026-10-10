"""Gap 7: does the satellite record find the drop at the reported spill date?

For every spill, the series of its circle minus its matched same-line spots in every clear pass a year either side
(analysis/spill_series.py), a single change point in the mean is searched over every split with at least 5 passes on
each side (least squares, the core of BFAST's break test). The detected date is compared with the reported date. The
same search runs on fake spills (each matched spot treated as the spill, against the other matched spots), so the
real hit rate can be compared with what a series without a spill gives. Across spills only; no spill's own date is
reported (plan 7.7).

Writes outputs/results/spill_timing/SUMMARY.md and figure_timing_<index>.png.
Usage: python spill_timing.py [--index NDVI] [--window 60]
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spill_series as ss  # noqa: E402

P = ss.P


def break_day(d: pd.DataFrame, index: str, min_side: int = 5):
    """The split (between two passes) that minimizes the squared error of a two-mean fit; returns its day and the shift."""
    d = d.dropna(subset=[index]).sort_values("days")
    y, t = d[index].to_numpy(), d["days"].to_numpy()
    if len(y) < 2 * min_side:
        return None
    best = None
    for k in range(min_side, len(y) - min_side + 1):
        a, b = y[:k], y[k:]
        sse = ((a - a.mean()) ** 2).sum() + ((b - b.mean()) ** 2).sum()
        if best is None or sse < best[0]:
            best = (sse, (t[k - 1] + t[k]) / 2, b.mean() - a.mean())
    return best[1], best[2]


def run(diffs: pd.DataFrame, index: str) -> pd.DataFrame:
    rows = []
    for unit, g in diffs.groupby("unit"):
        r = break_day(g, index)
        if r:
            rows.append({"unit": unit, "spill_id": g["spill_id"].iat[0], "day": r[0], "shift": r[1]})
    return pd.DataFrame(rows)


def main(a):
    files = sorted(ss.STATS.glob("spills_v1_series_*.csv"))
    v = ss.site_passes(files)
    dates = pd.to_datetime(pd.read_parquet(ss.AGENT / "spills.parquet").set_index("spill_id")["date"])
    m = pd.read_csv(P / "outputs" / "results" / "spills_9springs" / "matches.csv")
    m = m[(m["kind"] == "same line") & m["spill_id"].isin(v["spill_id"].unique())]
    real = m.assign(unit=m["spill_id"], focal=m["spill_id"] + "_spill", spot=m["site_id"])
    fake = [{"unit": s, "spill_id": sid, "focal": s, "spot": o} for sid, g in m.groupby("spill_id")
            for s in g["site_id"] for o in g["site_id"] if o != s]
    r = run(ss.differences(v, real, dates), a.index).assign(kind="spills")
    f = run(ss.differences(v, pd.DataFrame(fake), dates), a.index).assign(kind="fake spills")
    both = pd.concat([r, f], ignore_index=True)
    both["near"] = both["day"].abs() <= a.window
    both["near_drop"] = both["near"] & (both["shift"] < 0)
    out = P / "outputs" / "results" / "spill_timing"
    out.mkdir(parents=True, exist_ok=True)
    tab = both.groupby("kind").agg(units=("unit", "size"), near=("near", "mean"), near_drop=("near_drop", "mean"),
                                   median_abs_day=("day", lambda d: d.abs().median()))
    ct = [[int(both[(both.kind == k)]["near_drop"].sum()), int((~both[(both.kind == k)]["near_drop"]).sum())]
          for k in ("spills", "fake spills")]
    p = stats.fisher_exact(ct, alternative="greater").pvalue

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(6.5, 3.0), dpi=200)
    bins = np.arange(-365, 366, 30.4)
    for kind, color in [("fake spills", "#9a9a9a"), ("spills", "#7a1f2b")]:
        x = both[both["kind"] == kind]["day"]
        ax.hist(x, bins=bins, weights=np.full(len(x), 1 / max(len(x), 1)), color=color, alpha=0.55 if kind == "fake spills" else 0.85,
                label=f"{kind} ({len(x)})")
    ax.axvline(0, color="#7a1f2b", linestyle="--", linewidth=0.8)
    ax.set_xlabel("detected change in the series, days from the reported spill date")
    ax.set_ylabel("share of series")
    ax.set_title(f"When the satellite record shows the change ({a.index}, one change point per series)", fontsize=9, loc="left")
    ax.legend(frameon=False, fontsize=8)
    for s_ in ("top", "right"):
        ax.spines[s_].set_visible(False)
    fig.tight_layout()
    fig.savefig(out / f"figure_timing_{a.index}.png", facecolor="white")
    plt.close(fig)

    lines = [f"# When does the record show the change? {a.index}, a year either side of each spill ({pd.Timestamp.today():%Y-%m-%d})", "",
             "One change point in the mean per series (at least 5 clear passes each side). Across spills only.", "",
             f"| Series | Count | Change within {a.window} days of the date | ... and it is a drop | Median days from the date |",
             "|---|---|---|---|---|"] + \
            [f"| {k} | {int(r.units)} | {r.near:.0%} | {r.near_drop:.0%} | {r.median_abs_day:.0f} |" for k, r in tab.iterrows()] + \
            ["", f"Real spills show a drop within {a.window} days of the reported date more often than fake spills "
             f"(Fisher's exact test, one-sided p = {p:.4f}).", "",
             "A drop found near the date supports the reported timing; the same tool, run on series with no reported "
             "spill, is the route to finding unreported ones. First results, not findings."]
    (out / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--index", default="NDVI")
    ap.add_argument("--window", type=int, default=60)
    main(ap.parse_args())
