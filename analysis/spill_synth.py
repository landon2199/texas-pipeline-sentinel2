"""Gap 6: synthetic control for every spill (Abadie et al. 2010), as a check on the matched-spot comparison.

For each spill, the donors are its candidate spots on the same line (0.5 to 3 km each way) with no other spill within
1 km, measured in the spill series (analysis/spill_series.py: the 50 m circle in every clear pass a year either side).
Weights (non-negative, summing to 1) are fit so the blend of donors tracks the spill circle over the passes before the
spill; the effect in each pass after is the spill circle minus that blend. Only passes where the spill and all kept
donors are clear are used, and donors clear in under 70% of the passes before are dropped. Placebos: each donor in turn
treated as the spill, with the remaining donors as its pool. Across spills only (plan 7.7).

Writes outputs/results/spill_synth/SUMMARY.md and months.csv.
Usage: python spill_synth.py [--index NDVI]
"""
import argparse
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.optimize import minimize

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spill_series as ss  # noqa: E402

P = ss.P


def weights(y: np.ndarray, X: np.ndarray) -> np.ndarray:
    k = X.shape[1]
    res = minimize(lambda w: ((y - X @ w) ** 2).sum(), np.full(k, 1 / k), method="SLSQP",
                   bounds=[(0, 1)] * k, constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1}])
    return res.x


def one(wide: pd.DataFrame, treated: str, donors: list[str], days: pd.Series):
    pre = days < 0
    avail = wide.loc[pre, donors].notna().mean().sort_values(ascending=False)
    ok = list(avail[avail >= 0.7].index[:5])          # the 5 donors clear most often, so enough passes are shared
    if len(ok) < 2:
        return None
    cols = [treated] + ok
    w_rows = wide[cols].notna().all(axis=1)
    use_pre = pre & w_rows
    if use_pre.sum() < 8:
        return None
    w = weights(wide.loc[use_pre, treated].to_numpy(), wide.loc[use_pre, ok].to_numpy())
    gap = (wide.loc[w_rows, treated] - wide.loc[w_rows, ok].to_numpy() @ w)
    pre_rmse = np.sqrt((gap[use_pre[w_rows]] ** 2).mean())
    return pd.DataFrame({"days": days[w_rows], "gap": gap - gap[use_pre[w_rows]].mean()}), pre_rmse


def main(a):
    files = sorted(ss.STATS.glob("spills_v1_series_*.csv"))
    v = ss.site_passes(files)
    dates = pd.to_datetime(pd.read_parquet(ss.AGENT / "spills.parquet").set_index("spill_id")["date"])
    sites = gpd.read_file(P / "outputs" / "zones" / "statewide" / "spills_statewide.gpkg", layer="sites", ignore_geometry=True)
    cand = sites[(sites["site"] == "candidate") & ~sites["other_spill_within_1km"].astype(bool)]
    rows, placebo, fits = [], [], []
    for sid, g in v.groupby("spill_id"):
        wide = g.pivot_table(index=["date", "orbit"], columns="site_id", values=a.index)
        treated = f"{sid}_spill"
        donors = [d for d in cand[cand["spill_id"] == sid]["site_id"] if d in wide.columns]
        if treated not in wide.columns or len(donors) < 3:
            continue
        days = pd.Series((pd.to_datetime(wide.index.get_level_values("date")) - dates[sid]).days, index=wide.index)
        r = one(wide, treated, donors, days)
        if r is None:
            continue
        rows.append(r[0].assign(unit=sid))
        fits.append(r[1])
        for d in donors:
            pr = one(wide, d, [x for x in donors if x != d], days)
            if pr is not None:
                placebo.append(pr[0].assign(unit=d))
    rng = np.random.default_rng(392)

    def months(df, kind):
        df = df.assign(month=np.floor(df["days"] / ss.MONTH).astype(int))
        per = df[df["month"].between(-12, 11)].groupby(["unit", "month"])["gap"].median().reset_index()
        out = []
        for mth, gg in per.groupby("month"):
            x = gg["gap"].to_numpy()
            if len(x) >= 3:
                b = x[rng.integers(0, len(x), (1000, len(x)))].mean(axis=1)
                out.append({"kind": kind, "month": mth, "mean": x.mean(), "lo95": np.percentile(b, 2.5),
                            "hi95": np.percentile(b, 97.5), "n": len(x)})
        return pd.DataFrame(out)

    real, fake = pd.concat(rows), pd.concat(placebo)
    t = pd.concat([months(real, "spills"), months(fake, "placebo donors")])
    out = P / "outputs" / "results" / "spill_synth"
    out.mkdir(parents=True, exist_ok=True)
    t.to_csv(out / "months.csv", index=False)

    def window(kind, lo, hi):
        x = t[(t["kind"] == kind) & t["month"].between(lo, hi)]
        return f"{x['mean'].mean():+.3f}" if len(x) else "-"
    post = real[real["days"].between(0, 365)].groupby("unit")["gap"].mean()
    post_p = fake[fake["days"].between(0, 365)].groupby("unit")["gap"].mean()
    # placebo in space, aggregated: one random placebo donor per spill, averaged like the spills, 10,000 times
    owner = pd.Series({u: u.split("_")[0] for u in post_p.index})
    pools = [post_p[owner == s].to_numpy() for s in post.index if (owner == s).any()]
    draws = np.array([np.mean([p_[rng.integers(len(p_))] for p_ in pools]) for _ in range(10000)])
    perm_p = (np.sum(draws <= post.mean()) + 1) / (len(draws) + 1)
    lines = [f"# Synthetic control for each spill, {a.index} ({pd.Timestamp.today():%Y-%m-%d})", "",
             f"{real['unit'].nunique()} spills with at least 3 donors and 8 clear passes before; median fit error before "
             f"the spill {np.median(fits):.3f}; {fake['unit'].nunique()} placebo runs. Across spills only.", "",
             "| Series | Months 1-3 after | Months 4-6 | Months 7-12 |", "|---|---|---|---|",
             f"| spill minus its synthetic control | {window('spills', 0, 2)} | {window('spills', 3, 5)} | {window('spills', 6, 11)} |",
             f"| placebo donors | {window('placebo donors', 0, 2)} | {window('placebo donors', 3, 5)} | {window('placebo donors', 6, 11)} |",
             "", f"Mean effect over the year after: {post.mean():+.3f}. Placebo test (one random donor per spill treated as "
             f"the spill, averaged the same way, 10,000 draws): p = {perm_p:.4f}.", "",
             "This is a check on the matched-spot result (spill_series): the two should agree. First results, not findings."]
    (out / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--index", default="NDVI")
    main(ap.parse_args())
