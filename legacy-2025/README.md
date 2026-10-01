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

The full project, about 25 GB, is in Landon's Google Drive under **392 Project**: the ArcGIS Pro
project and its 18 GB geodatabase, the per-ecoregion shapefiles and tables for each distance, and
the EPA Level III Ecoregions of Texas shapefile. Ask Landon for access.

## What it did

1. Merged about 250 Railroad Commission pipeline shapefiles, sorted them by diameter into Small
   (12 to 18 in), Medium (18 to 24), Large (24 to 36) and Very Large (36 to 48), and grouped
   commodities. Only the 16,303 hydrocarbon liquid lines went forward.
2. Buffered them at 100, 250 and 500 m, simplified the buffers, and intersected them with the
   ecoregions, grouped into Deserts, Plains, Semi-Arid Plains and Semi-Arid Prairies. Splitting and
   simplifying were needed to stay under Earth Engine's feature limits.
3. Gave each piece an ID of `<ObjectID>_<ecoregion>` and uploaded each ecoregion as an Earth Engine asset.
4. Ran the script: Sentinel-2 surface reflectance, March 1 to May 1, 2025, scenes under 60% cloud,
   pixels masked with the scene classification band, per-pixel mean over time, then the mean of
   10 m pixels inside each piece.
5. Joined the tables back in ArcGIS Pro and mapped them.

## Problems found in the October 2026 audit

The same list, with who is fixing what, is on the dashboard's Tasks page.

**In the Earth Engine script**

- The cloud mask comments are wrong. Scene class 3 is cloud shadow, not vegetation, and class 11
  is snow, not water. Open water, class 6, is not masked, which inflates the water index wherever a
  piece crosses a pond or river.
- The "NDWI" uses bands 3 and 11. That is MNDWI (Xu 2006), an open-water index. NDWI for plant
  water content (Gao 1996) uses bands 8 and 11.
- No pixel count or image count is kept, so a value resting on one pixel looks the same as one
  resting on thousands.
- Small pieces with no pixel center inside them come back blank. This explains most blank rows.

**In the data**

- The 100 m Semi-Arid Plains table uses a space instead of an underscore in every ID, and 17% of
  its rows have no values.
- Combined tables are 0.5 to 1.2 MB smaller than the tables they were built from, at every
  distance, so rows were lost or changed when combining.
- IDs come from each layer's own ObjectIDs, so the same stretch of pipe has different IDs at
  100, 250 and 500 m.
- The 100 m layer has 1.86 million polygons for 16,303 lines, about 110 per line.
- The 100 m Plains shapefile's attribute table is at the 2 GB shapefile limit and is probably truncated.
- Simplify Polygon dropped features it could not process; the failures are only in the tool logs.

**In the design**

- One season, so nothing about change over time.
- No reference area, so no way to tell a pipeline effect from the land itself.
- Buffers are nested, not rings, so the 500 m value includes the 100 m one.
- The map symbolized 100 m by the water index and 250 and 500 m by NDVI.
