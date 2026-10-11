"""The estimators: the weighted median and the stratified bootstrap.

Statewide results are weighted medians: each segment counts with its sampling weight (or the km of pipe it stands
for). Their 95% intervals come from a bootstrap that resamples segments within their sampling strata.
"""
import numpy as np
import pandas as pd


def wmedian(v: np.ndarray, w: np.ndarray) -> float:
    """Weighted median of the values v with weights w (NumPy arrays): going up from the smallest value, the first
    value at which the running total of the weights reaches half of all the weight."""
    o = np.argsort(v)
    c = np.cumsum(w[o])
    return float(v[o][np.searchsorted(c, c[-1] / 2)])


def strata_groups(strata, sort: bool = True) -> list[np.ndarray]:
    """The row positions of each stratum: strata in sorted order, or with sort=False in order of first appearance.
    Rows with no stratum are left out. The order decides which random draws go to which stratum, so a script that
    must repeat its earlier intervals keeps its own order."""
    codes, uniques = pd.factorize(np.asarray(strata, dtype=object), sort=sort)
    return [np.flatnonzero(codes == k) for k in range(len(uniques))]


def resample(groups: list[np.ndarray], rng: np.random.Generator) -> np.ndarray:
    """One stratified bootstrap draw: from each stratum, as many rows as it has, drawn with replacement. Returns row
    positions, stratum by stratum."""
    return np.concatenate([g[rng.integers(0, len(g), len(g))] for g in groups])


def bootstrap(stat, groups: list[np.ndarray], draws: int, rng: np.random.Generator) -> list:
    """stat(rows) for each of `draws` stratified bootstrap draws, rows being the drawn row positions."""
    return [stat(resample(groups, rng)) for _ in range(draws)]
