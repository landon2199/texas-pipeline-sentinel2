"""Two design checks on the Central Great Plains zones, run locally (no Earth Engine):
1. Comparison-ring contamination: how much of each ring lies closer to SOME pipeline than the ring's own band says
   (e.g. a 500-1,000 m comparison ring that has another line running through it).
2. Overlap: how many zones cover the same ground, i.e. how many times Earth Engine measures the same pixel.
"""
import numpy as np
import pandas as pd
import pyogrio
import shapely
from pyproj import Transformer

Z = r"C:\mydrive\Graduate School\Courses\GEOG_392\projects\outputs\tests\design_test_2026-10-06\zones_before_cleaning\27_central_great_plains.gpkg"
L = r"C:\mydrive\Graduate School\Courses\GEOG_392\projects\data\statewide\pipelines_texas_rrc_20261006.gpkg"

seg = pyogrio.read_dataframe(Z, layer="segments", columns=["segment_id", "has_zones", "location_accuracy", "line_uid"])
rings = pyogrio.read_dataframe(Z, layer="rings", columns=["zone_id", "segment_id", "ring", "inner_m", "outer_m", "area_m2"])
print(f"segments {len(seg):,}; rings {len(rings):,}; CRS {rings.crs}")

# every pipeline line (all statuses) near the region, statewide file, projected like the zones
xmin, ymin, xmax, ymax = rings.total_bounds
to_ll = Transformer.from_crs(rings.crs, "EPSG:4267", always_xy=True)
lon, lat = to_ll.transform([xmin - 2000, xmax + 2000, xmin - 2000, xmax + 2000], [ymin - 2000, ymin - 2000, ymax + 2000, ymax + 2000])
lines = pyogrio.read_dataframe(L, layer="pipelines", columns=["STATUS_CD"], bbox=(min(lon), min(lat), max(lon), max(lat)))
lines = lines.to_crs(rings.crs)
geoms = lines.geometry.values
tree = shapely.STRtree(geoms)
print(f"pipeline lines near the region: {len(lines):,}")

# 1. contamination, on a random sample of 2,000 segments with zones
rng = np.random.default_rng(392)
ids = rng.choice(seg.loc[seg.has_zones.astype(bool), "segment_id"].to_numpy(), 2000, replace=False)
sub = rings[rings.segment_id.isin(ids) & (rings.inner_m > 0)]
out = []
for zid, ring, inner, g in zip(sub.zone_id, sub.ring, sub.inner_m, sub.geometry.values):
    near = tree.query(g, predicate="dwithin", distance=inner)
    if len(near) == 0:
        frac = 0.0
    else:
        band = shapely.union_all(shapely.buffer(geoms[near], inner, quad_segs=4))
        frac = shapely.area(shapely.intersection(g, band)) / shapely.area(g)
    out.append((zid, ring, frac))
c = pd.DataFrame(out, columns=["zone_id", "ring", "frac"])
print("\nshare of each ring's area that is closer to some pipeline than the ring's inner edge")
print(c.groupby("ring", sort=False)["frac"].describe(percentiles=[.5, .9]).round(3).to_string())
cmp = c[c.ring == "500-1000 m"]
print(f"comparison rings with over 10% contaminated: {(cmp.frac > .10).mean():.1%}; over 50%: {(cmp.frac > .50).mean():.1%}")
cmp = cmp.assign(segment_id=cmp.zone_id.str.rsplit("_r", n=1).str[0]).merge(seg[["segment_id", "location_accuracy"]], on="segment_id")
print(cmp.groupby("location_accuracy")["frac"].agg(["size", "mean"]).round(3).to_string())

# 2. overlap: random points, how many zones contain each one
pts = shapely.points(rng.uniform(xmin, xmax, 300_000), rng.uniform(ymin, ymax, 300_000))
zt = shapely.STRtree(rings.geometry.values)
hit_pt, _ = zt.query(pts, predicate="within")
n = np.bincount(hit_pt, minlength=len(pts))
covered = n[n > 0]
print(f"\nzone layers over the same ground (points inside at least one zone): mean {covered.mean():.2f}, median {np.median(covered):.0f}, 90th pct {np.quantile(covered, .9):.0f}")
print(f"sum of zone areas / ground they cover = {covered.mean():.2f}  (each pixel measured that many times per image)")
