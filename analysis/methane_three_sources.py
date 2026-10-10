"""Gap 15: methane plumes from three independent sources, each tested against the Railroad Commission gas lines.

  1. Carbon Mapper's public catalog (methane_plumes.py; Tanager-1, EMIT, AVIRIS-NG/-3, GAO): noncommercial,
     credit "Data by Carbon Mapper®".
  2. NASA's EMIT L2B Estimated Methane Plume Complexes V002 (LP DAAC, EMITL2BCH4PLM): plumes found and checked by the
     EMIT team; location = the pixel of maximum enhancement, from each plume's metadata file (Earthdata login from
     the user's _netrc via earthaccess; the small JSON files only, cached in data/emit_plumes).
  3. MAPL-EMIT (Google Research with NASA JPL, Batchu et al. 2026, PNAS; arXiv 2604.10094), in Earth Engine:
     deep-learning plumes in all EMIT scenes; location = plume_head_lat/lon; 'high' confidence only (seen in 3 or more
     EMIT passes, false positive rate about 3-5%), 'medium' reported beside it. CC BY 4.0, "This dataset is produced
     by Google". Read from image properties only, so no Earth Engine compute is charged beyond metadata.
For each source: distance from each plume origin to the nearest gas line, against 5 random points within 5 km of each
plume (the same local density of lines, as in methane_plumes.py). Then how often the sources agree: a plume in one
source with a plume in another within 1 km and 3 days (EMIT-based plumes only, since they share the satellite).
Nearness is not attribution: wells, compressors and tanks sit beside the lines.
Writes outputs/results/methane_three_sources/: plumes_<source>.csv, SUMMARY.md, figure_methane_three_sources.png.
Usage: python methane_three_sources.py [--refresh]
"""
import argparse
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

P = Path(r"C:\mydrive\Graduate School\Courses\GEOG_392\projects")
OUT = P / "outputs" / "results" / "methane_three_sources"
CACHE = P / "data" / "emit_plumes"
GAS = {"NGT", "NGG", "NFG", "NGZ"}
BINS = [0, 100, 250, 500, 1000, np.inf]
BANDS = ["under 100 m", "100-250 m", "250-500 m", "500 m-1 km", "over 1 km"]
MAPL = "projects/climate-and-sustainability/assets/ghg/emit/mapl_emit_plumes_v1_0"
EMIT_PLM = "C3242707413-LPCLOUD"
BOX = (-106.65, 25.84, -93.51, 36.5)


def carbon_mapper() -> pd.DataFrame:
    d = pd.read_csv(P / "data" / "carbonmapper" / "plumes_texas_ch4.csv")
    return pd.DataFrame({"plume_id": d["plume_id"], "time": pd.to_datetime(d["time"], format="ISO8601", utc=True),
                         "lon": d["lon"], "lat": d["lat"], "instrument": d["instrument"], "emission_kg_h": d["emission_kg_h"]})


def emit_l2b(refresh: bool) -> pd.DataFrame:
    table = CACHE / "emit_l2b_ch4plm_texas.csv"
    if table.exists() and not refresh:
        return pd.read_csv(table, parse_dates=["time"])
    import earthaccess
    earthaccess.login(strategy="netrc")
    grans = earthaccess.search_data(concept_id=EMIT_PLM, bounding_box=BOX)
    meta = [l for g in grans for l in g.data_links() if "CH4PLMMETA" in l and l.endswith(".json")]
    CACHE.mkdir(parents=True, exist_ok=True)
    have = {p.name for p in CACHE.glob("*.json")}
    todo = [u for u in meta if u.rsplit("/", 1)[1] not in have]
    if todo:
        earthaccess.download(todo, str(CACHE))
    rows = []
    for f in sorted(CACHE.glob("EMIT_L2B_CH4PLMMETA_*.json")):
        for feat in json.loads(f.read_text(encoding="utf-8")).get("features", []):
            p = feat.get("properties", {})
            if feat.get("geometry", {}).get("type") != "Point" and "Max Plume Concentration (ppm m)" not in p:
                continue
            lon = p.get("Longitude of max concentration") or (feat["geometry"]["coordinates"][0] if feat["geometry"]["type"] == "Point" else None)
            lat = p.get("Latitude of max concentration") or (feat["geometry"]["coordinates"][1] if feat["geometry"]["type"] == "Point" else None)
            rows.append({"plume_id": p.get("Plume ID", f.stem), "time": p.get("UTC Time Observed"), "lon": lon, "lat": lat,
                         "max_ppm_m": p.get("Max Plume Concentration (ppm m)"),
                         "emission_kg_h": p.get("Emissions Rate Estimate (kg/hr)"), "granule": f.stem})
    d = pd.DataFrame(rows).dropna(subset=["lon", "lat"]).drop_duplicates("plume_id")
    d["time"] = pd.to_datetime(d["time"], utc=True, errors="coerce")
    d.to_csv(table, index=False)
    return d


def mapl(refresh: bool) -> pd.DataFrame:
    table = CACHE / "mapl_emit_texas.csv"
    if table.exists() and not refresh:
        return pd.read_csv(table, parse_dates=["time"])
    import ee
    ee.Initialize(project="research-476723")
    col = ee.ImageCollection(MAPL).filterBounds(ee.Geometry.Rectangle(list(BOX)))
    keys = ["plume_head_lat", "plume_head_lon", "confidence", "d_norm", "cluster_size", "fitted_enh",
            "temporal_cluster_index", "time_start"]
    n = col.size().getInfo()
    rows = []
    for start in range(0, n, 500):
        part = ee.FeatureCollection(col.toList(500, start).map(
            lambda i: ee.Feature(None, ee.Image(i).toDictionary(keys)).set("image_id", ee.Image(i).get("system:index"))))
        rows += [f["properties"] for f in part.getInfo()["features"]]
    d = pd.DataFrame(rows).rename(columns={"plume_head_lat": "lat", "plume_head_lon": "lon", "image_id": "plume_id"})
    d["time"] = pd.to_datetime(d["time_start"], unit="ms", utc=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    d.to_csv(table, index=False)
    return d


def line_test(d: pd.DataFrame, tx, gas, rng) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    g = gpd.GeoDataFrame(d, geometry=gpd.points_from_xy(d["lon"], d["lat"]), crs=4326).to_crs(3083)
    g = g[g.within(tx)].copy()
    g = gpd.sjoin_nearest(g, gas[["geometry"]], how="left", distance_col="gas_line_m").drop_duplicates("plume_id").drop(columns="index_right")
    k = 5
    r, th = 5000 * np.sqrt(rng.random(len(g) * k)), 2 * np.pi * rng.random(len(g) * k)
    bx = np.repeat(g.geometry.x.to_numpy(), k) + r * np.cos(th)
    by = np.repeat(g.geometry.y.to_numpy(), k) + r * np.sin(th)
    base = gpd.GeoDataFrame({"i": np.arange(len(bx))}, geometry=gpd.points_from_xy(bx, by), crs=3083)
    base = gpd.sjoin_nearest(base, gas[["geometry"]], how="left", distance_col="gas_line_m").drop_duplicates("i")
    g["gas_band"] = pd.cut(g["gas_line_m"], BINS, right=False, labels=BANDS)
    t = pd.DataFrame({"plumes": g["gas_band"].value_counts().reindex(BANDS),
                      "share": g["gas_band"].value_counts(normalize=True).reindex(BANDS),
                      "random_share": pd.cut(base["gas_line_m"], BINS, right=False, labels=BANDS).value_counts(normalize=True).reindex(BANDS)})
    return g, t


def agreement(a: gpd.GeoDataFrame, b: gpd.GeoDataFrame, km: float = 1.0, days: float = 3.0) -> float:
    """Share of plumes in a with a plume in b within km and days."""
    if a.empty or b.empty:
        return np.nan
    j = gpd.sjoin(a[["plume_id", "time", "geometry"]], b[["time", "geometry"]].rename(columns={"time": "time_b"}),
                  how="left", predicate="dwithin", distance=km * 1000)          # every pair within km, not just the nearest
    j["dt"] = (j["time"] - j["time_b"]).abs().dt.total_seconds() / 86400
    return float(j.groupby("plume_id")["dt"].min().le(days).reindex(a["plume_id"]).fillna(False).mean())


def main(a):
    rng = np.random.default_rng(392)
    tx = gpd.read_file(P / "data" / "statewide" / "ecoregions_epa_l3_texas.gpkg").to_crs(3083).union_all()
    lines = gpd.read_file(P / "data" / "statewide" / "pipelines_texas_rrc_20261006.gpkg",
                          columns=["COMMODITY1", "dup_geometry"]).to_crs(3083)
    gas = lines[(lines["dup_geometry"] != 1) & lines["COMMODITY1"].isin(GAS)]
    m = mapl(a.refresh)
    sources = {"Carbon Mapper (all platforms)": carbon_mapper(), "EMIT L2B plume complexes (NASA)": emit_l2b(a.refresh),
               "MAPL-EMIT, high confidence (Google/JPL)": m[m["confidence"] == "high"],
               "MAPL-EMIT, medium confidence": m[m["confidence"] == "medium"]}
    OUT.mkdir(parents=True, exist_ok=True)
    done, tables = {}, {}
    for name, d in sources.items():
        g, t = line_test(d, tx, gas, rng)
        done[name], tables[name] = g, t
        g.drop(columns="geometry").to_csv(OUT / f"plumes_{name.split(' ')[0].lower().replace('-', '_')}_{len(tables)}.csv", index=False)
    cm_emit = done["Carbon Mapper (all platforms)"]
    cm_emit = cm_emit[cm_emit["instrument"] == "emi"]
    emit_sets = {"Carbon Mapper EMIT": cm_emit, "EMIT L2B": done["EMIT L2B plume complexes (NASA)"],
                 "MAPL-EMIT high": done["MAPL-EMIT, high confidence (Google/JPL)"]}
    lines_md = [f"# Methane plumes from three sources and the Texas gas lines ({pd.Timestamp.today():%Y-%m-%d})", "",
                "Share of plume origins by distance to the nearest Railroad Commission gas line, against random points within "
                "5 km of each plume. A ratio above 1 in the first column means plumes start on the gas network more often than chance.", "",
                "| Source | Plumes in Texas | Years | Under 100 m: plumes / random | Ratio | Median distance (m) |", "|---|---|---|---|---|---|"]
    for name, g in done.items():
        t = tables[name]
        yrs = f"{g['time'].dt.year.min():.0f}-{g['time'].dt.year.max():.0f}" if g["time"].notna().any() else "-"
        r0 = t["share"].iloc[0] / max(t["random_share"].iloc[0], 1e-9) if len(g) else np.nan
        lines_md.append(f"| {name} | {len(g):,} | {yrs} | {t['share'].iloc[0]:.0%} / {t['random_share'].iloc[0]:.0%} | "
                        f"{r0:.1f} | {g['gas_line_m'].median():,.0f} |" if len(g) else f"| {name} | 0 | - | - | - | - |")
    lines_md += ["", "Agreement between the EMIT-based sources (a plume in the row source with one in the column source within "
                 "1 km and 3 days):", "", "| | " + " | ".join(emit_sets) + " |", "|---" * (len(emit_sets) + 1) + "|"]
    for ra, ga in emit_sets.items():
        lines_md.append(f"| {ra} ({len(ga):,}) | " + " | ".join("-" if ra == rb else f"{agreement(ga, gb):.0%}" for rb, gb in emit_sets.items()) + " |")
    lines_md += ["", "Nearness is not attribution: wells, compressors and tanks sit beside the lines, and plume origins and the "
                 "mapped lines both have errors of tens of meters. Credits: Data by Carbon Mapper® (noncommercial use only); "
                 "EMIT L2B: NASA JPL / LP DAAC; MAPL-EMIT: This dataset is produced by Google (CC BY 4.0), Batchu et al. 2026."]
    (OUT / "SUMMARY.md").write_text("\n".join(lines_md) + "\n", encoding="utf-8")
    print("\n".join(lines_md))

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.4), dpi=200)
    txs = gpd.GeoSeries([tx], crs=3083)
    for ax, (name, color) in zip(axes, [("Carbon Mapper (all platforms)", "#b2182b"), ("EMIT L2B plume complexes (NASA)", "#2166ac"),
                                         ("MAPL-EMIT, high confidence (Google/JPL)", "#1b7837")]):
        txs.boundary.plot(ax=ax, color="#9a9a9a", linewidth=0.4)
        gas.plot(ax=ax, color="#d0d0d0", linewidth=0.08)
        g = done[name]
        ax.scatter(g.geometry.x, g.geometry.y, s=4, c=color, alpha=0.7, linewidths=0)
        ax.set_title(f"{name}\n{len(g):,} plumes", fontsize=8)
        ax.set_axis_off()
    fig.suptitle("Methane plumes over Texas from three sources, with Railroad Commission gas lines", fontsize=10)
    fig.text(0.01, 0.01, "Data by Carbon Mapper® (noncommercial use). EMIT L2B CH4PLM V002: NASA JPL, LP DAAC. "
             "MAPL-EMIT: This dataset is produced by Google (CC BY 4.0).", fontsize=6.5, color="0.3")
    fig.tight_layout()
    fig.savefig(OUT / "figure_methane_three_sources.png", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--refresh", action="store_true", help="download the EMIT and MAPL-EMIT plumes again")
    main(ap.parse_args())
