"""GeoAI prototype: find the real cleared right-of-way next to a mapped pipeline in NAIP aerial photos.

Why: most Railroad Commission lines are mapped only to within 300-500 ft, so a 0-50 m ring may miss the pipe. If the
cleared strip can be found in imagery, the mapped line can be checked and, later, moved onto it.

Two independent methods per segment (the project's "verify" idea: an answer counts when two methods agree):
  A. SAM 2 (Segment Anything 2, through Qiusheng Wu's SamGeo; Ravi et al. 2024), prompted with five points along the
     line, shifted sideways from -200 to +200 m in 20 m steps, with five 'not this' points 100 m to each side. The
     shift whose mask looks most like a right-of-way (covers at least 70% of the segment's length, 8-70 m wide, keeps
     the same offset along its length within 15 m, high model score) gives the strip's center and width. SAM sees only
     the color photo. (SAM 2's automatic mode was tried first: it broke long thin strips into short pieces.)
  B. A physical check: NAIP NDVI (near-infrared and red) in 2 m strips parallel to the line, -250 to +250 m. A cleared
     right-of-way in brush or woodland is a trough; the midpoint of its half-depth edges gives the center and width.
Imagery: USGS NAIP from The National Map (4 bands, exported at 0.6 m in EPSG:6579). Offsets are + to the left of the
line's direction. The methods "agree" when their centers are within 20 m.

Run with the GeoAI environment: C:\\Users\\Landon\\miniforge3\\envs\\geog392-geoai\\python.exe row_finder.py [--n 8]
"""
import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("GDAL_DATA", str(Path(sys.prefix) / "Library" / "share" / "gdal"))
os.environ.setdefault("PROJ_DATA", str(Path(sys.prefix) / "Library" / "share" / "proj"))

import geopandas as gpd  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import rasterio  # noqa: E402
import requests  # noqa: E402
import shapely  # noqa: E402
from rasterio import features  # noqa: E402

P = Path(r"C:\mydrive\Graduate School\Courses\GEOG_392\projects")
OUT = P / "outputs" / "geoai" / "row_finder"
NAIP = "https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage"
PIXEL = 0.6
REACH = 250                    # meters either side of the mapped line searched for the right-of-way
SHIFTS = range(-200, 201, 20)
REGIONS = ["Southern Texas Plains", "Edwards Plateau", "South Central Plains", "East Central Texas Plains"]
ACCURACY = ["Within 50 ft", "51-300 ft", "301-500 ft"]


def pick(n: int) -> gpd.GeoDataFrame:
    seg = gpd.read_file(P / "outputs" / "zones" / "sample_v1" / "sample.gpkg", layer="segments")
    seg = seg[seg["ecoregion"].isin(REGIONS) & seg["status"].eq("In service")]
    return pd.concat([seg[seg["location_accuracy"] == a].sample(n=min(n, (seg["location_accuracy"] == a).sum()),
                                                                 random_state=392) for a in ACCURACY])


def naip_chip(geom, path: Path):
    """Export the NAIP photo around one segment (4 bands, 0.6 m, EPSG:6579) as a GeoTIFF."""
    if path.exists():
        return path
    x0, y0, x1, y1 = geom.buffer(REACH + 60).bounds
    w, h = int((x1 - x0) / PIXEL), int((y1 - y0) / PIXEL)
    r = requests.get(NAIP, params={"bbox": f"{x0},{y0},{x1},{y1}", "bboxSR": 6579, "imageSR": 6579, "size": f"{w},{h}",
                                   "format": "tiff", "pixelType": "U8", "interpolation": "RSP_BilinearInterpolation",
                                   "f": "image"}, timeout=180)
    r.raise_for_status()
    if not r.content.startswith((b"II", b"MM")):
        raise RuntimeError(f"NAIP did not return a TIFF: {r.content[:200]!r}")
    path.write_bytes(r.content)
    return path


def line_frame(line, shape, transform):
    """For every pixel: signed distance to the line (left +), position along it (0-1), and the middle-80% flag."""
    rows, cols = np.indices(shape)
    xs, ys = rasterio.transform.xy(transform, rows.ravel(), cols.ravel(), offset="center")
    xs, ys = np.asarray(xs), np.asarray(ys)
    pts = shapely.points(xs, ys)
    d = shapely.distance(pts, line)
    along = shapely.line_locate_point(line, pts) / line.length
    near = shapely.line_interpolate_point(line, along, normalized=True)
    ahead = shapely.line_interpolate_point(line, np.clip(along + 0.01, 0, 1), normalized=True)
    dx, dy = shapely.get_x(ahead) - shapely.get_x(near), shapely.get_y(ahead) - shapely.get_y(near)
    side = np.sign(dx * (ys - shapely.get_y(near)) - dy * (xs - shapely.get_x(near)))
    return (d * side).reshape(shape), along.reshape(shape), ((along > 0.1) & (along < 0.9)).reshape(shape)


def shifted_points(line, shift: float) -> np.ndarray:
    pts = []
    for f in (0.15, 0.3, 0.5, 0.7, 0.85):
        p, q = line.interpolate(f, normalized=True), line.interpolate(min(f + 0.02, 1), normalized=True)
        t = np.array([q.x - p.x, q.y - p.y]); t /= np.linalg.norm(t)
        pts.append([p.x - t[1] * shift, p.y + t[0] * shift])      # the left normal is (-ty, tx)
    return np.array(pts)


def ndvi_profile(img, off, middle):
    """Method B: the NDVI trough's center (midpoint of its half-depth edges), depth and width."""
    ndvi = (img[3] - img[0]) / np.maximum(img[3] + img[0], 1)
    keep = middle & (np.abs(off) <= REACH)
    prof = pd.Series(ndvi[keep]).groupby(np.round(off[keep] / 2) * 2).median().sort_index()
    smooth = prof.rolling(5, center=True, min_periods=3).mean()
    base = float(smooth.median())
    low_at = float(smooth.idxmin())
    depth = float(base - smooth.min())
    below = smooth < base - depth / 2
    idx = list(smooth.index)
    i = j = idx.index(low_at)
    while i > 0 and below.iloc[i - 1]:
        i -= 1
    while j < len(idx) - 1 and below.iloc[j + 1]:
        j += 1
    lo, hi = idx[i], idx[j]
    return {"ndvi_offset_m": (lo + hi) / 2, "ndvi_width_m": hi - lo + 2, "ndvi_trough_depth": depth, "ndvi_base": base}, prof


def sam_search(sam, line, off, along, middle):
    """Method A: prompt SAM 2 with points along the line at each sideways shift; keep the most right-of-way-like mask."""
    best, bins = None, np.linspace(0.1, 0.9, 41)
    for shift in SHIFTS:
        # five "this" points along the shifted line, and five "not this" points 100 m to each side, so SAM returns a strip
        pts = np.vstack([shifted_points(line, shift), shifted_points(line, shift + 100), shifted_points(line, shift - 100)])
        labels = np.r_[np.ones(5), np.zeros(10)]
        masks, scores, _ = sam.predict(point_coords=pts, point_labels=labels, point_crs="EPSG:6579",
                                       multimask_output=False, return_results=True)
        m = np.asarray(masks[0]) > 0
        inside = m & middle
        if inside.sum() < 500:
            continue
        o, a = off[inside], along[inside]
        width = float(np.quantile(o, 0.9) - np.quantile(o, 0.1))
        coverage = float(np.mean(np.histogram(a, bins=bins)[0] > 0))
        score = float(np.ravel(scores)[0])
        # a right-of-way keeps the same offset along its length; a blob (yards, fields) wanders: the spread of the
        # median offset across the along-line bins measures it
        where = np.digitize(a, bins)
        centers = pd.Series(o).groupby(where).median()
        wander = float(centers.std()) if len(centers) > 3 else np.inf
        if coverage < 0.7 or not 8 <= width <= 70 or wander > 15:
            continue
        cand = {"sam_offset_m": float(np.median(o)), "sam_width_m": width, "sam_coverage": coverage, "sam_score": score,
                "sam_wander_m": wander, "sam_prompt_shift_m": shift, "mask": m}
        rank = coverage * score * (1 - wander / 15)
        if best is None or rank > best["rank"]:
            best = cand | {"rank": rank}
    return best


def figure(chip: Path, line, res: dict, prof: pd.Series, best, transform, out: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    with rasterio.open(chip) as src:
        rgb = np.moveaxis(src.read([1, 2, 3]), 0, -1)
        b = src.bounds
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(13, 5), gridspec_kw={"width_ratios": [1.5, 1]})
    ax.imshow(rgb, extent=(b.left, b.right, b.bottom, b.top))
    if best is not None:
        polys = [shapely.geometry.shape(g) for g, v in features.shapes(best["mask"].astype("uint8"), mask=best["mask"], transform=transform)]
        gpd.GeoSeries(polys).boundary.plot(ax=ax, color="yellow", lw=1.0)
        ax.plot([], [], color="yellow", label="right-of-way found by SAM 2")
    ax.plot(*line.xy, color="red", lw=1.6, label="mapped line (Railroad Commission)")
    ax.legend(loc="lower right", fontsize=8)
    ax.set_title(f"{res['segment_id']}  (mapped {res['location_accuracy']}; {res['ecoregion']})", fontsize=10)
    ax.set_axis_off()
    ax2.plot(prof.index, prof.values, color="#500000")
    ax2.axvline(0, color="red", lw=1, ls="--", label="mapped line")
    ax2.axvline(res["ndvi_offset_m"], color="#2c7bb6", lw=1.2, label=f"NDVI trough center ({res['ndvi_offset_m']:+.0f} m)")
    if best is not None:
        ax2.axvline(best["sam_offset_m"], color="goldenrod", lw=1.4, ls=":", label=f"SAM 2 center ({best['sam_offset_m']:+.0f} m)")
    ax2.set_xlabel("offset from the mapped line (m, + = left of the line's direction)")
    ax2.set_ylabel("NAIP NDVI (median of a 2 m strip)")
    ax2.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    plt.close(fig)


def main(a):
    (OUT / "chips").mkdir(parents=True, exist_ok=True)
    (OUT / "figures").mkdir(exist_ok=True)
    segs = pick(a.n)
    print(f"{len(segs)} segments: {segs['location_accuracy'].value_counts().to_dict()}", flush=True)
    from samgeo import SamGeo2
    sam = SamGeo2(model_id="sam2-hiera-large", automatic=False)
    rows = []
    for s in segs.itertuples():
        line = shapely.line_merge(s.geometry) if s.geometry.geom_type == "MultiLineString" else s.geometry
        try:
            chip = naip_chip(line, OUT / "chips" / f"{s.segment_id}.tif")
            with rasterio.open(chip) as src:
                img, transform = src.read().astype("float32"), src.transform
            off, along, middle = line_frame(line, img.shape[1:], transform)
            res, prof = ndvi_profile(img, off, middle)
            rgb = OUT / "chips" / f"{s.segment_id}_rgb.tif"
            if not rgb.exists():
                with rasterio.open(chip) as src, rasterio.open(rgb, "w", **(src.profile | {"count": 3})) as dst:
                    dst.write(src.read([1, 2, 3]))
            sam.set_image(str(rgb))
            best = sam_search(sam, line, off, along, middle)
        except Exception as e:
            print(f"  {s.segment_id}: failed ({type(e).__name__}: {e})", flush=True)
            continue
        res = {"segment_id": s.segment_id, "location_accuracy": s.location_accuracy, "ecoregion": s.ecoregion,
               "commodity": s.commodity, "diameter_in": s.diameter_in, **res,
               **({k: v for k, v in best.items() if k not in ("mask", "rank")} if best else {"sam_offset_m": np.nan})}
        figure(chip, line, res, prof, best, transform, OUT / "figures" / f"{s.segment_id}.png")
        rows.append(res)
        print(f"  {s.segment_id} ({s.location_accuracy}): NDVI trough {res['ndvi_offset_m']:+.0f} m, "
              f"{res['ndvi_width_m']:.0f} m wide, depth {res['ndvi_trough_depth']:.3f}; SAM 2 {res['sam_offset_m']:+.0f} m"
              + (f", {res['sam_width_m']:.0f} m wide" if best else ""), flush=True)
    t = pd.DataFrame(rows)
    t["methods_agree"] = (t["sam_offset_m"] - t["ndvi_offset_m"]).abs() <= 20
    t["offset_m_if_agree"] = np.where(t["methods_agree"], (t["sam_offset_m"] + t["ndvi_offset_m"]) / 2, np.nan)
    t.to_csv(OUT / "row_finder_results.csv", index=False)
    g = t.groupby("location_accuracy").agg(segments=("segment_id", "size"), sam_found=("sam_offset_m", lambda x: int(x.notna().sum())),
                                           methods_agree=("methods_agree", "sum"),
                                           median_abs_offset_m=("offset_m_if_agree", lambda x: float(x.abs().median())))
    print("\nby mapped location accuracy (offset = mean of the two methods where they agree within 20 m):")
    print(g.to_string())
    print(f"wrote {OUT}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--n", type=int, default=8, help="segments per location-accuracy class")
    main(ap.parse_args())
