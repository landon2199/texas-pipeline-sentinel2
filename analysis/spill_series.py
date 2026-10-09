"""Part 3, plan 7.4: when did greenness fall at the reported spills, and did it come back?

Reads the spill series (extract/run_spill_series.py: every clear image from a year before to a year after each spill,
the 50 m circle of every site, 10 m) and the matched comparison spots of the spill analysis (analysis/spills.py,
matches.csv), then:
  1. measures every site's 50 m circle in every clear pass, as spills.py does: the 0-25 and 25-50 m rings pooled by
     pixel count, all land cover together, one tile image per site and pass (D17), at least 20 pixels;
  2. for every spill and pass: the spill circle minus the mean of its matched same-line spots in the same pass, so
     season, sun angle and haze cancel;
  3. the anomaly: that difference minus its mean before the spill (at least 3 passes before);
  4. by month from the spill (-12 to +12): the median anomaly of each spill, then the mean across spills with a
     bootstrap 95% interval;
  5. fake spills: each matched same-line spot treated as the spill, with the other matched spots as its comparison.
     A real effect should not show up there.
Writes, in --out: series_passes.parquet (each spill's own passes: leave unread until the photo check, plan 7.7),
months.csv and SUMMARY.md (across spills only) and figure_series_<index>.png.

Usage: python spill_series.py [--matches outputs/results/spills_9springs/matches.csv] [--out outputs/results/spill_series]
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from corridor import one_image_per_pass  # noqa: E402

P = Path(r"C:\mydrive\Graduate School\Courses\GEOG_392\projects")
STATS = P / "outputs" / "geog392_zone_stats"
AGENT = P / "outputs" / "agent"
INDICES = ["NDVI", "NDRE", "NDMI", "BSI"]
MONTH = 30.44


def site_passes(files) -> pd.DataFrame:
    out = []
    for f in files:
        keep = {"zone_id", "landcover", "date", "image", "orbit"} | {f"{i}_{s}" for i in INDICES for s in ("mean", "count")}
        d = pd.read_csv(f, usecols=lambda c: c in keep)
        if d.empty:
            continue
        d[["site_id", "ring"]] = d["zone_id"].str.rsplit("_r", n=1, expand=True)
        d = one_image_per_pass(d[d["ring"].isin(["0-25", "25-50"])], "site_id")
        d = d.sort_values(["NDVI_count", "image"], ascending=[False, True], kind="stable").drop_duplicates(
            ["zone_id", "landcover", "date", "orbit"])
        g = d.assign(**{f"{i}_w": d[f"{i}_mean"] * d[f"{i}_count"] for i in INDICES}).groupby(["site_id", "date", "orbit"])
        v = pd.DataFrame({i: g[f"{i}_w"].sum() / g[f"{i}_count"].sum() for i in INDICES})
        v["pixels"] = g["NDVI_count"].sum()
        out.append(v[v["pixels"] >= 20].reset_index())
    v = pd.concat(out, ignore_index=True)
    v["spill_id"] = v["site_id"].str.split("_").str[0]
    return v


def differences(v: pd.DataFrame, pairs: pd.DataFrame, dates: pd.Series) -> pd.DataFrame:
    """Per pass: each unit's own circle minus the mean of its comparison spots, and the anomaly from before the spill.
    pairs has unit, spill_id, focal (the site treated as the spill) and spot (one comparison site) per row."""
    rows = []
    for (unit, spill_id, focal), g in pairs.groupby(["unit", "spill_id", "focal"]):
        me = v[v["site_id"] == focal].set_index(["date", "orbit"])[INDICES]
        spots = v[v["site_id"].isin(g["spot"])].groupby(["date", "orbit"])[INDICES].mean()
        d = (me - spots).dropna(how="all").reset_index()
        if d.empty:
            continue
        d["days"] = (pd.to_datetime(d["date"]) - dates[spill_id]).dt.days
        before = d[d["days"] < 0]
        if len(before) < 3:
            continue
        d[INDICES] = d[INDICES] - before[INDICES].mean()
        d["month"] = np.floor(d["days"] / MONTH).astype(int)
        rows.append(d.assign(unit=unit, spill_id=spill_id))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def by_month(d: pd.DataFrame, rng, boot: int = 1000) -> pd.DataFrame:
    """The median anomaly of each unit per month, then the mean across units with a bootstrap 95% interval."""
    per = d[d["month"].between(-12, 11)].groupby(["unit", "month"])[INDICES].median().reset_index()
    out = []
    for (m), g in per.groupby("month"):
        for i in INDICES:
            x = g[i].dropna().to_numpy()
            if len(x) < 3:
                continue
            means = x[rng.integers(0, len(x), (boot, len(x)))].mean(axis=1)
            out.append({"month": m, "index": i, "mean": x.mean(), "lo95": np.percentile(means, 2.5),
                        "hi95": np.percentile(means, 97.5), "n": len(x)})
    return pd.DataFrame(out)


def figure(months: pd.DataFrame, index: str, path: Path, n_spills: int):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(6.5, 3.2), dpi=200)
    for kind, color, label in [("spills", "#7a1f2b", f"spill sites ({n_spills} spills)"),
                               ("fake spills", "#8a8a8a", "fake spills (matched spots)")]:
        m = months[(months["kind"] == kind) & (months["index"] == index)].sort_values("month")
        ax.fill_between(m["month"] + 0.5, m["lo95"], m["hi95"], color=color, alpha=0.18, linewidth=0)
        ax.plot(m["month"] + 0.5, m["mean"], color=color, linewidth=1.6, label=label)
    ax.axhline(0, color="#444", linewidth=0.6)
    ax.axvline(0, color="#7a1f2b", linewidth=0.8, linestyle="--")
    ax.set_xlim(-12, 12)
    ax.set_xlabel("months from the spill")
    ax.set_ylabel(f"{index}: spill minus matched spots,\nchange from before the spill")
    ax.set_title(f"{index} at reported spills, every clear Sentinel-2 image, a year either side", fontsize=10, loc="left")
    ax.legend(frameon=False, fontsize=8, loc="lower left")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)


def main(a):
    files = sorted(STATS.glob("spills_v1_series_*.csv"))
    if not files:
        raise SystemExit(f"no spill series in {STATS} yet (extract/run_spill_series.py)")
    a.out.mkdir(parents=True, exist_ok=True)
    v = site_passes(files)
    dates = pd.to_datetime(pd.read_parquet(AGENT / "spills.parquet").set_index("spill_id")["date"])
    m = pd.read_csv(a.matches)
    m = m[(m["kind"] == "same line") & m["spill_id"].isin(v["spill_id"].unique())]
    real = m.assign(unit=m["spill_id"], focal=m["spill_id"] + "_spill", spot=m["site_id"])
    fake = []
    for spill_id, g in m.groupby("spill_id"):
        for s in g["site_id"]:
            others = g[g["site_id"] != s]["site_id"]
            fake += [{"unit": s, "spill_id": spill_id, "focal": s, "spot": o} for o in others]
    rng = np.random.default_rng(392)
    d_real = differences(v, real, dates)
    d_fake = differences(v, pd.DataFrame(fake), dates) if fake else pd.DataFrame()
    d_real.to_parquet(a.out / "series_passes.parquet", index=False)
    months = pd.concat([by_month(d_real, rng).assign(kind="spills")] +
                       ([by_month(d_fake, rng).assign(kind="fake spills")] if len(d_fake) else []), ignore_index=True)
    months.to_csv(a.out / "months.csv", index=False)
    n = d_real["spill_id"].nunique()
    for i in INDICES:
        figure(months, i, a.out / f"figure_series_{i}.png", n)

    def window(kind, i, lo, hi):
        x = months[(months["kind"] == kind) & (months["index"] == i) & months["month"].between(lo, hi)]
        return f"{x['mean'].mean():+.3f}" if len(x) else "-"
    lines = [f"# Spill series: a year either side of each spill ({pd.Timestamp.today():%Y-%m-%d})", "",
             f"{len(files)} spill series files; {n} spills with matched same-line spots and at least 3 clear passes before "
             f"the spill; {len(d_real):,} spill passes. Across spills only: each spill's own passes are in "
             "series_passes.parquet, to leave unread until the photo check (plan 7.7).", "",
             "Mean anomaly (spill circle minus matched spots, change from before the spill), by window:", "",
             "| Index | Months 1-3 after | Months 4-6 | Months 7-12 | Fake spills, months 1-12 |", "|---|---|---|---|---|"]
    for i in INDICES:
        lines.append(f"| {i} | {window('spills', i, 0, 2)} | {window('spills', i, 3, 5)} | {window('spills', i, 6, 11)} | "
                     f"{window('fake spills', i, 0, 11)} |")
    lines += ["", "Month 0 is the first 30 days after the spill. Intervals by month are in months.csv; the figures are "
              "figure_series_<index>.png. These are first results, not findings."]
    (a.out / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--matches", type=Path, default=P / "outputs" / "results" / "spills_9springs" / "matches.csv")
    ap.add_argument("--out", type=Path, default=P / "outputs" / "results" / "spill_series")
    main(ap.parse_args())
