# Refactor plan (branch `refactor`; never `main`)

Owner: Landon (GEOG 392/676 Group 10). Approved Oct 10, 2026. Runs in Claude cloud sessions; the full data lives on
Landon's PC (Google Drive), so cloud work is checked with the fixtures in `tests/`, and the final regression check runs
locally on the full data.

## Goal
The same results from cleaner code: one shared package of helpers, no copy-pasted estimators, paths in one place,
tests. **No result may change.** Every point estimate in `tests/expected_headlines.json` must match to 1e-9 on the full
data, and every fixture value in `tests/expected_fixture.json` on the fixtures.

## Rules
- Work only on branch `refactor`, and never push to `main`: GitHub Pages and the dashboard workflow deploy from `main`.
- Commit messages carry no AI or co-author trailers (Landon's rule).
- Keep every script's command line working: same arguments, same output files and columns. The team notebooks and the
  MCP servers read those outputs.
- Plain-language docstrings stay. Comments match the surrounding density.
- No data in the repo beyond `tests/fixtures`:
  - no spill results (the photo check is blind and the repo is public);
  - no Carbon Mapper data (noncommercial license);
  - no `docs/` (team documents name teammates; it is gitignored).

## Scope
**Refactor now (stable):**
- `zones/`: build_zones, draw_sample, draw_supplement, wall_zones, stations, labels, spill_zones;
- `analysis/`: corridor, coverage_estimate, size_standardized, clearing_calibration, wall_map, man_made_check,
  hot_spots_by_spring, gi_star, gap_drivers, strip_diagram;
- `publish/`: catalog, project_database;
- `extract/`: part2, run_springs, run_wall_to_wall, run_landsat_spills, run_pixel_pilot (the Earth Engine code).
  Keep the export names and selectors identical, because `jobs_log.csv` matches on names.

**Leave alone until their results settle** (they are being built now, plan D29–D32):
- `analysis/spills*.py`, `spill_*.py`;
- `analysis/methane*.py`, `leaks/`;
- `geoai/`;
- the pixel pilot and detector analyses (not written yet).

## What to consolidate
- **A shared module** (e.g. `common/`): the project paths (`P`, `R`, the stats folder, `AGENT`), the weighted median
  (copied in at least six files), the stratified bootstrap, ring and band label parsing, the diameter classes and
  breaks (`zones/labels.py` has the source of truth), NLCD names, and the job-log helpers.
- **Paths:** one config (an environment variable such as `GEOG392_PROJECT` with today's path as the default), not
  hard-coded `C:\mydrive\...` strings.
- **The calibration chain:** coverage_estimate, clearing_calibration and project_database each compute "a piece's
  median over springs, then a weighted median". Make that one function.

## Tests
- `pytest` tests that load `tests/fixtures/*` and reproduce `tests/expected_fixture.json`.
- Unit tests for the weighted median, the bootstrap (shape and seed behavior), the ring parser and the diameter classes.
- `tests/make_fixtures.py` regenerates the fixtures locally; don't run it in the cloud, because it needs the full data.

## Done when
1. Fixture tests pass in the cloud.
2. Locally, Landon or Claude reruns, on the full data:
   - coverage_estimate.py;
   - clearing_calibration.py (`--boot 500`);
   - size_standardized.py;
   - wall_map.py `--spring 2026`;
   - publish/catalog.py.

   Every value in `tests/expected_headlines.json` matches.
3. Landon reviews the branch diff before any merge.
