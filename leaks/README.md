# Reported pipeline leaks in Texas

Last year's project asked whether vegetation can reveal pipeline leaks but used no leak records.
This folder adds them: PHMSA's hazardous liquid accident reports, checked against the Railroad
Commission's pipeline lines.

## Files

| File | What it does |
|---|---|
| `phmsa_texas.py` | Reads PHMSA's accident table, keeps onshore Texas accidents with coordinates, measures the distance to the nearest Railroad Commission line, adds the ecoregion, and writes the summaries in `results/` |
| `figure_proposal.py` | Draws Figure 1 of the revised proposal: the spills on a map of Texas pipelines, beside the ring design |
| `results/` | Counts by year, commodity, part of the system, location type, ecoregion and cause, and a summary of how many accidents sit near a mapped line |

PHMSA's site blocks scripts, so download the zip by hand: "Hazardous Liquid Accident Data - January
2010 to present (ZIP)" on PHMSA's [accident and incident data page](https://www.phmsa.dot.gov/data-and-statistics/pipeline/distribution-transmission-gathering-lng-and-liquid-accident-and-incident-data).
The table includes the names of the people who filed each report; the scripts drop those columns and
nothing personal is written to `results/`. The accident points go to `outputs/` (ignored by Git).

## What the data holds (downloaded Oct 4, 2026; PHMSA updated it Sep 3, 2026)

- 6,009 hazardous liquid accidents nationwide since January 2010; **2,456 onshore in Texas** with
  coordinates inside the state.
- Most happened inside stations, terminals and tank farms: 1,857 were "totally contained on
  operator-controlled property". Those are not useful for vegetation along a line.
- **446 happened on the pipeline right-of-way.** 425 of them lie within 100 m of a Railroad
  Commission line in last year's download, so the two datasets agree well on location.
- **175 right-of-way spills were crude oil or refined products of 5 barrels or more.** These are the
  spills most likely to mark vegetation: 168 lie within 100 m of a mapped line, 171 report soil
  contamination, 96 were 50 barrels or more and 40 were 500 barrels or more.
- They are spread across every year from 2010 to 2026 (6 to 20 a full year; 2 so far in 2026), 11
  of the 12 ecoregions, and every month, so before-and-after comparisons are possible in all seasons.
- Highly volatile liquids (462 accidents) and carbon dioxide (28) turn to gas when released, so they
  are unlikely to leave a mark on vegetation; they are kept out of the 175.

## Caveats

- PHMSA covers the pipelines it regulates. Many small gathering lines, most of the Railroad
  Commission's 476,000 mapped lines, are not in it. The Railroad Commission's own H-8 loss reports
  (spills over 5 barrels, by year since 2009) may fill that gap; whether they carry coordinates is not
  yet checked.
- A reported location is where the operator said the release was; check a few against imagery
  before trusting all of them.
