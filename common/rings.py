"""Zone and ring labels.

A ring is named by its inner and outer distance from the line in meters, "0-50"; a zone_id is the segment_id, "_r"
and the ring: "003-003901-25-0-0_r0-50". Result tables write the ring with its unit, "0-50 m". The 500-1,000 m ring
is every segment's comparison ring, and the 0-50 m band the one next to the pipe.
"""
import pandas as pd

BAND = "0-50"
COMPARISON = "500-1000"


def ring_name(inner, outer) -> str:
    """'0-50' for the ring from 0 to 50 m."""
    return f"{inner}-{outer}"


def label(ring: str) -> str:
    """'0-50 m': a ring as result tables write it."""
    return f"{ring} m"


def suffix(ring: str) -> str:
    """'_r0-50': how the zone_ids of a ring end."""
    return f"_r{ring}"


def zone_id(segment_id, ring):
    """A zone's ID from its segment and ring; both may be strings or pandas Series."""
    return segment_id + "_r" + ring


def split_zone_ids(zone_ids: pd.Series) -> pd.DataFrame:
    """Columns segment_id and ring ('0-50') from zone_ids."""
    return zone_ids.str.rsplit("_r", n=1, expand=True).set_axis(["segment_id", "ring"], axis=1)


def segment_of(zone_ids: pd.Series) -> pd.Series:
    """The segment_id of each zone_id."""
    return zone_ids.str.rsplit("_r", n=1).str[0]


def ring_start(ring: str) -> int:
    """A ring's inner distance in meters, from '50-100' or '50-100 m'."""
    return int(ring.split("-")[0])


def by_distance(rings) -> list[str]:
    """Rings nearest first (50-100 before 100-150, which text sorting gets wrong)."""
    return sorted(rings, key=ring_start)


def pooling(groups) -> dict[str, str]:
    """Narrow band -> wide ring, from specs like '100-250=100-150,150-200,200-250' (corridor.py --pool)."""
    out = {}
    for g in groups:
        wide, parts = g.split("=")
        out.update({p: wide for p in parts.split(",")})
    return out
