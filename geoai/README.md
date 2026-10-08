# GeoAI: Qiusheng Wu's tools (gishub.org) in the project

| Tool | Where we use it |
|---|---|
| **SamGeo** (Segment Anything for geospatial data; Wu and Osco 2023) with **SAM 2** (Ravi et al. 2024) | `row_finder.py`: find the real cleared right-of-way beside each mapped line in NAIP photos |
| **geemap** | `projects/notebooks/Explore - Results Map.ipynb`: the team's interactive map of the results in Colab |
| **GeoAI** and **leafmap** | installed for the next steps (training a right-of-way model, interactive maps of GeoParquet) |

## The environment

A separate conda environment keeps PyTorch and SAM 2 away from the project venv and the thesis environment:
`C:\Users\Landon\miniforge3\envs\geog392-geoai`, with Python 3.12, PyTorch 2.11 on CUDA 12.8 (RTX 4080),
segment-geospatial 1.4.2 with SAM 2, geoai-py 0.43.1, geemap 0.38.9, leafmap 0.63.1, rasterio and geopandas.
`C:\Users\Landon\.geog392\setup_geoai_env.sh` rebuilds it.

The environment uses OpenBLAS, not MKL. With conda-forge's MKL 2026.1, `scipy.linalg.inv` crashed on Windows
(0xc06d007f), which stopped SamGeo from importing.

## The right-of-way finder (prototype, Oct 7, 2026)

```
C:\Users\Landon\miniforge3\envs\geog392-geoai\python.exe row_finder.py --n 8
```

It tests 8 segments per mapped-accuracy class, in brush and woodland ecoregions. For each segment it fetches a USGS
NAIP photo (4 bands, 0.6 m) and runs two independent methods:

1. **SAM 2.** It is prompted with points along the mapped line, shifted sideways in 20 m steps, with "not this" points
   100 m to each side. A strip-shaped mask is kept as the right-of-way only if it:
   - covers at least 70% of the segment;
   - is 8–70 m wide;
   - keeps its offset within 15 m along its length.
2. **A NAIP NDVI profile across the line.** The cleared strip shows as a trough.

The two methods "agree" when their centers are within 20 m.

**First results on 24 segments:**
- SAM 2 found a strip on 16 segments and agreed with the NDVI profile on 11.
- Where they agree, the mapped line is 6–13 m from the cut, even on lines rated 301–500 ft.
- The selection rules were tuned on these same 24 segments, so they need a test on new segments before any line is
  moved.

Outputs, in `outputs/geoai/row_finder/`:
- `row_finder_results.csv`
- a figure for each segment (the photo, the mapped line, SAM 2's strip, and the NDVI profile)
- the NAIP chips

## Next steps

- Test the rules on 50 new segments.
- Label 100 right-of-ways by hand and train a segmentation model with GeoAI.
- Feed the measured offsets back into Part 1, so rings are drawn on the real right-of-way.
