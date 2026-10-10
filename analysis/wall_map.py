"""Plan D23: the wall-to-wall map. Every measured segment's 0-50 m gap from one spring's median composite.

Reads the wall-to-wall tables (extract/run_wall_to_wall.py) and computes each segment's gap the same way as the strip
diagrams: the 0-50 m band minus its comparison ring, same NLCD land cover (pixel-weighted), at least 20 pixels in each.
The image-by-image sample stays the main test; this layer is for the map, and its statewide median is compared with the
sample's as a check that the cheaper composite measure tells the same story.
Blind until the photo check: the gap is left out within 1 km of a reported spill (along its route), as on the strip
diagrams. --unblind shows it, only after the photo check.
Writes outputs/results/wall_to_wall_<spring>/:
  - segments.parquet (GeoParquet 1.1, EPSG:4326): every measured segment with its gap;
  - gap_1km.tif (Cloud-Optimized GeoTIFF, EPSG:6579, 1 km cells): the length-weighted mean NDVI gap of the segments
    whose midpoints fall in each cell (band 1) and the km of measured pipe in it (band 2);
  - figure_wall_to_wall.png and SUMMARY.md.
Usage: python wall_map.py [--spring 2026] [--unblind]
"""
import argparse
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import rasterio
from rasterio.transform import from_origin

sys.path.insert(0, str(Path(__file__).resolve().parent))
from strip_diagram import gaps  # noqa: E402

P = Path(r"C:\mydrive\Graduate School\Courses\GEOG_392\projects")
S = P / "outputs" / "zones" / "statewide"
ZS = P / "outputs" / "geog392_zone_stats"
COLS = ["segment_id", "line_uid", "commodity", "service", "diameter_in", "status", "location_accuracy", "ecoregion",
        "piece_m", "start_m", "end_m", "has_comparison"]
CELL = 1000


def wmedian(v, w):
    o = np.argsort(v)
    c = np.cumsum(w[o])
    return v[o][np.searchsorted(c, c[-1] / 2)]


def main(a):
    files = sorted(a.tables.glob(f"wall_*_wall_{a.spring}.csv"))
    if not files:
        sys.exit(f"no wall-to-wall tables for spring {a.spring} in {a.tables}")
    d = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    regions = sorted(f.name[len("wall_"):-len(f"_wall_{a.spring}.csv")] for f in files)
    g = pd.concat([gaps(d, i)[0] for i in ("NDVI", "NDMI")], axis=1)
    seg = pd.concat([pyogrio.read_dataframe(S / f"{r}.gpkg", layer="segments", columns=COLS, where="has_zones = 1")
                     for r in regions], ignore_index=True)
    seg = seg.merge(g, left_on="segment_id", right_index=True, how="inner")
    seg["hidden_until_photo_check"] = False
    if not a.unblind:
        ev = pd.read_csv(S / "spill_stations.csv")
        for r in ev.dropna(subset=["measure_m"]).itertuples():
            near = (seg["line_uid"] == r.route) & (seg["end_m"] >= r.measure_m - 1000) & (seg["start_m"] <= r.measure_m + 1000)
            seg.loc[near, "hidden_until_photo_check"] = True
        seg.loc[seg["hidden_until_photo_check"], ["NDVI_gap", "NDMI_gap"]] = np.nan
    out = a.out or P / "outputs" / "results" / f"wall_to_wall_{a.spring}"
    out.mkdir(parents=True, exist_ok=True)
    seg.to_crs(4326).to_parquet(out / "segments.parquet", schema_version="1.1.0", write_covering_bbox=True, compression="zstd")

    ok = seg.dropna(subset=["NDVI_gap"])
    km = ok["piece_m"].to_numpy() / 1000
    mid = ok.geometry.interpolate(0.5, normalized=True)
    x0, y1 = np.floor(mid.x.min() / CELL) * CELL, np.ceil(mid.y.max() / CELL) * CELL
    cols, rows = int(np.ceil((mid.x.max() - x0) / CELL)) + 1, int(np.ceil((y1 - mid.y.min()) / CELL)) + 1
    ci, ri = ((mid.x - x0) // CELL).astype(int).to_numpy(), ((y1 - mid.y) // CELL).astype(int).to_numpy()
    num, den = np.zeros((rows, cols)), np.zeros((rows, cols))
    np.add.at(num, (ri, ci), ok["NDVI_gap"].to_numpy() * km)
    np.add.at(den, (ri, ci), km)
    mean = np.where(den > 0, num / np.where(den > 0, den, 1), -9999).astype("float32")
    with rasterio.open(out / "gap_1km.tif", "w", driver="COG", width=cols, height=rows, count=2, dtype="float32",
                       crs="EPSG:6579", transform=from_origin(x0, y1, CELL, CELL), nodata=-9999, compress="deflate",
                       overview_resampling="average") as dst:
        dst.write(mean, 1)
        dst.write(np.where(den > 0, den, -9999).astype("float32"), 2)
        dst.set_band_description(1, f"NDVI gap 0-50 m minus comparison, length-weighted mean, spring {a.spring}")
        dst.set_band_description(2, "km of measured pipe in the cell")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    tx = gpd.read_file(P / "data" / "statewide" / "ecoregions_epa_l3_texas.gpkg").to_crs(seg.crs)
    fig, ax = plt.subplots(figsize=(8, 7.4), dpi=220)
    tx.boundary.plot(ax=ax, color="#bdbdbd", linewidth=0.3)
    segs = [np.asarray(gm.coords)[:, :2] for gm in ok.geometry]
    lc = LineCollection(segs, array=ok["NDVI_gap"].clip(-0.1, 0.1).to_numpy(), cmap="RdBu", linewidths=0.35)
    lc.set_clim(-0.1, 0.1)
    ax.add_collection(lc)
    ax.set_axis_off()
    cb = fig.colorbar(lc, ax=ax, shrink=0.45)
    cb.set_label("NDVI gap, 0-50 m minus comparison\n(same land cover)", fontsize=7)
    cb.ax.tick_params(labelsize=6.5)
    ax.set_title(f"Every measured pipeline segment, spring {a.spring} median composite ({len(ok):,} segments, "
                 f"{km.sum():,.0f} km)\nRed: less green beside the pipe. Gaps within 1 km of a reported spill are left out "
                 "until the photo check. First results.", fontsize=7.5, loc="left")
    fig.savefig(out / "figure_wall_to_wall.png", facecolor="white", bbox_inches="tight")
    plt.close(fig)

    with_comp = ok[ok["has_comparison"].astype(bool)]
    s = pd.read_csv(P / "outputs" / "results" / "corridor_sample_v1_9springs_pooled" / "statewide.csv")
    s = s[(s["ring"] == "0-50 m") & (s["index"] == "NDVI") & (s["measure"] == "same land cover")
          & (s["springs"].astype(str) == str(a.spring))]
    st = s[s["scope"] == "statewide"]
    state = (f"{st['weighted_median'].iloc[0]:+.4f} [{st['lo95'].iloc[0]:+.4f}, {st['hi95'].iloc[0]:+.4f}]" if len(st) else "not available")
    s = s[s["scope"] == "ecoregion"]
    sample = {r.group: f"{r.weighted_median:+.4f} [{r.lo95:+.4f}, {r.hi95:+.4f}]" if pd.notna(r.lo95) else f"{r.weighted_median:+.4f}"
              for r in s.itertuples()}
    eco = with_comp.groupby("ecoregion").apply(lambda x: wmedian(x["NDVI_gap"].to_numpy(), x["piece_m"].to_numpy()), include_groups=False)
    lines = [f"# Wall-to-wall map, spring {a.spring} ({pd.Timestamp.today():%Y-%m-%d})", "",
             f"Regions measured: {len(regions)} of 11 ({', '.join(regions)}).",
             f"Segments with a gap: {len(ok):,} ({km.sum():,.0f} km); without enough pixels: {int(seg['NDVI_gap'].isna().sum() - seg['hidden_until_photo_check'].sum()):,}; "
             f"hidden near spills: {int(seg['hidden_until_photo_check'].sum()):,}.", "",
             f"Length-weighted median 0-50 m NDVI gap, segments with a clean comparison ring: "
             f"**{wmedian(with_comp['NDVI_gap'].to_numpy(), with_comp['piece_m'].to_numpy()):+.4f}** "
             f"(n={len(with_comp):,}); NDMI {wmedian(with_comp['NDMI_gap'].dropna().to_numpy(), with_comp.dropna(subset=['NDMI_gap'])['piece_m'].to_numpy()):+.4f}. "
             f"The image-by-image sample's statewide estimate for the same frame and spring is {state}. "
             "The composite measure is for the map; the sample is the test.", "",
             "| Ecoregion | Wall-to-wall: median NDVI gap (length-weighted) | Sample, image by image, same spring [95% CI] |",
             "|---|---|---|"] + [f"| {e} | {v:+.4f} | {sample.get(e, '-')} |" for e, v in eco.items()] + \
            ["", "Outputs: segments.parquet (GeoParquet), gap_1km.tif (COG, 1 km cells, EPSG:6579), figure_wall_to_wall.png. "
             "First results, not findings."]
    (out / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--spring", type=int, default=2026)
    ap.add_argument("--unblind", action="store_true", help="show the gap near spills (only after the photo check)")
    ap.add_argument("--tables", type=Path, default=ZS, help="folder with the wall-to-wall CSVs")
    ap.add_argument("--out", type=Path, help="output folder (default outputs/results/wall_to_wall_<spring>)")
    main(ap.parse_args())
