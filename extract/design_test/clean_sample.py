"""Clean rings for the same 200-segment sample that run_part2.py draws (random_state 392).

A ring from a to b meters keeps only ground whose nearest pipeline (any RRC line, any status) is at least a meters
away, so a 500-1,000 m comparison ring contains no ground within 500 m of any pipeline. The 0-50 m ring is unchanged.
"""
import numpy as np
import pandas as pd
import pyogrio
import shapely
from pyproj import Transformer

Z = r"C:\mydrive\Graduate School\Courses\GEOG_392\projects\outputs\tests\design_test_2026-10-06\zones_before_cleaning\27_central_great_plains.gpkg"
L = r"C:\mydrive\Graduate School\Courses\GEOG_392\projects\data\statewide\pipelines_texas_rrc_20261006.gpkg"
OUT = r"C:\mydrive\Graduate School\Courses\GEOG_392\projects\outputs\tests\design_test_2026-10-06"
MIN_KEEP_M2 = 1_000          # 10 pixels at 10 m; smaller leftovers are counted as not measurable

seg = pyogrio.read_dataframe(Z, layer="segments", read_geometry=False, columns=["segment_id", "has_zones"])
ids = seg.loc[seg["has_zones"].astype(bool), "segment_id"].sample(n=200, random_state=392)
quoted = ",".join(f"'{i}'" for i in ids)
rings = pyogrio.read_dataframe(Z, layer="rings", where=f"segment_id IN ({quoted})")
print(f"sample: {ids.size} segments, {len(rings)} rings")

xmin, ymin, xmax, ymax = rings.total_bounds
to_ll = Transformer.from_crs(rings.crs, "EPSG:4267", always_xy=True)
lon, lat = to_ll.transform([xmin - 2000, xmax + 2000, xmin - 2000, xmax + 2000], [ymin - 2000, ymin - 2000, ymax + 2000, ymax + 2000])
lines = pyogrio.read_dataframe(L, layer="pipelines", columns=["STATUS_CD"], bbox=(min(lon), min(lat), max(lon), max(lat))).to_crs(rings.crs)
geoms = lines.geometry.values
tree = shapely.STRtree(geoms)

clean = []
for g, inner in zip(rings.geometry.values, rings.inner_m):
    if inner > 0:
        near = tree.query(g, predicate="dwithin", distance=inner)
        if len(near):
            g = shapely.difference(g, shapely.union_all(shapely.buffer(geoms[near], inner)))
    parts = shapely.get_parts(g)
    parts = parts[(shapely.get_type_id(parts) == 3) & (shapely.area(parts) >= 1)]
    clean.append(shapely.multipolygons(parts) if len(parts) else shapely.Polygon())
rings["clean_m2"] = shapely.area(np.array(clean))
rings["kept_share"] = rings.clean_m2 / rings.area_m2
summary = rings.groupby("ring", sort=False).agg(rings=("zone_id", "size"), kept_share=("kept_share", "mean"),
                                                not_measurable=("clean_m2", lambda a: int((a < MIN_KEEP_M2).sum())))
print(summary.round(3).to_string())

out = rings.set_geometry(clean, crs=rings.crs)[rings.clean_m2 >= MIN_KEEP_M2]
out.to_file(fr"{OUT}\sample200_clean.gpkg", layer="rings_clean", driver="GPKG")
rings.drop(columns="geometry").to_csv(fr"{OUT}\sample200_clean_shares.csv", index=False)
wkt = shapely.to_wkt(np.asarray(out.to_crs(4326).geometry.array), rounding_precision=6)
pd.DataFrame({"zone_id": out["zone_id"].values, "WKT": wkt}).to_csv(fr"{OUT}\sample200_clean_rings.csv", index=False)
print(f"wrote {len(out)} clean rings for upload ({len(rings) - len(out)} too small to measure)")
