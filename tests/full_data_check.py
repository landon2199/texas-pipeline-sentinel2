"""The refactor's full-data check (REFACTOR_PLAN.md, "Done when" 2). Run locally: it reads the project's outputs.

  1. python tests/full_data_check.py --snapshot <folder>   before the reruns: copies today's outputs of the five
                                                           scripts (the reruns overwrite them; the copy also restores them)
  2. rerun coverage_estimate.py, clearing_calibration.py --boot 500, size_standardized.py, wall_map.py --spring 2026
     and publish/catalog.py with the refactored code
  3. python tests/full_data_check.py --baseline <folder>   checks every value in tests/expected_headlines.json to 1e-9,
                                                           recomputes the main sample's statewide gap from
                                                           segment_spring.csv with common/, and compares every rerun
                                                           output with the snapshot
Point estimates must match to 1e-9, and summaries (SUMMARY.md, metadata) word for word apart from dates. Bootstrap intervals
are reported separately: the plan allows them to move, but the refactor keeps the same draws, so they should not.
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.config import CORRIDOR, P, PUBLISH, R  # noqa: E402
from common.gaps import piece_gaps, wmedian_of  # noqa: E402

T = Path(__file__).resolve().parent
TOL = 1e-9
FOLDERS = {"coverage_estimate": R / "coverage_estimate", "clearing_calibration": R / "clearing_calibration",
           "size_standardized": R / "size_standardized", "wall_to_wall_2026": R / "wall_to_wall_2026", "publish": PUBLISH}
INTERVAL = re.compile(r"(^|_)(lo95|hi95)(_|$)")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?)?")
BRACKETS = re.compile(r"\[[^\]\n]*\]|\d[\d,.]*-\d[\d,.]* km²")     # intervals as summaries write them


def pick(d: pd.DataFrame, **k) -> pd.Series:
    return d.loc[np.logical_and.reduce([d[c] == v for c, v in k.items()])].iloc[0]


def headlines() -> dict:
    """The headline numbers, read exactly as tests/make_fixtures.py reads them."""
    cov = pd.read_csv(R / "coverage_estimate" / "estimates.csv")
    cal = pd.read_csv(R / "clearing_calibration" / "calibrated.csv")
    fp = pd.read_csv(R / "clearing_calibration" / "footprint.csv")
    st = pd.read_csv(CORRIDOR / "statewide.csv")
    W = pd.read_csv(R / "clearing_calibration" / "widths.csv", index_col=0)["cleared_width_m"]
    land = dict(scope="statewide", group="all land pipe 100 m or longer", measure="same land cover")
    return {"band_gap_all_land_pipe_ndvi": float(pick(cov, index="NDVI", frame="all land pipe", measure="same land cover")["gap"]),
            "band_gap_main_sample_ndvi_all_springs": float(pick(st, springs="all springs", scope="statewide", ring="0-50 m",
                                                                 index="NDVI", measure="same land cover")["weighted_median"]),
            "calibrated_gap_all_land_pipe_ndvi": float(pick(cal, **land)["calibrated_gap"]),
            "calibrated_pct_all_land_pipe": float(pick(cal, **land)["pct_of_comparison_ndvi"]),
            "cleared_width_m": {k: round(float(v), 3) for k, v in W.items()},
            "footprint_km2_all_land_pipe": float(fp["area_km2"].iloc[0])}


def main_sample_gap() -> float:
    """corridor.py's statewide 0-50 m NDVI gap (all springs, same land cover), rebuilt from segment_spring.csv with
    common.gaps: each segment's median over springs (grouped as corridor.py groups them), then the weighted median."""
    f = CORRIDOR / "segment_spring.csv"
    cols = pd.read_csv(f, nrows=0).columns
    groups = ["ecoregion", "commodity_group", "service", "diameter_class", "status", "location_accuracy"]
    keys = ["segment_id", "index", "stratum", "weight"] + [g for g in groups if g in cols]
    return wmedian_of(piece_gaps(f, keys), "diff_same_lc", "weight")


def check_headlines() -> list[str]:
    want = json.loads((T / "expected_headlines.json").read_text(encoding="utf-8"))
    got = headlines()
    bad = []
    for k, v in got.items():
        ok = v == want[k] if isinstance(v, dict) else abs(v - want[k]) <= TOL
        print(f"  {'ok ' if ok else 'BAD'} {k}: {v} (expected {want[k]})")
        bad += [] if ok else [k]
    again = main_sample_gap()
    ok = abs(again - want["band_gap_main_sample_ndvi_all_springs"]) <= TOL
    print(f"  {'ok ' if ok else 'BAD'} band_gap_main_sample_ndvi_all_springs rebuilt from segment_spring.csv with common/: {again}")
    return bad + ([] if ok else ["band_gap_main_sample_ndvi_all_springs (rebuilt)"])


def compare_tables(a: pd.DataFrame, b: pd.DataFrame) -> tuple[list[str], list[str]]:
    """(problems, interval notes) between a snapshot table and a rerun table."""
    if list(a.columns) != list(b.columns) or len(a) != len(b):
        return [f"columns or rows differ: {list(a.columns)} ({len(a)} rows) vs {list(b.columns)} ({len(b)} rows)"], []
    problems, notes = [], []
    for c in a.columns:
        x, y = a[c], b[c]
        if c == "geometry" or str(x.dtype) == "geometry":
            if not np.array_equal(np.asarray(x.to_wkb() if hasattr(x, "to_wkb") else x, dtype=object),
                                  np.asarray(y.to_wkb() if hasattr(y, "to_wkb") else y, dtype=object)):
                problems.append(f"{c}: geometries differ")
            continue
        if pd.api.types.is_numeric_dtype(x) and pd.api.types.is_numeric_dtype(y) and not pd.api.types.is_bool_dtype(x):
            xv, yv = x.to_numpy(float), y.to_numpy(float)
            same_nan = np.isnan(xv) == np.isnan(yv)
            diff = np.nanmax(np.abs(xv - yv)) if (~np.isnan(xv)).any() else 0.0
            if not same_nan.all() or diff > TOL:
                (notes if INTERVAL.search(c) else problems).append(f"{c}: max difference {diff:.3g}, "
                                                                    f"missing values differ in {(~same_nan).sum()} rows")
        elif not x.astype(str).equals(y.astype(str)):
            problems.append(f"{c}: {(x.astype(str) != y.astype(str)).sum()} values differ")
    return problems, notes


def compare_file(a: Path, b: Path) -> tuple[list[str], list[str]]:
    ext = a.suffix.lower()
    if ext == ".csv":
        return compare_tables(pd.read_csv(a), pd.read_csv(b))
    if ext == ".parquet":
        try:
            import geopandas as gpd
            return compare_tables(gpd.read_parquet(a), gpd.read_parquet(b))
        except (ValueError, ImportError):
            return compare_tables(pd.read_parquet(a), pd.read_parquet(b))
    if ext in (".tif", ".tiff"):
        import rasterio
        with rasterio.open(a) as ra, rasterio.open(b) as rb:
            same = ra.shape == rb.shape and ra.transform == rb.transform and np.array_equal(ra.read(), rb.read(), equal_nan=True)
        return ([] if same else ["raster values or grid differ"]), []
    if ext in (".md", ".xml", ".json", ".txt"):
        ta, tb = (DATE.sub("<date>", p.read_text(encoding="utf-8", errors="replace")).splitlines() for p in (a, b))
        if len(ta) != len(tb):
            return [f"text has {len(ta)} lines before and {len(tb)} after"], []
        changed = [(x, y) for x, y in zip(ta, tb) if x != y]
        values = [(x, y) for x, y in changed if BRACKETS.sub("[]", x) != BRACKETS.sub("[]", y)]
        show = lambda pairs: "\n".join(f"    - {x}\n    + {y}" for x, y in pairs[:6])  # noqa: E731
        return ([f"text differs in {len(values)} line(s):\n" + show(values)] if values else [],
                [f"intervals differ in {len(changed) - len(values)} line(s):\n" + show(changed)] if len(changed) > len(values) else [])
    if ext == ".png":
        return [], ([] if a.read_bytes() == b.read_bytes() else ["figure bytes differ (look at both)"])
    return ([] if a.read_bytes() == b.read_bytes() else ["bytes differ"]), []


def compare_with(baseline: Path) -> tuple[list[str], int]:
    bad, moved = [], 0
    for name, folder in FOLDERS.items():
        old = baseline / name
        if not old.exists():
            print(f"  (no snapshot of {name})")
            continue
        for f in sorted(p for p in old.rglob("*") if p.is_file()):
            rel = f.relative_to(old)
            new = folder / rel
            if not new.exists():
                bad.append(f"{name}/{rel}: missing after the rerun")
                print(f"  BAD {name}/{rel}: missing after the rerun")
                continue
            problems, notes = compare_file(f, new)
            tag = "BAD" if problems else ("note" if notes else "ok ")
            print(f"  {tag} {name}/{rel.as_posix()}" + "".join(f"\n        {m}" for m in problems + notes))
            bad += [f"{name}/{rel}"] if problems else []
            moved += bool(notes)
        for f in sorted(p for p in folder.rglob("*") if p.is_file()):       # the same output files, and no new ones
            rel = f.relative_to(folder)
            if not (old / rel).exists():
                bad.append(f"{name}/{rel}: new after the rerun")
                print(f"  BAD {name}/{rel.as_posix()}: new after the rerun (not in the snapshot)")
    return bad, moved


def snapshot(folder: Path):
    for name, src in FOLDERS.items():
        if src.exists():
            shutil.copytree(src, folder / name, dirs_exist_ok=False)
            print(f"copied {src} -> {folder / name}")
        else:
            print(f"(no {src})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--snapshot", type=Path, help="copy today's outputs here before the reruns (a new folder)")
    ap.add_argument("--baseline", type=Path, help="after the reruns: compare the outputs with this snapshot")
    a = ap.parse_args()
    sys.stdout.reconfigure(errors="replace")         # summaries hold characters a Windows console may not have
    print(f"project: {P}")
    if a.snapshot:
        snapshot(a.snapshot)
        sys.exit(0)
    print("headline numbers (tests/expected_headlines.json):")
    bad, moved = check_headlines(), 0
    if a.baseline:
        print(f"rerun outputs against the snapshot in {a.baseline}:")
        more, moved = compare_with(a.baseline)
        bad += more
    if bad:
        print(f"FAIL: {len(bad)} difference(s): {bad}")
    elif moved:
        print(f"PASS for the point estimates, but bootstrap intervals moved in {moved} file(s) (see the notes above)")
    else:
        print("PASS: no result changed" + (", intervals included" if a.baseline else ""))
    sys.exit(1 if bad else 0)
