"""Part 1: build the zones for the whole state, one ecoregion at a time (analysis plan, Section 4).

For every Railroad Commission line, as published, this:
  1. cuts the line where it crosses from one ecoregion into another, so every piece lies in exactly one ecoregion;
  2. cuts each part into pieces of up to 1 km, with IDs that never change;
  3. adds clean labels beside the published fields (labels.py) and records where each piece sits along its line, in
     meters and in engineering stations;
  4. draws five rings on both sides of every piece at least --min-piece meters long: 0-50, 50-100, 100-250 and
     250-500 m, and the 500-1,000 m comparison ring;
  5. cleans the rings: a ring from a to b meters keeps only ground whose nearest pipeline (any Railroad Commission
     line, any status) is at least a meters away, so the 500-1,000 m comparison ring has no pipeline within 500 m.
     In the Central Great Plains test, 48% of the comparison rings' ground was within 500 m of another line. Rings
     left too small to hold 20 pixels at 20 m (8,000 m2) are dropped and counted, and each segment records whether it
     still has a comparison ring;
  6. writes one GeoPackage per ecoregion (layers `segments` and `rings`, the rings sorted segment by segment) and a CSV
     copy of the rings for uploading to Earth Engine (zone_id and geometry only), a cleaning summary, and adds to a
     coverage table that counts everything kept and left out.

Finished ecoregions are skipped, so a stopped run picks up where it left off.

Usage:
  python build_zones.py --lines <statewide .gpkg> --ecoregions <ecoregions .gpkg> --out <folder>
                        [--only "Central Great Plains"] [--min-piece 1000] [--workers 12] [--no-clean] [--force]
"""
import argparse
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import time
import warnings
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import pyproj
import shapely
from shapely.ops import linemerge, substring

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.rings import label, ring_name, zone_id  # noqa: E402
from labels import add_labels, station  # noqa: E402

warnings.filterwarnings("ignore", category=RuntimeWarning)
EQUAL_AREA = 6579                                     # NAD83(2011) Texas Centric Albers: meters, true areas
PIECE_M = 1000
RINGS = [(0, 50), (50, 100), (100, 250), (250, 500), (500, 1000)]   # the last is the comparison ring
BANDS_50M = [(i, i + 50) for i in range(0, 500, 50)] + [(500, 1000)]  # plan v1.6: ten 50 m bands + comparison ring
SLIVER_M2 = 1.0                                       # sharp bends leave zero-area slivers; Earth Engine miscounts them
MIN_ZONE_M2 = 8_000                                   # 20 pixels at 20 m: a cleaned ring smaller than this can't be measured


def projection_note() -> str:
    """Which NAD27 conversion PROJ uses, with its stated accuracy: 0.35 m with NOAA's NADCON5 grids. Without them PROJ
    goes through WGS 84 (rated 9 m), which differed from the grids by a median 2.1 m (maximum 4.4 m) in Texas."""
    pyproj.network.set_network_enabled(os.environ.get("PROJ_NETWORK", "").upper() == "ON")
    t = pyproj.Transformer.from_crs(4267, EQUAL_AREA, always_xy=True)
    t.transform(-98.5, 31.0)
    op = t.get_last_used_operation()
    grids = pyproj.transformer.TransformerGroup(4267, EQUAL_AREA, always_xy=True).best_available
    return op.description + f" (PROJ's stated accuracy {op.accuracy:g} m" + ("" if grids else "; NADCON5 grids not installed") + ")"


def load_lines(path: Path) -> gpd.GeoDataFrame:
    lines = pyogrio.read_dataframe(path, layer="pipelines")
    order = lines.groupby("source_file").cumcount()
    county = lines["source_file"].str.extract(r"pipeline(\w+)\.zip", expand=False)
    lines["line_uid"] = county + "-" + order.astype(str).str.zfill(6)       # file and position: stable for this download
    lines = add_labels(lines).to_crs(EQUAL_AREA)
    lines["line_km"] = lines.length / 1000
    return lines


def cut(part, length: float = PIECE_M):
    """Cut one line part into pieces of `length` meters; the last piece is shorter. Returns (start_m, piece) pairs."""
    total = part.length
    if total <= length:
        return [(0.0, part)]
    return [(k * length, substring(part, k * length, min((k + 1) * length, total)))
            for k in range(int(np.ceil(total / length)))]


def segments_for(lines: gpd.GeoDataFrame, region) -> gpd.GeoDataFrame:
    """Every piece of every line inside one ecoregion, with its position along the original line."""
    poly = region.geometry
    idx = lines.sindex.query(poly, predicate="intersects")
    sub = lines.iloc[idx]
    originals = np.asarray(sub.geometry.array)
    clipped = shapely.intersection(originals, poly)
    rows, attrs = [], sub.drop(columns="geometry").to_dict("records")
    for a, original, geom in zip(attrs, originals, clipped):
        parts = [g for g in shapely.get_parts(geom) if g.geom_type == "LineString" and g.length >= 1]
        if not parts:
            continue
        merged = linemerge(original) if original.geom_type == "MultiLineString" else original
        whole = merged if merged.geom_type == "LineString" else None
        for p, part in enumerate(sorted(parts, key=lambda g: whole.project(shapely.Point(g.coords[0])) if whole else 0)):
            offset = whole.project(shapely.Point(part.coords[0])) if whole is not None else 0.0
            for k, (start, piece) in enumerate(cut(part)):
                if piece.length < 1:
                    continue
                rows.append({**a, "segment_id": f"{a['line_uid']}-{region.us_l3code}-{p}-{k}",
                             "ecoregion_code": region.us_l3code, "ecoregion": region.us_l3name,
                             "piece_m": piece.length, "start_m": offset + start, "end_m": offset + start + piece.length,
                             "geometry": piece})
    if not rows:                                       # an ecoregion with no pipelines in Texas
        return gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs=lines.crs)
    seg = gpd.GeoDataFrame(rows, crs=lines.crs)
    if len(seg):
        seg["start_station"], seg["end_station"] = station(seg["start_m"]), station(seg["end_m"])
    return seg


def rings_for(seg: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Five rings on both sides of every piece, built for all pieces at once, slivers removed."""
    g = np.asarray(seg.geometry.array)
    out = []
    for inner, outer in RINGS:
        band = shapely.buffer(g, outer, cap_style="flat")
        if inner > 0:
            band = shapely.difference(band, shapely.buffer(g, inner, cap_style="flat"))
        parts, which = shapely.get_parts(band, return_index=True)
        keep = (shapely.get_type_id(parts) == 3) & (shapely.area(parts) >= SLIVER_M2)
        polys = np.full(len(g), None, dtype=object)
        if keep.any():
            built = shapely.multipolygons(parts[keep], indices=which[keep])
            polys[: len(built)] = built
        ring = gpd.GeoDataFrame({"segment_id": seg["segment_id"].values, "ring": label(ring_name(inner, outer)),
                                 "inner_m": inner, "outer_m": outer, "comparison": outer == RINGS[-1][1]},
                                geometry=polys, crs=seg.crs)
        out.append(ring)
    rings = pd.concat(out, ignore_index=True)
    rings = rings[rings.geometry.notna() & ~rings.geometry.is_empty]
    rings.insert(0, "zone_id", zone_id(rings["segment_id"], rings["inner_m"].astype(str) + "-" + rings["outer_m"].astype(str)))
    rings["area_m2"] = rings.area
    return gpd.GeoDataFrame(rings, geometry="geometry", crs=seg.crs)


_LINES = _TREE = None


def _start_worker(lines_wkb):
    global _LINES, _TREE
    _LINES = shapely.from_wkb(lines_wkb)
    _TREE = shapely.STRtree(_LINES)


def _clean_chunk(job):
    """Cut out of each ring the ground closer to any pipeline than the ring's inner edge."""
    rings_wkb, inner = job
    out = []
    for g, d in zip(shapely.from_wkb(rings_wkb), inner):
        near = _TREE.query(g, predicate="dwithin", distance=d)
        if len(near):
            g = shapely.difference(g, shapely.union_all(shapely.buffer(_LINES[near], d)))
        parts = shapely.get_parts(g)
        parts = parts[(shapely.get_type_id(parts) == 3) & (shapely.area(parts) >= SLIVER_M2)]
        out.append(shapely.multipolygons(parts) if len(parts) else None)
    return shapely.to_wkb(np.array(out, dtype=object))


def clean_rings(rings: gpd.GeoDataFrame, lines: gpd.GeoDataFrame, workers: int):
    """Keep only ground whose nearest pipeline is at least the ring's inner distance away. The 0-50 m ring is unchanged.

    Every line counts as a pipeline here, in service or abandoned, measured or too short to measure, because each has
    its own right-of-way. Returns the rings that can still be measured and a per-band summary.
    """
    inner = rings["inner_m"].to_numpy()
    geoms = np.asarray(rings.geometry.array).copy()
    todo = np.flatnonzero(inner > 0)
    if len(todo):
        reach = shapely.box(*rings.total_bounds).buffer(max(i for i, _ in RINGS))
        near = np.asarray(lines.geometry.array)[lines.sindex.query(reach, predicate="intersects")]
        chunks = np.array_split(todo, max(1, len(todo) // 1500))
        jobs = [(shapely.to_wkb(geoms[c]), inner[c]) for c in chunks]
        with ProcessPoolExecutor(workers, initializer=_start_worker, initargs=(shapely.to_wkb(near),)) as pool:
            for c, wkb in zip(chunks, pool.map(_clean_chunk, jobs)):
                geoms[c] = shapely.from_wkb(wkb)
    out = rings.copy()
    out["full_area_m2"] = out["area_m2"]
    out = out.set_geometry(gpd.GeoSeries(geoms, index=out.index, crs=rings.crs))
    out["area_m2"] = out.geometry.area.fillna(0)
    out["kept_share"] = out["area_m2"] / out["full_area_m2"]
    usable = out["area_m2"] >= MIN_ZONE_M2
    summary = out.groupby("ring", sort=False).agg(rings=("zone_id", "size"), kept=("area_m2", lambda a: int((a >= MIN_ZONE_M2).sum())),
                                                   mean_kept_share=("kept_share", "mean")).reset_index()
    return out[usable].copy(), summary


def write_region(seg, rings, folder: Path, name: str):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "ee_upload").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / f"{name}.gpkg"
        seg.to_file(local, layer="segments", driver="GPKG")
        rings.to_file(local, layer="rings", driver="GPKG")          # a second layer in the same GeoPackage
        csv = Path(tmp) / f"{name}_rings.csv"
        wkt = shapely.to_wkt(np.asarray(rings.to_crs(4326).geometry.array), rounding_precision=6)
        pd.DataFrame({"zone_id": rings["zone_id"].values, "WKT": wkt}).to_csv(csv, index=False)
        shutil.copy(local, folder / local.name)
        shutil.copy(csv, folder / "ee_upload" / csv.name)


def slug(name: str) -> str:
    return name.lower().replace("/", "_").replace(" ", "_")


def main(a):
    global RINGS
    if a.bands == "50m":
        RINGS = BANDS_50M
    t0 = time.time()
    note = projection_note()
    print("projection:", note, flush=True)
    lines = load_lines(a.lines)
    eco = gpd.read_file(a.ecoregions).to_crs(EQUAL_AREA)
    if a.only:
        eco = eco[eco["us_l3name"].isin(a.only)]
        if eco.empty:
            raise SystemExit(f"no ecoregion named {a.only}")
    dupes = lines[lines["dup_geometry"]]
    if a.only:                                             # a partial run counts only the duplicates in its regions
        dupes = dupes.iloc[dupes.sindex.query(eco.union_all(), predicate="intersects")]
    lines = lines[~lines["dup_geometry"]]
    covered = pd.Series(0.0, index=lines["line_uid"].values)
    records = []
    for region in eco.itertuples():
        name = f"{region.us_l3code}_{slug(region.us_l3name)}"
        done = a.out / f"{name}.gpkg"
        if done.exists() and not a.force:
            seg = pyogrio.read_dataframe(done, layer="segments", read_geometry=False)
            print(f"{region.us_l3name}: already built, skipped (use --force to rebuild)", flush=True)
        else:
            t = time.time()
            seg = segments_for(lines, region)
            if seg.empty:
                print(f"{region.us_l3name}: no pipelines, nothing to build", flush=True)
                continue
            measured = seg[seg["piece_m"] >= a.min_piece - 1e-6]
            rings = rings_for(measured) if len(measured) else gpd.GeoDataFrame(geometry=[], crs=seg.crs)
            seg["has_zones"] = seg["piece_m"] >= a.min_piece - 1e-6
            if len(rings) and not a.no_clean:
                rings, summary = clean_rings(rings, lines, a.workers)
                summary.insert(0, "ecoregion", region.us_l3name)
                summary.to_csv(a.out / f"{name}_cleaning.csv", index=False)
            comp = rings.loc[rings["comparison"], ["segment_id", "kept_share"]] if len(rings) else pd.DataFrame(columns=["segment_id", "kept_share"])
            seg["has_comparison"] = seg["has_zones"] & seg["segment_id"].isin(comp["segment_id"])
            seg["comparison_kept_share"] = seg["segment_id"].map(comp.set_index("segment_id")["kept_share"]) if "kept_share" in comp else np.nan
            if len(rings):
                rings = rings.sort_values(["segment_id", "inner_m"], kind="stable")   # upload pieces then hold whole segments
            write_region(seg, rings, a.out, name)
            print(f"{region.us_l3name}: {seg['line_uid'].nunique():,} lines, {len(seg):,} pieces, "
                  f"{int(seg['has_zones'].sum()):,} measured ({int(seg['has_comparison'].sum()):,} with a clean comparison ring), "
                  f"{len(rings):,} rings ({time.time() - t:,.0f} s)", flush=True)
        km = seg.groupby("line_uid")["piece_m"].sum() / 1000
        covered = covered.add(km, fill_value=0)
        has_comp = seg["has_comparison"] if "has_comparison" in seg else seg["has_zones"]
        status = np.where(~seg["has_zones"], f"piece shorter than {a.min_piece:.0f} m",
                          np.where(has_comp, "", "measured, but no clean comparison ground (another pipeline within 500 m)"))
        for (kept, why), part in seg.groupby([seg["has_zones"], status]):
            for keys, grp in part.groupby(["commodity_group", "diameter_class", "status", "location_accuracy"], dropna=False):
                records.append({"ecoregion": region.us_l3name, "kept": bool(kept),
                                "reason": why,
                                "commodity_group": keys[0], "diameter_class": keys[1], "status": keys[2],
                                "location_accuracy": keys[3], "pieces": len(grp), "lines": grp["line_uid"].nunique(),
                                "km": grp["piece_m"].sum() / 1000})
    if not a.only:   # statewide: whatever no ecoregion covered is offshore or outside Texas's ecoregions
        outside = (lines.set_index("line_uid")["line_km"] - covered.reindex(lines["line_uid"]).fillna(0).values).clip(lower=0)
        lines_out = lines.set_index("line_uid").loc[outside[outside > 0.001].index]
        for keys, grp in lines_out.groupby(["commodity_group", "diameter_class", "status", "location_accuracy"], dropna=False):
            records.append({"ecoregion": "(none)", "kept": False, "reason": "offshore or outside Texas ecoregions",
                            "commodity_group": keys[0], "diameter_class": keys[1], "status": keys[2],
                            "location_accuracy": keys[3], "pieces": 0, "lines": len(grp),
                            "km": float(outside.loc[grp.index].sum())})
    for keys, grp in dupes.groupby(["commodity_group", "diameter_class", "status", "location_accuracy"], dropna=False):
        records.append({"ecoregion": "(any)", "kept": False, "reason": "exact duplicate of another line's geometry",
                        "commodity_group": keys[0], "diameter_class": keys[1], "status": keys[2],
                        "location_accuracy": keys[3], "pieces": 0, "lines": len(grp), "km": float(grp["line_km"].sum())})
    cov = pd.DataFrame(records)
    tag = "_".join(slug(n) for n in a.only) if a.only else "statewide"
    cov.to_csv(a.out / f"coverage_{tag}.csv", index=False)
    meta = {"built": dt.datetime.now().isoformat(timespec="seconds"), "lines_file": str(a.lines), "projection": note,
            "min_piece_m": a.min_piece, "rings_m": RINGS, "clean_rings": not a.no_clean, "min_zone_m2": MIN_ZONE_M2,
            "ecoregions": eco["us_l3name"].tolist(),
            "seconds": round(time.time() - t0)}
    (a.out / f"build_{tag}.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    kept = cov[cov["kept"]]
    print(f"coverage: kept {kept['km'].sum():,.0f} km in {int(kept['pieces'].sum()):,} pieces; "
          f"left out {cov.loc[~cov['kept'], 'km'].sum():,.0f} km -> {a.out / f'coverage_{tag}.csv'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lines", type=Path, required=True)
    ap.add_argument("--ecoregions", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--only", nargs="*", help="ecoregion names to build (default: all)")
    ap.add_argument("--min-piece", type=float, default=PIECE_M, help="shortest piece that gets rings, in meters")
    ap.add_argument("--bands", choices=["rings", "50m"], default="rings",
                    help="rings: 0-50, 50-100, 100-250, 250-500 m (v1.5); 50m: ten 50 m bands (v1.6); both add 500-1,000 m")
    ap.add_argument("--workers", type=int, default=max(1, min(12, (os.cpu_count() or 2) - 2)), help="processes for cleaning")
    ap.add_argument("--no-clean", action="store_true", help="keep the rings as drawn (the design before 2026-10-06)")
    ap.add_argument("--force", action="store_true")
    main(ap.parse_args())
