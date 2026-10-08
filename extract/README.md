# Extracting satellite values with the Earth Engine Python API

## Part 2: the statewide runs (analysis plan v1.7)

`part2.py` measures every zone image by image: Sentinel-2 surface reflectance with Cloud Score+ masks, NDVI, NDMI,
SAVI, MNDWI, NDRE, S2REP and BSI, each zone's mean and pixel count split by NLCD land cover, on a 20 m grid for the
corridor zones and 10 m for the spill zones. It also measures Landsat surface temperature, the gridMET drought indices
and the fixed values (terrain, drainage, water share, soil). `run_springs.py` submits every job for each spring inside
a monthly compute budget and keeps a log of them in `jobs_log.csv` (on this computer, not in the repository):

```
python extract/run_springs.py --sample projects/research-476723/assets/geog392/sample_v1_b50     --spills projects/research-476723/assets/geog392/spills_v1     --springs 2022 2021 2020 2019 2018 2026 2025 2023 2024 --budget 900
python extract/run_springs.py --status
```

- `--budget` is the month's ceiling in EECU-hours: about 140 on the Community tier (150 a month) and up to 900 on the
  Contributor tier (1,000 a month). The Contributor tier needs a billing account on the Cloud project; noncommercial
  Earth Engine use is not charged.
- Jobs already in the log are skipped, so the command can be rerun after a stop or a new month.
- Exports go to the Drive folder `geog392_zone_stats`. Earth Engine finds Drive folders by name, so keep exactly one
  folder with that name, in `projects/outputs`.
- `run_part2.py` runs a single job, a cost test on a few segments, or one region.

## Last year's method in Python

`indices.py` is last year's Code Editor script rebuilt in Python, as the professor asked, and
extended to Landsat so the record reaches back to 2000. `compare_with_2025.py` checks it against
last year's numbers. The archived practice notebooks (Oct 5) import `indices.py`.

## One-time setup

1. Register for Earth Engine for noncommercial use and make sure you can open
   https://code.earthengine.google.com with your account.
2. On your own computer, install the packages (see the main README) and sign in once with
   `earthengine authenticate`, which opens a browser. In Colab, `ee.Authenticate()` does the same.
   Credentials are saved in your user folder, outside this repository. Never copy them into it.
3. You need a Google Cloud project registered for Earth Engine. Last year's is
   `research-476723`; the team may set up a shared one instead.

## Check: reproduce last year's 250 m Deserts values (done Oct 2, 2026)

The legacy method repeats last year's script exactly, mistakes included:

```
python extract/indices.py --project research-476723 --method legacy \
    --asset projects/research-476723/assets/hydrocarbon250m_deserts_eco \
    --start 2025-03-01 --end 2025-05-01 --sample 500 --out outputs/legacy_deserts_250m_sample.csv

python extract/compare_with_2025.py outputs/legacy_deserts_250m_sample.csv \
    "PATH/391 Research Phase 1/Hydrocarbon_Diameter_eco_250m/hydrocarbons_Deserts_250m.csv"
```

Result: all 500 random polygons matched last year's NDVI and water index; the largest difference was
0.0000000000000013, which is rounding. Last year's 12 uploaded tables are still in
`projects/research-476723/assets`.

## This year's method (`v2`)

| | Last year (`legacy`) | This year (`v2`) |
|---|---|---|
| Sensor | Sentinel-2, 10 m, spring 2025 | Sentinel-2 at 10 m (`--sensor s2`, 2019 onward) or Landsat 5 to 9 at 30 m (`--sensor landsat`, 2000 onward) |
| Masked | Scene classes 3, 8, 9, 10, 11 (open water kept) | Clouds, shadows, snow, saturated pixels and open water |
| Indices | NDVI, and bands 3 and 11 labelled NDWI (really MNDWI) | NDVI, NDWI from NIR and SWIR1 (plant water), MNDWI (open water), SAVI (damps bare-soil brightness) |
| Composite | Per-pixel mean | Mean or median (`--composite`) |
| Grid | Latitude and longitude | UTM (`--crs` to choose) |
| Quality columns | None | Pixel count and mean clear images per pixel |
| Years | One | Any, for example `--years 2000-2026` |

Landsat 5 and 7 values are adjusted to match Landsat 8 with the Roy et al. (2016) coefficients;
check them against the paper before the final report.

A test on the same 500 Deserts polygons (Oct 2, 2026):

| Run | Polygons with a value | Median NDVI | Median clear images per pixel |
|---|---|---|---|
| Sentinel-2, spring 2025 | 500 | 0.119 | 8.0 |
| Landsat, spring 2000 | 500 | 0.135 | 4.0 |
| Landsat, spring 2012 | 500 | 0.161 | 2.0 |
| Landsat, spring 2025 | 500 | 0.141 | 4.6 |

Landsat and Sentinel-2 agree well in 2025 (NDVI correlation 0.96, Landsat about 0.02 higher), so
the two records can be joined with care. 2012 is the thinnest year: only Landsat 7, with its
scan-line gaps, was flying.

Full runs go to your Google Drive as CSVs, split into chunks:

```
python extract/indices.py --project YOUR-CLOUD-PROJECT --sensor landsat \
    --asset projects/YOUR-CLOUD-PROJECT/assets/YOUR-RINGS --id-field ring_id \
    --years 2000-2026 --export --chunk-field ring_number --chunks 10 --drive-folder pipeline_exports
```

Run one ecoregion or one chunk of segments at a time, so all its polygons sit in one UTM zone.
Outputs go in `outputs/` (ignored by Git) or the shared Drive folder, never in the repository.
