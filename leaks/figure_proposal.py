"""Figure 1 of the revised proposal: reported spills on a map of Texas pipelines, and the zone design on real examples.

    python leaks/figure_proposal.py [--segment 147-000014-32-0-1] [--spill S024]

(a) Right-of-way spills from PHMSA (outputs/phmsa_texas_accidents.gpkg in this code folder, from leaks/phmsa_texas.py)
    over this year's Railroad Commission lines and the EPA Level III ecoregions (data/statewide).
(b) The ten 50 m bands and the comparison ring of one sampled segment exactly as built (outputs/zones/sample_v1,
    layer rings_b50), to scale, with the ground the cleaning rule leaves out.
(c) One matched spill with its rings and its candidate comparison spots on the same line
    (outputs/zones/statewide/spills_statewide.gpkg), to scale.
Writes outputs/figures/figure1_proposal.png in the projects folder.
"""
import argparse
import warnings
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pyogrio  # noqa: E402
import shapely  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from pyproj import Transformer  # noqa: E402

warnings.filterwarnings("ignore", message=".*GDAL_DATA.*")
plt.rcParams["font.family"] = ["Calibri", "DejaVu Sans"]      # the proposal's font, where installed
CODE = Path(__file__).resolve().parents[1]
PROJECT = CODE.parent
LINES = PROJECT / "data" / "statewide" / "pipelines_texas_rrc_20261006.gpkg"
ECOREGIONS = PROJECT / "data" / "statewide" / "ecoregions_epa_l3_texas.gpkg"
SAMPLE = PROJECT / "outputs" / "zones" / "sample_v1" / "sample.gpkg"
SPILLS = PROJECT / "outputs" / "zones" / "statewide" / "spills_statewide.gpkg"
EQUAL_AREA = 6579
SPILL, EARLY = "#7b1f2b", "#d9b3b8"
INK, LINE_GREY = "#222222", "#8c8c8c"
COMPARISON, LEFT_OUT = "#e3d7b8", "#efefef"
S2_START = "2018-06-01"  # a full year of Sentinel-2 surface reflectance over Texas exists before this date
TO_NAD27 = Transformer.from_crs(EQUAL_AREA, 4267, always_xy=True)


def band_colour(inner_m: float):
    """Dark green at the pipe, fading to pale green at 450-500 m."""
    return plt.get_cmap("Greens")(0.85 - 0.6 * inner_m / 450)


def lines_near(bounds, pad: float) -> gpd.GeoDataFrame:
    """Every published line (any status) in a box around the bounds, in the equal-area projection."""
    x0, y0, x1, y1 = bounds
    xs, ys = TO_NAD27.transform([x0 - pad, x1 + pad, x0 - pad, x1 + pad], [y0 - pad, y0 - pad, y1 + pad, y1 + pad])
    g = pyogrio.read_dataframe(LINES, layer="pipelines", columns=["STATUS_CD"], bbox=(min(xs), min(ys), max(xs), max(ys)))
    return g.to_crs(EQUAL_AREA)


def scale_bar(ax, x, y, metres, label, height):
    ax.add_patch(Rectangle((x, y), metres, height, facecolor=INK, edgecolor="none"))
    ax.text(x + metres / 2, y + 1.8 * height, label, fontsize=6.5, color=INK, ha="center", va="bottom")


def panel_map(ax):
    eco = pyogrio.read_dataframe(ECOREGIONS).to_crs(EQUAL_AREA)
    lines = pyogrio.read_dataframe(LINES, layer="pipelines", columns=["dup_geometry"], use_arrow=True)
    lines = lines[~lines["dup_geometry"].fillna(False).astype(bool)].to_crs(EQUAL_AREA)
    lines["geometry"] = shapely.simplify(lines.geometry.values, 60)
    pts = gpd.read_file(CODE / "outputs" / "phmsa_texas_accidents.gpkg")
    keep = (pts["LOCATION_TYPE"].fillna("").str.contains("RIGHT-OF-WAY")
            & pts["COMMODITY_RELEASED_TYPE"].fillna("").str.contains("CRUDE|REFINED|BIOFUEL")
            & (pts["UNINTENTIONAL_RELEASE_BBLS"] >= 5))
    spills = pts[keep].to_crs(EQUAL_AREA)
    recent = pd.to_datetime(spills["LOCAL_DATETIME"], errors="coerce") >= S2_START
    lines.plot(ax=ax, color="#9a9a9a", linewidth=0.1, alpha=0.3, rasterized=True)
    eco.boundary.plot(ax=ax, color="#555555", linewidth=0.45)
    size = lambda s: 5 + 9 * np.log10(s["UNINTENTIONAL_RELEASE_BBLS"].clip(lower=5) / 5)  # noqa: E731
    early, late = spills[~recent], spills[recent]
    early.plot(ax=ax, color=EARLY, markersize=size(early), edgecolor="white", linewidth=0.3, zorder=4)
    late.plot(ax=ax, color=SPILL, markersize=size(late), alpha=0.9, edgecolor="white", linewidth=0.3, zorder=5)
    x0, y0, x1, y1 = eco.total_bounds  # frame Texas itself, so the title sits on the map
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.ticklabel_format(style="plain", useOffset=False)  # no "1e6" offset label pushing the title up
    ax.set_axis_off()
    ax.set_title(f"a. Right-of-way spills of 5+ barrels\ndark: {recent.sum()} since mid-2018; light: {(~recent).sum()} earlier",
                 fontsize=7.5, color=INK, loc="left", pad=1)
    for bbl in (5, 100, 1000, 10000):
        ax.scatter([], [], s=5 + 9 * np.log10(bbl / 5), color=SPILL, edgecolor="white", linewidth=0.3, label=f"{bbl:,} bbl")
    ax.legend(loc="lower left", fontsize=6.3, frameon=False, handletextpad=0.2, borderaxespad=0.0, title="Spill size",
              title_fontsize=6.6, labelspacing=0.3)
    return int(recent.sum()), int((~recent).sum())


def panel_segment(ax, segment_id: str):
    seg = pyogrio.read_dataframe(SAMPLE, layer="segments", where=f"segment_id = '{segment_id}'")
    zones = pyogrio.read_dataframe(SAMPLE, layer="rings_b50", where=f"segment_id = '{segment_id}'")
    line = seg.geometry.iloc[0]
    full = shapely.buffer(line, 1000, cap_style="flat")       # every zone before cleaning (zones/build_zones.py)
    left_out = full.difference(shapely.union_all(zones.geometry.values))
    x0, y0, x1, y1 = full.bounds
    view = shapely.box(x0 - 30, y0 - 230, x1 + 30, y1 + 120)   # room below for the line that causes the cut
    near = lines_near(view.bounds, pad=100).clip(view)
    near["gap_m"] = near.distance(line)
    gpd.GeoSeries([left_out]).plot(ax=ax, color=LEFT_OUT, linewidth=0)
    for _, z in zones.sort_values("inner_m").iterrows():
        colour = COMPARISON if z["inner_m"] >= 500 else band_colour(z["inner_m"])
        gpd.GeoSeries([z.geometry]).plot(ax=ax, color=colour, linewidth=0)
    gpd.GeoSeries([full.exterior]).plot(ax=ax, color="#a8a8a8", linewidth=0.4, linestyle=(0, (2, 1.5)))
    near.plot(ax=ax, color=LINE_GREY, linewidth=0.9)
    seg.plot(ax=ax, color=INK, linewidth=1.6)
    # labels on the zones themselves, instead of a key
    mid = line.interpolate(0.5, normalized=True)
    comp = zones[zones["inner_m"] >= 500].geometry.iloc[0]
    right = max(shapely.get_parts(comp), key=lambda g: g.centroid.x)
    c = right.centroid
    ax.text(c.x, c.y + 120, "comparison\nring\n500–1,000 m", fontsize=6.5, color=INK, ha="center", va="center",
            linespacing=0.95)
    ax.text(mid.x, y1 + 25, "ten 50 m bands to 500 m, both sides", fontsize=6.5, color=INK, ha="center", va="bottom",
            bbox=dict(facecolor="white", edgecolor="none", pad=0.6))
    gone = max(shapely.get_parts(left_out), key=lambda g: g.area).representative_point()
    ax.text(gone.x - 120, gone.y - 60, "left out", fontsize=6.5, color="#555555", ha="center", va="center")
    other = near[near["gap_m"] > 50].sort_values("gap_m").iloc[0]  # the nearest other pipeline
    xs = np.linspace(x1 - 520, x1 - 120, 9)
    ys = [shapely.intersection(other.geometry, shapely.box(x - 1, view.bounds[1], x + 1, view.bounds[3])).centroid.y
          for x in xs]
    ax.text(xs.mean(), np.nanmin(ys) - 25, "another pipeline", fontsize=6.5, color="#555555", ha="center", va="top")
    vx0, vy0, vx1, vy1 = view.bounds
    ax.set_xlim(vx0, vx1)
    ax.set_ylim(vy0, vy1)
    ax.set_aspect("equal")
    ax.set_axis_off()                                          # the 1 km segment and the 50 m bands give the scale
    return seg.iloc[0]


def panel_spill(ax, spill_id: str):
    sites = pyogrio.read_dataframe(SPILLS, layer="sites", where=f"spill_id = '{spill_id}'")
    sites = sites[sites["site"].isin(["spill", "candidate"])]
    zones = pyogrio.read_dataframe(SPILLS, layer="zones", where=f"spill_id = '{spill_id}' AND zone_type = 'ring'")
    zones = zones[zones["site_id"].isin(sites["site_id"])]
    spill = sites[sites["site"] == "spill"].iloc[0]
    x0, y0, x1, y1 = sites.total_bounds
    pad = 450
    box = shapely.box(x0 - pad, y0 - pad, x1 + pad, y1 + pad)
    near = lines_near(box.bounds, pad=200).clip(box)
    near.plot(ax=ax, color="#c4c4c4", linewidth=0.5)
    # the matched line: the published line nearest to all of the spill's same-line spots
    d = np.array([shapely.distance(np.asarray(sites.geometry.array), g).sum() for g in near.geometry.values])
    near.iloc[[int(np.argmin(d))]].plot(ax=ax, color=LINE_GREY, linewidth=1.0)
    for _, z in zones.sort_values("outer_m", ascending=False).iterrows():
        at_spill = z["site_id"] == spill["site_id"]
        face = SPILL if at_spill else "white"
        alpha = {25: 1.0, 50: 0.75, 100: 0.5, 200: 0.28}[int(z["outer_m"])] if at_spill else 1.0
        gpd.GeoSeries([z.geometry]).plot(ax=ax, color=face, alpha=alpha, edgecolor=SPILL if at_spill else INK,
                                         linewidth=0.3, zorder=4)
    ax.set_xlim(x0 - pad, x1 + pad)
    ax.set_ylim(y0 - pad, y1 + pad)
    ax.set_aspect("equal")
    ax.set_axis_off()
    scale_bar(ax, x0 - pad + 80, y0 - pad + 60, 1000, "1 km", 45)
    sx, sy = spill.geometry.x, spill.geometry.y
    when = pd.Timestamp(spill["spill_date"]).strftime("%B %Y")
    ax.text(sx, sy + 260, f"spill, {spill['barrels']:,.0f} bbl, {when}", fontsize=6.5, color=SPILL, ha="center",
            bbox=dict(facecolor="white", edgecolor="none", pad=0.6, alpha=0.85),
            va="bottom")
    ax.text(x1 + pad - 60, y0 - pad + 60, "spots every 0.5 km, to 3 km each way", fontsize=6.5, color=INK, ha="right",
            va="bottom")
    return spill, len(sites) - 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--segment", default="147-000014-32-0-1")
    ap.add_argument("--spill", default="S024")
    ap.add_argument("--out", type=Path, default=PROJECT / "outputs" / "figures" / "figure1_proposal.png")
    a = ap.parse_args()
    a.out.parent.mkdir(parents=True, exist_ok=True)

    fig = plt.figure(figsize=(5.75, 2.75), dpi=300)
    recent, early = panel_map(fig.add_axes([0.0, 0.0, 0.47, 0.88]))

    bx = fig.add_axes([0.5, 0.29, 0.5, 0.59], anchor="N")
    s = panel_segment(bx, a.segment)
    bx.set_title("b. Zones of one sampled 1 km segment, to scale", fontsize=7.5, color=INK, loc="left", pad=1)

    cx = fig.add_axes([0.5, 0.0, 0.5, 0.19])
    spill, spots = panel_spill(cx, a.spill)
    # the candidates: spills.py keeps up to 3 per side that match the spill's land cover, soil and terrain (D18)
    cx.set_title(f"c. One spill and its {spots} candidate spots on the same line", fontsize=7.5, color=INK, loc="left", pad=1)

    fig.savefig(a.out, dpi=300, facecolor="white")
    print(f"wrote {a.out} | (a) {recent} spills since {S2_START}, {early} earlier | (b) {a.segment}: {s['commodity']}, "
          f"{s['diameter_in']} in, {s['status']}, {s['ecoregion']}, comparison kept {s['comparison_kept_share']:.2f} | "
          f"(c) {a.spill}: {spill['spill_date']}, {spill['barrels']} bbl, {spill['ecoregion']}, {spots} same-line spots")


if __name__ == "__main__":
    main()
