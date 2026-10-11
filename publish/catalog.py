"""Gaps 14 and 17: cloud-native outputs with standard metadata, ready for Group C to publish in the TAMU ArcGIS Online org.

For each published layer this writes:
  - the data as GeoParquet 1.1 (EPSG:4326, zstd, with a bbox covering column so cloud readers can filter by area),
    which ArcGIS Pro, QGIS, DuckDB and GDAL all open;
  - ISO 19139 metadata (the XML encoding of ISO 19115; pygeometa), with a data quality section in the ISO 19157
    elements: completeness, logical consistency, positional, temporal and thematic accuracy, and lineage;
  - a STAC 1.1 item (pystac, table extension) in one self-contained catalog, so the outputs can be browsed and
    searched like any cloud imagery catalog.
QUALITY.md repeats the quality statements in plain words. Rasters (COG) follow with the wall-to-wall map.
No layer carries a spill's own result (the photo check is still blind) or operator names.
Writes outputs/publish/: data/, metadata/, stac/, QUALITY.md, README.md.
Usage: python catalog.py
"""
import datetime as dt
import json
import shutil
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pystac
import shapely
from pystac.extensions.table import TableExtension
from pygeometa.core import read_mcf
from pygeometa.schemas.iso19139 import ISO19139OutputSchema

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.config import CORRIDOR, CORRIDOR_SUPPLEMENT, P, PUBLISH, R, S, SAMPLE, SUPPLEMENT  # noqa: E402
from common.gaps import piece_gaps  # noqa: E402

OUT = PUBLISH
TODAY = dt.date.today().isoformat()
TEAM = "GEOG 392/676 Group 10, Department of Geography, Texas A&M University"
SPRINGS = ("2018-03-01", "2026-04-30")
ATTRS = ["segment_id", "line_uid", "commodity", "service", "diameter_in", "status", "location_accuracy",
         "ecoregion", "county_fips", "piece_m"]
ACCESS = "Restricted to the Texas A&M ArcGIS Online organization (TAMU sign-in) while results are first results."
SOURCES = ("Railroad Commission of Texas pipeline layer (downloaded 2026-10-06); Copernicus Sentinel-2 L2A "
           "harmonized surface reflectance with Google Cloud Score+ (Earth Engine); USGS NLCD 2021; EPA Level III "
           "ecoregions; PHMSA hazardous liquid incident reports.")


def pooled_gaps() -> pd.DataFrame:
    """Each piece's median 0-50 m gap over the nine springs, per index, as coverage_estimate.py uses it."""
    out = [piece_gaps(f, ["segment_id", "index"], indices=["NDVI", "NDRE", "NDMI"]).set_index(["segment_id", "index"])
           for f in (CORRIDOR / "segment_spring.csv", CORRIDOR_SUPPLEMENT / "segment_spring.csv")]
    g = pd.concat(out).unstack("index")
    g.columns = [f"{i}_gap_{'same_lc' if m == 'diff_same_lc' else 'all'}" for m, i in g.columns]
    return g.reset_index()


def corridor_segments() -> gpd.GeoDataFrame:
    main = gpd.read_file(SAMPLE / "sample.gpkg", layer="segments", columns=ATTRS + ["stratum", "weight"]).assign(frame="main")
    supp = gpd.read_file(SUPPLEMENT / "supplement.gpkg", layer="segments", columns=ATTRS + ["stratum", "weight", "frame"])
    seg = pd.concat([main, supp], ignore_index=True)
    seg["km_represented"] = seg["weight"] * np.where(seg["frame"] == "short", seg["piece_m"] / 1000, 1.0)
    return gpd.GeoDataFrame(seg.merge(pooled_gaps(), on="segment_id", how="left"), crs=main.crs)


def hot_spots() -> gpd.GeoDataFrame:
    seg = gpd.read_file(SAMPLE / "sample.gpkg", layer="segments", columns=ATTRS)
    hs = pd.read_csv(R / "hot_spots_by_spring" / "segments.csv").rename(columns={"cold": "springs_cold", "hot": "springs_hot",
                                                                                 "class": "pattern", "tau": "trend_tau"})
    return seg.merge(hs, on="segment_id", how="inner")


def spill_events() -> gpd.GeoDataFrame:
    sp = gpd.read_file(S / "spills_statewide.gpkg", layer="spills_matched",
                       columns=["spill_id", "report_number", "date", "barrels", "commodity", "cause", "ecoregion"])
    st = pd.read_csv(S / "spill_stations.csv", usecols=["spill_id", "route", "measure_m", "station", "offset_m",
                                                                       "side", "measure_along", "location_accuracy"])
    return sp.merge(st, on="spill_id", how="left")


def methane_plumes() -> gpd.GeoDataFrame:
    d = pd.read_csv(R / "methane_plumes" / "plumes.csv").drop(columns=["index_right"], errors="ignore")
    d = d.rename(columns={"COMMODITY1": "nearest_line_commodity_code", "STATUS_CD": "nearest_line_status_code"})
    return gpd.GeoDataFrame(d, geometry=gpd.points_from_xy(d["lon"], d["lat"]), crs=4326)


LAYERS = {
    "corridor_segments": dict(
        title="Vegetation gap beside Texas pipelines, sampled segments (Sentinel-2, springs 2018-2026)",
        abstract=("Stratified random sample of Railroad Commission pipeline pieces (frames: 3,499 one-km segments with a "
                  "clean comparison ring, 1,276 in dense areas, 1,878 pieces of 100 m to 1 km). For each piece, the 0-50 m "
                  "band minus its own 500-1,000 m comparison ring, same NLCD land cover, image by image in March-April, "
                  "median over the nine springs; NDVI, NDRE and NDMI. km_represented is the pipe each piece stands for, "
                  "so weighted summaries are statewide per-km estimates (outputs/results/coverage_estimate)."),
        geomtype="line", build=corridor_segments, keywords=["pipeline right-of-way", "Sentinel-2", "NDVI", "vegetation", "Texas"]),
    "hot_spots": dict(
        title="Hot and cold spots of the pipeline vegetation gap, by spring (Getis-Ord Gi*)",
        abstract=("For each main-sample segment: in how many of the nine springs it was a significant cold spot (more "
                  "loss of green than its neighbors) or hot spot of the 0-50 m NDVI gap (Gi*, 8 nearest neighbors, "
                  "Benjamini-Hochberg FDR), its pattern class, and the 2018-2026 Mann-Kendall trend."),
        geomtype="line", build=hot_spots, keywords=["hot spot analysis", "Getis-Ord Gi*", "pipeline", "Texas"]),
    "spill_events": dict(
        title="Reported pipeline spills as route events (station along the line)",
        abstract=("PHMSA-reported hazardous liquid spills matched to Railroad Commission lines, located as route events: "
                  "route (line_uid), measure in meters along the mapped line, engineering station in feet, and offset "
                  "with side. Positions only; the spill results stay unpublished until the blind photo check is done."),
        geomtype="point", build=spill_events, keywords=["linear referencing", "pipeline spills", "PHMSA", "Texas"]),
    "methane_plumes": dict(
        title="Methane plumes near Texas gas lines (Carbon Mapper)",
        abstract=("Carbon Mapper methane plumes over Texas with the distance to the nearest Railroad Commission line and "
                  "gas line. Data by Carbon Mapper; noncommercial use only, credit 'Data by Carbon Mapper®'."),
        geomtype="point", build=methane_plumes, keywords=["methane", "Carbon Mapper", "EMIT", "Tanager", "natural gas"],
        rights="Data by Carbon Mapper®. Noncommercial use only (Carbon Mapper data terms)."),
}


def wall_to_wall() -> gpd.GeoDataFrame:
    return gpd.read_parquet(sorted(R.glob("wall_to_wall_*/segments.parquet"))[-1])


if list(R.glob("wall_to_wall_*/segments.parquet")):
    LAYERS["wall_to_wall"] = dict(
        title="Vegetation gap beside every measured Texas pipeline segment (wall-to-wall, one spring)",
        abstract=("Every 1 km segment with rings in the measured ecoregions: the 0-50 m band minus its comparison ring, same "
                  "NLCD land cover, from one spring's median Sentinel-2 composite (plan D23). For the map; the image-by-image "
                  "sample is the test. Segments within 1 km of a reported spill have no gap until the photo check."),
        geomtype="line", build=wall_to_wall, keywords=["pipeline right-of-way", "Sentinel-2", "NDVI", "wall-to-wall", "Texas"])


def quality(name: str, gdf) -> dict:
    """ISO 19157 data quality elements, in words, from the project's own checks."""
    cov = pd.read_csv(S / "coverage_statewide.csv")
    total = cov["km"].sum()
    covered = cov.loc[cov["kept"], "km"].sum() + 181_260
    valid = float(shapely.is_valid(np.asarray(gdf.geometry.array)).mean()) if len(gdf) else 1.0
    row = P / "outputs" / "geoai" / "row_survey" / "results.csv"
    pos = "Railroad Commission quality codes: within 50 ft, 51-300 ft, 301-500 ft (field location_accuracy). "
    if row.exists():
        r = pd.read_csv(row)
        cp = r[r["offset_m"].notna() & ~r["photo_check_first"].astype(bool)]
        by = "; ".join(f"{k} {np.sqrt((g['offset_m'] ** 2).mean()):.1f} m (n={len(g)})" for k, g in cp.groupby("location_accuracy"))
        pos += (f"Cross-track RMSE of the mapped lines at imagery checkpoints (SAM 2 and a NAIP NDVI profile agreeing within "
                f"20 m; {len(r)} random segments, {r['offset_m'].notna().sum()} checkpoints, "
                f"{int(r['photo_check_first'].sum())} far ones held for the photo check): {by}; all "
                f"{np.sqrt((cp['offset_m'] ** 2).mean()):.1f} m. A screening estimate in the spirit of the ASPRS "
                "Positional Accuracy Standards (2024), not a survey.")
    else:
        pos += "Cross-track RMSE against imagery checkpoints: in progress (geoai/row_survey.py)."
    q = {"completeness": (f"Sample frames cover {covered / total:.1%} of the {total:,.0f} km of mapped land pipe; left out and "
                          "counted: pieces under 100 m, exact duplicate geometries and offshore lines "
                          "(outputs/zones/statewide/coverage_statewide.csv). Pieces with too few clear pixels have empty gaps."),
         "logical_consistency": (f"{valid:.1%} of geometries are valid (OGC simple features). Stations agree with ArcGIS Pro "
                                 "Locate Features Along Routes within 0.05 m (zones/arcgis_stations_check.py)."),
         "positional_accuracy": pos,
         "temporal_quality": "Sentinel-2 images of March-April in each spring 2018-2026, one image per pass; every spring is measured.",
         "thematic_accuracy": ("Land cover from NLCD 2021 (about 86% overall agreement at Level II for NLCD 2016; Wickham et al. "
                               "2021). Gaps are first results, not findings; the blind photo check (Group B) validates them."),
         "lineage": SOURCES + " Processing: analysis plan v1.10 (docs/analysis_plan.html) and the code in 'code (do not edit)'."}
    if name == "methane_plumes":
        q["thematic_accuracy"] = "Plume detections and emission rates as published by Carbon Mapper, with its stated uncertainty."
        q["lineage"] = "Carbon Mapper public plume catalog (api.carbonmapper.org), Texas, methane; nearest lines from the Railroad Commission layer."
    if name == "spill_events":
        q["positional_accuracy"] = ("Spill coordinates as reported to PHMSA, snapped to the nearest matched line (median offset 2 m, "
                                    "max 66 m). Routes whose parts don't join measure along each part (measure_along).")
    return q


def mcf(name: str, spec: dict, gdf, q: dict) -> dict:
    b = [float(v) for v in gdf.total_bounds]
    return {"mcf": {"version": "2.0"},
            "metadata": {"identifier": f"geog392-group10-{name}", "language": "en", "charset": "utf8",
                         "hierarchylevel": "dataset", "dates": {"creation": TODAY}},
            "spatial": {"datatype": "vector", "geomtype": spec["geomtype"]},
            "identification": {"language": "en", "charset": "utf8", "title": spec["title"], "abstract": spec["abstract"],
                               "dates": {"creation": TODAY}, "status": "onGoing", "maintenancefrequency": "asNeeded",
                               "topiccategory": ["environment", "imageryBaseMapsEarthCover"],
                               "keywords": {"default": {"keywords": spec["keywords"], "keywords_type": "theme"}},
                               "extents": {"spatial": [{"bbox": b, "crs": 4326}],
                                           "temporal": [{"begin": SPRINGS[0], "end": SPRINGS[1]}]},
                               "accessconstraints": "otherRestrictions",
                               "rights": spec.get("rights", ACCESS), "fees": "None", "url": "https://geography.tamu.edu"},
            "contact": {"pointOfContact": {"organization": TEAM, "positionname": "Team lead", "country": "United States"},
                        "distributor": {"organization": TEAM, "country": "United States"}},
            "distribution": {"geoparquet": {"url": f"../data/{name}.parquet", "type": "WWW:DOWNLOAD", "name": f"{name}.parquet",
                                            "description": "GeoParquet 1.1, EPSG:4326", "function": "download"}},
            "dataquality": {"scope": {"level": "dataset"},
                            "lineage": {"statement": " ".join(f"{k.replace('_', ' ').capitalize()}: {v}" for k, v in q.items())}}}


def main():
    for d in ("data", "metadata", "stac"):            # files are overwritten in place (Drive keeps the folders locked)
        (OUT / d).mkdir(parents=True, exist_ok=True)
    tx = shapely.box(-106.65, 25.84, -93.51, 36.5)
    cat = pystac.Catalog(id="geog392-group10", title="Can satellites see pipeline leaks? Group 10 outputs",
                         description=f"{TEAM}. Sentinel-2 vegetation along Texas pipelines, 2018-2026. First results, not findings.")
    col = pystac.Collection(id="pipeline-vegetation", title="Pipeline vegetation outputs",
                            description="Vector layers and tables from the GEOG 392 pipeline project.", license="other",
                            extent=pystac.Extent(pystac.SpatialExtent([list(tx.bounds)]),
                                                 pystac.TemporalExtent([[dt.datetime(2018, 3, 1, tzinfo=dt.timezone.utc),
                                                                         dt.datetime(2026, 4, 30, tzinfo=dt.timezone.utc)]])))
    cat.add_child(col)
    qlines = [f"# Data quality statements (ISO 19157 elements), {TODAY}", ""]
    for name, spec in LAYERS.items():
        gdf = spec["build"]().to_crs(4326)
        path = OUT / "data" / f"{name}.parquet"
        gdf.to_parquet(path, schema_version="1.1.0", write_covering_bbox=True, compression="zstd")
        q = quality(name, gdf)
        (OUT / "metadata" / f"{name}.xml").write_text(ISO19139OutputSchema().write(read_mcf(mcf(name, spec, gdf, q))), encoding="utf-8")
        item = pystac.Item(id=name, geometry=shapely.geometry.mapping(shapely.box(*gdf.total_bounds)), bbox=list(gdf.total_bounds),
                           datetime=None, start_datetime=dt.datetime(2018, 3, 1, tzinfo=dt.timezone.utc),
                           end_datetime=dt.datetime(2026, 4, 30, tzinfo=dt.timezone.utc),
                           properties={"title": spec["title"], "description": spec["abstract"], "access": ACCESS,
                                       **({"rights": spec["rights"]} if "rights" in spec else {})})
        item.add_asset("data", pystac.Asset(href=f"../../../data/{name}.parquet", media_type="application/vnd.apache.parquet",
                                            roles=["data"], title="GeoParquet 1.1"))
        item.add_asset("metadata", pystac.Asset(href=f"../../../metadata/{name}.xml", media_type="application/xml",
                                                roles=["metadata"], title="ISO 19139 metadata"))
        t = TableExtension.ext(item, add_if_missing=True)
        t.columns = [{"name": c, "type": str(gdf[c].dtype)} for c in gdf.columns if c != "geometry"]
        t.primary_geometry = "geometry"
        t.row_count = len(gdf)
        col.add_item(item)
        qlines += [f"## {spec['title']} (`{name}`, {len(gdf):,} rows)", ""] + [f"- **{k.replace('_', ' ').capitalize()}:** {v}" for k, v in q.items()] + [""]
        print(f"{name}: {len(gdf):,} rows, {path.stat().st_size / 1e6:.1f} MB")
    figs = pystac.Item(id="figures", geometry=shapely.geometry.mapping(tx), bbox=list(tx.bounds), datetime=None,
                       start_datetime=dt.datetime(2018, 3, 1, tzinfo=dt.timezone.utc), end_datetime=dt.datetime(2026, 4, 30, tzinfo=dt.timezone.utc),
                       properties={"title": "Strip diagrams and coverage estimate"})
    for f in sorted((R / "strip_diagram").glob("*.png")):
        shutil.copy(f, OUT / "data" / f"strip_{f.name}")
        figs.add_asset(f"strip_{f.stem}", pystac.Asset(href=f"../../../data/strip_{f.name}", media_type=pystac.MediaType.PNG,
                                                      roles=["overview"], title=f"Strip diagram, route {f.stem}"))
    pd.read_csv(R / "coverage_estimate" / "estimates.csv").to_parquet(OUT / "data" / "coverage_estimate.parquet")
    figs.add_asset("coverage_estimate", pystac.Asset(href="../../../data/coverage_estimate.parquet", media_type="application/vnd.apache.parquet",
                                                     roles=["data"], title="Statewide per-km gap estimates"))
    col.add_item(figs)
    for tif in sorted(R.glob("wall_to_wall_*/gap_1km.tif")):             # the map raster, as a Cloud-Optimized GeoTIFF
        import rasterio
        from rasterio.warp import transform_bounds
        from pystac.extensions.projection import ProjectionExtension
        spring = int(tif.parent.name.rsplit("_", 1)[1])
        dst = OUT / "data" / f"gap_1km_{spring}.tif"
        shutil.copy(tif, dst)
        with rasterio.open(tif) as r:
            b = transform_bounds(r.crs, "EPSG:4326", *r.bounds)
            shape, transform = [r.height, r.width], list(r.transform)[:6]
        it = pystac.Item(id=f"gap_1km_{spring}", geometry=shapely.geometry.mapping(shapely.box(*b)), bbox=list(b), datetime=None,
                         start_datetime=dt.datetime(spring, 3, 1, tzinfo=dt.timezone.utc),
                         end_datetime=dt.datetime(spring, 4, 30, tzinfo=dt.timezone.utc),
                         properties={"title": f"NDVI gap beside the pipe on a 1 km grid, spring {spring}", "access": ACCESS,
                                     "description": "Band 1: length-weighted mean 0-50 m NDVI gap of the segments in each cell; "
                                                    "band 2: km of measured pipe. Near-spill segments left out until the photo check."})
        it.add_asset("data", pystac.Asset(href=f"../../../data/{dst.name}", media_type=pystac.MediaType.COG, roles=["data"],
                                          title="Cloud-Optimized GeoTIFF"))
        pe = ProjectionExtension.ext(it, add_if_missing=True)
        try:
            pe.apply(epsg=6579, shape=shape, transform=transform)
        except TypeError:
            pe.apply(code="EPSG:6579", shape=shape, transform=transform)
        col.add_item(it)
    cat.normalize_hrefs(str(OUT / "stac"))
    cat.save(catalog_type=pystac.CatalogType.SELF_CONTAINED)
    (OUT / "QUALITY.md").write_text("\n".join(qlines), encoding="utf-8")
    (OUT / "README.md").write_text(
        f"# Publishable outputs ({TODAY})\n\nBuilt by `code (do not edit)/publish/catalog.py`. `data/` holds GeoParquet 1.1 "
        "layers (ArcGIS Pro 3.7 opens them; also QGIS, DuckDB) and figures; `metadata/` holds ISO 19139 XML (import in ArcGIS "
        "Pro: Metadata > Import, ISO 19139) and, after `publish/arcgis_metadata.py`, the same as ISO 19115-3 "
        "(`*_iso19115-3.xml`); `stac/catalog.json` is a STAC 1.1 catalog of everything (open with any STAC browser "
        "or pystac). `QUALITY.md` gives the data quality statements.\n\n" + ACCESS +
        " Risk layers stay behind TAMU sign-in. Carbon Mapper data: noncommercial only, credit \"Data by Carbon Mapper®\".\n",
        encoding="utf-8")
    print(f"catalog: {OUT / 'stac' / 'catalog.json'}")


if __name__ == "__main__":
    main()
