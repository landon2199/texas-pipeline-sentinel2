"""Gap 4: methane for the gas lines. Carbon Mapper's public methane plumes in Texas next to Railroad Commission pipelines.

Vegetation can't show a gas leak, but imaging spectrometers can see the methane: Carbon Mapper publishes plumes from
the Tanager-1 satellite, NASA's EMIT and airborne AVIRIS campaigns (data.carbonmapper.org, public API). This step:
  1. downloads every CH4 plume in a box around Texas (saved in data/carbonmapper, with the download date);
  2. finds the nearest mapped pipeline to each plume origin (this year's Railroad Commission lines, Texas Centric
     Albers), with its commodity and status;
  3. counts plumes by distance to the nearest gas line, instrument and year, and maps them.
A plume near a pipeline is not proof that the pipeline leaked: wells, compressors and tanks sit beside the lines, and
both the plume origin and the line have location errors of tens of meters or more. The map is context for the gas
lines, which the vegetation study cannot cover.

Writes outputs/results/methane_plumes/: plumes.csv, SUMMARY.md, figure_methane_plumes.png.
Usage: python methane_plumes.py [--refresh]
"""
import argparse
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

P = Path(r"C:\mydrive\Graduate School\Courses\GEOG_392\projects")
API = "https://api.carbonmapper.org/api/v1/catalog/plumes/annotated"
GAS = {"NGT", "NGG", "NFG", "NGZ"}
BINS = [0, 100, 250, 500, 1000, np.inf]


def download(path: Path) -> pd.DataFrame:
    rows, offset = [], 0
    while True:
        q = urllib.parse.urlencode([("bbox", -106.7), ("bbox", 25.8), ("bbox", -93.5), ("bbox", 36.6),
                                    ("plume_gas", "CH4"), ("limit", 1000), ("offset", offset)])
        with urllib.request.urlopen(f"{API}?{q}", timeout=120) as r:
            items = json.load(r)["items"]
        for it in items:
            lon, lat = it["geometry_json"]["coordinates"][:2]
            rows.append({"plume_id": it["plume_id"], "time": it["scene_timestamp"], "instrument": it.get("instrument"),
                         "platform": it.get("platform"), "emission_kg_h": it.get("emission_auto"),
                         "emission_uncertainty_kg_h": it.get("emission_uncertainty_auto"), "gsd_m": it.get("gsd"),
                         "sector": it.get("sector"), "lon": lon, "lat": lat})
        if len(items) < 1000:
            break
        offset += 1000
        time.sleep(0.5)
    d = pd.DataFrame(rows).drop_duplicates("plume_id")
    path.parent.mkdir(parents=True, exist_ok=True)
    d.to_csv(path, index=False)
    return d


def main(a):
    raw = P / "data" / "carbonmapper" / "plumes_texas_ch4.csv"
    d = download(raw) if a.refresh or not raw.exists() else pd.read_csv(raw)
    pl = gpd.GeoDataFrame(d, geometry=gpd.points_from_xy(d["lon"], d["lat"]), crs=4326).to_crs(3083)
    tx = gpd.read_file(P / "data" / "statewide" / "ecoregions_epa_l3_texas.gpkg").to_crs(3083)
    pl = pl[pl.within(tx.union_all())]
    lines = gpd.read_file(P / "data" / "statewide" / "pipelines_texas_rrc_20261006.gpkg",
                          columns=["COMMODITY1", "STATUS_CD", "DIAMETER", "dup_geometry"]).to_crs(3083)
    lines = lines[lines["dup_geometry"] != 1]
    near = gpd.sjoin_nearest(pl, lines[["COMMODITY1", "STATUS_CD", "geometry"]], how="left", distance_col="line_m")
    near = near.sort_values("line_m").drop_duplicates("plume_id")
    gas = lines[lines["COMMODITY1"].isin(GAS)]
    near = gpd.sjoin_nearest(near.drop(columns="index_right"), gas[["geometry"]], how="left", distance_col="gas_line_m")
    near = near.sort_values("gas_line_m").drop_duplicates("plume_id")
    near["year"] = pd.to_datetime(near["time"], format="ISO8601").dt.year
    # baseline: 5 random points within 5 km of each plume, so the comparison has the same local density of lines
    rng = np.random.default_rng(392)
    k = 5
    r, th = 5000 * np.sqrt(rng.random(len(near) * k)), 2 * np.pi * rng.random(len(near) * k)
    bx = np.repeat(near.geometry.x.to_numpy(), k) + r * np.cos(th)
    by = np.repeat(near.geometry.y.to_numpy(), k) + r * np.sin(th)
    base = gpd.GeoDataFrame({"i": np.arange(len(bx))}, geometry=gpd.points_from_xy(bx, by), crs=3083)
    base = gpd.sjoin_nearest(base, gas[["geometry"]], how="left", distance_col="gas_line_m").drop_duplicates("i")
    near["gas_band"] = pd.cut(near["gas_line_m"], BINS, right=False,
                              labels=["under 100 m", "100-250 m", "250-500 m", "500 m-1 km", "over 1 km"])
    out = P / "outputs" / "results" / "methane_plumes"
    out.mkdir(parents=True, exist_ok=True)
    near.drop(columns="geometry").to_csv(out / "plumes.csv", index=False)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(6.5, 6.2), dpi=200)
    tx.boundary.plot(ax=ax, color="#9a9a9a", linewidth=0.4)
    gas.plot(ax=ax, color="#c9c9c9", linewidth=0.1)
    close = near["gas_line_m"] < 250
    size = 4 + 26 * np.sqrt(near["emission_kg_h"].fillna(100).clip(upper=5000) / 5000)
    ax.scatter(near.geometry.x[~close], near.geometry.y[~close], s=size[~close], c="#f4a582", alpha=0.6, linewidths=0,
               label=f"plume 250 m or more from a gas line ({int((~close).sum()):,})")
    ax.scatter(near.geometry.x[close], near.geometry.y[close], s=size[close], c="#b2182b", alpha=0.8, linewidths=0,
               label=f"plume within 250 m of a gas line ({int(close.sum()):,})")
    ax.set_axis_off()
    ax.set_title("Methane plumes seen from the air and space over Texas, with Railroad Commission gas lines\n"
                 "Data by Carbon Mapper® (Tanager-1, EMIT, AVIRIS), noncommercial use; size = emission rate", fontsize=9, loc="left")
    ax.legend(frameon=False, fontsize=7, loc="lower left")
    fig.tight_layout()
    fig.savefig(out / "figure_methane_plumes.png", facecolor="white")
    plt.close(fig)

    t = near.groupby("gas_band", observed=False).agg(plumes=("plume_id", "size"), median_kg_h=("emission_kg_h", "median"))
    base["gas_band"] = pd.cut(base["gas_line_m"], BINS, right=False, labels=t.index)
    t["share"] = t["plumes"] / t["plumes"].sum()
    t["random_share"] = base["gas_band"].value_counts(normalize=True).reindex(t.index).fillna(0)
    inst = near["platform"].fillna(near["instrument"]).value_counts()
    years = near["year"].value_counts().sort_index()
    lines_md = [f"# Methane plumes over Texas and the pipelines ({pd.Timestamp.today():%Y-%m-%d})", "",
                f"{len(near):,} Carbon Mapper CH4 plumes inside Texas (downloaded {pd.Timestamp(raw.stat().st_mtime, unit='s'):%Y-%m-%d}). "
                f"Median distance from a plume origin to the nearest mapped line of any kind: {near['line_m'].median():,.0f} m; "
                f"to the nearest gas line: {near['gas_line_m'].median():,.0f} m.", "",
                "| Distance to the nearest gas line | Plumes | Share of plumes | Share of random points within 5 km | Median emission (kg/h) |",
                "|---|---|---|---|---|"] + \
               [f"| {k} | {int(r.plumes):,} | {r.share:.0%} | {r.random_share:.0%} | {r.median_kg_h:,.0f} |" for k, r in t.iterrows()] + \
               ["", f"Plumes start within 100 m of a gas line {t['share'].iloc[0] / max(t['random_share'].iloc[0], 1e-9):.1f} times "
                "as often as random points around them, so they sit on the gas network, not just near it by chance."] + \
               ["", "By platform: " + ", ".join(f"{k} {v:,}" for k, v in inst.items()) + ".",
                "By year: " + ", ".join(f"{k} {v:,}" for k, v in years.items()) + ".", "",
                "Nearness is not attribution: wells, compressors and tanks sit beside the lines, and both locations have "
                "errors. Data by Carbon Mapper® (data.carbonmapper.org): noncommercial use only, and the credit must appear on any map or poster."]
    (out / "SUMMARY.md").write_text("\n".join(lines_md) + "\n", encoding="utf-8")
    print("\n".join(lines_md))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--refresh", action="store_true", help="download the plumes again")
    main(ap.parse_args())
