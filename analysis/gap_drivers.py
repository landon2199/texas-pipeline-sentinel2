"""Plan v1.10, D26 (exploratory): what goes with a larger corridor gap?

Response: each main-sample segment's 0-50 m NDVI gap (same land cover, median over the nine springs). Predictors, all
for the 0-50 m band unless named otherwise:
  - the line: diameter, commodity group, service, status, mapped accuracy (Railroad Commission);
  - land cover shares (NLCD 2021 groups; pixel counts over spring 2024's clear images);
  - man-made cover: impervious %, roads, developed land, energy sites, Dynamic World built-up, NLCD change (D19);
  - terrain: slope, height above the nearest drainage, topographic wetness index, elevation, soil texture.
A random forest (Breiman 2001; scikit-learn), weighted by the design weights, is checked by leaving one ecoregion out
at a time (spatial cross-validation: Ploton et al. 2020; Meyer and Pebesma 2021), beside an ordinary random 10-fold
split to show how much a non-spatial check flatters the model. Permutation importance comes from the held-out
ecoregions; partial dependence from the model fit on all segments. With --arcgis, ArcGIS Pro's Forest-based and
Boosted Classification and Regression runs on the same table (arcgis_forest.py), side by side.
It shows what goes with the gap, not what causes it. First results, not findings.
Writes outputs/results/gap_drivers/: SUMMARY.md, importance.csv, cv.csv, table.csv, figure_gap_drivers.png.
Usage: python gap_drivers.py [--arcgis]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.inspection import partial_dependence, permutation_importance
from sklearn.metrics import r2_score
from sklearn.model_selection import KFold, LeaveOneGroupOut

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.codes import DIAMETER_CLASSES, NLCD_GROUPS  # noqa: E402
from common.config import ARCPY_PYTHON, CORRIDOR, R, SAMPLE, STATS  # noqa: E402
from common.gaps import piece_gaps  # noqa: E402
from common.rings import BAND, suffix  # noqa: E402

OUT = R / "gap_drivers"
HERE = Path(__file__).resolve().parent
LABELS = {"diameter_in": "Pipe diameter (in)", "impervious_pct": "Impervious surface (%)", "road": "Roads",
          "developed": "Developed land (impervious descriptor)", "energy": "Well pads and energy sites",
          "dw_built": "Built-up (Dynamic World)", "lc_changed": "Land cover changed 2001-2021", "slope_deg_mean": "Slope (deg)",
          "hand_m_mean": "Height above drainage (m)", "twi_mean": "Wetness index", "elevation_m_mean": "Elevation (m)"}


def table() -> pd.DataFrame:
    seg = gpd.read_file(SAMPLE / "sample.gpkg", layer="segments",
                        columns=["segment_id", "diameter_in", "commodity_group", "service", "status", "location_accuracy",
                                 "ecoregion", "weight"])
    seg["x"], seg["y"] = seg.geometry.centroid.x, seg.geometry.centroid.y
    seg = pd.DataFrame(seg.drop(columns="geometry"))
    y = piece_gaps(CORRIDOR / "segment_spring.csv", ["segment_id"], measures=["diff_same_lc"]).set_index("segment_id")["diff_same_lc"].rename("gap")
    lc = []
    for c in pd.read_csv(STATS / "sample_v1_b50_per_image_2024.csv", usecols=["zone_id", "landcover", "NDVI_count"], chunksize=1_000_000):
        lc.append(c[c["zone_id"].str.endswith(suffix(BAND))].groupby(["zone_id", "landcover"])["NDVI_count"].sum())
    lc = pd.concat(lc).groupby(level=[0, 1]).sum().unstack(fill_value=0)
    share = pd.DataFrame({f"nlcd_{k}": lc[[c for c in v if c in lc]].sum(axis=1) for k, v in NLCD_GROUPS.items()})
    share = share.div(lc.sum(axis=1), axis=0)
    mm = pd.read_csv(STATS / "sample_v1_b50_and_spills_v1_man_made.csv")
    fx = pd.read_csv(STATS / "sample_v1_b50_and_spills_v1_fixed.csv")
    zones = mm.merge(fx, on="zone_id", how="outer")
    zones = zones[zones["zone_id"].str.endswith(suffix(BAND))].set_index("zone_id")
    share.index = share.index.str.replace(suffix(BAND), "", regex=False)
    zones.index = zones.index.str.replace(suffix(BAND), "", regex=False)
    t = seg.set_index("segment_id").join(y, how="inner").join(share).join(zones)
    t["soil_texture"] = t["soil_texture_mode"].round().astype("Int64").astype(str)
    return t.drop(columns=["soil_texture_mode", "water_share_mean"], errors="ignore").dropna(subset=["gap"])


def design(t: pd.DataFrame):
    cats = ["commodity_group", "service", "status", "location_accuracy", "soil_texture"]
    nums = ["diameter_in", "impervious_pct", "road", "developed", "energy", "dw_built", "lc_changed", "slope_deg_mean",
            "hand_m_mean", "twi_mean", "elevation_m_mean"] + [c for c in t if c.startswith("nlcd_")]
    X = pd.concat([t[nums], pd.get_dummies(t[cats].astype(str), prefix=cats, dtype=float)], axis=1)
    X = X.loc[:, X.std() > 0].fillna(X.median())
    groups = {c: [c] for c in nums if c in X} | {g: [c for c in X if c.startswith(g + "_")] for g in cats}
    return X, {g: cols for g, cols in groups.items() if cols}


def forest():
    return RandomForestRegressor(n_estimators=500, min_samples_leaf=5, max_features=0.33, n_jobs=-1, random_state=392)


def cv(X, y, w, splits) -> tuple[float, list]:
    pred = np.full(len(y), np.nan)
    folds = []
    for tr, te in splits:
        m = forest().fit(X.iloc[tr], y.iloc[tr], sample_weight=w.iloc[tr])
        pred[te] = m.predict(X.iloc[te])
        folds.append((tr, te, m))
    return r2_score(y, pred, sample_weight=w), folds


def main(a):
    OUT.mkdir(parents=True, exist_ok=True)
    t = table()
    t.to_csv(OUT / "table.csv")
    X, groups = design(t)
    y, w = t["gap"], t["weight"] / t["weight"].mean()
    eco = t["ecoregion"].to_numpy()
    r2_spatial, folds = cv(X, y, w, LeaveOneGroupOut().split(X, y, eco))
    r2_random, _ = cv(X, y, w, KFold(10, shuffle=True, random_state=392).split(X))
    per_region = []
    for tr, te, m in folds:
        per_region.append({"held_out": eco[te][0], "segments": len(te),
                           "r2": r2_score(y.iloc[te], m.predict(X.iloc[te]), sample_weight=w.iloc[te])})
    # permutation importance of each predictor group, on the held-out ecoregions
    rng = np.random.default_rng(392)
    imp = {g: [] for g in groups}
    for tr, te, m in folds:
        Xt, yt, wt = X.iloc[te], y.iloc[te], w.iloc[te]
        base = r2_score(yt, m.predict(Xt), sample_weight=wt)
        for g, cols in groups.items():
            drops = []
            for _ in range(5):
                Xp = Xt.copy()
                Xp[cols] = Xp[cols].to_numpy()[rng.permutation(len(Xp))]
                drops.append(base - r2_score(yt, m.predict(Xp), sample_weight=wt))
            imp[g].append(np.mean(drops) * len(te))
    importance = pd.Series({g: sum(v) / len(y) for g, v in imp.items()}).sort_values(ascending=False).rename("r2_drop")
    importance.to_csv(OUT / "importance.csv")
    pd.DataFrame(per_region).to_csv(OUT / "cv.csv", index=False)
    full = forest().fit(X, y, sample_weight=w)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    top_num = [g for g in importance.index if g in X and not g.startswith(("commodity", "service", "status", "location", "soil"))][:4]
    fig, ax = plt.subplots(1, 1 + len(top_num), figsize=(3.2 * (1 + len(top_num)), 3.4), dpi=200,
                           gridspec_kw={"width_ratios": [1.6] + [1] * len(top_num)})
    top = importance.head(10)[::-1]
    ax[0].barh([LABELS.get(g, g.replace("nlcd_", "Land cover: ").replace("_", " ")) for g in top.index], top.to_numpy(), color="#4d4d4d")
    ax[0].set_xlabel("Drop in R² when shuffled\n(held-out ecoregions)", fontsize=7)
    ax[0].tick_params(labelsize=6.5)
    for k, g in enumerate(top_num, start=1):
        pdp = partial_dependence(full, X, [g], grid_resolution=30, percentiles=(0.05, 0.95))
        ax[k].plot(pdp["grid_values"][0], pdp["average"][0], color="#b2182b")
        ax[k].axhline(0, color="0.6", lw=0.6)
        ax[k].set_xlabel(LABELS.get(g, g.replace("nlcd_", "Land cover: ").replace("_", " ")), fontsize=7)
        ax[k].tick_params(labelsize=6.5)
        if k == 1:
            ax[k].set_ylabel("Predicted 0-50 m NDVI gap", fontsize=7)
    fig.suptitle(f"What goes with a larger gap? Random forest, {len(y):,} segments; R² {r2_spatial:.2f} leaving one ecoregion out "
                 f"({r2_random:.2f} with a random split)", fontsize=8.5)
    fig.tight_layout()
    fig.savefig(OUT / "figure_gap_drivers.png", facecolor="white")
    plt.close(fig)

    arc = None
    if a.arcgis:
        g = gpd.GeoDataFrame(t.reset_index(), geometry=gpd.points_from_xy(t["x"], t["y"]), crs=6579)
        g.drop(columns=["ecoregion"]).to_file(OUT / "arcgis_input.gpkg", layer="segments", driver="GPKG")
        run = subprocess.run([str(ARCPY_PYTHON), str(HERE / "arcgis_forest.py"), str(OUT / "arcgis_input.gpkg"), str(OUT)],
                             capture_output=True, text=True)
        arc = json.loads(run.stdout.strip().splitlines()[-1]) if run.returncode == 0 else {"error": run.stderr[-500:]}
    lines = [f"# What goes with a larger corridor gap? (plan D26, exploratory; {pd.Timestamp.today():%Y-%m-%d})", "",
             f"Random forest of each main-sample segment's 0-50 m NDVI gap (same land cover, median over the nine springs) on "
             f"{X.shape[1]} predictors, {len(y):,} segments, design weights.", "",
             f"- R² leaving one ecoregion out (spatial cross-validation): **{r2_spatial:.2f}**",
             f"- R² with an ordinary random 10-fold split: {r2_random:.2f} (the gap between the two is how much a non-spatial "
             "check would flatter the model)", "",
             "| Predictor | Drop in R² when shuffled (held-out ecoregions) |", "|---|---|"] + \
            [f"| {LABELS.get(g, g)} | {v:.3f} |" for g, v in importance.head(12).items()] + \
            ["", "By held-out ecoregion: " + ", ".join(f"{r['held_out']} {r['r2']:.2f} (n={r['segments']})" for r in per_region) + "."]
    if arc:
        lines += ["", "ArcGIS Pro side by side (Forest-based and Boosted Classification and Regression, same table, unweighted, "
                  f"{arc.get('trees', '?')} trees, 10% random validation): " + (
                      f"validation R² {arc['validation_r2']}; top variables " + ", ".join(arc["top"]) + "." if "top" in arc else str(arc))]
    s = pd.read_csv(CORRIDOR / "statewide.csv")
    s = s[(s["springs"] == "all springs") & (s["ring"] == "0-50 m") & (s["index"] == "NDVI") & (s["measure"] == "same land cover")
          & (s["scope"] == "diameter_class") & (s["group"] != "Not recorded")]
    s = s.set_index("group").reindex(DIAMETER_CLASSES).dropna(subset=["weighted_median"])
    lines += ["", "The model predicts single segments poorly, but its partial dependence points the same way as the design-based "
              "estimates by pipe size (corridor.py, weighted medians with 95% intervals): " +
              "; ".join(f"{g} {r.weighted_median:+.4f} [{r.lo95:+.4f}, {r.hi95:+.4f}]" for g, r in s.iterrows()) +
              ". Bigger pipes have wider clearings (about 80 ft of construction clearing for 8-16 in pipe, 125 ft for "
              "40-42 in; INGAA Foundation 1999), and the 0-50 m band is the same width for every pipe. So part or all of "
              "this trend can be clearing width, not a stronger effect per square meter of cleared ground. Group "
              "comparisons at one size mix are in size_standardized (plan D27)."]
    lines += ["", "It shows what goes with the gap, not what causes it: predictors are correlated (e.g. land cover and terrain), "
              "and permutation importance splits shared credit between them. First results, not findings."]
    (OUT / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--arcgis", action="store_true", help="also run ArcGIS Pro's Forest-based regression on the same table")
    main(ap.parse_args())
