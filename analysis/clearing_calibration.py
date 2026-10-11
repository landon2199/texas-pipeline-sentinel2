"""Plan v1.10, D28: the clearing-width calibration, the step between the band gap and the corridor results.

The 0-50 m band is 100 m wide (50 m each side) for every pipe, but the cleared strip inside it is narrower, and wider
for bigger pipes. So the band's gap is (cleared width / 100 m) x (how much less green the cleared strip is), and its
size trend mixes the two. This step:
  1. measures the cleared width per diameter class from the NAIP surveys (geoai/row_survey.py, by accuracy and by
     diameter): only strips both methods confirm (SAM 2 and the NDVI trough within 20 m, not flagged); full width =
     mean of SAM 2's 10th-90th percentile spread / 0.8 and the trough's half-depth width. Class width = median of its
     confirmed widths, or, with fewer than 8, a Theil-Sen fit of width on log diameter over all confirmed strips;
  2. calibrates every segment: calibrated gap = band gap x 100 m / cleared width of its class (the cleared strip's
     own greenness gap, assuming the strip lies inside the band; mapped lines are about 13 m off);
  3. reports the calibrated gap statewide (main sample, and all land pipe 100 m or longer with the supplement), by
     pipe size and by group, and the footprint: km of pipe x cleared width = cleared right-of-way area in Texas.
Intervals: one bootstrap that resamples confirmed widths within class and segments within strata together.
Published widths (INGAA Foundation 1999 construction widths; a 50 ft permanent easement) are listed as a check.
Writes outputs/results/clearing_calibration/: widths.csv, calibrated.csv, footprint.csv, SUMMARY.md.
Usage: python clearing_calibration.py [--boot 500]
"""
import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy import stats

P = Path(r"C:\mydrive\Graduate School\Courses\GEOG_392\projects")
R = P / "outputs" / "results"
OUT = R / "clearing_calibration"
BAND_M = 100.0                       # the 0-50 m band, both sides of the line
SAM_SPREAD = 0.8                     # SAM 2's width is the 10th-90th percentile spread of the strip
MIN_CONFIRMED = 8
CLASSES = ["Under 4.5 in", "4.5-8.6 in", "8.6-12.75 in", "12.75-16 in", "16-24 in", "24-36 in", "Over 36 in"]
PUBLISHED_FT = {"8.6-12.75 in": 80, "12.75-16 in": 80, "16-24 in": 95, "24-36 in": 110, "Over 36 in": 125}  # INGAA 1999
EASEMENT_FT = 50
TEXAS_LAND_KM2 = 676_587             # US Census Bureau, Texas land area
SCOPES = ["ecoregion", "commodity_group", "service", "status", "location_accuracy"]


def wmedian(v, w):
    o = np.argsort(v)
    c = np.cumsum(w[o])
    return v[o][np.searchsorted(c, c[-1] / 2)]


def confirmed_widths() -> pd.DataFrame:
    seg = gpd.read_file(P / "outputs" / "zones" / "sample_v1" / "sample.gpkg", layer="segments",
                        columns=["segment_id", "diameter_class", "diameter_in"])
    rows = []
    for survey in ("row_survey", "width_survey"):
        f = P / "outputs" / "geoai" / survey / "results.csv"
        if f.exists():
            rows.append(pd.read_csv(f).assign(survey=survey))
    t = pd.concat(rows, ignore_index=True).drop(columns=["diameter_class", "diameter_in"], errors="ignore")
    t = t.merge(pd.DataFrame(seg.drop(columns="geometry")), on="segment_id", how="left")
    t["confirmed"] = t["checkpoint"].astype(bool) & ~t["photo_check_first"].astype(bool) & t["sam_width_m"].notna()
    t["width_m"] = (t["sam_width_m"] / SAM_SPREAD + t["ndvi_width_m"]) / 2
    return t


def class_widths(t: pd.DataFrame, rng=None) -> pd.Series:
    """Cleared width per class; with rng, a bootstrap draw (confirmed strips resampled within class)."""
    c = t[t["confirmed"]]
    if rng is not None:
        idx = np.concatenate([rng.choice(ix, len(ix)) for ix in c.groupby("diameter_class").indices.values()])
        c = c.iloc[idx]
    fit = stats.theilslopes(c["width_m"], np.log(c["diameter_in"].clip(lower=1)))
    med_d = t.groupby("diameter_class")["diameter_in"].median()
    out = {}
    for k in CLASSES:
        g = c[c["diameter_class"] == k]["width_m"]
        out[k] = g.median() if len(g) >= MIN_CONFIRMED else fit.intercept + fit.slope * np.log(max(med_d.get(k, 6.0), 1))
    out = pd.Series(out)
    out["Not recorded"] = c["width_m"].median()
    return out.clip(lower=5.0)


def segments() -> pd.DataFrame:
    """Each piece's band gap (median over springs), with its frame, km and design weight (as coverage_estimate.py)."""
    keep = ["segment_id", "ring", "index", "diff_all", "diff_same_lc", "stratum", "weight", "diameter_class"] + SCOPES
    parts = []
    for f, frame in ((R / "corridor_sample_v1_9springs_pooled" / "segment_spring.csv", "main"),
                     (R / "corridor_supplement_9springs" / "segment_spring.csv", None)):
        cols = pd.read_csv(f, nrows=0).columns
        d = pd.concat(c[(c["ring"] == "0-50 m") & (c["index"] == "NDVI")]
                      for c in pd.read_csv(f, usecols=[k for k in keep if k in cols], chunksize=500_000))
        g = d.groupby(["segment_id"] + [k for k in keep if k in d and k not in ("segment_id", "ring", "index", "diff_all", "diff_same_lc")],
                      dropna=False, as_index=False)[["diff_same_lc", "diff_all"]].median()
        parts.append(g.assign(frame=frame))
    main, supp = parts
    main["km"] = 1.0
    info = pd.read_csv(P / "outputs" / "zones" / "sample_v2_supplement" / "sample_segments.csv",
                       usecols=["segment_id", "frame", "piece_m", "diameter_class"] + [s for s in SCOPES if s != "location_accuracy"] + ["location_accuracy"])
    supp = supp.drop(columns=[c for c in supp if c in info and c != "segment_id"]).merge(info, on="segment_id", how="left")
    supp["km"] = supp.pop("piece_m") / 1000
    d = pd.concat([main, supp], ignore_index=True)
    d["w_km"] = d["weight"] * d["km"]
    d["boot_stratum"] = d["frame"] + "|" + d["stratum"].astype(str)
    d["diameter_class"] = d["diameter_class"].fillna("Not recorded")
    return d


def comparison_ndvi(d: pd.DataFrame) -> float:
    """The comparison land's own greenness: each main-sample segment's 500-1,000 m ring, pixel-weighted mean per image,
    median over a spring's images, median over springs; then the design-weighted median. Cached (the raw files are big)."""
    cache = R / "clearing_calibration" / "comparison_ndvi.csv"     # fixed place: it is a baseline, not a result
    if not cache.exists():
        zs = P / "outputs" / "geog392_zone_stats"
        per = []
        for f in sorted(zs.glob("sample_v1_b50_per_image_20[0-9][0-9].csv")):
            parts = []
            for c in pd.read_csv(f, usecols=["zone_id", "image", "NDVI_mean", "NDVI_count"], chunksize=2_000_000):
                c = c[c["zone_id"].str.endswith("_r500-1000") & (c["NDVI_count"] > 0)]
                parts.append(c.assign(v=c["NDVI_mean"] * c["NDVI_count"]).groupby(["zone_id", "image"])[["v", "NDVI_count"]].sum())
            img = pd.concat(parts).groupby(level=[0, 1]).sum()
            img = (img["v"] / img["NDVI_count"]).rename("ndvi").reset_index()
            per.append(img.groupby("zone_id")["ndvi"].median().rename(f.stem[-4:]))
        s = pd.concat(per, axis=1).median(axis=1).rename("comparison_ndvi")
        s.index = s.index.str.replace("_r500-1000", "", regex=False)
        cache.parent.mkdir(parents=True, exist_ok=True)
        s.rename_axis("segment_id").to_csv(cache)
    s = pd.read_csv(cache, index_col="segment_id")["comparison_ndvi"]
    m = d[d["frame"] == "main"].merge(s, left_on="segment_id", right_index=True)
    return wmedian(m["comparison_ndvi"].to_numpy(float), m["w_km"].to_numpy(float))


def estimate(d, widths, measure, mask):
    x = d[mask]
    v = (x[measure] * BAND_M / x["diameter_class"].map(widths)).to_numpy(float)
    ok = np.isfinite(v)
    return wmedian(v[ok], x["w_km"].to_numpy(float)[ok]) if ok.any() else np.nan


def main(a):
    global OUT
    OUT = a.out or OUT
    rng = np.random.default_rng(392)
    t = confirmed_widths()
    W = class_widths(t)
    d = segments()
    targets = [("statewide", "main sample (1 km segments, clean comparison ring)", d["frame"] == "main"),
               ("statewide", "all land pipe 100 m or longer", d["frame"].notna())]
    targets += [("pipe size", k, (d["frame"] == "main") & (d["diameter_class"] == k)) for k in CLASSES]
    targets += [(s, g, (d["frame"] == "main") & (d[s] == g)) for s in SCOPES for g in sorted(d.loc[d["frame"] == "main", s].dropna().unique())]
    strata = [np.flatnonzero(d["boot_stratum"].to_numpy() == s) for s in d["boot_stratum"].unique()]
    point = {(sc, g, m): estimate(d, W, m, mk) for sc, g, mk in targets for m in ("diff_same_lc", "diff_all")}
    band = {(sc, g): wmedian(d.loc[mk, "diff_same_lc"].dropna().to_numpy(float), d.loc[mk].dropna(subset=["diff_same_lc"])["w_km"].to_numpy(float))
            for sc, g, mk in targets}
    draws, wdraws = {k: [] for k in point}, []
    for _ in range(a.boot):
        Wb = class_widths(t, rng)
        wdraws.append(Wb)
        i = np.concatenate([s[rng.integers(0, len(s), len(s))] for s in strata])
        db = d.iloc[i].reset_index(drop=True)
        for sc, g, mk in targets:
            mb = mk.to_numpy()[i]
            for m in ("diff_same_lc", "diff_all"):
                draws[(sc, g, m)].append(estimate(db, Wb, m, pd.Series(mb)))
    rows = []
    for (sc, g, m), est in point.items():
        lo, hi = np.nanpercentile(draws[(sc, g, m)], [2.5, 97.5])
        rows.append({"scope": sc, "group": g, "measure": "same land cover" if m == "diff_same_lc" else "all ground",
                     "band_gap": band[(sc, g)] if m == "diff_same_lc" else np.nan, "calibrated_gap": est, "lo95": lo, "hi95": hi})
    cal = pd.DataFrame(rows)
    base = comparison_ndvi(d)
    for c in ("calibrated_gap", "lo95", "hi95"):
        cal[c.replace("calibrated_gap", "pct") + ("" if c == "calibrated_gap" else "_pct")] = 100 * cal[c] / base
    cal = cal.rename(columns={"pct": "pct_of_comparison_ndvi"})
    wd = pd.DataFrame(wdraws)
    conf = t[t["confirmed"]].groupby("diameter_class")["width_m"].agg(["size", "median"])
    widths = pd.DataFrame({"cleared_width_m": W, "lo95": wd.quantile(0.025), "hi95": wd.quantile(0.975),
                           "confirmed_strips": conf["size"].reindex(W.index).fillna(0).astype(int),
                           "method": ["median of confirmed strips" if conf["size"].get(k, 0) >= MIN_CONFIRMED else "fit on log diameter"
                                      for k in W.index],
                           "published_construction_m": [PUBLISHED_FT.get(k, np.nan) * 0.3048 for k in W.index],
                           "easement_50ft_m": EASEMENT_FT * 0.3048})
    # footprint: km represented x cleared width, all land pipe 100 m or longer and without the dense-area frame
    d["area_km2"] = d["w_km"] * d["diameter_class"].map(W) / 1000
    fp = pd.DataFrame([{"pipe": "all land pipe 100 m or longer", "km": d["w_km"].sum(), "area_km2": d["area_km2"].sum()},
                       {"pipe": "without dense-area segments (where corridors may share a clearing)",
                        "km": d.loc[d["frame"] != "dense", "w_km"].sum(), "area_km2": d.loc[d["frame"] != "dense", "area_km2"].sum()}])
    area_draws = [(d["w_km"] * d["diameter_class"].map(Wb)).sum() / 1000 for Wb in wdraws]
    fp["share_of_texas_land"] = fp["area_km2"] / TEXAS_LAND_KM2
    OUT.mkdir(parents=True, exist_ok=True)
    widths.to_csv(OUT / "widths.csv")
    cal.to_csv(OUT / "calibrated.csv", index=False)
    fp.to_csv(OUT / "footprint.csv", index=False)
    sl = cal[cal["measure"] == "same land cover"]
    lines = [f"# Clearing-width calibration (plan D28; {pd.Timestamp.today():%Y-%m-%d})", "",
             f"Cleared widths from {int(t['confirmed'].sum())} confirmed strips in {len(t)} surveyed segments (SAM 2 and the "
             "NAIP NDVI trough agree). Calibrated gap = band gap x 100 m / cleared width: how much less green the cleared "
             "strip itself is than similar land 500-1,000 m away. 95% intervals resample widths and segments together.", "",
             "## Cleared width by pipe size", "", "| Diameter | Cleared width (m) [95% CI] | Confirmed strips | Method | Published construction width (m) |",
             "|---|---|---|---|---|"]
    for k, r in widths.iterrows():
        lines.append(f"| {k} | {r.cleared_width_m:.1f} [{r.lo95:.1f}, {r.hi95:.1f}] | {r.confirmed_strips} | {r.method} | "
                     + (f"{r.published_construction_m:.0f}" if np.isfinite(r.published_construction_m) else "-") + " |")
    lines += ["", f"A 50 ft permanent easement is {EASEMENT_FT * 0.3048:.1f} m.", "", "## Calibrated gap (same land cover)", "",
              f"The comparison land's own greenness (weighted median NDVI of the 500-1,000 m rings): {base:.3f}.", "",
              "| Scope | Group | Band gap (0-50 m) | Calibrated gap on the cleared strip [95% CI] | As % of nearby land's greenness |",
              "|---|---|---|---|---|"]
    for r in sl.itertuples():
        lines.append(f"| {r.scope} | {r.group} | {r.band_gap:+.4f} | {r.calibrated_gap:+.4f} [{r.lo95:+.4f}, {r.hi95:+.4f}] | "
                     f"{r.pct_of_comparison_ndvi:+.0f}% [{r.lo95_pct:+.0f}, {r.hi95_pct:+.0f}] |")
    lines += ["", "## Footprint", "", "| Pipe | km | Cleared area (km²) | Share of Texas land |", "|---|---|---|---|"]
    for r in fp.itertuples():
        lines.append(f"| {r.pipe} | {r.km:,.0f} | {r.area_km2:,.0f} | {r.share_of_texas_land:.2%} |")
    lines += ["", f"Cleared area for all land pipe, 95% interval from the widths: {np.percentile(area_draws, 2.5):,.0f}-"
              f"{np.percentile(area_draws, 97.5):,.0f} km². Where pipelines share a corridor, their clearings overlap, so the "
              "all-pipe area is an upper bound; the area without the dense-area frame is closer to a lower bound.", "",
              "Read the calibrated gap as the effect size and the band gap as the measurement it comes from. If the "
              "calibrated gap is the same for every pipe size, the size trend in the band gap is clearing width alone. "
              "First results, not findings."]
    (OUT / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--boot", type=int, default=500)
    ap.add_argument("--out", type=Path, help="output folder (default outputs/results/clearing_calibration)")
    main(ap.parse_args())
