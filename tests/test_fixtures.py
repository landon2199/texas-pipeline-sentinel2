"""The fixtures (tests/make_fixtures.py) through the calibration chain: the numbers in expected_fixture.json, to 1e-9.

Rule (expected_fixture.json): per segment, the median over springs of diff_same_lc at ring '0-50 m'; the weighted
median with design weights; calibrated = gap x 100 / cleared width of the segment's diameter class.
"""
import json
from pathlib import Path

import pandas as pd
import pytest

from common.gaps import calibrated, piece_gaps, wmedian_of

T = Path(__file__).resolve().parent
F = T / "fixtures"
EXPECTED = json.loads((T / "expected_fixture.json").read_text(encoding="utf-8"))
TOL = 1e-9


@pytest.fixture(scope="module")
def pieces():
    widths = pd.read_csv(F / "widths.csv", index_col=0)["cleared_width_m"]
    per = piece_gaps(F / "segment_spring_small.csv", ["segment_id", "stratum", "weight", "diameter_class"],
                     measures=["diff_same_lc"])
    per["calibrated"] = calibrated(per["diff_same_lc"], per["diameter_class"], widths)
    return per


def test_fixture_segments(pieces):
    assert pieces["segment_id"].nunique() == EXPECTED["fixture_segments"]


def test_band_gap(pieces):
    got = wmedian_of(pieces, "diff_same_lc", "weight")
    assert abs(got - EXPECTED["fixture_weighted_median_band_gap_ndvi_0_50"]) <= TOL


def test_calibrated_gap(pieces):
    got = wmedian_of(pieces, "calibrated", "weight")
    assert abs(got - EXPECTED["fixture_weighted_median_calibrated_gap_ndvi"]) <= TOL


def test_widths_match_the_headline_widths():
    head = json.loads((T / "expected_headlines.json").read_text(encoding="utf-8"))["cleared_width_m"]
    widths = pd.read_csv(F / "widths.csv", index_col=0)["cleared_width_m"]
    assert {k: round(float(v), 3) for k, v in widths.items()} == head
