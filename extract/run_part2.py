"""Run Part 2 for one ecoregion and one spring, and report what it cost in Earth Engine compute.

Before the export, a check on 20 zones runs interactively, so a mistake shows up in seconds instead of after an hour.
Results go to the Drive of the Earth Engine account, folder `--drive-folder`; the collect step moves them into the team
folder. With --wait, the script follows the task and prints its run time and compute (EECU-hours), with a rough
statewide estimate.

Usage: python run_part2.py --zones <asset folder> --region "Central Great Plains" --year 2025
                           --mode per_image|per_pass|composite [--sample-segments N --sample-from <zones .gpkg>]
                           [--drive-folder geog392_zone_stats] [--wait]
Only a sample of whole segments (all five rings) gives a fair cost: the uploaded pieces are sorted by ring band, so
--pieces holds the narrowest rings only and is for quick checks, not for estimates.
"""
import argparse
import sys
import time
from pathlib import Path

import ee

sys.path.insert(0, str(Path(__file__).resolve().parent))
import part2  # noqa: E402

STATEWIDE_SEGMENTS = 441_602    # 1 km pieces with rings (2,208,010 rings / 5, 2025 layer); refined by the statewide build


def region_geometry(name: str):
    """One EPA Level III ecoregion clipped to Texas, or all of Texas (for the statewide sample)."""
    texas = ee.FeatureCollection("TIGER/2018/States").filter(ee.Filter.eq("NAME", "Texas")).geometry()
    if name == "Texas":
        return texas
    return ee.FeatureCollection("EPA/Ecoregions/2013/L3").filter(ee.Filter.eq("us_l3name", name)).geometry().intersection(texas, 100)


def columns(mode: str) -> list[str]:
    if mode == "lst":
        return ["zone_id", "landcover", "date", "image", "path", "row", "spacecraft", "LST_mean", "LST_count"]
    if mode == "fixed":
        return ["zone_id"] + [f"{b}_mean" for b in part2.FIXED if b != "soil_texture"] + ["soil_texture_mode"]
    if mode == "drought":
        return ["zone_id", "year"] + part2.DROUGHT
    if mode in ("per_image", "per_pass"):
        ids = ["image", "orbit", "tile"] if mode == "per_image" else ["orbit", "tiles"]
        return (["zone_id", "landcover", "date"] + ids + ["sun_zenith", "view_zenith"]
                + [f"{i}_{s}" for s in ("mean", "count") for i in part2.INDICES])
    names = [f"{i}_median" for i in part2.INDICES] + [f"{i}_p90" for i in part2.INDICES] + ["clear_images"]
    return ["zone_id", "landcover", "year"] + [f"{n}_{s}" for n in names for s in ("mean", "median", "stdDev", "p10", "p90", "count")]


def main(a):
    ee.Initialize(project=a.project)
    part2.SCALE, part2.TILE_SCALE = a.scale, a.tile_scale
    zones, parts = part2.zones_from(a.zones)
    if a.sample_segments:             # a fair cost sample: N random segments with all five of their rings
        import pyogrio
        seg = pyogrio.read_dataframe(a.sample_from, layer="segments", read_geometry=False, columns=["segment_id", "has_zones"])
        ids = seg.loc[seg["has_zones"].astype(bool), "segment_id"].sample(n=a.sample_segments, random_state=392)
        zone_ids = [f"{s}_r{i}-{o}" for s in ids for i, o in ((0, 50), (50, 100), (100, 250), (250, 500), (500, 1000))]
        zones = zones.filter(ee.Filter.inList("zone_id", zone_ids))
    if a.from_piece:                  # resume: only the pieces from this one on (whole segments per piece)
        parts = parts[a.from_piece:]
        zones = ee.FeatureCollection([ee.FeatureCollection(p) for p in parts]).flatten()
    if a.pieces:                      # a quick check: the first N uploaded pieces
        parts = parts[: a.pieces]
        zones = ee.FeatureCollection([ee.FeatureCollection(p) for p in parts]).flatten()
    n_parts = len(parts)
    region = region_geometry(a.region)
    crs = None if a.region == "Texas" else part2.utm_crs(region)   # statewide: each image in its own UTM zone
    box = region.bounds(100)          # a simple box is much cheaper than the ecoregion's outline for finding images
    n_images = part2.spring_images(box, a.year).size().getInfo()
    grid = crs or "each image's own UTM zone"
    print(f"{a.region}, spring {a.year}: {n_images} Sentinel-2 images; zones from {n_parts} pieces; "
          f"{a.scale} m pixels on {grid}", flush=True)
    build = {"per_image": part2.per_image_values, "per_pass": part2.per_pass_values, "composite": part2.composite_values,
             "lst": part2.lst_values, "fixed": part2.fixed_values, "drought": part2.drought_values}[a.mode]
    # 20 zones next to each other (within 3 km of one zone), and only the images over them: a scattered sample would
    # stretch the check over the whole region and run out of memory
    piece = ee.FeatureCollection(parts[0])
    few = piece.filterBounds(ee.Feature(piece.first()).geometry().buffer(3000)).limit(20)
    sample = build(few, few.geometry().bounds(10), a.year, crs).limit(5).getInfo()["features"]
    if not sample:
        raise SystemExit("the 20-zone check returned no rows; not starting the export")
    first = sample[0]["properties"]
    missing = [c for c in columns(a.mode) if c not in first]
    print(f"20-zone check: {len(sample)} rows; e.g. zone {first.get('zone_id')}, land cover {first.get('landcover')}, "
          f"NDVI {first.get('NDVI_mean') or first.get('NDVI_median_mean')}; missing columns: {missing or 'none'}", flush=True)
    rows = build(zones, box, a.year, crs)
    name = (f"{Path(a.zones).name}_{a.mode}_{a.year}" + (f"_sample{a.pieces}" if a.pieces else "")
            + (f"_seg{a.sample_segments}" if a.sample_segments else "")
            + (f"_{a.scale}m" if a.scale != 20 else "") + (f"_ts{a.tile_scale}" if a.tile_scale != 1 else "")
            + (f"_from{a.from_piece}" if a.from_piece else ""))
    task = ee.batch.Export.table.toDrive(collection=rows, description=name, folder=a.drive_folder, fileNamePrefix=name,
                                         fileFormat="CSV", selectors=columns(a.mode))
    task.start()
    print(f"started export {name} -> Drive folder {a.drive_folder}", flush=True)
    if not a.wait:
        return
    t0 = time.time()
    while True:
        time.sleep(30)
        status = task.status()
        if status["state"] in ("COMPLETED", "FAILED", "CANCELLED"):
            break
    op = ee.data.getOperation(status["name"])
    eecu = float(op.get("metadata", {}).get("batchEecuUsageSeconds", 0)) / 3600
    print(f"{status['state']} after {(time.time() - t0) / 60:,.0f} min: {eecu:,.2f} EECU-hours"
          + (f" ({status.get('error_message')})" if status["state"] != "COMPLETED" else ""), flush=True)
    if status["state"] == "COMPLETED" and eecu and a.segments:
        print(f"{eecu * 1000 / a.segments:,.1f} EECU-hours per 1,000 segments; these {a.segments:,} segments for all "
              f"nine springs: about {eecu * 9:,.0f} EECU-hours (Community tier: 150 a month)")
    elif status["state"] == "COMPLETED" and eecu and a.sample_segments:
        per_spring = eecu * STATEWIDE_SEGMENTS / a.sample_segments
        print(f"{eecu * 1000 / a.sample_segments:,.1f} EECU-hours per 1,000 segments; statewide for this measure: "
              f"{per_spring:,.0f} EECU-hours per spring, {per_spring * 9:,.0f} for all nine springs "
              f"(Community tier: 150 a month)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--zones", required=True)
    ap.add_argument("--region", required=True, help='an EPA Level III ecoregion name, or "Texas" for the statewide sample')
    ap.add_argument("--year", type=int, default=2025)
    ap.add_argument("--mode", choices=["per_image", "per_pass", "composite", "lst", "fixed", "drought"], required=True)
    ap.add_argument("--drive-folder", default="geog392_zone_stats")
    ap.add_argument("--project", default="research-476723")
    ap.add_argument("--scale", type=int, default=20, help="pixel size in meters (20, the 20 m bands' native size; 10 for spill zones)")
    ap.add_argument("--tile-scale", type=int, default=1, help="Earth Engine tileScale for the per-image measure")
    ap.add_argument("--segments", type=int, help="how many segments the zone asset holds, for the cost report")
    ap.add_argument("--from-piece", type=int, default=0, help="use only the uploaded pieces from this index on")
    pick = ap.add_mutually_exclusive_group()
    pick.add_argument("--pieces", type=int, help="only the first N uploaded pieces (a quick check; one ring band only)")
    pick.add_argument("--sample-segments", type=int, help="N random segments with all their rings (a fair cost sample)")
    ap.add_argument("--sample-from", help="the region's local zones .gpkg, to draw the segment sample from")
    ap.add_argument("--wait", action="store_true")
    main(ap.parse_args())
