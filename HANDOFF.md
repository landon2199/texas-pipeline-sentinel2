# Handoff: where the project stands (Oct 1, 2026)

Notes for picking this project up on a local machine, written at the end of the first
planning session with Claude Code. Delete or update this file once it is out of date.

## Where things stand

- **This repository** is public on GitHub: `landon2199/texas-pipeline-sentinel2`. It holds the
  team dashboard, the check-in form, and last year's materials in `legacy-2025/`.
- **The old Aggie Map repository** was deleted. Everything worth keeping was moved here first.
- **The professor** has approved the change to pipeline monitoring and suggested using the Earth
  Engine Python API instead of the Code Editor.
- **Last year's full project** (about 25 GB) is in Google Drive under **392 Project**.
- **Last year's Earth Engine script** was found and saved as
  `legacy-2025/gee_s2_ndvi_ndwi_2025.js`. `legacy-2025/README.md` records the method and every
  problem the audit found.

## Landon's to-do list

- [ ] Turn on the dashboard site: Settings, Pages, **Deploy from a branch**, `main`, root.
      It will be at https://landon2199.github.io/texas-pipeline-sentinel2/
- [ ] Add teammates as collaborators: Settings, Collaborators, Add people. Known usernames:
      `jfloyd-27` (Jayden) and `tinlongg` (Henry).
- [ ] Ask Jayden and Henry to check in again here; their old check-ins were deleted with the
      old repository.
- [ ] Confirm the Kickoff poll link in `team.json` is the one emailed to the team.
- [ ] Finish the proposal draft by **Sun Oct 4** and send it to the professor early next week.
- [ ] Set up one shared Google Cloud project for Earth Engine and add teammates to it.
- [ ] Share the **392 Project** Drive folder with the team.

## Setting up on a local machine

```
git clone https://github.com/landon2199/texas-pipeline-sentinel2
cd texas-pipeline-sentinel2

python -m venv .venv
# Windows: .venv\Scripts\activate    Mac or Linux: source .venv/bin/activate
pip install earthengine-api geemap geopandas pandas matplotlib

python -c "import ee; ee.Authenticate(); ee.Initialize(project='YOUR-CLOUD-PROJECT'); print('Earth Engine OK')"
```

Last year's Earth Engine project was `research-476723`. Use it or create a new shared one.
`.venv/` is already in `.gitignore`.

To preview the dashboard locally, run `python -m http.server` in the repository folder and open
http://localhost:8000.

To keep working with Claude Code locally, run `claude` inside the repository folder. A local
session does not see this cloud session's conversation, so point it at this file and
`legacy-2025/README.md` first.

## Decisions made so far

- Python for every step; nothing done by hand in ArcGIS Pro. This also lets Mac users take part.
- Large data stays in Google Drive or Earth Engine assets, never in the repository.
- Three groups: **A** Data and segments, **B** Earth Engine in Python, **C** Analysis and maps.
  Tasks for each are in `team.json`.
- Distance rings (0 to 100, 100 to 250, 250 to 500 m) plus a 500 to 1,000 m reference ring,
  replacing last year's nested buffers.
- EPA Level III ecoregions (12 in Texas) instead of last year's four groups, with soil class from
  gSSURGO or STATSGO2 as a covariate.
- Same spring window, March 1 to May 1, for 2019 to 2025.
- Every pipeline segment gets one ID that stays the same at every distance.

## Fixes to carry into the new Earth Engine script

- Mask scene classes 1, 2, 3, 6, 8, 9, 10 and 11 (saturated, dark, shadow, water, cloud, cirrus,
  snow). Last year's mask kept open water, class 6.
- Compute NDWI from bands 8 and 11 for plant moisture. Last year's bands 3 and 11 give MNDWI, a
  water index.
- Add a pixel count to every zonal result and an image count per pixel; flag thin results.
- Compare a mean composite with a median composite on one region.
- Upload assets as GeoJSON or from a geodatabase, not shapefiles, so field names are not cut to
  ten characters.

## Open questions

- Why did 16,303 pipeline lines become 1.86 million polygons at 100 m? Fixing this may remove
  the need to split and simplify at all. This is group A's first task.
- Is Level IV ecoregion detail worth it, or do too many units have too few segments?
- How wide should the reference ring be, and should it exclude land near other pipelines?
- Which statistical test: paired ring-versus-reference differences, or a mixed model with
  ecoregion and soil?

## Proposal outline

1. The question: do vegetation and moisture near Texas liquid pipelines differ from comparable
   land nearby, and does that change with distance, pipe size, ecoregion and year?
2. Last year's result and its three limits: one season, no reference area, IDs that did not match.
3. The new approach: one Python pipeline using the Earth Engine Python API.
4. The three groups, their tasks and their reports.
5. Two-week milestones (by Fri Oct 16): stable IDs on a 1,000-segment test set, the Python script
   matching last year's 250 m Deserts values, and the audit report.
6. Timeline to GIS Day, Nov 16, and the course deadline, Dec 6.
