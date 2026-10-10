"""Part 3, gap 2: what goes with a larger or smaller spill effect? A mixed model across spills.

The outcome is each spill's E1 (analysis/spills.py: the first spring after minus the springs before, spill circle minus
matched spots). The fixed effects are:
  - log barrels released;
  - excavation damage as the cause (a line struck by a machine is found and contained at once);
  - soil removed in the cleanup, as read from the PHMSA narrative with a supporting quote (discovery/spill_reports.py),
    since digging bares the ground whatever the oil did;
  - drought in the first spring after (gridMET SPEI 90-day at the spill site; negative = drier).
Ecoregion is a random intercept. An ordinary least squares fit with HC3 errors is the check, and both run on the strict
and the broad matching. Only coefficients across spills are reported: each spill's own E1 stays unread until the photo
check (plan 7.7).

Writes, in --out: coefficients.csv and SUMMARY.md.
Usage: python spill_model.py [--index NDVI] [--out outputs/results/spill_model]
"""
import argparse
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

P = Path(r"C:\mydrive\Graduate School\Courses\GEOG_392\projects")
RESULTS = P / "outputs" / "results"
FORMULA = "E1 ~ log_bbl + excavation + soil_removed + spei_after"


def covariates() -> pd.DataFrame:
    rep = pd.read_parquet(P / "outputs" / "discovery" / "spill_reports.parquet",
                          columns=["spill_id", "soil_removed", "soil_removed_supported"]).dropna(subset=["spill_id"])
    rep["soil_removed"] = ((rep["soil_removed"] == "yes") & rep["soil_removed_supported"].astype(bool)).astype(int)
    spills = pd.read_parquet(P / "outputs" / "agent" / "spills.parquet", columns=["spill_id", "date"])
    d = pd.to_datetime(spills["date"])
    spills["first_after"] = np.where(d < pd.to_datetime(d.dt.year.astype(str) + "-03-01"), d.dt.year, d.dt.year + 1)
    dr = pd.read_parquet(P / "outputs" / "agent" / "drought.parquet", columns=["zone_id", "year", "spei90d"])
    # gridMET pixels are 4 km, so the small inner circles get no value; any ring of the spill site is the same pixel
    dr = dr[dr["zone_id"].str.contains("_spill_r")].assign(spill_id=lambda x: x["zone_id"].str.split("_").str[0])
    dr = dr.groupby(["spill_id", "year"], as_index=False)["spei90d"].mean()
    spills = spills.merge(dr[["spill_id", "year", "spei90d"]], left_on=["spill_id", "first_after"],
                          right_on=["spill_id", "year"], how="left").rename(columns={"spei90d": "spei_after"})
    return spills[["spill_id", "spei_after"]].merge(rep[["spill_id", "soil_removed"]], on="spill_id", how="left")


def fit(e: pd.DataFrame, label: str) -> list[dict]:
    rows = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            m = smf.mixedlm(FORMULA, e, groups=e["ecoregion"]).fit(reml=True)
            ci = m.conf_int()
            for k in ["log_bbl", "excavation", "soil_removed", "spei_after"]:
                rows.append({"matching": label, "model": "mixed (ecoregion intercept)", "term": k, "coef": m.params[k],
                             "lo95": ci.loc[k, 0], "hi95": ci.loc[k, 1], "p": m.pvalues[k], "n": int(m.nobs)})
        except Exception as err:          # too few spills per ecoregion can make the random effect singular
            rows.append({"matching": label, "model": f"mixed failed: {type(err).__name__}", "term": "", "n": len(e)})
        o = smf.ols(FORMULA, e).fit(cov_type="HC3")
        ci = o.conf_int()
        for k in ["log_bbl", "excavation", "soil_removed", "spei_after"]:
            rows.append({"matching": label, "model": "OLS, HC3 errors", "term": k, "coef": o.params[k],
                         "lo95": ci.loc[k, 0], "hi95": ci.loc[k, 1], "p": o.pvalues[k], "n": int(o.nobs)})
    return rows


def main(a):
    a.out.mkdir(parents=True, exist_ok=True)
    cov = covariates()
    rows, counts = [], {}
    for folder, label in [("spills_9springs", "strict"), ("spills_9springs_relaxed", "broad")]:
        e = pd.read_csv(RESULTS / folder / "effects.csv")
        e = e[(e["index"] == a.index)].dropna(subset=["E1"]).merge(cov, on="spill_id", how="left")
        e["log_bbl"] = np.log10(e["barrels"])
        e["excavation"] = (e["cause"] == "EXCAVATION DAMAGE").astype(int)
        e = e.dropna(subset=["log_bbl", "spei_after", "soil_removed"])
        counts[label] = {"spills": len(e), "soil removed": int(e["soil_removed"].sum()), "excavation": int(e["excavation"].sum())}
        rows += fit(e, label)
    t = pd.DataFrame(rows)
    t.to_csv(a.out / "coefficients.csv", index=False)
    names = {"log_bbl": "log10 barrels", "excavation": "excavation damage", "soil_removed": "soil removed (narrative)",
             "spei_after": "SPEI-90 in the first spring after"}
    lines = [f"# What goes with a larger spill effect? {a.index} E1 across spills ({pd.Timestamp.today():%Y-%m-%d})", "",
             f"Model: {FORMULA}, with ecoregion as a random intercept; OLS with HC3 errors as the check. Negative "
             "coefficients mean a larger loss of green at the spill site. Coefficients only; each spill's own effect "
             "stays unread until the photo check.", ""]
    for label, c in counts.items():
        lines.append(f"- {label} matching: {c['spills']} spills, {c['soil removed']} with soil removed, "
                     f"{c['excavation']} from excavation damage")
    lines += ["", "| Matching | Model | Term | Coefficient [95% CI] | p |", "|---|---|---|---|---|"]
    for r in t.dropna(subset=["coef"]).itertuples():
        lines.append(f"| {r.matching} | {r.model} | {names[r.term]} | {r.coef:+.3f} [{r.lo95:+.3f}, {r.hi95:+.3f}] | {r.p:.3f} |")
    for r in t[t["coef"].isna()].itertuples() if "coef" in t else []:
        lines.append(f"| {r.matching} | {r.model} | | | |")
    lines += ["", "With about 40 spills these are weak tests; read them as directions, not findings."]
    (a.out / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--index", default="NDVI")
    ap.add_argument("--out", type=Path, default=RESULTS / "spill_model")
    main(ap.parse_args())
