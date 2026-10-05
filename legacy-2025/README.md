# Last year's version (GIS Day 2025)

Landon's GIS Day project from November 2025, kept as the starting point and as a record of what to
fix. Nothing in this folder is part of the new pipeline; read it, do not build on it.

## Files

- `gee_s2_ndvi_ndwi_2025.js`: the Earth Engine Code Editor script that produced the NDVI and water
  index values, copied exactly as it was found. It ran on the 250 m layers, two ecoregions at a time.
- `Tablejoining_NDVI_NDWI.ipynb`: the ArcGIS Pro notebook that joined the Earth Engine tables back
  onto the buffer polygons, once per buffer distance. It needs `arcpy` and paths from Landon's computer.
- `samples/`: the first 200 rows of each combined result table. Columns are `PipelineEcoID`,
  `NDVI` and `NDWI`.

The full project, about 25 GB, is in Landon's Google Drive under `GEOG_392/projects/data/GEOG391_GIS_Day_2025_backup`: the ArcGIS Pro
project and its 18 GB geodatabase, the per-ecoregion shapefiles and tables for each distance, and
the EPA Level III Ecoregions of Texas shapefile. Ask Landon for access.

## The question it asked

From last year's final report and presentation ("Influence of Petroleum Pipelines on Vegetation and
Soil Moisture in Texas: A Remote Sensing Approach", GEOG 391, fall 2025; both files are on Landon's
computer, not in this repository):

- **Motivation:** pipelines run underground and out of sight, so a leak might first show up as
  stressed vegetation or changed moisture near the line.
- **Hypothesis:** pipelines harm nearby vegetation in proportion to their size.
- **Conclusion drawn:** smaller pipes, not the largest, were linked to the most "stress" (NDVI below
  0.3), and the report suggested smaller lines are less well maintained and leak more.

The October 2026 audit means that conclusion cannot be relied on:

- There was no comparison land, so low NDVI near small pipes may only reflect where small pipes
  run (dry West Texas oil fields have many of them).
- Leaks were never measured. No leak or spill records were used.
- Half of the 100 m area had no values, and overlapping buffers counted the same ground once for
  every pipeline sharing a corridor.
- NDWI measures water in plants, not soil moisture.

This year's design (rings with a reference ring, many years, soil, and possibly reported leak
locations) is what it takes to test the original question properly.

## What it did

1. Merged about 250 Railroad Commission pipeline shapefiles, sorted them by diameter into Small
   (12 to 18 in), Medium (18 to 24), Large (24 to 36) and Very Large (36 to 48), and grouped
   commodities. Only the 16,303 hydrocarbon liquid lines went forward.
2. Buffered them at 100, 250 and 500 m in latitude and longitude, intersected the buffers with the
   ecoregions, grouped into Deserts, Plains, Semi-Arid Plains and Semi-Arid Prairies, then
   simplified the pieces. Splitting and simplifying were needed to stay under Earth Engine's
   feature limits. The exact tools and settings are in `audit/results/arcgis_tool_history.csv`.
3. Gave each piece an ID of `<ObjectID>_<ecoregion>` and uploaded each ecoregion as an Earth Engine asset.
4. Ran the script: Sentinel-2 surface reflectance, March 1 to May 1, 2025, scenes under 60% cloud,
   pixels masked with the scene classification band, per-pixel mean over time, then the mean of
   10 m pixels inside each piece.
5. Joined the tables back in ArcGIS Pro and mapped them.

## The later version: phase IV (Nov 10 to 13, 2025)

A later copy of the project, `391 phase iv updated_11_10`, came off a USB stick on Oct 1, 2026. It
is 16 GB instead of 25 GB because it leaves out the per-ecoregion upload shapefiles and Earth Engine
tables (still in the first copy) and because one 7.8-million-polygon working layer was deleted. It
adds 47 tool runs and these steps:

- **Statistics by diameter class and ecoregion group** for the 250 m and 500 m layers, with
  heatmaps and box plots (`tablejoinfordataipynb.ipynb`), and two PDF reports
  (`NDVI_NDWI_Analysis_Report_pdf.pdf`, `NDVI_NDWI_Analysis_Report_500M.pdf`).
- **Hot spot analysis** (Getis-Ord Gi*) of NDVI and the water index at 250 m and 500 m, after the
  polygons were turned into points and projected to Texas Statewide Mapping System (EPSG:3081).
- **Cluster and outlier analysis** (Anselin Local Moran's I), which failed both times it ran.
- **A per-piece summary table** (`PipelineEco_Summaryfor250m_hydrocarbons`).
- **Natural gas 100 m buffers intersected with the ecoregions** (723,423 pieces), never sent to
  Earth Engine.

Checked on Oct 2, 2026:

- The NDVI tables in both PDFs match the 500 m data. The water-index tables in both PDFs do not
  match the data: the first gives a standard deviation of exactly 0.050 and a minimum of exactly
  the mean minus 0.100 for every group, and the second's numbers differ from what the data gives.
  The written findings in both call the pipe diameter classes "tree diameter". Do not reuse these
  reports.
- The summary table groups by piece ID, which is unique per piece, so it holds one row per piece
  (559,411) rather than one per pipeline.
- The hot spot points are the centres of the overlapping pieces described below, so many points
  sit on the same ground and are counted more than once. Treat those hot spots with caution.

## Problems found in the October 2026 audit

The same list, with who is fixing what, is on the dashboard's Plan page. The full numbers, the
scripts that produced them, and corrections to the first version of this list are in
[`audit/README.md`](../audit/README.md).

**In the Earth Engine script**

- The cloud mask comments are wrong. Scene class 3 is cloud shadow, not vegetation, and class 11
  is snow, not water. Open water, class 6, is not masked, which inflates the water index wherever a
  piece crosses a pond or river.
- The "NDWI" uses bands 3 and 11. That is MNDWI (Xu 2006), an open-water index. NDWI for plant
  water content (Gao 1996) uses bands 8 and 11.
- No pixel count or image count is kept, so a value resting on one pixel looks the same as one
  resting on thousands.
- `reduceRegions` takes its projection from the mean composite, which is latitude and longitude,
  so pixels were read on a 10 m grid in degrees instead of Sentinel-2's own grid.
- Pieces too small to hold a pixel centre come back blank. All 158,940 blank rows are 100 m
  slivers smaller than one pixel.

**In the data**

- Intersecting the buffers with the ecoregions also cut every buffer wherever another pipeline's
  buffer overlapped it: 16,303 buffers became 1.86 million pieces at 100 m, 3.7 million at 250 m
  and 7.8 million at 500 m.
- The three distances were simplified differently. At 250 m and 500 m every piece under 900 m² was
  deleted (85% and 88% of pieces); at 100 m none was.
- In the final 100 m layer only 52% of the area has a value. The master table's IDs were spelled
  with underscores inside the ecoregion names, so no Semi-Arid Plains or Semi-Arid Prairies piece
  joined (48% of the area), and 342,254 Plains slivers were never sent to Earth Engine because the
  shapefile hit the 2 GB limit.
- IDs come from each layer's own ObjectIDs, so the same stretch of pipe has different IDs at
  100, 250 and 500 m. Each piece's `ORIG_FID` still points to its source line.
- No Railroad Commission field is a unique line ID.
- No rows were lost when tables were combined; the combined files are smaller only because numbers
  were written with one digit fewer.

**In the design**

- One season, so nothing about change over time.
- No reference area, so no way to tell a pipeline effect from the land itself.
- Buffers are nested, not rings, so the 500 m value includes the 100 m one.
- The map symbolized 100 m by the water index and 250 and 500 m by NDVI.
