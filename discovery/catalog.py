"""Discovery, catalog: one searchable table of every dataset in the project, where it came from and what it feeds.

Each entry has an ID, a title, a plain description, its kind (source data, Earth Engine dataset, Earth Engine asset,
zone file, measurement table, result, agent table, figure or document), where it lives, its provider and license, the
years it covers, its size and columns, and its lineage: the script that made it and the entries it was made from. The
descriptions are embedded with nomic-embed-text (on this computer, through Ollama), so agents can search the catalog by
meaning as well as by words. Written to outputs/discovery/catalog.parquet; the layout follows STAC's item fields
(id, title, description, datetime range, assets, providers, license) flattened into one table.

Usage: python catalog.py
"""
import json
import os
import re
import urllib.request
from datetime import datetime
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

P = Path(r"C:\mydrive\Graduate School\Courses\GEOG_392\projects")
OUT = P / "outputs" / "discovery" / "catalog.parquet"
EE = "projects/research-476723/assets/geog392"

# Curated entries: the inputs, the Earth Engine datasets and the main products
ITEMS = [
    dict(id="rrc_pipelines", kind="source data", title="Texas Railroad Commission pipelines, statewide (Oct 6, 2026)",
         path="data/statewide/pipelines_texas_rrc_20261006.gpkg", provider="Railroad Commission of Texas", license="public",
         years="2026", produced_by="prep/download_rrc_pipelines.py, prep/build_statewide_pipelines.py", inputs="",
         description="Every published pipeline line in Texas (497,884 lines), all commodities, diameters and statuses, "
                     "downloaded county by county and joined into one file, with the RRC's own attributes kept."),
    dict(id="epa_ecoregions", kind="source data", title="EPA Level III ecoregions of Texas", years="2013",
         path="data/statewide/ecoregions_epa_l3_texas.gpkg", provider="U.S. EPA", license="public",
         produced_by="zones/get_ecoregions.py", inputs="",
         description="The 12 Level III ecoregions that cover Texas, used to split pipelines into regions and to stratify "
                     "the statewide sample."),
    dict(id="phmsa_accidents", kind="source data", title="PHMSA hazardous liquid pipeline accidents, 2010 to present",
         path="data/phmsa/accident_hazardous_liquid_jan2010_present.txt", provider="U.S. PHMSA", license="public",
         years="2010-2026", produced_by="downloaded by hand from phmsa.dot.gov", inputs="",
         description="Every reported hazardous liquid pipeline accident in the United States since 2010 (6,009 reports, "
                     "648 fields), with location, commodity, barrels released and recovered, cause and a written narrative."),
    dict(id="ee_sentinel2", kind="Earth Engine dataset", title="Sentinel-2 surface reflectance with Cloud Score+",
         path="COPERNICUS/S2_SR_HARMONIZED; GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED", provider="ESA Copernicus; Google",
         license="Copernicus open data", years="2018-2026", produced_by="", inputs="",
         description="10 to 20 m multispectral images every few days, the source of every vegetation, moisture, red-edge, "
                     "bare-soil and water index; clouds and shadows masked with Cloud Score+."),
    dict(id="ee_landsat_lst", kind="Earth Engine dataset", title="Landsat 8 and 9 surface temperature (Collection 2 Level 2)",
         path="LANDSAT/LC08/C02/T1_L2; LANDSAT/LC09/C02/T1_L2", provider="USGS", license="public", years="2018-2026",
         produced_by="", inputs="", description="Land surface temperature at 30 m, quality-screened with ST_QA."),
    dict(id="ee_nlcd", kind="Earth Engine dataset", title="National Land Cover Database (NLCD)",
         path="USGS/NLCD_RELEASES", provider="USGS", license="public", years="2021", produced_by="", inputs="",
         description="Land cover classes at 30 m, used to compare like with like inside every zone."),
    dict(id="ee_terrain_soil_water", kind="Earth Engine dataset", title="Terrain, drainage, soil texture and surface water",
         path="USGS/3DEP/10m_collection; MERIT/Hydro; OpenLandMap soil texture; JRC surface water",
         provider="USGS; University of Tokyo; OpenLandMap; EC JRC", license="public or CC-BY", years="static",
         produced_by="", inputs="", description="Elevation and slope, height above the nearest drainage and a wetness "
                     "index, USDA soil texture class, and how often each pixel is open water."),
    dict(id="ee_gridmet_drought", kind="Earth Engine dataset", title="gridMET drought indices", path="GRIDMET drought",
         provider="University of Idaho", license="public", years="2018-2026", produced_by="", inputs="",
         description="Palmer Drought Severity Index, SPEI-90 and SPI-90 at 4 km, so a dry spring is not mistaken for "
                     "pipeline damage."),
    dict(id="ee_satellite_embedding", kind="Earth Engine dataset", title="Google Satellite Embedding V1 (annual)",
         path="GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL", provider="Google DeepMind", license="CC-BY 4.0", years="2017-2025",
         produced_by="", inputs="", description="64 numbers per 10 m pixel per year that summarize what a place looks like "
                     "over the whole year; places with similar numbers look alike. Used to find look-alike places."),
    dict(id="naip", kind="imagery service", title="USDA NAIP aerial photos (USGS National Map)",
         path="https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer", provider="USDA; USGS",
         license="public", years="latest", produced_by="", inputs="",
         description="About 0.6 m aerial photos, used to see the cleared right-of-way and to check spill sites by eye."),
    dict(id="zones_statewide", kind="zone file", title="Statewide segments and clean rings, one file per ecoregion",
         path="outputs/zones/statewide", provider="Group 10", license="team", years="2026",
         produced_by="zones/build_zones.py", inputs="rrc_pipelines, epa_ecoregions",
         description="Every pipeline cut into 1 km segments with stable IDs, each with rings on both sides cleaned of ground "
                     "near other pipelines, and a coverage table of everything kept and left out, with the reason."),
    dict(id="sample_v1", kind="zone file", title="The statewide stratified sample (3,499 segments) and its ten 50 m bands",
         path="outputs/zones/sample_v1/sample.gpkg", provider="Group 10", license="team", years="2026",
         produced_by="zones/draw_sample.py, zones/sample_bands.py", inputs="zones_statewide",
         description="A stratified random sample by ecoregion, commodity and diameter, with exact sampling weights that "
                     "stand for 296,191 segments; layers segments, rings (v1.5) and rings_b50 (ten 50 m bands)."),
    dict(id="spill_zones", kind="zone file", title="Spill sites, same-line comparison spots and regional spots",
         path="outputs/zones/statewide/spills_statewide.gpkg", provider="Group 10", license="team", years="2026",
         produced_by="zones/spill_zones.py", inputs="phmsa_accidents, rrc_pipelines, epa_ecoregions",
         description="82 reported spills matched to a mapped line, rings to 200 m around each, comparison spots every 0.5 km "
                     "along the same line out to 3 km, and random spots on similar lines in the same ecoregion."),
    dict(id="ee_assets", kind="Earth Engine asset", title="The zones uploaded to Earth Engine", path=EE,
         provider="Group 10", license="team", years="2026", produced_by="zones/ee_upload.py",
         inputs="sample_v1, spill_zones",
         description="sample_v1 (four rings), sample_v1_b50 (ten 50 m bands) and spills_v1, each in pieces under the "
                     "project's Earth Engine asset folder geog392."),
    dict(id="agent_tables", kind="agent table", title="Analysis-ready tables for the agents and the dashboard",
         path="outputs/agent", provider="Group 10", license="team", years="2023-2026",
         produced_by="analysis/agent_tables.py", inputs="corridor results, spill measurements, temperature, drought",
         description="Segments with weights and fixed values, per-segment springs, weighted statewide summaries, the "
                     "distance profile, coverage, spills, spill sites and springs, surface temperature and drought (Parquet)."),
    dict(id="spill_reports", kind="discovery table", title="Spill narratives read by a local language model",
         path="outputs/discovery/spill_reports.parquet", provider="Group 10", license="team", years="2010-2026",
         produced_by="discovery/spill_reports.py", inputs="phmsa_accidents",
         description="Each right-of-way spill's narrative with fields a local model extracted (how it was found, cleanup, "
                     "soil removed, water reached), each checked against a quote, and a search embedding."),
    dict(id="place_embeddings", kind="discovery table", title="Satellite embeddings of every segment and spill site",
         path="outputs/geog392_zone_stats/embeddings_*.csv", provider="Group 10", license="team", years="2017-2025",
         produced_by="discovery/embeddings.py", inputs="ee_satellite_embedding, ee_assets",
         description="The mean Satellite Embedding of every segment's 0-50 m band and comparison ring and of every spill "
                     "site and comparison spot, each year, for finding places that look like spill sites."),
    dict(id="analysis_plan", kind="document", title="Analysis plan v1.7", path="proposal/GEOG392_Analysis_Plan_Group10.pdf",
         provider="Group 10", license="team", years="2026", produced_by="docs/build_docs.ps1", inputs="",
         description="The questions, data, methods, tests and decisions, written before the statewide results, with every "
                     "later change dated in its change log."),
]

# Measurement and result files, described from their names
PATTERNS = [
    (r"sample_v1_b50_per_image_(\d{4})(_from9)?\.csv", "measurement table",
     "Sentinel-2 values of the sample's ten 50 m bands and comparison rings, every clear image in spring {0}, by land cover",
     "extract/run_springs.py", "ee_assets, ee_sentinel2"),
    (r"sample_v1_per_image_(\d{4})\.csv", "measurement table",
     "Sentinel-2 values of the sample's four v1.5 rings, every clear image in spring {0}, by land cover",
     "extract/run_springs.py", "ee_assets, ee_sentinel2"),
    (r"spills_v1_per_image_(\d{4})_10m\.csv", "measurement table",
     "Sentinel-2 values of every spill site and comparison spot (10 m), every clear image in spring {0}, by land cover",
     "extract/run_springs.py", "ee_assets, ee_sentinel2"),
    (r"(sample_v1(?:_b50)?)_and_spills_v1_lst_(\d{4})\.csv", "measurement table",
     "Landsat surface temperature of every {0} zone and spill zone, spring {1}", "extract/run_springs.py",
     "ee_assets, ee_landsat_lst"),
    (r"(sample_v1(?:_b50)?)_and_spills_v1_drought_(\d{4})\.csv", "measurement table",
     "gridMET drought indices of every {0} zone and spill zone, spring {1}", "extract/run_springs.py",
     "ee_assets, ee_gridmet_drought"),
    (r"(sample_v1(?:_b50)?)_and_spills_v1_fixed\.csv", "measurement table",
     "Fixed values (terrain, drainage, wetness, water share, soil) of every {0} zone and spill zone",
     "extract/run_springs.py", "ee_assets, ee_terrain_soil_water"),
    (r"embeddings_(\d{4})_(\w+)\.csv", "discovery table", "Satellite Embedding means for {1}, year {0}",
     "discovery/embeddings.py", "ee_satellite_embedding, ee_assets"),
]


def ollama_url() -> str:
    host = os.environ.get("OLLAMA_HOST") or (Path.home() / ".geog392" / "ollama_host.txt").read_text().strip()
    return (host if host.startswith("http") else "http://" + host).rstrip("/")


def embed(texts):
    vecs = []
    for k in range(0, len(texts), 32):
        req = urllib.request.Request(ollama_url() + "/api/embed", headers={"Content-Type": "application/json"},
                                     data=json.dumps({"model": "nomic-embed-text", "input": texts[k:k + 32]}).encode())
        with urllib.request.urlopen(req, timeout=300) as r:
            vecs += json.loads(r.read())["embeddings"]
    return vecs


def describe_file(path: Path) -> dict:
    """Size, rows and columns of a table, read cheaply (Parquet metadata, or the CSV header and a line count)."""
    info = {"bytes": path.stat().st_size, "updated": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="minutes")}
    if path.suffix == ".parquet":
        meta = pq.ParquetFile(path).metadata
        info.update(rows=meta.num_rows, columns=", ".join(pq.ParquetFile(path).schema_arrow.names))
    elif path.suffix == ".csv":
        with path.open(encoding="utf-8", errors="replace") as fh:
            header = fh.readline().strip()
            info.update(rows=sum(1 for _ in fh), columns=header.replace(",", ", "))
    return info


def main():
    rows = []
    for item in ITEMS:
        f = P / item["path"] if not item["path"].startswith(("projects/", "COPERNICUS", "LANDSAT", "USGS", "GOOGLE",
                                                             "GRIDMET", "https://")) else None
        extra = describe_file(f) if f is not None and f.is_file() else {}
        rows.append({**item, **extra})
    stats = P / "outputs" / "geog392_zone_stats"
    for f in sorted(stats.glob("*.csv")):
        for pattern, kind, text, script, inputs in PATTERNS:
            m = re.fullmatch(pattern, f.name)
            if m:
                rows.append({"id": f.stem, "kind": kind, "title": f.name, "path": str(f.relative_to(P)).replace("\\", "/"),
                             "provider": "Group 10", "license": "team", "years": next((g for g in m.groups() if g and g.isdigit()), ""),
                             "produced_by": script, "inputs": inputs, "description": text.format(*m.groups()),
                             **describe_file(f)})
                break
    for f in sorted((P / "outputs" / "agent").glob("*.parquet")):
        rows.append({"id": "agent_" + f.stem, "kind": "agent table", "title": f.name,
                     "path": str(f.relative_to(P)).replace("\\", "/"), "provider": "Group 10", "license": "team",
                     "years": "", "produced_by": "analysis/agent_tables.py", "inputs": "agent_tables",
                     "description": f"Agent table {f.stem.replace('_', ' ')}, part of the analysis-ready tables",
                     **describe_file(f)})
    cat = pd.DataFrame(rows)
    text = ("search_document: " + cat["title"] + ". " + cat["description"] + " Kind: " + cat["kind"] + ".").tolist()
    cat["embedding"] = embed(text)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    cat.to_parquet(OUT, index=False)
    print(f"wrote {OUT}: {len(cat)} entries ({', '.join(f'{k} {v}' for k, v in cat['kind'].value_counts().items())})")


if __name__ == "__main__":
    main()
