"""Gaps 9 and 12: where is the pipe really? A fresh test of the right-of-way finder and the lines' position accuracy.

row_finder.py's rules were tuned on 24 segments, so this runs them, unchanged, on a fresh random sample: --per-class
segments from each mapped-accuracy class (Railroad Commission quality code: within 50 ft, 51-300 ft, 301-500 ft), in
service, from every ecoregion, never one of the 24. For each segment, SAM 2 and the NAIP NDVI profile each look for the
cleared strip. Where both find it and agree within 20 m, the segment is a checkpoint, and the line's cross-track offset
is the mean of the two. Reported:
  - how often the strip can be seen at all (it shows in brush and woodland, hardly in grassland or cropland);
  - the cross-track RMSE of the mapped lines at the checkpoints, by accuracy class. This is the error that matters for
    the 0-50 m band, in the spirit of the ASPRS Positional Accuracy Standards (2024, edition 2), which report RMSE
    against independent checkpoints. Here the checkpoints come from imagery, not survey, so read it as a screening
    estimate. Group A's photo check of the same segments is the independent confirmation.
Run with the GeoAI environment: C:\\Users\\Landon\\miniforge3\\envs\\geog392-geoai\\python.exe row_survey.py [--per-class 20]
Writes outputs/geoai/row_survey/: results.csv, SUMMARY.md and a figure per segment.

With --by diameter (plan D28) it instead draws --per-class fresh segments from each pipe diameter class, never one
already surveyed, to measure how wide the cleared strip is for each pipe size: the clearing-width calibration
(analysis/clearing_calibration.py). Written to outputs/geoai/width_survey/.
"""
import argparse
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import shapely

sys.path.insert(0, str(Path(__file__).resolve().parent))
import row_finder as rf  # noqa: E402

OUT = rf.P / "outputs" / "geoai" / "row_survey"


DIAMETERS = ["Under 4.5 in", "4.5-8.6 in", "8.6-12.75 in", "12.75-16 in", "16-24 in", "24-36 in", "Over 36 in"]


def pick(per_class: int, seed: int, by: str = "accuracy") -> gpd.GeoDataFrame:
    seg = gpd.read_file(rf.P / "outputs" / "zones" / "sample_v1" / "sample.gpkg", layer="segments")
    done = set(pd.read_csv(rf.OUT / "row_finder_results.csv")["segment_id"]) if (rf.OUT / "row_finder_results.csv").exists() else set()
    if by == "diameter":                # never re-measure a segment the accuracy survey already has
        prev = rf.P / "outputs" / "geoai" / "row_survey" / "results.csv"
        done |= set(pd.read_csv(prev)["segment_id"]) if prev.exists() else set()
    seg = seg[seg["status"].eq("In service") & ~seg["segment_id"].isin(done)]
    col, keep = ("diameter_class", DIAMETERS) if by == "diameter" else ("location_accuracy", rf.ACCURACY)
    return pd.concat([g.sample(n=min(per_class, len(g)), random_state=seed) for a, g in seg.groupby(col) if a in keep])


def main(a):
    global OUT
    if a.by == "diameter":
        OUT = rf.P / "outputs" / "geoai" / "width_survey"
    (OUT / "chips").mkdir(parents=True, exist_ok=True)
    (OUT / "figures").mkdir(exist_ok=True)
    segs = pick(a.per_class, a.seed, a.by)
    col = "diameter_class" if a.by == "diameter" else "location_accuracy"
    print(f"{len(segs)} fresh segments: {segs[col].value_counts().to_dict()}", flush=True)
    rows = []
    if (OUT / "results.csv").exists() and not a.redo:        # keep finished segments; run only the ones that failed
        old = pd.read_csv(OUT / "results.csv")
        old = old[old["segment_id"].isin(segs["segment_id"])].drop(columns=["checkpoint", "offset_m", "photo_check_first"], errors="ignore")
        rows = old.to_dict("records")
        segs = segs[~segs["segment_id"].isin(old["segment_id"])]
        print(f"  {len(rows)} done before; {len(segs)} to run", flush=True)
    from samgeo import SamGeo2
    sam = SamGeo2(model_id="sam2-hiera-large", automatic=False)
    for s in segs.itertuples():
        line = shapely.line_merge(s.geometry) if s.geometry.geom_type == "MultiLineString" else s.geometry
        try:
            chip = rf.naip_chip(line, OUT / "chips" / f"{s.segment_id}.tif")
            with rasterio.open(chip) as src:
                img, transform = src.read().astype("float32"), src.transform
            off, along, middle = rf.line_frame(line, img.shape[1:], transform)
            res, prof = rf.ndvi_profile(img, off, middle)
            rgb = OUT / "chips" / f"{s.segment_id}_rgb.tif"
            if not rgb.exists():
                with rasterio.open(chip) as src, rasterio.open(rgb, "w", **(src.profile | {"count": 3})) as dst:
                    dst.write(src.read([1, 2, 3]))
            sam.set_image(str(rgb))
            best = rf.sam_search(sam, line, off, along, middle)
        except Exception as e:
            print(f"  {s.segment_id}: failed ({type(e).__name__}: {e})", flush=True)
            continue
        res = {"segment_id": s.segment_id, "location_accuracy": s.location_accuracy, "ecoregion": s.ecoregion,
               "commodity": s.commodity, "service": s.service, "diameter_in": s.diameter_in,
               "diameter_class": s.diameter_class, **res,
               **({k: v for k, v in best.items() if k not in ("mask", "rank")} if best else {"sam_offset_m": np.nan})}
        rf.figure(chip, line, res, prof, best, transform, OUT / "figures" / f"{s.segment_id}.png")
        rows.append(res)
        print(f"  {s.segment_id} ({s.location_accuracy}, {s.ecoregion}): NDVI {res['ndvi_offset_m']:+.0f} m; "
              f"SAM 2 {res['sam_offset_m']:+.0f} m", flush=True)
    t = pd.DataFrame(rows)
    t["checkpoint"] = (t["sam_offset_m"] - t["ndvi_offset_m"]).abs() <= 20
    t["offset_m"] = np.where(t["checkpoint"], (t["sam_offset_m"] + t["ndvi_offset_m"]) / 2, np.nan)
    # two methods can agree on the wrong strip (a road or another right-of-way alongside), most likely far from the line
    t["photo_check_first"] = t["offset_m"].abs() > 30
    t.to_csv(OUT / "results.csv", index=False)
    if a.by == "diameter":
        cp = t[t["checkpoint"] & ~t["photo_check_first"]]
        lines = [f"# How wide is the cleared strip? {len(t)} fresh segments by pipe size ({pd.Timestamp.today():%Y-%m-%d})", "",
                 "| Diameter | Segments | SAM 2 found a strip | Confirmed (both methods agree) | Median SAM 2 width (m) | Median NDVI width (m) |",
                 "|---|---|---|---|---|---|"]
        for d in DIAMETERS:
            g, c = t[t["diameter_class"] == d], cp[cp["diameter_class"] == d]
            lines.append(f"| {d} | {len(g)} | {int(g['sam_offset_m'].notna().sum())} | {len(c)} | "
                         f"{g['sam_width_m'].median():.0f} | {c['ndvi_width_m'].median():.0f} |")
        lines += ["", "SAM 2's width is the 10th-90th percentile spread of the strip mask (about 80% of the full width); "
                  "the NDVI width runs between the trough's half-depth edges. analysis/clearing_calibration.py turns these "
                  "into a cleared width per pipe size. First results, not findings."]
        (OUT / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n".join(lines))
        return
    lines = [f"# Where is the pipe? Right-of-way finder on {len(t)} fresh segments ({pd.Timestamp.today():%Y-%m-%d})", "",
             "| Mapped accuracy | Segments | SAM 2 found a strip | Checkpoints (both methods agree) | Cross-track RMSE (m) | Median abs. offset (m) | Max (m) |",
             "|---|---|---|---|---|---|---|"]
    for acc in rf.ACCURACY + ["all"]:
        g = t if acc == "all" else t[t["location_accuracy"] == acc]
        cp = g["offset_m"].dropna()
        rmse = float(np.sqrt((cp ** 2).mean())) if len(cp) else np.nan
        lines.append(f"| {acc} | {len(g)} | {int(g['sam_offset_m'].notna().sum())} | {len(cp)} | "
                     f"{rmse:.1f} | {cp.abs().median():.1f} | {cp.abs().max():.1f} |" if len(cp) else
                     f"| {acc} | {len(g)} | {int(g['sam_offset_m'].notna().sum())} | 0 | - | - | - |")
    by_eco = t.groupby("ecoregion").agg(segments=("segment_id", "size"), checkpoints=("checkpoint", "sum"))
    lines += ["", "Strip found and confirmed, by ecoregion: " +
              ", ".join(f"{e} {int(r.checkpoints)}/{int(r.segments)}" for e, r in by_eco.iterrows()) + ".", "",
              f"{int(t['photo_check_first'].sum())} checkpoints sit more than 30 m from the mapped line "
              "(`photo_check_first`): the two methods may have agreed on a road or another right-of-way alongside, so "
              "Group A looks at those first. Without them, the cross-track RMSE is "
              f"{np.sqrt((t.loc[~t['photo_check_first'], 'offset_m'].dropna() ** 2).mean()):.1f} m.", "",
              "Checkpoints come from imagery (two independent methods agreeing), not from survey, so this is a screening "
              "estimate of the lines' position error; Group A's photo check of these segments confirms it. A cross-track "
              "error under about 25 m keeps the pipe inside the 0-50 m band. First results, not findings."]
    (OUT / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--per-class", type=int, default=20)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--redo", action="store_true", help="rerun every segment, not just the ones without a result")
    ap.add_argument("--by", choices=["accuracy", "diameter"], default="accuracy",
                    help="draw segments per mapped-accuracy class (position check) or per diameter class (width calibration)")
    main(ap.parse_args())
