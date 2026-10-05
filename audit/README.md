# Audit of last year's data (GIS Day 2025)

Three scripts that check last year's result tables, ArcGIS Pro project and geodatabase, and what
they found. They were run on Oct 1, 2026 against Landon's local copy of the **392 Project** folder
(since Oct 4 at `GEOG_392/projects/data/GEOG391_GIS_Day_2025_backup` in Drive).
They only read the data; nothing in the folder is changed.

## Running the scripts

You need Python with `pandas`, `pyogrio` and `shapely` 2 (script 03 also uses `numpy`). Point each
script at your copy of `391 Research Phase 1`:

```
python audit/01_audit_tables.py --data "PATH/391 Research Phase 1"
python audit/02_tool_history.py --aprx "PATH/391 Research Phase 1/391 Research Phase 1.aprx"
python audit/03_polygon_explosion.py --gdb "PATH/391 Research Phase 1/391 Research Phase 1.gdb"
```

Script 01 takes about 10 minutes, 02 a few seconds, 03 about 2 minutes. Results go to
`audit/results/`:

| File | What it holds |
|---|---|
| `tables_audit.md` | Every table from script 01 in one readable page |
| `tables_per_file.csv` | Rows, blanks, duplicate IDs and ID spelling for each CSV |
| `tables_lineage.csv` | Each combined table checked against the ecoregion tables it was built from |
| `tables_vs_shapefiles.csv` | Rows returned by Earth Engine against polygons uploaded |
| `ids_across_distances.csv` | How often the same ID appears at two distances |
| `arcgis_tool_history.csv` | All 238 tool runs in the ArcGIS Pro project, with their settings |
| `polygon_counts.csv` | Polygons at each processing step, for each distance |
| `recut_test.csv` | The test that explains where the extra polygons came from |
| `final_100m_coverage.csv` | How much of the final 100 m layer has values, and why the rest does not |

## What we found

### 1. No rows were lost when the tables were combined

- Every combined table holds every row of the ecoregion tables it was built from, with the same
  values (differences below 0.0000000000000001).
- The combined files are smaller only because each number was written with one digit fewer. At
  500 m that accounts for 847,281 of the 847,353 missing bytes; three header lines account for most
  of the rest.
- The complete tables are `combined_all_regions_masterset.csv` (100 m),
  `hydrocarbon_liquids_250m_masterdataset.csv` (250 m) and
  `combined_hydrocarbons_500m_masterdatset.csv` (500 m). The other combined files are in-between
  steps that leave out one or two ecoregions.
- No table has a duplicate ID. Earth Engine returned exactly one row per uploaded polygon for all
  12 uploads.
- The zip in the 500 m folder holds copies of the four 500 m ecoregion tables that sit next to it
  (same names and sizes).

### 2. Blank values exist only at 100 m, and they are tiny pieces

- At 100 m, 158,940 of 1,514,532 rows (10.5%) have no NDVI or water index value. Every ecoregion
  has them: Deserts 15.1%, Plains 10.0%, Semi-Arid Plains 17.3%, Semi-Arid Prairies 7.9%.
- At 250 m and 500 m there are none, because every piece under 900 m² was deleted there before
  upload (see 4).
- The blank pieces are slivers: median area 0.1 m², and every one is smaller than a single 10 m
  pixel (100 m²), so Earth Engine found no pixel centre inside them. Together they cover almost none
  of the buffer area.

### 3. Why 16,303 lines became 1.86 million polygons

- The jump happens at one step, the Intersect with the ecoregions: 16,303 buffers became 1,856,841
  pieces at 100 m, 3,661,062 at 250 m and 7,756,817 at 500 m.
- Ecoregion borders explain almost none of it. Only 508 buffers cross a border; buffer and
  ecoregion together make 16,833 combinations, not 1.86 million.
- **The cause:** the Intersect also cut every buffer wherever another pipeline's buffer overlapped
  it, making one piece for each different combination of overlapping buffers. Re-cutting 25 random
  buffers this way gave exactly ArcGIS's number of pieces for 24 of them (`recut_test.csv`).
  Pipelines run side by side in shared corridors, so wider buffers overlap more and break into more
  pieces.
- 86% of the 100 m pieces are smaller than 900 m², but together they hold under 1% of the area.
- **Fix for this year:** clip each segment's rings on their own, so one pipeline never cuts
  another. In Python, `geopandas.overlay` does this; in ArcGIS, Pairwise Intersect does. Earth
  Engine handles overlapping polygons without trouble, so there is no need to split or simplify.
- Three buffers have no pieces at all: they sit offshore or in bays (Chambers, Jefferson and Nueces
  counties), outside the ecoregion layer.

### 4. The three distances were simplified with different settings

| Distance | Method | Tolerance | Minimum area | Pieces removed | Area removed |
|---|---|---|---|---|---|
| 100 m | Bend simplify | 20 m | none | 55 (0.003%) | none |
| 250 m | Bend simplify | 30 m | 900 m² | 3,101,651 (85%) | 0.65% |
| 500 m | Point remove | 30 m | 900 m² | 6,806,767 (88%) | 2.4% |

- This is why the 250 m layer ended with fewer polygons than the 500 m layer, and why only the
  100 m results have blanks.
- Every removed piece was kept as a point in a `..._Pnt` layer, so nothing disappeared without a
  record.
- ArcGIS warned at every run that the data had no projected coordinate system, so tolerances in
  metres were applied to latitude and longitude.

### 5. The 100 m map had values for only about half of its area

In the final 100 m layer, `MergedLayer_Hydrocarbons_100m_Masterlayer`:

| Piece | Pieces | Share of pieces | Share of area |
|---|---|---|---|
| Has a value | 1,049,543 | 56.5% | 52.2% |
| Join failed: ID spelled differently in the table | 337,124 | 18.2% | 47.7% |
| Never sent: shapefile hit 2 GB | 342,254 | 18.4% | 0.1% |
| Blank: Earth Engine returned no value | 127,865 | 6.9% | 0.0% |

- **Join failed.** The four 100 m tables from Earth Engine write each ID with a space, for example
  `7699 SEMIARID Plains`. The master table changed every space to an underscore, including the
  spaces inside ecoregion names (`7699_SEMIARID_Plains`), while the layer's IDs read
  `7699_SEMIARID Plains`. So no Semi-Arid Plains or Semi-Arid Prairies piece received its value,
  even though the values exist in the ecoregion tables. Those two ecoregions are 48% of the 100 m
  buffer area.
- **Never sent.** Export Features wrote Plains pieces to a shapefile in ID order until the attribute
  table reached the 2 GB shapefile limit. It stopped at 980,585 records; one more 2,190-byte record
  would have passed the limit. The other 342,254 Plains pieces never went to Earth Engine. The
  export logged "General function failure" for features in that range. They are slivers, so little
  area was missed.
- At 250 m and 500 m every piece has a value.

### 6. IDs cannot link the distances, and no existing field is a unique line ID

- Each ID is an ObjectID plus an ecoregion, made separately for each layer, so the same number at
  two distances is a coincidence (`ids_across_distances.csv`).
- Every piece does carry `ORIG_FID`, the ObjectID of its source pipeline line, at every distance.
  Last year's values can therefore still be traced back to the 16,300 lines that have pieces.
- In the Railroad Commission fields of the 16,303 lines, `TPMS_ID` has 15,173 distinct values
  (2,199 lines share one with another line), `PLINE_ID` has 1,566 (841 lines blank) and `SYS_ID`
  931. None is unique, so this year's stable ID has to be built and then checked for uniqueness.
- `STATUS_CD` is `I` for 15,526 lines, `B` for 776 and `R` for 1. Check the Railroad Commission's
  code list before deciding which lines to keep. The `LENGTH` field is zero for every line.

## Corrections to the first audit (Oct 1, cloud session)

The first audit worked from files that downloaded from Drive, which failed above about 6 MB. With
the full files, four of its statements change:

| First audit said | The full data shows |
|---|---|
| Combined tables are smaller, so rows were lost | No rows were lost. Numbers were written with one digit fewer. |
| The 100 m Semi-Arid Plains table uses a space instead of an underscore, and 17% of its rows are blank | All four 100 m tables use a space, and all have blanks (10.5% overall). The real damage was the master table's spelling, which broke the join for both semi-arid ecoregions. |
| Simplify Polygon dropped features without a record | It kept a point for every removed piece. The failure warnings came from Export Features at the 2 GB cut-off. |
| Why the 250 m layer has fewer polygons than the 500 m layer is unknown | Different minimum-area settings (point 4). |

Confirmed as stated: the 2 GB truncation, the about 110 pieces per line at 100 m, IDs that differ
between distances, the cloud mask and water index problems in the Earth Engine script.
