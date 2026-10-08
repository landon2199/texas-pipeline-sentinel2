"""Part 3, the corridor question (Q1): every ring against its own comparison ring, image by image, weighted to the state.

Analysis plan v1.6, Sections 5.5 and 6. Reads the per-image tables that extract/run_part2.py exports (one CSV per
spring) and the sample's weights (zones/draw_sample.py), then:
  1. removes repeats from overlapping Sentinel-2 tiles: for each segment and pass, the tile image with the most clear
     pixels over the segment's zones (ties go to the first image ID), so a ring and its comparison ring come from the
     same image and the result does not depend on row order;
  2. pairs every ring with its own segment's 500-1,000 m comparison ring in the same pass, two ways: all ground (each
     ring's pixel-weighted mean) and like-for-like land cover (each NLCD class against the same class, weighted by the
     smaller of the two pixel counts). A pass counts only if both rings hold at least --min-pixels land pixels;
  3. takes the median over each spring's passes, for every segment, ring, index and spring, with the number of passes
     it rests on and their median day of year;
  4. summarizes the state with each segment's sampling weight: weighted medians, with 95% intervals from a stratified
     bootstrap (segments resampled within their sampling strata), for all springs pooled and for each spring, statewide
     and by ecoregion, commodity group, service, diameter class, status and mapped location accuracy.

Writes, in --out: segment_spring.csv (one row per segment, spring, ring and index: the input for maps, hot spots and
the dashboard), statewide.csv (the weighted summaries) and SUMMARY.md.

Usage: python corridor.py --results <folder of per-image CSVs> --pattern "*per_image*.csv" --sample <sample folder>
                          --out <folder> [--indices NDVI NDMI NDRE BSI] [--min-pixels 20] [--boot 500]
"""
import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd

COMPARISON = "500-1000"
INDICES_ALL = ["NDVI", "NDMI", "SAVI", "MNDWI", "NDRE", "S2REP", "BSI"]


def rings_in(d: pd.DataFrame) -> list[str]:
    """Every ring band in the data except the comparison ring, nearest first (works for 4 rings or ten 50 m bands)."""
    return sorted(set(d["ring"]) - {COMPARISON}, key=lambda r: int(r.split("-")[0]))


def pool_rings(d: pd.DataFrame, groups: list[str]) -> pd.DataFrame:
    """Rebuild wide rings from narrow bands, e.g. "100-250=100-150,150-200,200-250": each index's mean is pooled with its
    pixel counts, per segment, land cover class and pass, so a wide ring is exactly the ground of its bands."""
    rename = {}
    for g in groups:
        wide, parts = g.split("=")
        rename.update({p: wide for p in parts.split(",")})
    d = d.assign(ring=d["ring"].replace(rename))
    key = ["segment_id", "ring", "landcover", "date", "orbit", "year"]
    idx = [i for i in INDICES_ALL if f"{i}_mean" in d]
    agg = d.assign(**{f"{i}_w": d[f"{i}_mean"] * d[f"{i}_count"] for i in idx}).groupby(key)
    out = agg[[f"{i}_w" for i in idx] + [f"{i}_count" for i in idx]].sum()
    for i in idx:
        out[f"{i}_mean"] = out[f"{i}_w"] / out[f"{i}_count"]
    out["doy"] = agg["doy"].first()
    out = out.drop(columns=[f"{i}_w" for i in idx]).reset_index()
    out["zone_id"] = out["segment_id"] + "_r" + out["ring"]
    print(f"pooled bands into wider rings: {sorted(set(rename.values()), key=lambda r: int(r.split('-')[0]))}")
    return out
GROUPS = ["ecoregion", "commodity_group", "service", "diameter_class", "status", "location_accuracy"]
KEY = ["segment_id", "year", "date", "orbit"]


def one_image_per_pass(d: pd.DataFrame, unit: str, count: str = "NDVI_count", pass_key=("date", "orbit")) -> pd.DataFrame:
    """Where tiles overlap (Sentinel-2 tiles, or Landsat scenes along a path), a pass is measured once per tile. Keep one
    tile image per unit (a segment or a spill site) and pass: the one with the most clear pixels over all the unit's
    zones, ties going to the first image ID. A ring and its comparison ring then always come from the same image, and
    the choice does not depend on row order."""
    key = [unit, *pass_key]
    px = d.groupby(key + ["image"], sort=False)[count].sum().reset_index()
    best = px.sort_values([count, "image"], ascending=[False, True], kind="stable").drop_duplicates(key)
    return d.merge(best[key + ["image"]], on=key + ["image"])


def read_file(f: Path, indices=None) -> pd.DataFrame:
    """One export, with only the columns the analysis uses (all seven indices when indices is None)."""
    keep = {"zone_id", "landcover", "date", "image", "orbit"}
    for i in (INDICES_ALL if indices is None else sorted(set(indices) | {"NDVI"})):
        keep |= {f"{i}_mean", f"{i}_count"}
    return pd.read_csv(f, usecols=lambda c: c in keep, dtype={"landcover": "int16"})


def load_results(folder: Path, pattern: str, indices=None, files=None) -> pd.DataFrame:
    files = files or sorted(folder.glob(pattern))
    if not files:
        raise SystemExit(f"no files match {pattern} in {folder}")
    d = pd.concat([read_file(f, indices) for f in files], ignore_index=True)
    d[["segment_id", "ring"]] = d["zone_id"].str.rsplit("_r", n=1, expand=True)
    d["year"] = d["date"].str[:4].astype(int)
    d["doy"] = pd.to_datetime(d["date"]).dt.dayofyear
    # 1. repeats from overlapping tiles: one tile image per segment and pass
    d = one_image_per_pass(d, "segment_id")
    d = d.sort_values(["NDVI_count", "image"], ascending=[False, True], kind="stable").drop_duplicates(
        ["zone_id", "landcover", "date", "orbit"])
    print(f"read {len(files)} file(s): {len(d):,} rows after removing tile repeats, {d['segment_id'].nunique():,} segments, "
          f"springs {sorted(d['year'].unique())}")
    return d


def paired(d: pd.DataFrame, idx: str, min_px: int, rings: list[str]) -> pd.DataFrame:
    """2-3. Per segment, spring and ring: the median over passes of ring minus comparison ring."""
    m, n = f"{idx}_mean", f"{idx}_count"
    d = d[d[n] > 0]
    pooled = d.assign(v=d[m] * d[n]).groupby(KEY + ["ring"]).agg(v=("v", "sum"), n=(n, "sum"), doy=("doy", "first"))
    pooled["v"] = pooled["v"] / pooled["n"]
    pooled = pooled.unstack("ring")
    by_lc = d.set_index(KEY + ["landcover", "ring"])[[m, n]].unstack("ring")
    rows = []
    for r in rings:
        if (("v", r) not in pooled) or (("v", COMPARISON) not in pooled):
            continue
        ok = (pooled[("n", r)] >= min_px) & (pooled[("n", COMPARISON)] >= min_px)
        p = pooled[ok]
        diff_all = p[("v", r)] - p[("v", COMPARISON)]
        w = np.minimum(by_lc[(n, r)], by_lc[(n, COMPARISON)]).where(by_lc[(m, r)].notna() & by_lc[(m, COMPARISON)].notna())
        num = ((by_lc[(m, r)] - by_lc[(m, COMPARISON)]) * w).groupby(level=KEY).sum(min_count=1)
        den = w.groupby(level=KEY).sum(min_count=1)
        diff_same = (num / den).reindex(p.index)
        per = pd.DataFrame({"diff_all": diff_all, "diff_same_lc": diff_same, "doy": p[("doy", r)]})
        g = per.groupby(level=["segment_id", "year"])
        out = pd.DataFrame({"diff_all": g["diff_all"].median(), "diff_same_lc": g["diff_same_lc"].median(),
                            "passes": g["diff_all"].size(), "doy_median": g["doy"].median()}).reset_index()
        out.insert(2, "ring", f"{r} m")
        out.insert(3, "index", idx)
        rows.append(out)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def wmedian(v: np.ndarray, w: np.ndarray) -> float:
    o = np.argsort(v)
    c = np.cumsum(w[o])
    return float(v[o][np.searchsorted(c, c[-1] / 2)])


def summarize(v, w, strata, boot, rng):
    """Weighted median with a stratified bootstrap interval (segments resampled within their strata)."""
    ok = np.isfinite(v)
    v, w, strata = v[ok], w[ok], strata[ok]
    if len(v) < 3:
        return len(v), np.nan, np.nan, np.nan
    groups = [np.flatnonzero(strata == s) for s in np.unique(strata)]
    est = wmedian(v, w)
    if boot == 0:
        return len(v), est, np.nan, np.nan
    draws = []
    for _ in range(boot):
        pick = np.concatenate([g[rng.integers(0, len(g), len(g))] for g in groups])
        draws.append(wmedian(v[pick], w[pick]))
    return len(v), est, float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975))


def main(a):
    # One spring at a time: every pass lies inside one spring, so this gives the same per-segment springs as loading
    # everything at once, in a fraction of the memory. A spring's files (pieces) are always loaded together.
    files = sorted(a.results.glob(a.pattern))
    if not files:
        raise SystemExit(f"no files match {a.pattern} in {a.results}")
    springs = {}
    for f in files:
        springs.setdefault(re.search(r"_(\d{4})(?:_|\.)", f.name).group(1), []).append(f)
    tables = []
    for spring, group in sorted(springs.items()):
        d = load_results(a.results, a.pattern, a.indices, files=group)
        if a.pool:
            d = pool_rings(d, a.pool)
        rings = rings_in(d)
        tables += [t for t in (paired(d, idx, a.min_pixels, rings) for idx in a.indices) if len(t)]
        del d
    seg = pd.concat(tables, ignore_index=True)
    dupes = seg.duplicated(["segment_id", "year", "ring", "index"]).sum()
    if dupes:
        raise SystemExit(f"{dupes} segment springs appear twice: check the file names give each spring's year")
    sample = pd.read_csv(a.sample / "sample_segments.csv")
    attrs = ["segment_id", "stratum", "weight"] + [g for g in GROUPS if g in sample.columns]
    seg = seg.merge(sample[attrs], on="segment_id", how="left")
    missing = seg["weight"].isna().sum()
    if missing:
        print(f"warning: {missing:,} rows have segments that are not in the sample file; they get weight 1")
        seg["weight"] = seg["weight"].fillna(1.0)
        seg["stratum"] = seg["stratum"].fillna("(not in sample)")
    a.out.mkdir(parents=True, exist_ok=True)
    seg.to_csv(a.out / "segment_spring.csv", index=False)

    # 4. pooled over springs: each segment's median across its springs, then the weighted statewide median
    rng = np.random.default_rng(392)
    pooled = (seg.groupby(["segment_id", "ring", "index"] + ["stratum", "weight"] + [g for g in GROUPS if g in seg])
                 [["diff_all", "diff_same_lc"]].median().reset_index())
    pooled["year"] = "all springs"
    seg["year"] = seg["year"].astype(str)
    out = []
    for data in (pooled, seg):
        for (yr, ring, idx), part in data.groupby(["year", "ring", "index"]):
            scopes = [("statewide", "Texas", part)] + [(g, k, p) for g in GROUPS if g in part for k, p in part.groupby(g)]
            for scope, value, p in scopes:
                for measure in ("diff_all", "diff_same_lc"):
                    n, est, lo, hi = summarize(p[measure].to_numpy(float), p["weight"].to_numpy(float),
                                               p["stratum"].to_numpy(str), a.boot if scope == "statewide" or yr == "all springs" else 0, rng)
                    out.append({"springs": yr, "scope": scope, "group": value, "ring": ring, "index": idx,
                                "measure": "all ground" if measure == "diff_all" else "same land cover",
                                "segments": n, "weighted_median": est, "lo95": lo, "hi95": hi})
    res = pd.DataFrame(out)
    res.to_csv(a.out / "statewide.csv", index=False)

    head = res[(res["springs"] == "all springs") & (res["scope"] == "statewide")].copy()
    head["result"] = head.apply(lambda x: f"{x['weighted_median']:+.4f} [{x['lo95']:+.4f}, {x['hi95']:+.4f}] n={x['segments']}", axis=1)
    table = head.pivot_table(index=["ring"], columns=["index", "measure"], values="result", aggfunc="first")
    table = table.reindex([f"{r} m" for r in rings if f"{r} m" in table.index])      # distance order, not alphabetical
    acc = res[(res["springs"] == "all springs") & (res["scope"] == "location_accuracy") & (res["ring"] == "0-50 m")
              & (res["measure"] == "same land cover")]
    lines = ["# Corridor results: ring minus its own 500-1,000 m comparison ring", "",
             f"Springs: {', '.join(sorted(seg['year'].unique()))}. Segments: {seg['segment_id'].nunique():,}. "
             f"Weighted median of each segment's typical difference, with 95% stratified-bootstrap intervals ({a.boot} draws).", "",
             "| ring | " + " | ".join(f"{i} ({m})" for i, m in table.columns) + " |",
             "|---|" + "---|" * len(table.columns)]
    lines += [f"| {r} | " + " | ".join(str(table.loc[r, c]) for c in table.columns) + " |" for r in table.index]
    lines += ["", "## 0-50 m ring, same land cover, by mapped location accuracy", "",
              "| accuracy | index | segments | weighted median | 95% interval |", "|---|---|---|---|---|"]
    lines += [f"| {x['group']} | {x['index']} | {x['segments']} | {x['weighted_median']:+.4f} | [{x['lo95']:+.4f}, {x['hi95']:+.4f}] |"
              for _, x in acc.sort_values(["index", "group"]).iterrows()]
    (a.out / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:8 + len(table.index)]))
    print(f"wrote {a.out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--results", type=Path, required=True)
    ap.add_argument("--pattern", default="*per_image*.csv")
    ap.add_argument("--sample", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--indices", nargs="+", default=["NDVI", "NDMI", "NDRE", "BSI"])
    ap.add_argument("--min-pixels", type=int, default=20)
    ap.add_argument("--boot", type=int, default=500)
    ap.add_argument("--pool", nargs="*", help='rebuild wide rings from narrow bands, e.g. "100-250=100-150,150-200,200-250"')
    main(ap.parse_args())
