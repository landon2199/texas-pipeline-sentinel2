"""Gap 5: are the reported spills in more socially vulnerable places than comparable pipeline elsewhere?

Each spill site is compared with its matched regional spots (analysis/spills.py, matches.csv: points on similar
pipelines in the same ecoregion, matched on land cover, soil and terrain, with no spill within 1 km). That makes the
comparison "a spill site versus pipeline like it", not versus Texas as a whole. The measure is the census tract's CDC/ATSDR
Social Vulnerability Index 2022 (overall percentile within Texas, RPL_THEMES, and its four themes), plus population
density. Per spill: the site's tract value minus the mean of its regional spots' tracts. Across spills: the mean
difference with a bootstrap 95% interval and a Wilcoxon signed-rank test.

Inputs: data/svi/Texas.csv (CDC SVI 2022, Texas tracts) and data/svi/tl_2022_48_tract.zip (Census TIGER/Line 2022).
Writes outputs/results/spill_svi/SUMMARY.md and differences.csv (no satellite results, so nothing here is blind).
Usage: python spill_svi.py [--matches outputs/results/spills_9springs/matches.csv]
"""
import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy import stats

P = Path(r"C:\mydrive\Graduate School\Courses\GEOG_392\projects")
THEMES = {"RPL_THEMES": "overall", "RPL_THEME1": "socioeconomic", "RPL_THEME2": "household and disability",
          "RPL_THEME3": "minority status and language", "RPL_THEME4": "housing and transportation"}


def main(a):
    a.out.mkdir(parents=True, exist_ok=True)
    svi = pd.read_csv(P / "data" / "svi" / "Texas.csv", dtype={"FIPS": str}, encoding="utf-8-sig")
    svi = svi[["FIPS", "E_TOTPOP", "AREA_SQMI"] + list(THEMES)].replace(-999, np.nan)
    svi["density"] = svi["E_TOTPOP"] / svi["AREA_SQMI"]
    tracts = gpd.read_file(P / "data" / "svi" / "tl_2022_48_tract.zip")[["GEOID", "geometry"]]
    sites = gpd.read_file(P / "outputs" / "zones" / "statewide" / "spills_statewide.gpkg", layer="sites")
    m = pd.read_csv(a.matches)
    reg = m[m["kind"] == "regional"]
    pts = sites[(sites["site"] == "spill") | sites["site_id"].isin(reg["site_id"])][["spill_id", "site_id", "site", "geometry"]]
    pts = gpd.sjoin(pts.to_crs(tracts.crs), tracts, how="left", predicate="within").merge(
        svi, left_on="GEOID", right_on="FIPS", how="left")
    cols = list(THEMES) + ["density"]
    spill = pts[pts["site"] == "spill"].set_index("spill_id")[cols]
    spots = pts[pts["site"] != "spill"].groupby("spill_id")[cols].mean()
    both = spill.index.intersection(spots.index)
    diff = (spill.loc[both] - spots.loc[both])
    diff.to_csv(a.out / "differences.csv")
    rng = np.random.default_rng(392)
    lines = [f"# Social vulnerability at spills versus matched regional spots ({pd.Timestamp.today():%Y-%m-%d})", "",
             f"{len(both)} spills with matched regional spots ({len(reg)} spots). Tract values: CDC/ATSDR SVI 2022, percentiles "
             "within Texas (0 = least vulnerable, 1 = most). Positive differences mean the spill site's tract is more "
             "vulnerable (or denser) than its regional spots' tracts.", "",
             "| Measure | Spill sites (mean) | Regional spots (mean) | Difference [95% CI] | Wilcoxon p |", "|---|---|---|---|---|"]
    for c in cols:
        x = diff[c].dropna().to_numpy()
        boot = x[rng.integers(0, len(x), (2000, len(x)))].mean(axis=1)
        p = stats.wilcoxon(x).pvalue if len(x) > 5 else np.nan
        name = THEMES.get(c, "people per square mile")
        fmt = "{:,.0f}" if c == "density" else "{:.3f}"
        lines.append(f"| {name} | {fmt.format(spill.loc[both, c].mean())} | {fmt.format(spots.loc[both, c].mean())} | "
                     f"{x.mean():+.3f} [{np.percentile(boot, 2.5):+.3f}, {np.percentile(boot, 97.5):+.3f}] | {p:.3f} |"
                     if c != "density" else
                     f"| {name} | {fmt.format(spill.loc[both, c].mean())} | {fmt.format(spots.loc[both, c].mean())} | "
                     f"{x.mean():+,.0f} [{np.percentile(boot, 2.5):+,.0f}, {np.percentile(boot, 97.5):+,.0f}] | {p:.3f} |")
    lines += ["", "Rural tracts are large, so a tract's people may live far from the spill. Read this as where spills fall "
              "relative to comparable pipeline, not as exposure. First results, not findings."]
    (a.out / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--matches", type=Path, default=P / "outputs" / "results" / "spills_9springs" / "matches.csv")
    ap.add_argument("--out", type=Path, default=P / "outputs" / "results" / "spill_svi")
    main(ap.parse_args())
