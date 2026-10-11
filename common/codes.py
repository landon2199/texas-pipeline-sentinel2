"""Class names shared by the scripts: pipe diameter classes and NLCD land cover.

Diameter classes follow the Railroad Commission's outside diameters (zones/labels.py adds them to every segment);
NLCD classes are the National Land Cover Database 2021 legend, with its standard colors.
"""
import numpy as np
import pandas as pd

DIAMETER_BREAKS = [0, 4.5, 8.63, 12.75, 16, 24, 36, np.inf]          # outside diameters, inches
DIAMETER_CLASSES = ["Under 4.5 in", "4.5-8.6 in", "8.6-12.75 in", "12.75-16 in", "16-24 in", "24-36 in", "Over 36 in"]
NOT_RECORDED = "Not recorded"


def diameter_class(inches: pd.Series) -> pd.Series:
    """Each diameter's class; a break belongs to the class above it (4.5 in is '4.5-8.6 in'). Missing or negative
    diameters are 'Not recorded'."""
    return pd.cut(inches, DIAMETER_BREAKS, labels=DIAMETER_CLASSES, right=False).astype("string").fillna(NOT_RECORDED)


NLCD = {11: ("Open water", "#466b9f"), 21: ("Developed, open", "#dec5c5"), 22: ("Developed, low", "#d99282"),
        23: ("Developed, medium", "#eb0000"), 24: ("Developed, high", "#ab0000"), 31: ("Barren", "#b3ac9f"),
        41: ("Deciduous forest", "#68ab5f"), 42: ("Evergreen forest", "#1c5f2c"), 43: ("Mixed forest", "#b5c58f"),
        52: ("Shrub/scrub", "#ccb879"), 71: ("Grassland", "#dfdfc2"), 81: ("Pasture/hay", "#dcd939"),
        82: ("Cultivated crops", "#ab6c28"), 90: ("Woody wetlands", "#b8d9eb"), 95: ("Herbaceous wetlands", "#6c9fb8")}
# NLCD classes grouped for land cover shares (gap_drivers.py)
NLCD_GROUPS = {"developed": [21, 22, 23, 24], "barren": [31], "forest": [41, 42, 43], "shrub": [52], "grassland": [71],
               "pasture": [81], "crops": [82], "wetland": [90, 95], "water": [11]}
