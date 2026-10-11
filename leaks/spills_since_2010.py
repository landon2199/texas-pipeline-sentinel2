"""Plan D30: the spill list back to 2010, with the same rules as the Sentinel-2 list (leaks/figure_proposal.py).

Rules: PHMSA hazardous liquid accidents in Texas, on the right-of-way, crude oil, refined product or biofuel (not
highly volatile liquids, which evaporate, or CO2), 5 barrels or more, with coordinates. The 83 spills since June 2018
keep their ids (S001-S083, matched by PHMSA report number); the earlier ones get new ids from S084 on, oldest last.
Writes data/statewide/spills_right_of_way_since_2010.gpkg (same fields as the starter list) and prints the counts.
Usage: python spills_since_2010.py
"""
from pathlib import Path

import geopandas as gpd
import pandas as pd

P = Path(r"C:\mydrive\Graduate School\Courses\GEOG_392\projects")
CODE = P / "code (do not edit)"
START = "2010-01-01"


def main():
    pts = gpd.read_file(CODE / "outputs" / "phmsa_texas_accidents.gpkg")
    keep = (pts["LOCATION_TYPE"].fillna("").str.contains("RIGHT-OF-WAY")
            & pts["COMMODITY_RELEASED_TYPE"].fillna("").str.contains("CRUDE|REFINED|BIOFUEL")
            & (pts["UNINTENTIONAL_RELEASE_BBLS"] >= 5))
    s = pts[keep].copy()
    s["date"] = pd.to_datetime(s["LOCAL_DATETIME"], errors="coerce")
    s = s[s["date"] >= START].to_crs(4326)
    eco = gpd.read_file(P / "data" / "statewide" / "ecoregions_epa_l3_texas.gpkg").to_crs(4326)
    name = "us_l3name" if "us_l3name" in eco else [c for c in eco.columns if "name" in c.lower()][0]
    s = gpd.sjoin(s, eco[[name, "geometry"]], how="left", predicate="within").rename(columns={name: "ecoregion"})
    s = s.drop_duplicates("REPORT_NUMBER")
    old = gpd.read_file(P / "data" / "starter" / "spills_right_of_way_since_mid2018.gpkg")
    ids = dict(zip(old["report_number"].astype(str), old["spill_id"]))
    s["report_number"] = s["REPORT_NUMBER"].astype(str)
    s["spill_id"] = s["report_number"].map(ids)
    new = s[s["spill_id"].isna()].sort_values("date", ascending=False)
    s.loc[new.index, "spill_id"] = [f"S{i:03d}" for i in range(len(old) + 1, len(old) + 1 + len(new))]
    out = gpd.GeoDataFrame({"spill_id": s["spill_id"], "report_number": s["report_number"],
                            "date": s["date"].dt.strftime("%Y-%m-%d"), "barrels": s["UNINTENTIONAL_RELEASE_BBLS"],
                            "commodity": s["COMMODITY_RELEASED_TYPE"], "cause": s["CAUSE"], "ecoregion": s["ecoregion"]},
                           geometry=s.geometry, crs=4326).sort_values("spill_id")
    f = P / "data" / "statewide" / "spills_right_of_way_since_2010.gpkg"
    out.to_file(f, driver="GPKG")
    y = pd.to_datetime(out["date"]).dt.year.value_counts().sort_index()
    print(f"wrote {f}: {len(out)} spills ({out['spill_id'].isin(old['spill_id']).sum()} kept from the Sentinel-2 list, "
          f"{len(new)} new); by year {y.to_dict()}")


if __name__ == "__main__":
    main()
