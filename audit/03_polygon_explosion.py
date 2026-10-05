"""Find out why 16,303 pipeline lines became millions of polygons, and what that did to the results.

Reads last year's geodatabase (read-only) and writes three small tables to audit/results/:

  polygon_counts.csv          features at each step: lines, buffers, ecoregion intersect,
                              Simplify Polygon output and the polygons it removed
  recut_test.csv              for a sample of 100 m buffers: how many pieces ArcGIS made, and how
                              many distinct patterns of overlap with other pipelines' buffers the
                              buffer has. If the two numbers match, overlaps caused the pieces.
  final_100m_coverage.csv     pieces and area of the final 100 m layer, split by why a piece has
                              a value or not

    python audit/03_polygon_explosion.py --gdb "D:/path/to/391 Research Phase 1.gdb" --sample 25

Needs pandas, numpy, shapely 2 and pyogrio. Takes a few minutes.
"""
import argparse
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio
import shapely
from shapely.ops import polygonize, unary_union

warnings.filterwarnings('ignore', message='.*GDAL_DATA.*')

LINES = 'hydrocarbonsliquids_WGS1984Project'
STEPS = {
    '100m': ('hydrocarbonsliquids_DiameterClasses100m_Buffer',
             'hydrocarbonsliquid_DiameterClass100mBuffer_EcoIntersect',
             'hydrocarbonsliquid_DiameterClass100mBuffer_EcoIntersect_SimplifiedPolygon'),
    '250m': ('hydrocarbonsliquids_DiameterClasses_250mBuffer',
             'hydrocarbonsliquid_DiameterClass250mBuffer_EcoIntersect',
             'hydrocarbonsliquid_DiameterClass250mBuffer_EcoIntersect_simplifiedpolygon'),
    '500m': ('hydrocarbonsliquids_DiameterClasses_500mBuffer',
             'hydrocarbonsliquid_DiameterClass500mBuffer_EcoIntersect',
             'hydrocarbonsliquid_DiameterClass500mBuffer_EcoIntersect_simplifiedpolygon'),
}
FINAL_100M = 'MergedLayer_Hydrocarbons_100m_Masterlayer'
# One square degree is about 1.0547e10 square metres at 31 N, the middle of Texas. Good enough to
# sort pieces into "smaller than a 30 m by 30 m square" or not; not good enough for real areas.
SQ_DEG_TO_M2 = 1.0547e10


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--gdb', required=True)
    ap.add_argument('--sample', type=int, default=25, help='how many 100 m buffers to re-cut')
    ap.add_argument('--out', default='audit/results')
    args = ap.parse_args()
    gdb, out = args.gdb, Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    def count(layer):
        return pyogrio.read_info(gdb, layer=layer)['features']

    def attrs(layer, cols):
        return pyogrio.read_dataframe(gdb, layer=layer, columns=cols, read_geometry=False,
                                      use_arrow=True, fid_as_index=True)

    # 1. Feature counts along each chain, and how much area Simplify Polygon removed.
    rows = []
    for dist, (buf, inter, simp) in STEPS.items():
        a = attrs(inter, ['Shape_Area'])['Shape_Area']
        b = attrs(simp, ['Shape_Area'])['Shape_Area']
        small = a * SQ_DEG_TO_M2 < 900
        rows.append({
            'distance': dist,
            'pipeline_lines': count(LINES),
            'buffers': count(buf),
            'after_ecoregion_intersect': len(a),
            'after_simplify': len(b),
            'removed_by_simplify_kept_as_points': count(simp + '_Pnt'),
            'pct_of_pieces_kept': round(100 * len(b) / len(a), 1),
            'pct_of_area_kept': round(100 * b.sum() / a.sum(), 2),
            'pieces_under_900m2_before_simplify': int(small.sum()),
            'pct_of_area_in_those_pieces': round(100 * a[small].sum() / a.sum(), 2),
        })
    counts = pd.DataFrame(rows)
    counts.to_csv(out / 'polygon_counts.csv', index=False)
    print(counts.T.to_string(), '\n')

    # 2. Pieces per buffer at 100 m, and whether ecoregion boundaries explain them.
    fid = 'FID_' + STEPS['100m'][0]
    ix = attrs(STEPS['100m'][1], [fid, 'FID_ECOREGIONSWGS1984'])
    per = ix.groupby(fid).size()
    combos = ix.groupby([fid, 'FID_ECOREGIONSWGS1984']).ngroups
    print(f'100 m: {per.size:,} buffers cut into {len(ix):,} pieces; median {per.median():.0f} per buffer, '
          f'largest {per.max():,}. Buffer-and-ecoregion combinations: {combos:,}.')

    # 3. Re-cut a random sample of buffers by the outlines of every other buffer they touch.
    buffers = pyogrio.read_dataframe(gdb, layer=STEPS['100m'][0], columns=[], use_arrow=True, fid_as_index=True)
    eco = pyogrio.read_dataframe(gdb, layer='ECOREGIONSWGS1984', columns=[], use_arrow=True)
    geoms = buffers.geometry.values
    tree = shapely.STRtree(geoms)
    rng = np.random.default_rng(392)
    pool = per[per < 400].index.to_numpy()
    test = []
    for b in rng.choice(pool, min(args.sample, len(pool)), replace=False):
        B = buffers.geometry.loc[b]
        others = [geoms[i] for i in tree.query(B, predicate='intersects') if buffers.index[i] != b]
        cuts = [B.boundary] + [o.boundary for o in others] + [e.boundary for e in eco.geometry if e.intersects(B)]
        faces = [f for f in polygonize(unary_union(cuts)) if B.contains(f.representative_point())]
        patterns = {tuple(i for i, o in enumerate(others) if o.contains(f.representative_point())) for f in faces}
        test.append({'buffer': int(b), 'arcgis_pieces': int(per[b]), 'other_buffers_touching': len(others),
                     'overlap_patterns': len(patterns), 'faces': len(faces)})
    test = pd.DataFrame(test)
    test['match'] = test['arcgis_pieces'] == test['overlap_patterns']
    test.to_csv(out / 'recut_test.csv', index=False)
    print(f'Re-cut test: pieces equal overlap patterns for {test["match"].sum()} of {len(test)} buffers; '
          f'median gap {(test["arcgis_pieces"] - test["overlap_patterns"]).abs().median():.0f}.\n')

    # 4. The final 100 m layer: which pieces got a value, and why the others did not.
    f = attrs(FINAL_100M, ['PipelineEcoID', 'ECOREGION_GROUP', 'NDVI_12', 'Shape_Area'])
    f['number'] = f['PipelineEcoID'].str.extract(r'^(\d+)_')[0].astype(int)
    plains = f['ECOREGION_GROUP'] == 'Plains'
    # Plains pieces were written to the shapefile in ID order until the attribute table hit 2 GB.
    # Everything after the last Plains piece that came back from Earth Engine was never sent.
    cutoff = f.loc[plains & f['NDVI_12'].notna(), 'number'].max()
    f['state'] = np.select(
        [f['NDVI_12'].notna(), f['ECOREGION_GROUP'].str.startswith('SEMI'), plains & (f['number'] > cutoff)],
        ['has a value', 'join failed: ID spelled differently in the table', 'never sent: shapefile hit 2 GB'],
        default='blank: Earth Engine returned no value')
    cov = f.groupby('state').agg(pieces=('number', 'size'), area=('Shape_Area', 'sum'))
    cov['pct_of_pieces'] = (100 * cov['pieces'] / cov['pieces'].sum()).round(1)
    cov['pct_of_area'] = (100 * cov['area'] / cov['area'].sum()).round(1)
    cov.drop(columns='area').to_csv(out / 'final_100m_coverage.csv')
    print(cov.drop(columns='area').to_string())


if __name__ == '__main__':
    main()
