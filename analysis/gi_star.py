"""Open-source Getis-Ord Gi* hot spot bins that reproduce ArcGIS Pro's Hot Spot Analysis (NumPy and SciPy only).

Gi* of Ord and Getis (1995), as ArcGIS documents it: binary weights over each point's k nearest neighbors plus the
point itself,

    Gi* = (sum_j w_ij x_j - xbar * sum_j w_ij) / (S * sqrt((n * sum_j w_ij^2 - (sum_j w_ij)^2) / (n - 1)))

with S the population standard deviation of x. Two-sided normal p-values, and the false discovery rate correction
(Benjamini-Hochberg) at each confidence level, so the bins read like ArcGIS's Gi_Bin: +-3 for 99%, +-2 for 95%, +-1
for 90%, 0 for not significant. The agents and the analyses use this by default; ArcGIS Pro stays an option
(analysis/arcgis_gi_by_spring.py, agent/arcgis_hotspots.py) for the course, and the two were checked against each other.
"""
import numpy as np
from scipy import stats
from scipy.spatial import cKDTree


def bh_cut(p: np.ndarray, alpha: float) -> float:
    """The Benjamini-Hochberg p-value threshold at level alpha (0 when nothing passes)."""
    s = np.sort(p)
    ok = s <= alpha * np.arange(1, len(s) + 1) / len(s)
    return s[ok].max() if ok.any() else 0.0


def gi_bins(xy: np.ndarray, values: np.ndarray, k: int = 8, apply_fdr: bool = True):
    """xy: (n, 2) projected coordinates; values: (n,). Returns the Gi* z-scores and the bins."""
    x = np.asarray(values, dtype=float)
    n = len(x)
    _, nb = cKDTree(np.asarray(xy, dtype=float)).query(xy, k=k + 1)    # the point itself and its k nearest
    wsum = k + 1.0                                                     # binary weights: sum_j w_ij = sum_j w_ij^2
    xbar, s = x.mean(), x.std()
    z = (x[nb].sum(axis=1) - xbar * wsum) / (s * np.sqrt((n * wsum - wsum ** 2) / (n - 1)))
    p = 2 * stats.norm.sf(np.abs(z))
    bins = np.zeros(n, dtype=int)
    for level, alpha in ((1, 0.10), (2, 0.05), (3, 0.01)):
        hit = p <= (bh_cut(p, alpha) if apply_fdr else alpha)
        bins[hit] = np.sign(z[hit]).astype(int) * level
    return z, bins
