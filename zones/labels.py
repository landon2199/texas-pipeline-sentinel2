"""Readable, queryable labels for the Railroad Commission's pipeline codes, from its TPMS attribute definitions.

Every zone keeps the published fields unchanged; these functions add clean fields beside them (a code and a readable
name), so a dashboard can filter on any of them. Source: Railroad Commission of Texas, "TPMS attribute definitions and
valid codes" (rrc.texas.gov/media/vjxom1id/tpmsattributedefinitionsandvalidcodes.pdf).
"""
import numpy as np
import pandas as pd

# COMMODITY1 code: (commodity, service, commodity group)
COMMODITY = {
    "AA": ("Anhydrous ammonia", "Transmission", "Other"),
    "CO2": ("Carbon dioxide", "Transmission", "Other"),
    "CRO": ("Crude oil", "Transmission", "Crude oil"),
    "CRL": ("Crude oil", "Gathering", "Crude oil"),
    "CFL": ("Crude full well stream", "Gathering", "Crude oil"),
    "CRA": ("Crude oil, offshore", "Offshore gathering", "Crude oil"),
    "HVL": ("Highly volatile liquid", "Transmission", "Highly volatile liquid"),
    "NGT": ("Natural gas", "Transmission", "Natural gas"),
    "NGG": ("Natural gas", "Gathering", "Natural gas"),
    "NFG": ("Natural gas, full well stream", "Gathering", "Natural gas"),
    "NGZ": ("Natural gas, offshore", "Offshore gathering", "Natural gas"),
    "PRD": ("Refined liquid product", "Transmission", "Refined product"),
    "OGT": ("Other gas", "Transmission", "Other"),
}
STATUS = {"I": "In service", "B": "Abandoned", "R": "Revoked (code not in the RRC definitions; inferred)"}
INTERSTATE = {"Y": "Interstate", "N": "Intrastate"}
# QUALITY_CD: the operator's estimate of positional accuracy -> (label, largest error in meters)
QUALITY = {"E": ("Within 50 ft", 15.2), "V": ("51-300 ft", 91.4), "G": ("301-500 ft", 152.4),
           "P": ("501-1,000 ft", 304.8), "U": ("Unknown", np.nan)}
DIAMETER_BREAKS = [0, 4.5, 8.63, 12.75, 16, 24, 36, np.inf]          # outside diameters, inches
DIAMETER_CLASSES = ["Under 4.5 in", "4.5-8.6 in", "8.6-12.75 in", "12.75-16 in", "16-24 in", "24-36 in", "Over 36 in"]


def add_labels(df: pd.DataFrame) -> pd.DataFrame:
    """Add the clean fields. Unknown codes are labeled 'Not in the RRC code list', never dropped."""
    out = df.copy()
    code = out["COMMODITY1"].astype("string").str.strip().str.upper()
    known = code.map(COMMODITY)
    out["commodity_code"] = code
    out["commodity"] = known.map(lambda v: v[0] if isinstance(v, tuple) else "Not in the RRC code list")
    out["service"] = known.map(lambda v: v[1] if isinstance(v, tuple) else "Unknown")
    out["commodity_group"] = known.map(lambda v: v[2] if isinstance(v, tuple) else "Unknown")
    d = pd.to_numeric(out["DIAMETER"], errors="coerce")
    out["diameter_in"] = d.where(d > 0)
    out["diameter_class"] = pd.cut(out["diameter_in"], DIAMETER_BREAKS, labels=DIAMETER_CLASSES, right=False).astype("string").fillna("Not recorded")
    status = out["STATUS_CD"].astype("string").str.strip().str.upper()
    out["status"] = status.map(STATUS).fillna("Not recorded")
    # GeoPackage field names ignore case, so a label must never share a published field's name (INTERSTATE).
    out["interstate_type"] = out["INTERSTATE"].astype("string").str.strip().str.upper().map(INTERSTATE).fillna("Not recorded")
    q = out["QUALITY_CD"].astype("string").str.strip().str.upper()
    out["location_accuracy"] = q.map(lambda c: QUALITY[c][0] if c in QUALITY else "Not recorded")
    out["location_error_max_m"] = q.map(lambda c: QUALITY[c][1] if c in QUALITY else np.nan)
    out["county_fips"] = "48" + out["COUNTY"].astype("string").str.strip().str.zfill(3)
    return out


def station(meters) -> np.ndarray:
    """Engineering stationing in feet, as on pipeline alignment sheets: 3,749 m -> '123+00'."""
    feet = np.rint(np.asarray(meters, dtype=float) * 3.28084).astype(np.int64)
    return np.char.add(np.char.add((feet // 100).astype(str), "+"), np.char.zfill((feet % 100).astype(str), 2))
