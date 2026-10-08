"""First ring-versus-comparison results for the 200-segment sample, spring 2025, Central Great Plains.

For every segment and satellite pass: ring value minus the same segment's 500-1,000 m comparison ring, in the same
pass. Two versions: all ground pooled, and like-for-like land cover (each NLCD class compared with the same class,
weighted by the smaller pixel count). Per segment: the median over passes. Across segments: median with a 95%
bootstrap interval (segments resampled).
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio

D = Path(r"C:/mydrive/Graduate School/Courses/GEOG_392/projects/outputs/tests/design_test_2026-10-06/ee_results")
Z = r"C:\mydrive\Graduate School\Courses\GEOG_392\projects\outputs\tests\design_test_2026-10-06\zones_before_cleaning\27_central_great_plains.gpkg"
RUNS = {"current rings, tile by tile": "zones_27_rings_per_image_2025_seg200.csv",
        "current rings, per pass": "zones_27_rings_per_pass_2025_seg200.csv",
        "clean rings, per pass": "zones_27_sample200_clean_per_pass_2025_seg200.csv",
        "clean rings, 20 m": "zones_27_sample200_clean_per_image_2025_seg200_20m_ts1.csv"}
SHOW = ["NDVI", "NDMI", "NDRE", "BSI"]
RINGS = ["0-50", "50-100", "100-250", "250-500"]
MIN_PX = 10
rng = np.random.default_rng(392)


def load(path):
    d = pd.read_csv(path)
    d[["segment_id", "ring"]] = d.zone_id.str.rsplit("_r", n=1, expand=True)
    d = d.sort_values("NDVI_count", ascending=False).drop_duplicates(["zone_id", "landcover", "date", "orbit"])
    return d[d.NDVI_count >= MIN_PX]


def paired(d, idx):
    """Per segment and ring: median over passes of (ring - comparison), pooled and same land cover."""
    key = ["segment_id", "date", "orbit"]
    w = d.assign(v=d[f"{idx}_mean"] * d.NDVI_count)
    pooled = w.groupby(key + ["ring"])[["v", "NDVI_count"]].sum()
    pooled = (pooled.v / pooled.NDVI_count).unstack("ring")
    same = d.set_index(key + ["landcover", "ring"])[[f"{idx}_mean", "NDVI_count"]].unstack("ring")
    res = {}
    for r in RINGS:
        if r not in pooled or "500-1000" not in pooled:
            continue
        p = (pooled[r] - pooled["500-1000"]).dropna()
        m = same[f"{idx}_mean"]
        c = same["NDVI_count"]
        ok = m[r].notna() & m["500-1000"].notna()
        wt = np.minimum(c[r], c["500-1000"])[ok]
        s = ((m[r] - m["500-1000"])[ok] * wt).groupby(level=key).sum() / wt.groupby(level=key).sum()
        res[(r, "all ground")] = p.groupby(level="segment_id").median()
        res[(r, "same land cover")] = s.groupby(level="segment_id").median()
    return res


def summarize(per_seg):
    v = per_seg.dropna().to_numpy()
    boots = np.median(rng.choice(v, (2000, v.size)), axis=1)
    return np.median(v), np.quantile(boots, .025), np.quantile(boots, .975), v.size


seg = pyogrio.read_dataframe(Z, layer="segments", read_geometry=False, columns=["segment_id", "location_accuracy", "commodity_group"])
tables = {}
for label, f in RUNS.items():
    if not (D / f).exists():
        print(f"[{label}] not there yet: {f}")
        continue
    d = load(D / f)
    n_pass = d.groupby("segment_id")[["date", "orbit"]].apply(lambda x: len(x.drop_duplicates()))
    print(f"\n[{label}] rows {len(d):,}; segments {d.segment_id.nunique()}; passes per segment median {n_pass.median():.0f}")
    for idx in SHOW:
        res = paired(d, idx)
        for (r, how), per_seg in res.items():
            med, lo, hi, n = summarize(per_seg)
            tables.setdefault(idx, []).append({"run": label, "ring": r, "how": how, "median": med, "lo95": lo, "hi95": hi, "segments": n})
        if idx == "NDVI" and ("0-50", "same land cover") in res:
            by = res[("0-50", "same land cover")].rename("diff").to_frame().join(seg.set_index("segment_id"))
            print("  0-50 m minus comparison, NDVI, same land cover, by mapped location accuracy:")
            print("  " + by.groupby("location_accuracy")["diff"].agg(["size", "median"]).round(4).to_string().replace("\n", "\n  "))

for idx, rows in tables.items():
    t = pd.DataFrame(rows)
    t["result"] = t.apply(lambda x: f"{x['median']:+.4f} [{x['lo95']:+.4f}, {x['hi95']:+.4f}] n={x['segments']}", axis=1)
    print(f"\n{idx}: ring minus 500-1,000 m comparison ring (median per segment, 95% bootstrap interval)")
    print(t.pivot_table(index=["how", "ring"], columns="run", values="result", aggfunc="first", sort=False).to_string())

# how much the contaminated comparison ring differs from the clean one, same segments, same passes
a, b = D / RUNS["current rings, per pass"], D / RUNS["clean rings, per pass"]
if a.exists() and b.exists():
    x, y = load(a), load(b)
    key = ["segment_id", "date", "orbit"]
    for idx in SHOW:
        def pooled(d):
            c = d[d.ring == "500-1000"].assign(v=lambda q: q[f"{idx}_mean"] * q.NDVI_count)
            g = c.groupby(key)[["v", "NDVI_count"]].sum()
            return g.v / g.NDVI_count
        diff = (pooled(x) - pooled(y)).dropna().groupby(level="segment_id").median()
        med, lo, hi, n = summarize(diff)
        print(f"{idx}: current comparison ring minus clean comparison ring = {med:+.4f} [{lo:+.4f}, {hi:+.4f}], {n} segments")
