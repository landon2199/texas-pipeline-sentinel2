"""Compare this program's legacy-method results with last year's Earth Engine table.

Joins the two tables on PipelineEcoID (spaces and underscores after the number are treated as
the same) and reports how closely NDVI and the water index agree. Writes nothing; prints a report.

    python extract/compare_with_2025.py outputs/legacy_deserts_250m_sample.csv \\
        "PATH/391 Research Phase 1/Hydrocarbon_Diameter_eco_250m/hydrocarbons_Deserts_250m.csv"

"""
import argparse
import re

import numpy as np
import pandas as pd


def load(path):
    df = pd.read_csv(path, dtype={'PipelineEcoID': str})
    df['id'] = df['PipelineEcoID'].str.strip().str.replace(r'^(\d+)[ _]', r'\1_', regex=True)
    return df.set_index('id')[['NDVI', 'NDWI']]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('new', help='CSV written by indices.py --method legacy')
    ap.add_argument('old', help="last year's CSV for the same polygons")
    ap.add_argument('--tolerance', type=float, default=0.01, help='difference counted as a match')
    args = ap.parse_args()

    new, old = load(args.new), load(args.old)
    both = new.join(old, lsuffix='_new', rsuffix='_2025', how='inner')
    print(f'{len(new):,} new rows, {len(both):,} found in last year\'s table')
    if both.empty:
        print('No IDs in common. Check that both tables describe the same polygons.')
        return
    for band in ['NDVI', 'NDWI']:
        a, b = both[f'{band}_new'], both[f'{band}_2025']
        ok = a.notna() & b.notna()
        d = (a[ok] - b[ok]).abs()
        print(f'\n{band}: {ok.sum():,} pairs with values on both sides')
        print(f'  correlation {np.corrcoef(a[ok], b[ok])[0, 1]:.5f}')
        print(f'  difference: median {d.median():.5f}, 95th percentile {d.quantile(.95):.5f}, largest {d.max():.5f}')
        print(f'  within {args.tolerance}: {(d <= args.tolerance).mean():.1%}')
        print(f'  blank only in new: {(a.isna() & b.notna()).sum():,}; blank only in 2025: {(a.notna() & b.isna()).sum():,}')


if __name__ == '__main__':
    main()
