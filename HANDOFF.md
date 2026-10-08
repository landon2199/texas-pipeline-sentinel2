# Handoff: where the project stood on Oct 4, 2026

> **Superseded on Oct 7, 2026.** The statewide zones are built and springs 2023-2025 are measured. The current plan is
> analysis plan v1.7 (`docs/analysis_plan.html`), and the dashboard shows the groups and dates. This note is kept for
> the record.

Notes for picking this project up, first written at the end of the cloud planning session and
updated after the first local session. Delete or update this file once it is out of date.

## Where things stand

- **This repository** is public on GitHub: `landon2199/texas-pipeline-sentinel2`. It holds the
  team dashboard, the check-in form, last year's materials in `legacy-2025/`, the audit of last
  year's data in `audit/`, the Earth Engine Python program in `extract/`, and the reported-leak
  analysis in `leaks/`.
- **The dashboard** is live at https://landon2199.github.io/texas-pipeline-sentinel2/ with two
  pages, Home and Plan.
- **The old Aggie Map repository** was deleted. Everything worth keeping was moved here first.
- **The professor** has approved the change to pipeline monitoring and suggested using the Earth
  Engine Python API instead of the Code Editor.
- **Everything for the project is in one Google Drive folder,** `GEOG_392\projects` in Landon's
  course folder (`C:\mydrive\Graduate School\Courses\GEOG_392\projects` on the desktop): the
  proposal, this repository (in `code (do not edit)\`) and the team's data (`data\`). On the
  desktop, git's database and the Python environment sit outside Drive in
  `C:\Users\Landon\.geog392` (the repository's `.git` is a one-line pointer file), so Drive never
  syncs them; activate with `C:\Users\Landon\.geog392\venv\Scripts\activate`.
- **Last year's full project** (about 25 GB) is in that Drive folder under
  `data\GEOG391_GIS_Day_2025_backup`, and on Landon's computer at `D:\GEOG391_GIS_Day_2025\391 Research Phase 1` (renamed from
  `D:\391 google upload file space for november 10` on Oct 4). A later version with the hot spot
  analysis, `391 phase iv updated_11_10` (16 GB, Nov 13, 2025), sits beside it, with its
  `Clusteranalysis.ipynb` and `Hotspotanalysis.ipynb` next to the project file; the final slides
  and report are in `final\`. `legacy-2025/README.md` describes what the later version adds and
  what to distrust in it.
- **The audit of last year's data is done.** `audit/README.md` has the findings and the scripts
  that produced them. Headlines below.
- **The Earth Engine program works.** Signed in on Landon's desktop (project `research-476723`),
  its legacy method reproduces last year's 250 m Deserts values exactly on 500 random polygons
  (differences below 0.000000000000002). It now also reads Landsat 5 to 9 for 2000 onward; a test
  on the same polygons gave values for 2000, 2012 and 2025, agreeing with Sentinel-2 in 2025
  (NDVI correlation 0.96). See `extract/README.md`.
- **The plan changed on Oct 4** (the revised proposal): Sentinel-2 at 10 m for 2018 to 2026
  (full surface-reflectance coverage of Texas starts in 2018), every Railroad Commission line as
  delivered, ecoregions as delivered, NLCD land cover and OpenLandMap soil texture, Landsat 8-9
  land surface temperature, Google Colab for the team, and reported leaks from PHMSA
  (`leaks/README.md`): 83 crude or refined-product spills of 5+ barrels on Texas rights-of-way
  since mid-2018 (175 since 2010), 81 within 100 m of a mapped line. The work is six weeks and
  four deliverables: 1 zone layer (group A, Oct 23), 2 zone statistics (group B, Oct 29),
  3 results (group C, Nov 6), 4 web map and poster (everyone, Nov 13); the steps per
  group and fortnight are in `team.json` and the proposal. Following the instructor's Oct 2
  suggestions, the analysis flattens the NDVI and NDWI arrays into linear regressions that
  predict land surface temperature, and statewide embeddings (Google's Satellite Embedding
  dataset) are an if-time-allows extra. The two-page proposal (Word
  and PDF) is in the Drive project folder, `GEOG_392\projects`.

## What the audit found (details in `audit/README.md`)

- **Why 1.86 million polygons:** the Intersect with the ecoregions also cut each buffer wherever
  another pipeline's buffer overlapped it, one piece per combination of overlapping buffers.
  Clipping each segment's rings on their own removes the need to split or simplify.
- **The 100 m map had values for only 52% of its area.** The master table spelled the semi-arid
  IDs with underscores inside the ecoregion names, so neither semi-arid ecoregion joined, and
  342,254 Plains slivers were never sent because the shapefile hit 2 GB.
- **The three distances were simplified differently:** 85% and 88% of pieces were deleted at 250
  and 500 m, none at 100 m. That is why 250 m has fewer polygons than 500 m and only 100 m has
  blanks.
- **No rows were lost when tables were combined.** The first audit's claim was wrong; the files
  are smaller only because numbers were written with one digit fewer.
- **No Railroad Commission field is a unique line ID.** `ORIG_FID` links every piece to its source
  line, so last year's values can still be traced to the lines.

## Landon's to-do list

- [x] Turn on the dashboard site.
- [ ] Add teammates as collaborators: Settings, Collaborators, Add people. Known usernames:
      `jfloyd-27` (Jayden) and `tinlongg` (Henry).
- [ ] Ask Jayden and Henry to check in again here; their old check-ins were deleted with the
      old repository.
- [ ] Confirm the Kickoff poll link in `team.json` is the one emailed to the team.
- [x] Sign in to Earth Engine on this computer and run the legacy check.
- [ ] Rewrite the proposal draft in the team's own words, confirm the group assignments, and
      submit it on Canvas.
- [ ] Set up one shared Google Cloud project for Earth Engine and add teammates to it.
- [ ] Share the Drive folder `GEOG_392\projects\data` with the team.

## Setting up on a local machine

```
git clone https://github.com/landon2199/texas-pipeline-sentinel2
cd texas-pipeline-sentinel2

python -m venv .venv
# Windows: .venv\Scripts\activate    Mac or Linux: source .venv/bin/activate
pip install -r requirements.txt

earthengine authenticate
python -c "import ee; ee.Initialize(project='YOUR-CLOUD-PROJECT'); print('Earth Engine OK')"
```

Last year's Earth Engine project was `research-476723`. Use it or create a new shared one.
`.venv/` and `outputs/` are already in `.gitignore`. Do not create `.venv` inside a Google Drive
folder: Drive would sync thousands of files. On Landon's desktop the environment is
`C:\Users\Landon\.geog392\venv`.

To preview the dashboard locally, run `python -m http.server` in the repository folder and open
http://localhost:8000.

New to the project? Read this file, `legacy-2025/README.md` and `audit/README.md` first.

## Decisions made so far

- Python for every step; nothing done by hand in ArcGIS Pro. This also lets Mac users take part.
- Large data stays in Google Drive or Earth Engine assets, never in the repository.
- Three groups: **A** Data and zones, **B** Earth Engine, **C** Analysis and maps, each owning
  one deliverable, with the fourth (web map and poster) shared. Tasks for each are in
  `team.json`.
- Zones, from the revised proposal: 1 km segments, each in one ecoregion; rings on both sides at
  0 to 50, 50 to 100, 100 to 250 and 250 to 500 m plus a 500 to 1,000 m comparison ring, replacing
  last year's nested buffers; 50 and 100 m circles around each spill, with control circles about
  0.5 km along the same line on each side.
- EPA Level III ecoregions (12 in Texas) instead of last year's four groups. NLCD land cover
  splits each zone pixel by pixel, so a ring is compared only with comparison land of the same
  cover; each ring's soil texture class (OpenLandMap, 250 m, already in Earth Engine) is a factor
  in the regressions. This replaced splitting by 10 m gSSURGO soil, which is not in Earth Engine
  and would have meant uploading a statewide raster.
- Sentinel-2 at 10 m, with the same spring window, March 1 to May 1, every year from 2018 to 2026.
  Zones for the whole state; Earth Engine gets a stratified sample of up to 2 million zones (about
  400,000 segments) in 13 files, one per ecoregion and one for the spills. For Question 2, every spill.
- Every pipeline segment gets one ID that stays the same at every distance.

Recommended by the audit, for the team to confirm:

- Clip each segment's rings on their own; never intersect all the rings as one overlapping layer.
- Do all geometry work in one equal-area projection: NAD83(2011) Texas Centric Albers Equal Area,
  EPSG:6579, which last year's map already used. Earth Engine then reads pixels on a UTM grid.

## Fixes carried into the new Earth Engine program (`extract/indices.py`, method `v2`)

- Mask scene classes 1, 2, 3, 6, 8, 9, 10 and 11 (saturated, dark, shadow, water, cloud, cirrus,
  snow). Last year's mask kept open water, class 6.
- NDWI from bands 8 and 11 for plant moisture, with last year's bands 3 and 11 kept as MNDWI.
- A pixel count for every polygon and the mean number of clear images per pixel.
- Mean or median composite, to compare on one region.
- An explicit UTM grid instead of the composite's latitude-and-longitude projection.
- Upload assets as GeoJSON or from a geodatabase, not shapefiles, so field names are not cut to
  ten characters and no file hits the 2 GB limit.

## Open questions

- What do the Railroad Commission's `STATUS_CD` values mean (`I` 15,526 lines, `B` 776, `R` 1),
  and should lines that are not in service be left out?
- What stable ID should the 1 km segments carry? `TPMS_ID` plus a part number is a candidate, but
  2,199 lines share a `TPMS_ID`.
- Should the 500 to 1,000 m comparison ring leave out land within reach of other pipelines? Most
  pipelines share corridors, as the overlap finding shows.
- Is Level IV ecoregion detail worth it, or do too many units have too few segments?
- Which statistical test: paired ring-versus-reference differences, or a mixed model with
  ecoregion and soil?
- Natural gas buffers (76,863 lines) were built last year but never extracted. A later extension?
- Do the Railroad Commission's H-8 loss reports (spills over 5 barrels, by year from 2009) carry
  coordinates? They would add spills on the many small lines PHMSA does not regulate.
- Spill controls are planned about 0.5 km along the same line on each side. Do they match the
  spill site's soil and land cover, and where they do not, how far should they move?

## Useful facts from the planning session

- The Drive folder's names are inconsistent ("Deserts" and "Desserts", "masterdatset",
  "exclduing"); the audit maps each file to its ecoregion and distance.
- Last year dropped lines under 12 inches and used four diameter classes: Small 12 to 18 in,
  Medium 18 to 24, Large 24 to 36, Very Large 36 to 48.
- No hydrocarbon liquid line crossed the Arizona/New Mexico Mountains ecoregion, so it never
  appears in the results.
- Teammates so far: Jayden (`jfloyd-27`) has ArcGIS Pro on Windows; Henry (`tinlongg`) uses an
  Apple Silicon Mac with 16 GB of memory.
- Course dates: update presentations Oct 19 to 23 (moved from Oct 12 to 16), Midterm 2 Oct 30, final
  presentations from Nov 23, hard deadline Dec 6.

## Proposal

The planning session's outline was replaced by the revised proposal of Oct 4 (see above). Its two-week milestone, for Oct 16: zones built for one ecoregion, spills matched
to pipeline segments, and a first before-and-after check on 10 spills.
