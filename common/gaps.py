"""The calibration chain, from corridor.py's per-spring gaps to a statewide number.

corridor.py writes segment_spring.csv: one row per segment (or piece), spring, ring and index, with the ring's gap
against its own comparison ring (diff_same_lc: like-for-like land cover; diff_all: all ground). Every later step
takes the same three steps:
  1. a piece's gap is the median over its springs of one ring's gap (piece_gaps);
  2. the calibrated gap is the band gap x 100 m / the cleared width of the piece's diameter class (calibrated): the
     0-50 m band is 100 m wide for every pipe, but only the strip inside it is cleared;
  3. across pieces, the weighted median (wmedian_of), with the design weights or the km each piece stands for.
"""
import pandas as pd

from .stats import wmedian

BAND_M = 100.0                       # the 0-50 m band, both sides of the line
MEASURES = ("diff_same_lc", "diff_all")


def read_ring(path, ring: str, indices, columns, chunksize: int = 500_000) -> pd.DataFrame:
    """The rows of one ring and the given indices of a segment_spring table, read in chunks (the files are big)."""
    return pd.concat(c[(c["ring"] == ring) & c["index"].isin(indices)]
                     for c in pd.read_csv(path, usecols=columns, chunksize=chunksize))


def piece_gaps(path, keys, ring: str = "0-50 m", indices=("NDVI",), measures=MEASURES, dropna: bool = True) -> pd.DataFrame:
    """Each piece's gap: the median over its springs of each measure, for one ring and the given indices of a
    segment_spring table. keys are the columns that identify a row of the result (segment_id, and index, stratum,
    weight or other attributes to carry along); with dropna, rows missing any key are left out. One row per piece,
    sorted by the keys."""
    keys, measures = list(keys), list(measures)
    d = read_ring(path, ring, list(indices), list(dict.fromkeys(keys + ["ring", "index"] + measures)))
    return d.groupby(keys, dropna=dropna, as_index=False)[measures].median()


def calibrated(gap: pd.Series, diameter_class: pd.Series, widths: pd.Series) -> pd.Series:
    """The cleared strip's own gap: band gap x 100 m / cleared width of the piece's diameter class (widths: cleared
    width in meters by class, as in clearing_calibration's widths.csv)."""
    return gap * BAND_M / diameter_class.map(widths)


def wmedian_of(d: pd.DataFrame, value: str, weight: str) -> float:
    """The weighted median of one column over the rows that have a value."""
    d = d.dropna(subset=[value])
    return wmedian(d[value].to_numpy(float), d[weight].to_numpy(float))
