"""The team's project database: one GeoPackage with every layer and table, a 1 km raster, and one symbology file that
the QGIS project, the ArcGIS Pro project and the Colab notebook all read, so every map uses the same classes and colors.

Layers (EPSG:6579, NAD83(2011) Texas Centric Albers Equal Area):
  pipelines_2026        every measured 1 km segment, spring 2026: band gap, cleared width, calibrated gap and how much
                        less green than nearby land (%), with a plain class label (plan D23, D28)
  sample_9springs       the 3,499 random segments plus the supplement, median over all nine springs (steadier per segment)
  counties, ecoregions  the same summarized: calibrated % per county (from pipelines_2026) and per ecoregion (the official
                        calibrated estimates with 95% intervals, clearing_calibration)
  hot_spots             Gi* cold and hot spots of the 0-50 m gap, how many springs each segment was one
  spill_locations       the 82 reported spills as points, with their station along the line (no spill results: blind)
  methane_plumes        Carbon Mapper (noncommercial use only), NASA EMIT and Google MAPL-EMIT plumes, distance to gas lines
Tables: about_layers (what each layer is), widths, calibrated_by_group, coverage, distance_profile, size_standardized,
methane_summary. Raster: pct_vs_nearby_1km_2026.tif (Cloud-Optimized GeoTIFF).
Class breaks follow the measurement's noise: one segment's value swings about +/-27% from spring to spring, so a single
segment is only called less green past -25%, and much less green past -50%. Summaries (counties, ecoregions, 1 km cells)
average many segments and use finer breaks.
Writes projects/Project database/. Usage: python project_database.py
"""
import json
import sqlite3
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.codes import diameter_class  # noqa: E402
from common.config import ECOREGIONS, P, PUBLISH, R, STATS  # noqa: E402
from common.gaps import calibrated  # noqa: E402
from common.rings import COMPARISON, suffix  # noqa: E402
from common.stats import wmedian  # noqa: E402

OUT = P / "Project database"
GPKG = OUT / "Group10_pipeline_project.gpkg"
CRS = 6579

SYMBOLOGY = {
    "segments": {
        "field": "pct_vs_nearby", "title": "Greenness of the pipeline strip vs. similar land nearby",
        "note": "One segment's value swings about ±27% from spring to spring, so only large drops stand out.",
        "classes": [
            {"label": "Much less green (−50% or lower)", "min": -1000, "max": -50, "color": "#6b3a07", "width_mm": 0.9, "dash": False},
            {"label": "Less green (−50% to −25%)", "min": -50, "max": -25, "color": "#e07b39", "width_mm": 0.6, "dash": False},
            {"label": "About the same (−25% to +25%)", "min": -25, "max": 25, "color": "#bdbdbd", "width_mm": 0.25, "dash": False},
            {"label": "Greener (+25% or more)", "min": 25, "max": 1000, "color": "#2a78d6", "width_mm": 0.35, "dash": True}]},
    "areas": {
        "field": "pct_vs_nearby", "title": "Pipeline strips vs. nearby land, summarized",
        "note": "Calibrated for clearing width; median over many segments, so the classes can be finer.",
        "classes": [
            {"label": "−25% or lower", "min": -1000, "max": -25, "color": "#6b3a07", "hatch": False},
            {"label": "−25% to −15%", "min": -25, "max": -15, "color": "#b0521a", "hatch": False},
            {"label": "−15% to −10%", "min": -15, "max": -10, "color": "#e07b39", "hatch": False},
            {"label": "−10% to −5%", "min": -10, "max": -5, "color": "#f5b86b", "hatch": False},
            {"label": "−5% to 0%", "min": -5, "max": 0, "color": "#fbe3c0", "hatch": False},
            {"label": "Greener than nearby (above 0%)", "min": 0, "max": 1000, "color": "#c6dbef", "hatch": True}],
        "no_data": {"label": "Too little pipe to measure (under 20 km)", "color": "#ffffff"}},
    "hot_spots": {
        "field": "springs_cold", "title": "Springs (of 9) the segment was in a cold spot (cluster of less-green segments)",
        "classes": [
            {"label": "Never", "min": 0, "max": 0, "color": "#d9d9d9", "size_mm": 1.2},
            {"label": "1–2 springs", "min": 1, "max": 2, "color": "#f5b86b", "size_mm": 1.8},
            {"label": "3–5 springs", "min": 3, "max": 5, "color": "#d0702a", "size_mm": 2.4},
            {"label": "6–9 springs", "min": 6, "max": 9, "color": "#6b3a07", "size_mm": 3.0}]},
    "methane": {
        "field": "source", "title": "Methane plumes",
        "categories": [
            {"value": "Carbon Mapper", "color": "#2a78d6", "shape": "circle", "size_mm": 1.6},
            {"value": "NASA EMIT", "color": "#eb6834", "shape": "triangle", "size_mm": 2.0},
            {"value": "Google MAPL-EMIT", "color": "#1baf7a", "shape": "square", "size_mm": 1.7}],
        "credit": "Data by Carbon Mapper® (noncommercial use only). NASA EMIT (JPL, LP DAAC). MAPL-EMIT: this dataset is produced by Google (CC BY 4.0)."},
    "spills": {"title": "Reported spills (PHMSA)", "color": "#000000", "outline": "#ffffff", "shape": "star", "size_mm": 3.2},
    "checks": {"palettes": "Validated with the dataviz palette validator (colorblind separation, normal vision) and for "
                           "black-and-white print (lightness steps); classes that would merge in gray print carry a "
                           "second cue: line width, dashes, hatching or shape."},
}


def comparison_ndvi_wall() -> pd.Series:
    rows = []
    for f in sorted(STATS.glob("wall_*_wall_2026.csv")):
        d = pd.read_csv(f, usecols=["zone_id", "NDVI_mean", "NDVI_count"])
        d = d[d["zone_id"].str.endswith(suffix(COMPARISON)) & (d["NDVI_count"] > 0)]
        rows.append(d.assign(v=d["NDVI_mean"] * d["NDVI_count"]).groupby("zone_id")[["v", "NDVI_count"]].sum())
    s = pd.concat(rows)
    s = (s["v"] / s["NDVI_count"]).rename("comparison_ndvi")
    s.index = s.index.str.replace(suffix(COMPARISON), "", regex=False)
    return s


def label(pct, classes):
    out = np.full(len(pct), None, dtype=object)
    for c in classes:
        out[(pct >= c["min"]) & (pct < c["max"])] = c["label"]
    return out


def main():
    OUT.mkdir(exist_ok=True)
    if GPKG.exists():
        GPKG.unlink()
    widths = pd.read_csv(R / "clearing_calibration" / "widths.csv", index_col=0)
    W = widths["cleared_width_m"]

    seg = gpd.read_parquet(R / "wall_to_wall_2026" / "segments.parquet").to_crs(CRS)
    seg["diameter_class"] = diameter_class(seg["diameter_in"])
    seg = seg.join(comparison_ndvi_wall(), on="segment_id")
    seg["cleared_width_m"] = seg["diameter_class"].map(W)
    seg["calibrated_gap"] = calibrated(seg["NDVI_gap"], seg["diameter_class"], W)
    seg["pct_vs_nearby"] = (100 * seg["calibrated_gap"] / seg["comparison_ndvi"].clip(lower=0.05)).clip(-100, 100)
    seg["class"] = label(seg["pct_vs_nearby"].to_numpy(), SYMBOLOGY["segments"]["classes"])
    seg.loc[seg["hidden_until_photo_check"], "class"] = "Hidden until the photo check"
    seg = seg.rename(columns={"NDVI_gap": "band_gap_ndvi", "NDMI_gap": "band_gap_ndmi"})
    keep = ["segment_id", "line_uid", "commodity", "service", "diameter_in", "diameter_class", "status", "location_accuracy",
            "ecoregion", "piece_m", "start_m", "end_m", "band_gap_ndvi", "band_gap_ndmi", "comparison_ndvi", "cleared_width_m",
            "calibrated_gap", "pct_vs_nearby", "class", "hidden_until_photo_check", "geometry"]
    seg = seg[keep]
    seg.to_file(GPKG, layer="pipelines_2026", driver="GPKG")

    counties = gpd.read_file(f"zip://{P / 'data' / 'svi' / 'tl_2022_48_tract.zip'}").to_crs(CRS).dissolve("COUNTYFP", as_index=False)
    svi = pd.read_csv(P / "data" / "svi" / "Texas.csv", usecols=["STCNTY", "COUNTY"]).drop_duplicates("STCNTY")
    svi["COUNTYFP"] = svi["STCNTY"].astype(str).str[-3:]
    counties = counties.merge(svi[["COUNTYFP", "COUNTY"]], on="COUNTYFP", how="left").rename(columns={"COUNTY": "county"})
    mid = seg[seg["pct_vs_nearby"].notna()].copy()
    mid["geometry"] = mid.geometry.interpolate(0.5, normalized=True)
    j = gpd.sjoin(mid, counties[["COUNTYFP", "geometry"]], predicate="within")
    rows = []
    for fp, g in j.groupby("COUNTYFP"):
        km = g["piece_m"].sum() / 1000
        gap = wmedian(g["calibrated_gap"].to_numpy(float), g["piece_m"].to_numpy(float))
        comp = wmedian(g["comparison_ndvi"].to_numpy(float), g["piece_m"].to_numpy(float))
        rows.append({"COUNTYFP": fp, "km_measured": km, "segments": len(g), "calibrated_gap": gap,
                     "pct_vs_nearby": 100 * gap / max(comp, 0.05) if km >= 20 else np.nan})
    counties = counties.merge(pd.DataFrame(rows), on="COUNTYFP", how="left")
    counties["class"] = label(counties["pct_vs_nearby"].to_numpy(), SYMBOLOGY["areas"]["classes"])
    counties["class"] = counties["class"].fillna(SYMBOLOGY["areas"]["no_data"]["label"])
    counties[["COUNTYFP", "county", "km_measured", "segments", "calibrated_gap", "pct_vs_nearby", "class", "geometry"]].to_file(
        GPKG, layer="counties", driver="GPKG")

    cal = pd.read_csv(R / "clearing_calibration" / "calibrated.csv")
    eco_vals = cal[(cal["scope"] == "ecoregion") & (cal["measure"] == "same land cover")].rename(
        columns={"group": "ecoregion", "pct_of_comparison_ndvi": "pct_vs_nearby", "lo95_pct": "pct_lo95", "hi95_pct": "pct_hi95"})
    eco = gpd.read_file(ECOREGIONS).to_crs(CRS)
    name = "us_l3name" if "us_l3name" in eco else [c for c in eco.columns if "name" in c.lower()][0]
    eco = eco.dissolve(name, as_index=False).rename(columns={name: "ecoregion"})
    eco = eco.merge(eco_vals[["ecoregion", "band_gap", "calibrated_gap", "pct_vs_nearby", "pct_lo95", "pct_hi95"]], on="ecoregion", how="left")
    eco["class"] = label(eco["pct_vs_nearby"].to_numpy(), SYMBOLOGY["areas"]["classes"])
    eco[["ecoregion", "band_gap", "calibrated_gap", "pct_vs_nearby", "pct_lo95", "pct_hi95", "class", "geometry"]].to_file(
        GPKG, layer="ecoregions", driver="GPKG")

    pub = PUBLISH / "data"
    comp9 = pd.read_csv(R / "clearing_calibration" / "comparison_ndvi.csv", index_col="segment_id")["comparison_ndvi"]
    smp = gpd.read_parquet(pub / "corridor_segments.parquet").to_crs(CRS)
    smp["diameter_class"] = diameter_class(smp["diameter_in"])
    smp["cleared_width_m"] = smp["diameter_class"].map(W)
    smp["comparison_ndvi"] = smp["segment_id"].map(comp9)
    smp["calibrated_gap"] = calibrated(smp["NDVI_gap_same_lc"], smp["diameter_class"], W)
    smp["pct_vs_nearby"] = (100 * smp["calibrated_gap"] / smp["comparison_ndvi"].clip(lower=0.05)).clip(-100, 100)
    smp["class"] = label(smp["pct_vs_nearby"].to_numpy(), SYMBOLOGY["segments"]["classes"])
    smp.drop(columns=["bbox"], errors="ignore").to_file(GPKG, layer="sample_9springs", driver="GPKG")

    hs = gpd.read_parquet(pub / "hot_spots.parquet").to_crs(CRS).drop(columns=["bbox"], errors="ignore")
    hs["geometry"] = hs.geometry.interpolate(0.5, normalized=True)
    hs.to_file(GPKG, layer="hot_spots", driver="GPKG")
    gpd.read_parquet(pub / "spill_events.parquet").to_crs(CRS).drop(columns=["bbox"], errors="ignore").to_file(
        GPKG, layer="spill_locations", driver="GPKG")

    plumes = []
    for f, src in (("plumes_carbon_1.csv", "Carbon Mapper"), ("plumes_emit_2.csv", "NASA EMIT"), ("plumes_mapl_emit,_3.csv", "Google MAPL-EMIT")):
        d = pd.read_csv(R / "methane_three_sources" / f)
        keep_cols = [c for c in ["plume_id", "time", "lon", "lat", "instrument", "emission_kg_h", "max_ppm_m", "confidence",
                                 "gas_line_m", "gas_band"] if c in d]
        plumes.append(d[keep_cols].assign(source=src, license="noncommercial only; credit Data by Carbon Mapper®" if src == "Carbon Mapper"
                                          else ("CC BY 4.0; produced by Google" if "MAPL" in src else "NASA open data")))
    pl = pd.concat(plumes, ignore_index=True)
    pl["time"] = pl["time"].astype(str)
    gpd.GeoDataFrame(pl, geometry=gpd.points_from_xy(pl["lon"], pl["lat"]), crs=4326).to_crs(CRS).to_file(
        GPKG, layer="methane_plumes", driver="GPKG")

    # 1 km raster of the calibrated % (length-weighted gap over length-weighted comparison greenness per cell)
    ok = seg.dropna(subset=["calibrated_gap", "comparison_ndvi"])
    m = ok.geometry.interpolate(0.5, normalized=True)
    x0, y1 = np.floor(m.x.min() / 1000) * 1000, np.ceil(m.y.max() / 1000) * 1000
    cols, nrows = int(np.ceil((m.x.max() - x0) / 1000)) + 1, int(np.ceil((y1 - m.y.min()) / 1000)) + 1
    ci, ri = ((m.x - x0) // 1000).astype(int).to_numpy(), ((y1 - m.y) // 1000).astype(int).to_numpy()
    km = ok["piece_m"].to_numpy() / 1000
    g, c, n = np.zeros((nrows, cols)), np.zeros((nrows, cols)), np.zeros((nrows, cols))
    np.add.at(g, (ri, ci), ok["calibrated_gap"].to_numpy() * km)
    np.add.at(c, (ri, ci), ok["comparison_ndvi"].to_numpy() * km)
    np.add.at(n, (ri, ci), km)
    pct = np.where(n > 0, 100 * g / np.maximum(c, 0.05 * np.maximum(n, 1e-9)), -9999).astype("float32")
    pct = np.where(n > 0, np.clip(pct, -100, 100), -9999).astype("float32")
    with rasterio.open(OUT / "pct_vs_nearby_1km_2026.tif", "w", driver="COG", width=cols, height=nrows, count=1, dtype="float32",
                       crs=f"EPSG:{CRS}", transform=from_origin(x0, y1, 1000, 1000), nodata=-9999, compress="deflate") as dst:
        dst.write(pct, 1)
        dst.set_band_description(1, "Pipeline strip greenness vs nearby land (%), calibrated, spring 2026, 1 km cells")

    tables = {
        "widths": widths.reset_index().rename(columns={"index": "diameter_class"}),
        "calibrated_by_group": cal,
        "coverage": pd.read_csv(R / "coverage_estimate" / "estimates.csv"),
        "distance_profile": pd.read_csv(R / "corridor_sample_v1_b50_9springs" / "statewide.csv").query("scope == 'statewide'"),
        "size_standardized": pd.read_csv(R / "size_standardized" / "estimates.csv"),
        "about_layers": pd.DataFrame([
            ("pipelines_2026", "Every measured 1 km pipeline segment, spring 2026 composite. pct_vs_nearby = how much less green the "
             "cleared strip is than similar land 500-1,000 m away (calibrated for clearing width). One spring: noisy per segment."),
            ("sample_9springs", "The random sample, median over nine springs (2018-2026): steadier per segment than pipelines_2026."),
            ("counties", "Median of pipelines_2026 per county (counties with 20 km or more of measured pipe)."),
            ("ecoregions", "Official calibrated estimates per EPA Level III ecoregion with 95% intervals (nine springs, sample)."),
            ("hot_spots", "Gi* cold/hot spots of the 0-50 m gap, how many of nine springs each segment was one (points at segment midpoints)."),
            ("spill_locations", "Reported PHMSA spills on mapped lines, with station along the line. No spill results (blind photo check)."),
            ("methane_plumes", "Methane plumes from three sources with distance to the nearest gas line. Carbon Mapper: noncommercial only."),
            ("pct_vs_nearby_1km_2026.tif", "Raster of pipelines_2026 summarized to 1 km cells (same measure as counties).")],
            columns=["layer", "what_it_is"]),
    }
    with sqlite3.connect(GPKG) as con:
        for name, t in tables.items():
            t.to_sql(name, con, if_exists="replace", index=False)
            con.execute("INSERT OR REPLACE INTO gpkg_contents (table_name, data_type, identifier, description) VALUES (?, 'attributes', ?, ?)",
                        (name, name, f"table: {name}"))
    (OUT / "symbology.json").write_text(json.dumps(SYMBOLOGY, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {GPKG}: {len(seg):,} segments, {len(counties)} counties, {len(eco)} ecoregions, {len(pl):,} plumes")
    print(seg["class"].value_counts().to_dict())


if __name__ == "__main__":
    main()
