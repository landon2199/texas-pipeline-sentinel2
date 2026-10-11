"""Make the small test fixtures and the expected numbers for the refactor (REFACTOR_PLAN.md). Run locally only: it
reads the full results in the Drive folder, which the cloud session can't see.

  tests/fixtures/segment_spring_small.csv   80 random main-sample segments, all springs, rings, NDVI/NDRE/NDMI gaps
  tests/fixtures/widths.csv                  cleared width per pipe size (clearing_calibration)
  tests/fixtures/comparison_ndvi_small.csv   the same 80 segments' comparison-ring greenness
  tests/expected_fixture.json                point estimates the refactored code must reproduce on the fixtures
  tests/expected_headlines.json              the full-data headline numbers (checked locally after the refactor)
No spill results anywhere (the repo is public and the photo check is blind); no Carbon Mapper data (noncommercial).
Usage: python tests/make_fixtures.py
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

P = Path(r"C:\mydrive\Graduate School\Courses\GEOG_392\projects")
R = P / "outputs" / "results"
T = Path(__file__).resolve().parent
F = T / "fixtures"


def wmedian(v, w):
    o = np.argsort(v)
    c = np.cumsum(w[o])
    return float(v[o][np.searchsorted(c, c[-1] / 2)])


def main():
    F.mkdir(parents=True, exist_ok=True)
    seg = pd.read_csv(R / "corridor_sample_v1_9springs_pooled" / "segment_spring.csv",
                      usecols=["segment_id", "year", "ring", "index", "diff_all", "diff_same_lc", "passes", "stratum",
                               "weight", "ecoregion", "diameter_class", "service"])
    seg = seg[seg["index"].isin(["NDVI", "NDRE", "NDMI"])]
    ids = pd.Series(seg["segment_id"].unique()).sample(80, random_state=392)
    small = seg[seg["segment_id"].isin(ids)].round(6)
    small.to_csv(F / "segment_spring_small.csv", index=False)
    widths = pd.read_csv(R / "clearing_calibration" / "widths.csv", index_col=0)
    widths.to_csv(F / "widths.csv")
    comp = pd.read_csv(R / "clearing_calibration" / "comparison_ndvi.csv")
    comp[comp["segment_id"].isin(ids)].round(6).to_csv(F / "comparison_ndvi_small.csv", index=False)

    # expected point estimates on the fixtures (deterministic: no bootstrap)
    nd = small[(small["index"] == "NDVI") & (small["ring"] == "0-50 m")]
    per = nd.groupby(["segment_id", "stratum", "weight", "diameter_class"], as_index=False)["diff_same_lc"].median()
    W = widths["cleared_width_m"]
    per["calibrated"] = per["diff_same_lc"] * 100 / per["diameter_class"].map(W)
    exp = {"fixture_weighted_median_band_gap_ndvi_0_50": wmedian(per["diff_same_lc"].to_numpy(), per["weight"].to_numpy()),
           "fixture_weighted_median_calibrated_gap_ndvi": wmedian(per["calibrated"].to_numpy(), per["weight"].to_numpy()),
           "fixture_segments": int(per["segment_id"].nunique()),
           "rule": "per segment: median over springs of diff_same_lc at ring '0-50 m'; weighted median with design weights; "
                   "calibrated = gap x 100 / cleared width of the segment's diameter class"}
    (T / "expected_fixture.json").write_text(json.dumps(exp, indent=2), encoding="utf-8")

    cov = pd.read_csv(R / "coverage_estimate" / "estimates.csv")
    cal = pd.read_csv(R / "clearing_calibration" / "calibrated.csv")
    fp = pd.read_csv(R / "clearing_calibration" / "footprint.csv")
    st = pd.read_csv(R / "corridor_sample_v1_9springs_pooled" / "statewide.csv")
    pick = lambda d, **k: d.loc[np.logical_and.reduce([d[c] == v for c, v in k.items()])].iloc[0]  # noqa: E731
    head = {
        "band_gap_all_land_pipe_ndvi": float(pick(cov, index="NDVI", frame="all land pipe", measure="same land cover")["gap"]),
        "band_gap_main_sample_ndvi_all_springs": float(pick(st, springs="all springs", scope="statewide", ring="0-50 m", index="NDVI",
                                                            measure="same land cover")["weighted_median"]),
        "calibrated_gap_all_land_pipe_ndvi": float(pick(cal, scope="statewide", group="all land pipe 100 m or longer",
                                                        measure="same land cover")["calibrated_gap"]),
        "calibrated_pct_all_land_pipe": float(pick(cal, scope="statewide", group="all land pipe 100 m or longer",
                                                   measure="same land cover")["pct_of_comparison_ndvi"]),
        "cleared_width_m": {k: round(float(v), 3) for k, v in W.items()},
        "footprint_km2_all_land_pipe": float(fp["area_km2"].iloc[0]),
        "tolerance": "point estimates must match to 1e-9; bootstrap intervals may move if the random draws change order",
    }
    (T / "expected_headlines.json").write_text(json.dumps(head, indent=2), encoding="utf-8")
    print(json.dumps(exp, indent=2))


if __name__ == "__main__":
    main()
