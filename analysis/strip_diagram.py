"""Gap 13: a strip diagram of one pipeline route, the way alignment sheets show a pipeline (station along the bottom).

Tracks, all against the measure along the route (zones/stations.py):
  1. ecoregion and county crossings;
  2. land cover in the 0-50 m band, segment by segment (NLCD 2021);
  3. the corridor gap: the 0-50 m band minus its own comparison ring, same land cover, from one median composite over
     all nine springs (2018-2026), the wall-to-wall measure (part2.lean_composite_values, plan 5.4);
  4. events: the reported spills on the route (public PHMSA reports) and the stretches with no clean comparison ring.
Until Group B's photo check is done, the gap is hidden within 1 km of a spill (--unblind shows it), so the diagram never
shows a spill's own result. The route's values come from the wall-to-wall tables when they exist; otherwise one small
Earth Engine request measures just this route (about 0.3 EECU-hours for 40 segments), cached in the output folder.
Usage: python strip_diagram.py [--route 127-006093] [--unblind]
Writes outputs/results/strip_diagram/<route>.png and <route>_segments.csv.
"""
import argparse
import datetime as dt
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyogrio
from matplotlib.patches import Patch

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE))
sys.path.insert(0, str(CODE / "zones"))
from common.codes import NLCD  # noqa: E402
from common.config import EE_PROJECT, R, S  # noqa: E402
from common.rings import BAND, COMPARISON, segment_of, suffix  # noqa: E402
from labels import station  # noqa: E402
from stations import route_segments  # noqa: E402

OUT = R / "strip_diagram"
RING, COMP = suffix(BAND), suffix(COMPARISON)


def zone_values(route: str, seg: pd.DataFrame) -> pd.DataFrame:
    cache = OUT / "_raw_do_not_open" / f"{route}_zone_values.csv"     # unmasked, like effects.csv: not before the photo check
    cache.parent.mkdir(exist_ok=True)
    if (OUT / f"{route}_zone_values.csv").exists():
        (OUT / f"{route}_zone_values.csv").rename(cache)
    if cache.exists():
        return pd.read_csv(cache)
    import ee
    sys.path.insert(0, str(CODE / "extract"))
    import part2
    from run_springs import read_log, write_log
    ee.Initialize(project=EE_PROJECT)
    ids = ",".join(f"'{s}'" for s in seg["segment_id"])
    rings = pd.concat([pyogrio.read_dataframe(f, layer="rings", columns=["zone_id", "segment_id"], where=f"segment_id IN ({ids})")
                       for f in sorted(S.glob("[0-9][0-9]_*.gpkg"))])
    rings = gpd.GeoDataFrame(rings, geometry="geometry")
    rings = rings[rings["zone_id"].str.endswith(RING) | rings["zone_id"].str.endswith(COMP)].to_crs(4326)
    fc = ee.FeatureCollection(rings[["zone_id", "geometry"]].__geo_interface__)
    part2.SCALE = 20
    box = ee.Geometry.Rectangle(list(rings.total_bounds))
    rows = part2.lean_composite_values(fc, box, 0, bands=("NDVI", "NDMI", "NDRE")).getInfo()["features"]
    d = pd.DataFrame([f["properties"] for f in rows])
    d.to_csv(cache, index=False)
    log = read_log()
    name = f"strip_{route}"
    log[name] = {"name": name, "task_id": "interactive", "spring": 0, "measure": "strip_diagram", "zones": route,
                 "submitted": dt.datetime.now().isoformat(timespec="seconds"), "state": "INTERACTIVE",
                 "eecu_hours": f"{0.3 * len(seg) / 40:.2f}"}
    write_log(log)
    return d


def gaps(d: pd.DataFrame, idx: str, min_px: int = 20) -> pd.DataFrame:
    d = d.assign(segment_id=segment_of(d["zone_id"]),
                 which=np.where(d["zone_id"].str.endswith(COMP), "comp", "ring"))
    m, n = f"{idx}_mean", f"{idx}_count"
    w = d.pivot_table(index=["segment_id", "landcover"], columns="which", values=[m, n], aggfunc="first")
    tot = d.groupby(["segment_id", "which"])[n].sum().unstack()
    ok = tot.index[(tot.get("ring", 0) >= min_px) & (tot.get("comp", 0) >= min_px)]
    both = w.dropna()
    wt = np.minimum(both[(n, "ring")], both[(n, "comp")])
    num = ((both[(m, "ring")] - both[(m, "comp")]) * wt).groupby(level=0).sum()
    gap = (num / wt.groupby(level=0).sum()).reindex(ok)
    share = d[d["which"] == "ring"].pivot_table(index="segment_id", columns="landcover", values=n, aggfunc="sum").fillna(0)
    return gap.rename(f"{idx}_gap"), share.div(share.sum(axis=1), axis=0)


def figure(route: str, seg: pd.DataFrame, ev: pd.DataFrame, gap: pd.Series, share: pd.DataFrame, unblind: bool, out: Path):
    seg = seg.sort_values("start_m").copy()
    x0, x1 = seg["start_m"].to_numpy() / 1000, seg["end_m"].to_numpy() / 1000
    hidden = np.zeros(len(seg), bool)
    if not unblind:
        for m in ev["measure_m"] / 1000:
            hidden |= (x1 >= m - 1) & (x0 <= m + 1)
    fig, ax = plt.subplots(4, 1, figsize=(12, 6.2), sharex=True, gridspec_kw={"height_ratios": [0.45, 1.1, 1.8, 0.8], "hspace": 0.08})
    eco_colors = dict(zip(seg["ecoregion"].unique(), ["#c9d9c3", "#e8dcb5", "#c7d3e3", "#e3c7c7"]))
    for a, b, e in zip(x0, x1, seg["ecoregion"]):
        ax[0].axvspan(a, b, color=eco_colors[e], lw=0)
    block = (seg["ecoregion"] != seg["ecoregion"].shift()).cumsum()
    for _, g in seg.groupby(block):
        if g["end_m"].max() - g["start_m"].min() > 0.12 * x1.max() * 1000:      # label every long stretch
            ax[0].text(g["start_m"].min() / 1000 + 0.2, 0.5, f"{g['ecoregion'].iloc[0]} ecoregion", va="center", fontsize=8)
    cty = seg["county_fips"].astype(str)
    for k in np.flatnonzero(cty.to_numpy()[1:] != cty.to_numpy()[:-1]):
        ax[0].axvline(x1[k], color="0.2", ls=":", lw=1)
    ax[0].set_yticks([]); ax[0].set_ylabel("Region", rotation=0, ha="right", va="center", fontsize=8)
    bottom = np.zeros(len(seg))
    sh = share.reindex(seg["segment_id"]).fillna(0)
    for c in sh.columns:
        v = sh[c].to_numpy()
        if v.max() < 0.02:
            continue
        name, col = NLCD.get(int(c), (str(c), "0.6"))
        ax[1].bar(x0, v, width=x1 - x0, bottom=bottom, align="edge", color=col, lw=0, label=name)
        bottom += v
    ax[1].set_ylim(0, 1); ax[1].set_yticks([0, 0.5, 1]); ax[1].set_yticklabels(["0", "50%", "100%"], fontsize=7)
    ax[1].set_ylabel("Land cover\n0-50 m", rotation=0, ha="right", va="center", fontsize=8)
    ax[1].legend(loc="upper left", bbox_to_anchor=(1.005, 1.0), fontsize=7, frameon=False)
    g = gap.reindex(seg["segment_id"]).to_numpy()
    shown = np.where(hidden, np.nan, g)
    ax[2].bar(x0, shown, width=x1 - x0, align="edge", color=np.where(shown < 0, "#b2182b", "#2166ac"), lw=0.3, ec="white")
    lim = max(0.02, np.nanmax(np.abs(g)) * 1.1) if np.isfinite(g).any() else 0.05
    for a, b in zip(x0[hidden], x1[hidden]):
        ax[2].axvspan(a, b, color="0.85", lw=0)
    if hidden.any():
        ax[2].text((x0[hidden].min() + x1[hidden].max()) / 2, lim * 0.55, "hidden\nuntil the\nphoto check", fontsize=7,
                   color="0.35", ha="center", va="center")
    ax[2].axhline(0, color="0.2", lw=0.8)
    ax[2].set_ylim(-lim, lim)
    ax[2].set_ylabel("NDVI gap\n0-50 m minus\ncomparison", rotation=0, ha="right", va="center", fontsize=8)
    ax[2].tick_params(labelsize=7)
    zones = seg["has_zones"].astype(bool).to_numpy()
    nocomp = zones & ~seg["has_comparison"].astype(bool).to_numpy()
    for a, b in zip(x0[nocomp], x1[nocomp]):
        ax[3].axvspan(a, b, ymin=0.05, ymax=0.3, color="0.55", lw=0)
    for a, b in zip(x0[~zones], x1[~zones]):
        ax[3].axvspan(a, b, ymin=0.05, ymax=0.3, color="0.85", lw=0)
    ev = ev.sort_values("measure_m")
    km = ev["measure_m"].to_numpy() / 1000
    group = np.concatenate([[0], np.cumsum(np.diff(km) > 2)]) if len(km) else []
    for _, g in ev.assign(km=km, group=group).groupby("group"):
        ax[3].plot(g["km"], [0.62] * len(g), "v", color="#7b3294", ms=9)
        right = g["km"].mean() > 0.6 * x1.max()
        label = "\n".join(f"{r.spill_id} · {str(r.date)[:7]} · {r.barrels:g} bbl" for r in g.itertuples())
        ax[3].text(g["km"].min() - 0.4 if right else g["km"].max() + 0.4, 0.62, label, ha="right" if right else "left",
                   va="center", fontsize=7)
    ax[3].set_ylim(0, 1); ax[3].set_yticks([])
    ax[3].set_ylabel("Events", rotation=0, ha="right", va="center", fontsize=8)
    ax[3].legend(handles=[Patch(color="#7b3294", label="reported spill (PHMSA)"), Patch(color="0.55", label="no clean comparison ring"),
                          Patch(color="0.85", label="piece under 1 km: no rings\n(measured in the supplement)")],
                 loc="upper left", bbox_to_anchor=(1.005, 1.0), fontsize=7, frameon=False)
    ax[3].set_xlabel("Distance along the route (km)", fontsize=8)
    ax[3].tick_params(labelsize=7)
    top = ax[0].secondary_xaxis("top")
    step_ft = 20_000 if x1.max() > 15 else 10_000
    ticks = np.arange(0, x1.max() * 3280.84 + 1, step_ft) / 3280.84
    top.set_xticks(ticks); top.set_xticklabels(station(ticks * 1000), fontsize=7)
    top.set_xlabel("Station (ft)", fontsize=8)
    first = seg.iloc[0]
    fig.suptitle(f"Route {route}: {first.commodity.lower()} {first.service.lower()} line, {first.diameter_in:g} in, mapped "
                 f"{first.location_accuracy.lower()}; {x1.max():.1f} km, {len(seg)} segments", fontsize=10, y=0.995)
    fig.text(0.01, 0.005, "Gap: median composite of all clear Sentinel-2 images in March-April 2018-2026, same land cover; "
             "red = less green than the comparison ring. Land cover: NLCD 2021. Measures along the mapped Railroad "
             "Commission line;\nthe line is published in digitized parts, each cut into 1 km segments, so pieces under 1 km "
             "fall where parts meet. First results, not findings.", fontsize=6.5, color="0.3")
    fig.savefig(out, dpi=200, bbox_inches="tight")
    plt.close(fig)


def main(a):
    OUT.mkdir(parents=True, exist_ok=True)
    ev = pd.read_csv(S / "spill_stations.csv")
    ev = ev[ev["route"] == a.route]
    seg = route_segments([a.route])
    if (seg["measure_along"] == "this part only").any():
        sys.exit(f"{a.route}: its parts don't join, so its measures restart on each part; pick a route measured along the whole line")
    d = zone_values(a.route, seg)
    gap, share = gaps(d, "NDVI")
    t = seg.drop(columns="geometry").merge(gap, left_on="segment_id", right_index=True, how="left")
    for idx in ("NDRE", "NDMI"):
        t = t.merge(gaps(d, idx)[0], left_on="segment_id", right_index=True, how="left")
    if not a.unblind:                       # the table is as blind as the figure
        near = np.zeros(len(t), bool)
        for m in ev["measure_m"]:
            near |= (t["end_m"] >= m - 1000) & (t["start_m"] <= m + 1000)
        t.loc[near, ["NDVI_gap", "NDRE_gap", "NDMI_gap"]] = np.nan
        t["hidden_until_photo_check"] = near
    t.to_csv(OUT / f"{a.route}_segments.csv", index=False)
    figure(a.route, seg, ev, gap, share, a.unblind, OUT / f"{a.route}.png")
    shown = t["NDVI_gap"].notna().sum()
    print(f"{a.route}: {len(seg)} segments, {shown} with a gap; {len(ev)} spills; wrote {OUT / (a.route + '.png')}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--route", default="127-006093")
    ap.add_argument("--unblind", action="store_true", help="show the gap near spills (only after the photo check)")
    main(ap.parse_args())
