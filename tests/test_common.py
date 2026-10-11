"""Unit tests for common/: the weighted median, the stratified bootstrap, the ring labels, the diameter classes and the
project path. Run from the repository folder: python -m pytest tests"""
import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from common import codes, config, rings, stats

ROOT = Path(__file__).resolve().parents[1]


def wmedian_before_refactor(v, w):
    """The weighted median as six scripts had copied it before the refactor."""
    o = np.argsort(v)
    c = np.cumsum(w[o])
    return v[o][np.searchsorted(c, c[-1] / 2)]


# ---- weighted median ---------------------------------------------------------------------------------------------
def test_wmedian_equal_weights():
    assert stats.wmedian(np.array([3.0, 1.0, 2.0]), np.ones(3)) == 2.0
    assert stats.wmedian(np.array([4.0, 1.0, 3.0, 2.0]), np.ones(4)) == 2.0      # even count: the lower middle value
    assert stats.wmedian(np.array([7.5]), np.array([0.2])) == 7.5


def test_wmedian_weights_move_it():
    v = np.array([1.0, 2.0, 3.0, 4.0])
    assert stats.wmedian(v, np.array([1.0, 1.0, 1.0, 10.0])) == 4.0
    assert stats.wmedian(v, np.array([10.0, 1.0, 1.0, 1.0])) == 1.0
    assert stats.wmedian(v, np.array([1.0, 1.0, 2.0, 0.0])) == 2.0          # running total reaches exactly half at 2


def test_wmedian_is_a_float_and_order_free():
    rng = np.random.default_rng(0)
    v = np.round(rng.normal(size=501), 2)                                     # rounding makes ties
    w = rng.uniform(1, 200, size=501)
    m = stats.wmedian(v, w)
    assert type(m) is float
    for _ in range(5):
        p = rng.permutation(len(v))
        assert stats.wmedian(v[p], w[p]) == m


def test_wmedian_matches_the_copies_it_replaced():
    rng = np.random.default_rng(392)
    for n in (1, 2, 3, 10, 101, 3499):
        v = np.round(rng.normal(0, 0.02, n), 4)
        for w in (np.ones(n), rng.uniform(1, 300, n), rng.integers(1, 9, n).astype(float)):
            assert stats.wmedian(v, w) == wmedian_before_refactor(v, w)


# ---- stratified bootstrap ----------------------------------------------------------------------------------------
STRATA = np.array(["b", "a", "c", "a", "b", "b", "c", "a", "a"], dtype=object)


def test_strata_groups_order():
    assert [g.tolist() for g in stats.strata_groups(STRATA)] == [[1, 3, 7, 8], [0, 4, 5], [2, 6]]
    assert [g.tolist() for g in stats.strata_groups(STRATA, sort=False)] == [[0, 4, 5], [1, 3, 7, 8], [2, 6]]


def test_strata_groups_leave_out_missing_and_match_pandas():
    s = pd.Series(["x", np.nan, "y", "x", np.nan, "z"])
    assert [g.tolist() for g in stats.strata_groups(s)] == [[0, 3], [2], [5]]
    by_pandas = [g.to_numpy() for g in s.to_frame("k").groupby("k").groups.values()]
    assert all((a == b).all() for a, b in zip(stats.strata_groups(s), by_pandas))


def test_resample_shape_and_strata():
    groups = stats.strata_groups(STRATA)
    pick = stats.resample(groups, np.random.default_rng(1))
    assert pick.shape == (len(STRATA),)
    start = 0
    for g in groups:                                   # each stratum's block holds only that stratum's rows
        block = pick[start:start + len(g)]
        assert set(block) <= set(g)
        start += len(g)


def test_bootstrap_seed_behavior():
    groups = stats.strata_groups(STRATA)
    v = np.arange(len(STRATA), dtype=float)
    w = np.ones(len(STRATA))
    stat = lambda i: stats.wmedian(v[i], w[i])  # noqa: E731
    a = stats.bootstrap(stat, groups, 200, np.random.default_rng(392))
    b = stats.bootstrap(stat, groups, 200, np.random.default_rng(392))
    c = stats.bootstrap(stat, groups, 200, np.random.default_rng(393))
    assert len(a) == 200 and a == b and a != c
    assert stats.bootstrap(stat, groups, 0, np.random.default_rng(392)) == []


def test_bootstrap_repeats_the_draws_of_the_old_loops():
    """The scripts drew with rng.integers (corridor, size_standardized, clearing_calibration) or rng.choice (coverage_estimate,
    man_made_check); both give the same draws as resample, so the intervals did not move."""
    rng_old, rng_choice, rng_new = (np.random.default_rng(392) for _ in range(3))
    strata = np.random.default_rng(0).choice(["27 | Crude oil | 16-24 in", "25 | Natural gas | 4.5-8.6 in", "30 | Other"], 300)
    v, w = np.random.default_rng(1).normal(size=300), np.random.default_rng(2).uniform(1, 50, 300)
    groups_old = [np.flatnonzero(strata == s) for s in np.unique(strata)]
    old = []
    for _ in range(50):
        pick = np.concatenate([g[rng_old.integers(0, len(g), len(g))] for g in groups_old])
        old.append(wmedian_before_refactor(v[pick], w[pick]))
    choice = [wmedian_before_refactor(v[i], w[i]) for i in (np.concatenate([rng_choice.choice(g, len(g)) for g in groups_old])
                                                              for _ in range(50))]
    new = stats.bootstrap(lambda i: stats.wmedian(v[i], w[i]), stats.strata_groups(strata), 50, rng_new)
    assert new == old == choice


# ---- ring and band labels ----------------------------------------------------------------------------------------
def test_zone_ids_split_and_build():
    z = pd.Series(["003-003901-25-0-0_r0-50", "127-006093-27-1-12_r500-1000", "003-003901-25-0-0_r450-500"])
    t = rings.split_zone_ids(z)
    assert list(t.columns) == ["segment_id", "ring"]
    assert t["segment_id"].tolist() == ["003-003901-25-0-0", "127-006093-27-1-12", "003-003901-25-0-0"]
    assert t["ring"].tolist() == ["0-50", "500-1000", "450-500"]
    assert rings.segment_of(z).tolist() == t["segment_id"].tolist()
    assert rings.zone_id("003-003901-25-0-0", rings.ring_name(0, 50)) == z[0]
    assert (rings.zone_id(t["segment_id"], t["ring"]) == z).all()
    assert z[1].endswith(rings.suffix(rings.COMPARISON)) and z[0].endswith(rings.suffix(rings.BAND))


def test_ring_order_and_labels():
    bands = ["500-1000", "50-100", "100-150", "0-50", "450-500"]
    assert rings.by_distance(bands) == ["0-50", "50-100", "100-150", "450-500", "500-1000"]
    assert rings.ring_start("250-500 m") == 250 and rings.ring_start("0-50") == 0
    assert rings.label("0-50") == "0-50 m"
    assert rings.pooling(["100-250=100-150,150-200,200-250", "0-50=0-50"]) == {
        "100-150": "100-250", "150-200": "100-250", "200-250": "100-250", "0-50": "0-50"}


# ---- diameter classes --------------------------------------------------------------------------------------------
def test_diameter_classes_at_the_breaks():
    d = pd.Series([0.5, 4.49, 4.5, 8.62, 8.63, 12.75, 15.99, 16, 24, 36, 48, np.nan, -2.0])
    assert codes.diameter_class(d).tolist() == [
        "Under 4.5 in", "Under 4.5 in", "4.5-8.6 in", "4.5-8.6 in", "8.6-12.75 in", "12.75-16 in", "12.75-16 in", "16-24 in",
        "24-36 in", "Over 36 in", "Over 36 in", "Not recorded", "Not recorded"]
    assert len(codes.DIAMETER_CLASSES) == len(codes.DIAMETER_BREAKS) - 1


def test_zone_labels_use_the_same_classes():
    sys.path.insert(0, str(ROOT / "zones"))
    labels = importlib.import_module("labels")
    df = pd.DataFrame({"COMMODITY1": ["CRO", "NGG", "XX"], "DIAMETER": ["8.63", "0", None], "STATUS_CD": ["I", "B", None],
                       "INTERSTATE": ["N", "Y", None], "QUALITY_CD": ["E", "V", None], "COUNTY": ["1", "201", "35"]})
    out = labels.add_labels(df)
    assert out["diameter_class"].tolist() == ["8.6-12.75 in", "Not recorded", "Not recorded"]
    assert labels.DIAMETER_CLASSES == codes.DIAMETER_CLASSES and labels.DIAMETER_BREAKS == codes.DIAMETER_BREAKS


def test_nlcd_names():
    assert codes.NLCD[11][0] == "Open water" and codes.NLCD[95][0] == "Herbaceous wetlands"
    grouped = sorted(c for cs in codes.NLCD_GROUPS.values() for c in cs)
    assert grouped == sorted(codes.NLCD)                       # every class in exactly one group


# ---- project path ------------------------------------------------------------------------------------------------
def test_project_path_default_and_override(monkeypatch, tmp_path):
    monkeypatch.delenv("GEOG392_PROJECT", raising=False)
    c = importlib.reload(config)
    assert c.P == Path(r"C:\mydrive\Graduate School\Courses\GEOG_392\projects")
    monkeypatch.setenv("GEOG392_PROJECT", str(tmp_path))
    c = importlib.reload(config)
    assert c.P == tmp_path and c.R == tmp_path / "outputs" / "results" and c.STATS == tmp_path / "outputs" / "geog392_zone_stats"
    assert c.CORRIDOR == tmp_path / "outputs" / "results" / "corridor_sample_v1_9springs_pooled"
    assert c.JOBS_LOG == ROOT / "extract" / "jobs_log.csv"
    monkeypatch.delenv("GEOG392_PROJECT")
    importlib.reload(config)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
