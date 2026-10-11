"""Gap 13: linear referencing. Where each reported spill sits along its pipeline, as a route event.

Pipeline companies locate everything by route and measure (station), as in Esri's Utility and Pipeline Data Model
(UPDM) and ArcGIS Pipeline Referencing. The segments already carry start_m/end_m along their line (build_zones.py);
this adds the spills as point events on the same routes:
  - route = line_uid, measure = meters along the line, and the engineering station in feet ('123+45');
  - offset = the spill's distance from the line, with the side (left or right, looking along the line's digitized
    direction), as an event table's offset field;
  - the segment the spill falls on, and whether the measure runs along the whole line or only along one part of a line
    whose parts don't join (then each part restarts at 0, and the measure is only good within that part).
The routes are the published Railroad Commission lines, so measures are along the mapped line, not the true pipe
(see geoai/row_survey.py for how far apart those are). Open source (shapely); arcgis_stations_check.py repeats it with
ArcGIS Pro's Locate Features Along Routes as the side-by-side check.
Writes outputs/zones/statewide/spill_stations.csv and the routes' segment table for the strip diagram,
outputs/zones/statewide/route_segments.parquet (GeoParquet, the lines of every route that has a spill).
Usage: python stations.py
"""
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import shapely

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.config import S  # noqa: E402
from labels import station  # noqa: E402

SEG_COLS = ["segment_id", "line_uid", "ecoregion", "piece_m", "start_m", "end_m", "start_station", "end_station",
            "commodity", "service", "diameter_in", "location_accuracy", "status", "county_fips", "has_zones", "has_comparison"]


def route_segments(uids) -> gpd.GeoDataFrame:
    where = "line_uid IN (" + ",".join(f"'{u}'" for u in sorted(uids)) + ")"
    parts = [pyogrio.read_dataframe(f, layer="segments", columns=SEG_COLS, where=where)
             for f in sorted(S.glob("[0-9][0-9]_*.gpkg"))]
    seg = pd.concat([p for p in parts if len(p)], ignore_index=True)
    seg["part"] = seg["segment_id"].str.rsplit("-", n=2).str[1].astype(int)
    # a line whose parts don't join restarts every part at 0 (build_zones.segments_for); flag those routes
    starts = seg[seg["segment_id"].str.endswith("-0")].groupby("line_uid")["start_m"].apply(lambda s: (s == 0).sum())
    seg["measure_along"] = np.where(seg["line_uid"].map(starts).fillna(0) > 1, "this part only", "whole line")
    return seg


def locate(spills: gpd.GeoDataFrame, seg: gpd.GeoDataFrame) -> pd.DataFrame:
    rows = []
    for s in spills.itertuples():
        mine = seg[seg["line_uid"] == s.line_uid]
        if mine.empty:
            rows.append({"spill_id": s.spill_id, "line_uid": s.line_uid})
            continue
        d = mine.geometry.distance(s.geometry).to_numpy()
        g = mine.iloc[int(np.argmin(d))]
        along = g.geometry.project(s.geometry)
        a, b = shapely.line_interpolate_point(g.geometry, [max(along - 1, 0), min(along + 1, g.geometry.length)])
        cross = (b.x - a.x) * (s.geometry.y - a.y) - (b.y - a.y) * (s.geometry.x - a.x)
        m = g.start_m + along
        rows.append({"spill_id": s.spill_id, "report_number": s.report_number, "date": s.date, "barrels": s.barrels,
                     "route": s.line_uid, "measure_m": round(m, 1), "station": station([m])[0],
                     "offset_m": round(float(d.min()), 1), "side": "left" if cross > 0 else "right",
                     "segment_id": g.segment_id, "measure_along": g.measure_along, "route_km": seg.loc[seg["line_uid"] == s.line_uid, "end_m"].max() / 1000,
                     "ecoregion": g.ecoregion, "location_accuracy": g.location_accuracy})
    return pd.DataFrame(rows)


def main():
    sp = gpd.read_file(S / "spills_statewide.gpkg", layer="spills_matched")
    seg = route_segments(sp["line_uid"].dropna().unique())
    seg = gpd.GeoDataFrame(seg, geometry="geometry", crs=pyogrio.read_info(next(S.glob("[0-9][0-9]_*.gpkg")), layer="segments")["crs"])
    sp = sp.to_crs(seg.crs)
    ev = locate(sp, seg)
    ev.to_csv(S / "spill_stations.csv", index=False)
    seg.to_parquet(S / "route_segments.parquet")
    check = S / "stations_check.gpkg"                   # inputs for arcgis_stations_check.py
    seg[["segment_id", "line_uid", "start_m", "end_m", "geometry"]].to_file(check, layer="route_segments", driver="GPKG")
    sp[["spill_id", "line_uid", "geometry"]].to_file(check, layer="spills", driver="GPKG")
    ok = ev["measure_m"].notna()
    print(f"{ok.sum()} of {len(ev)} spills located on {ev.loc[ok, 'route'].nunique()} routes; "
          f"{(ev['measure_along'] == 'this part only').sum()} on routes whose parts don't join; "
          f"offset median {ev['offset_m'].median():.0f} m (max {ev['offset_m'].max():.0f} m)")
    print(ev.loc[ok, ["route", "station", "offset_m", "side", "measure_along", "route_km"]].head(8).to_string(index=False))


if __name__ == "__main__":
    main()
