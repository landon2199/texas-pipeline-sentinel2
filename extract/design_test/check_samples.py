"""What the 2-piece sample (0-50 m rings of 7,664 segments, spring 2025) can already tell us."""
import numpy as np
import pandas as pd

D = r"C:/mydrive/Graduate School/Courses/GEOG_392/projects/outputs/tests/design_test_2026-10-06/ee_results"
IDX = ["NDVI", "NDMI", "SAVI", "MNDWI", "NDRE", "S2REP", "BSI"]

pi = pd.read_csv(fr"{D}\zones_27_rings_per_image_2025_sample2.csv")
co = pd.read_csv(fr"{D}\zones_27_rings_composite_2025_sample2.csv")
print(f"per-image rows {len(pi):,}; zones {pi.zone_id.nunique():,}; images {pi.image.nunique()}; dates {pi.date.nunique()}; orbits {sorted(pi.orbit.unique())}")

# 1. the same zone, same date and orbit, seen in two overlapping tiles
key = ["zone_id", "landcover", "date", "orbit"]
dup = pi.duplicated(key, keep=False)
print(f"rows that repeat a zone-date-orbit from another tile: {dup.sum():,} of {len(pi):,} ({dup.mean():.1%})")
same = pi[dup].groupby(key)["NDVI_mean"].agg(lambda s: s.max() - s.min())
print(f"  NDVI spread between the repeated tiles: median {same.median():.4f}, 95th pct {same.quantile(.95):.4f}")

# keep one row per zone-date-orbit (the tile with the most clear pixels)
one = pi.sort_values("NDVI_count", ascending=False).drop_duplicates(key)
dates = one.groupby("zone_id")["date"].nunique()
print(f"clear dates per zone: median {dates.median():.0f}, 10th pct {dates.quantile(.1):.0f}, min {dates.min()}, zones with < 5 dates {int((dates < 5).sum())}")

# 2. image-by-image vs composite, per zone and land cover class
w = one.assign(px=one.NDVI_count)
g = w.groupby(["zone_id", "landcover"])
pim = g[[f"{i}_mean" for i in IDX]].median()          # median over dates of the zone mean
pim["n_dates"] = g["date"].nunique()
pim["px"] = g["px"].median()
m = pim.join(co.set_index(["zone_id", "landcover"])[[f"{i}_median_mean" for i in IDX] + ["NDVI_median_count"]], how="inner")
m = m[(m.n_dates >= 5) & (m.NDVI_median_count >= 10)]
print(f"\nzone-land cover pairs compared: {len(m):,}")
print(f"{'index':6} {'r':>6} {'bias (image - composite)':>26} {'RMSE':>8}")
for i in IDX:
    a, b = m[f"{i}_mean"], m[f"{i}_median_mean"]
    ok = a.notna() & b.notna()
    a, b = a[ok], b[ok]
    print(f"{i:6} {np.corrcoef(a, b)[0, 1]:6.3f} {np.mean(a - b):26.4f} {np.sqrt(np.mean((a - b) ** 2)):8.4f}")

# 3. land pixels left in each 0-50 m ring after clouds and water
px = co.groupby("zone_id")["NDVI_median_count"].sum()
print(f"\nland pixels per 0-50 m ring (all land cover): median {px.median():.0f} of ~1,000; rings under 100 pixels: {int((px < 100).sum())}")
lc = co.groupby("landcover")["NDVI_median_count"].sum().sort_values(ascending=False)
print("pixels by NLCD class:", (lc / lc.sum()).round(3).head(8).to_dict())
