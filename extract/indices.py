"""Vegetation and moisture for pipeline polygons from Sentinel-2 or Landsat, with Earth Engine.

Last year's Code Editor script (legacy-2025/gee_s2_ndvi_ndwi_2025.js) rebuilt in Python. It runs
from a command line or, for the team, from the Google Colab notebooks in notebooks/, which import
these functions.

Methods
  legacy  Exactly what last year's script did, mistakes included (Sentinel-2 only): scene classes
          3, 8, 9, 10 and 11 masked (open water kept), "NDWI" from bands 3 and 11 (really MNDWI),
          scenes under 60% cloud, a per-pixel mean, and pixels read in the composite's own
          projection, which is latitude and longitude. Use it only to check this program against
          last year's numbers.
  v2      This year's method: clouds, shadows, snow and open water masked; NDVI, NDWI from NIR and
          SWIR1 (plant water content, Gao 1996), MNDWI from green and SWIR1 (open water, Xu 2006)
          and SAVI (a vegetation index that damps bare-soil brightness, Huete 1988); a mean or
          median composite; a pixel count and the mean number of clear images per pixel for every
          polygon; pixels read on a UTM grid.

Sensors (v2 only)
  s2       Sentinel-2 surface reflectance, 10 m. In Earth Engine from 2017; full Texas coverage
           from about 2019.
  landsat  Landsat 5, 7, 8 and 9 surface reflectance (Collection 2), 30 m, 1984 to now. Landsat 5
           and 7 values are adjusted to match Landsat 8 (Roy et al. 2016) so years can be compared.

Command-line examples

  python extract/indices.py --project YOUR-CLOUD-PROJECT --method legacy \\
      --asset projects/research-476723/assets/hydrocarbon250m_deserts_eco \\
      --start 2025-03-01 --end 2025-05-01 --sample 500 --out outputs/legacy_deserts_250m_sample.csv

  python extract/indices.py --project YOUR-CLOUD-PROJECT --sensor landsat \\
      --asset projects/YOUR-CLOUD-PROJECT/assets/YOUR-RINGS --id-field ring_id \\
      --years 2000-2026 --export --drive-folder pipeline_exports

Sign in once with `earthengine authenticate` (in Colab, ee.Authenticate()).
"""
import argparse
import math
import sys
from pathlib import Path

import ee

CLOUD_MAX = 60  # scene-level cloud filter, as last year

# ---------------------------------------------------------------- Sentinel-2

S2 = 'COPERNICUS/S2_SR_HARMONIZED'
# Scene classification (SCL): 1 saturated, 2 dark, 3 cloud shadow, 4 vegetation, 5 bare,
# 6 water, 7 unclassified, 8 and 9 cloud, 10 thin cirrus, 11 snow or ice
LEGACY_MASKED = [3, 8, 9, 10, 11]
V2_MASKED = [1, 2, 3, 6, 8, 9, 10, 11]


def mask_scl(classes):
    def apply(img):
        bad = img.select('SCL').remap(classes, [1] * len(classes), 0)
        return img.updateMask(bad.Not())
    return apply


def legacy_indices(img):
    ndvi = img.normalizedDifference(['B8', 'B4']).rename('NDVI')
    ndwi = img.normalizedDifference(['B3', 'B11']).rename('NDWI')  # really MNDWI, kept as last year
    return img.addBands(ndvi).addBands(ndwi)


def s2_prepare(img):
    """Mask, scale to reflectance (0 to 1) and rename to common band names."""
    img = mask_scl(V2_MASKED)(img)
    refl = img.select(['B2', 'B3', 'B4', 'B8', 'B11', 'B12'],
                      ['blue', 'green', 'red', 'nir', 'swir1', 'swir2']).divide(10000)
    return refl.copyProperties(img, ['system:time_start'])


def s2_collection(region, start, end):
    return (ee.ImageCollection(S2).filterBounds(region).filterDate(start, end)
            .filter(ee.Filter.lt('CLOUD_COVERAGE_ASSESSMENT', CLOUD_MAX)))

# ---------------------------------------------------------------- Landsat

LANDSAT = {
    # collection: (surface reflectance bands as blue, green, red, nir, swir1, swir2; adjust to OLI?)
    'LANDSAT/LT05/C02/T1_L2': (['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B7'], True),
    'LANDSAT/LE07/C02/T1_L2': (['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B7'], True),
    'LANDSAT/LC08/C02/T1_L2': (['SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6', 'SR_B7'], False),
    'LANDSAT/LC09/C02/T1_L2': (['SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6', 'SR_B7'], False),
}
# Landsat 7 ETM+ to Landsat 8 OLI surface reflectance, ordinary least squares (Roy et al. 2016,
# Remote Sensing of Environment 185: 57-70), as used in Earth Engine's harmonization tutorial.
# Applied to Landsat 5 TM too, which is the usual approximation. Check the numbers against the
# paper before the final report.
ROY_SLOPE = [0.8474, 0.8483, 0.9047, 0.8462, 0.8937, 0.9071]
ROY_INTERCEPT = [0.0003, 0.0088, 0.0061, 0.0412, 0.0254, 0.0172]
# QA_PIXEL bits: 0 fill, 1 dilated cloud, 2 cirrus, 3 cloud, 4 cloud shadow, 5 snow, 7 water
QA_BAD = (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4) | (1 << 5) | (1 << 7)
BANDS = ['blue', 'green', 'red', 'nir', 'swir1', 'swir2']


def landsat_prepare(bands, adjust):
    def apply(img):
        ok = img.select('QA_PIXEL').bitwiseAnd(QA_BAD).eq(0).And(img.select('QA_RADSAT').eq(0))
        refl = img.select(bands, BANDS).multiply(0.0000275).add(-0.2)
        if adjust:
            refl = refl.multiply(ee.Image.constant(ROY_SLOPE)).add(ee.Image.constant(ROY_INTERCEPT)).rename(BANDS)
        return refl.updateMask(ok).copyProperties(img, ['system:time_start'])
    return apply


def landsat_collection(region, start, end):
    merged = None
    for name, (bands, adjust) in LANDSAT.items():
        col = (ee.ImageCollection(name).filterBounds(region).filterDate(start, end)
               .filter(ee.Filter.lt('CLOUD_COVER', CLOUD_MAX))
               .map(landsat_prepare(bands, adjust)))
        merged = col if merged is None else merged.merge(col)
    return merged

# ---------------------------------------------------------------- shared


def v2_indices(img):
    nir, red = img.select('nir'), img.select('red')
    ndvi = img.normalizedDifference(['nir', 'red']).rename('NDVI')
    ndwi = img.normalizedDifference(['nir', 'swir1']).rename('NDWI')
    mndwi = img.normalizedDifference(['green', 'swir1']).rename('MNDWI')
    savi = nir.subtract(red).multiply(1.5).divide(nir.add(red).add(0.5)).rename('SAVI')
    return ee.Image.cat([ndvi, ndwi, mndwi, savi]).copyProperties(img, ['system:time_start'])


def utm_for(fc):
    """EPSG code of the UTM zone at the centre of the first 500 polygons (Texas spans 13 to 15).

    Run one ecoregion or one chunk at a time so one zone fits all of its polygons.
    """
    lon, lat = fc.limit(500).geometry().bounds().centroid(1).coordinates().getInfo()
    zone = int(math.floor((lon + 180) / 6)) + 1
    return f'EPSG:{32600 + zone if lat >= 0 else 32700 + zone}'


def zonal(fc, start, end, method='v2', sensor='s2', id_field='PipelineEc', composite='mean',
          crs=None, tile_scale=4):
    """One row of statistics per polygon. Returns (FeatureCollection, column names)."""
    region = fc.geometry().bounds()
    if method == 'legacy':
        col = s2_collection(region, start, end).map(mask_scl(LEGACY_MASKED)).map(legacy_indices)
        comp = col.select(['NDVI', 'NDWI']).mean()
        # Last year passed the composite's own projection, which for a composite is EPSG:4326.
        out = comp.reduceRegions(collection=fc, reducer=ee.Reducer.mean(), scale=10,
                                 crs=comp.projection().crs().getInfo())
        keep = ['PipelineEcoID', 'NDVI', 'NDWI']
        return out.map(lambda f: f.set('PipelineEcoID', ee.String(f.get(id_field)).trim()).select(keep)), keep

    if sensor == 's2':
        col, scale = s2_collection(region, start, end).map(s2_prepare), 10
    else:
        col, scale = landsat_collection(region, start, end), 30
    idx = col.map(v2_indices)
    comp = idx.median() if composite == 'median' else idx.mean()
    clear = idx.select('NDVI').count().rename('clear_images')
    reducer = ee.Reducer.mean().combine(ee.Reducer.count(), sharedInputs=True)
    out = comp.addBands(clear).reduceRegions(collection=fc, reducer=reducer, scale=scale,
                                            crs=crs or utm_for(fc), tileScale=tile_scale)
    keep = [id_field, 'NDVI_mean', 'NDWI_mean', 'MNDWI_mean', 'SAVI_mean', 'NDVI_count', 'clear_images_mean']
    extra = {'sensor': sensor, 'start': start, 'end': end, 'composite': composite}
    return out.map(lambda f: f.set(extra).select(keep + list(extra))), keep + list(extra)


def sample(fc, n, start, end, **kw):
    """Compute n random polygons now and return a pandas DataFrame. Keep n at 2,000 or below."""
    import pandas as pd
    part = fc.randomColumn('r', 392).sort('r').limit(n)
    stats, cols = zonal(part, start, end, **kw)
    rows = [f['properties'] for f in stats.getInfo()['features']]
    return pd.DataFrame(rows).reindex(columns=cols)


def export(fc, name, start, end, folder='pipeline_exports', chunk_field=None, chunks=1, **kw):
    """Start Drive export tasks, optionally split on a numeric property. Returns the tasks."""
    parts = [(None, fc)]
    if chunks > 1:
        lo, hi = fc.aggregate_min(chunk_field).getInfo(), fc.aggregate_max(chunk_field).getInfo()
        step = (hi - lo + 1) / chunks
        parts = [(i + 1, fc.filter(ee.Filter.And(ee.Filter.gte(chunk_field, lo + i * step),
                                                 ee.Filter.lt(chunk_field, lo + (i + 1) * step))))
                 for i in range(chunks)]
    tasks = []
    for n, sub in parts:
        stats, cols = zonal(sub, start, end, **kw)
        desc = name + (f'_part{n:02d}' if n else '')
        task = ee.batch.Export.table.toDrive(collection=stats, description=desc, folder=folder,
                                             fileNamePrefix=desc, fileFormat='CSV', selectors=cols)
        task.start()
        tasks.append(task)
    return tasks


def windows(years, season_start='03-01', season_end='05-01'):
    first, last = (int(y) for y in years.split('-'))
    return [(f'{y}-{season_start}', f'{y}-{season_end}') for y in range(first, last + 1)]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument('--project', required=True, help='Google Cloud project registered for Earth Engine')
    ap.add_argument('--asset', required=True, help='Earth Engine table asset holding the polygons')
    ap.add_argument('--method', choices=['legacy', 'v2'], default='v2')
    ap.add_argument('--sensor', choices=['s2', 'landsat'], default='s2', help='v2 only')
    ap.add_argument('--id-field', default='PipelineEc', help='polygon ID property (last year: PipelineEc)')
    ap.add_argument('--start', default='2025-03-01')
    ap.add_argument('--end', default='2025-05-01', help='end date, not included')
    ap.add_argument('--years', help='one spring per year, for example 2000-2026 (v2 only)')
    ap.add_argument('--season-start', default='03-01')
    ap.add_argument('--season-end', default='05-01')
    ap.add_argument('--composite', choices=['mean', 'median'], default='mean', help='v2 only')
    ap.add_argument('--crs', help='v2 only; default is the UTM zone at the centre of the polygons')
    how = ap.add_mutually_exclusive_group(required=True)
    how.add_argument('--sample', type=int, help='compute this many random polygons now')
    how.add_argument('--export', action='store_true', help='start Drive export tasks')
    ap.add_argument('--out', default='outputs/sample.csv', help='CSV path for --sample')
    ap.add_argument('--chunk-field', help='numeric property to split exports on, for example ORIG_FID')
    ap.add_argument('--chunks', type=int, default=1, help='how many export tasks per year')
    ap.add_argument('--drive-folder', default='pipeline_exports')
    args = ap.parse_args()
    if args.method == 'legacy' and (args.years or args.sensor != 's2'):
        ap.error('legacy reproduces last year: one Sentinel-2 season, no --years or --sensor')
    if args.chunks > 1 and not args.chunk_field:
        ap.error('--chunks needs --chunk-field')

    ee.Initialize(project=args.project)
    try:
        fc = ee.FeatureCollection(args.asset)
        total = fc.size().getInfo()
    except ee.EEException as e:
        sys.exit(f'Could not open {args.asset}: {e}\nCheck the asset ID, and that your account can read it.')
    print(f'{args.asset}: {total:,} polygons; method {args.method}, sensor {args.sensor}')

    kw = dict(method=args.method, sensor=args.sensor, id_field=args.id_field,
              composite=args.composite, crs=args.crs)
    spans = windows(args.years, args.season_start, args.season_end) if args.years else [(args.start, args.end)]
    for start, end in spans:
        if args.sample:
            df = sample(fc, args.sample, start, end, **kw)
            out = Path(args.out if not args.years else args.out.replace('.csv', f'_{start[:4]}.csv'))
            out.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(out, index=False)
            print(f'{start} to {end}: {len(df):,} polygons -> {out}')
        else:
            name = f'{Path(args.asset).name}_{args.method}_{args.sensor}_{start[:4]}'
            for t in export(fc, name, start, end, args.drive_folder, args.chunk_field, args.chunks, **kw):
                print(f'started {t.config["description"]} (task {t.id})')
    if args.export:
        print('Follow the tasks at https://code.earthengine.google.com/tasks or with `earthengine task list`.')


if __name__ == '__main__':
    main()
