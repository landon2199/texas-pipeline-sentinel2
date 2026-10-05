"""Count PHMSA hazardous liquid pipeline accidents in Texas and check how many could be studied.

PHMSA (the federal Pipeline and Hazardous Materials Safety Administration) publishes every
reported hazardous liquid pipeline accident since 2010. This script reads that table, keeps the
onshore Texas accidents with usable coordinates, and reports:

  - how many there are by year, by what spilled, and by where on the system they happened
  - how many sat on the pipeline right-of-way rather than inside a station or tank farm
  - how many lie within 100, 250 and 500 m of a Railroad Commission pipeline line
  - which EPA Level III ecoregion each one falls in

Download the zip by hand (the site blocks scripts): https://www.phmsa.dot.gov/data-and-statistics/
pipeline/distribution-transmission-gathering-lng-and-liquid-accident-and-incident-data, the link
"Hazardous Liquid Accident Data - January 2010 to present (ZIP)". Unzip it, then:

    python leaks/phmsa_texas.py --phmsa "PATH/accident_hazardous_liquid_jan2010_present.txt" \\
        --gdb "PATH/391 Research Phase 1/391 Research Phase 1.gdb"

Writes small summary tables to leaks/results/ and the Texas accident points, without any personal
names, to outputs/phmsa_texas_accidents.gpkg (ignored by Git).
"""
import argparse
import warnings
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio

warnings.filterwarnings('ignore', message='.*GDAL_DATA.*')
EQUAL_AREA = 6579  # NAD83(2011) Texas Centric Albers Equal Area, metres
KEEP = ['REPORT_NUMBER', 'IYEAR', 'LOCAL_DATETIME', 'NAME', 'LOCATION_LATITUDE', 'LOCATION_LONGITUDE',
        'COMMODITY_RELEASED_TYPE', 'UNINTENTIONAL_RELEASE_BBLS', 'RECOVERED_BBLS', 'SYSTEM_PART_INVOLVED',
        'LOCATION_TYPE', 'ONSHORE_COUNTY_NAME', 'ITEM_INVOLVED', 'PIPE_DIAMETER', 'INSTALLATION_YEAR',
        'SOIL_CONTAMINATION', 'WATER_CONTAM_IND', 'CAUSE', 'CAUSE_DETAILS']


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--phmsa', required=True, help='the unzipped tab-separated accident table')
    ap.add_argument('--gdb', required=True, help="last year's geodatabase, for the pipeline lines and ecoregions")
    ap.add_argument('--lines', default='pipe235_merge_final_250', help='layer with every Railroad Commission line')
    ap.add_argument('--out', default='leaks/results')
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    raw = pd.read_csv(args.phmsa, sep='\t', encoding='latin-1', low_memory=False, dtype=str)
    keep = [c for c in KEEP if c in raw.columns]
    tx = raw[(raw['ONSHORE_STATE_ABBREVIATION'] == 'TX') & (raw['ON_OFF_SHORE'] == 'ONSHORE')][keep].copy()
    for c in ['LOCATION_LATITUDE', 'LOCATION_LONGITUDE', 'UNINTENTIONAL_RELEASE_BBLS', 'RECOVERED_BBLS', 'IYEAR']:
        tx[c] = pd.to_numeric(tx[c], errors='coerce')
    in_texas = tx['LOCATION_LATITUDE'].between(25.8, 36.6) & tx['LOCATION_LONGITUDE'].between(-106.7, -93.5)
    print(f'{len(raw):,} accidents nationwide since 2010; {len(tx):,} onshore in Texas; '
          f'{in_texas.sum():,} with coordinates inside Texas')
    tx = tx[in_texas]
    pts = gpd.GeoDataFrame(tx, geometry=gpd.points_from_xy(tx['LOCATION_LONGITUDE'], tx['LOCATION_LATITUDE']),
                           crs=4326).to_crs(EQUAL_AREA)

    # Distance from each accident to the nearest Railroad Commission line.
    lines = pyogrio.read_dataframe(args.gdb, layer=args.lines, columns=['CMDTY_DESC', 'DIAMETER'],
                                   use_arrow=True).to_crs(EQUAL_AREA)
    near = gpd.sjoin_nearest(pts, lines, how='left', max_distance=5000, distance_col='m_to_line')
    near = near[~near.index.duplicated()]
    pts['m_to_line'] = near['m_to_line']
    pts['nearest_line_commodity'] = near['CMDTY_DESC']

    eco = pyogrio.read_dataframe(args.gdb, layer='ECOREGIONSWGS1984', columns=['US_L3NAME'],
                                 use_arrow=True).to_crs(EQUAL_AREA)
    pts = gpd.sjoin(pts, eco, how='left', predicate='within').drop(columns='index_right')
    pts = pts[~pts.index.duplicated()]

    row = pts['LOCATION_TYPE'].fillna('').str.contains('RIGHT-OF-WAY', case=False)
    line_part = pts['SYSTEM_PART_INVOLVED'].fillna('').str.contains('PIPELINE', case=False)
    big = pts['UNINTENTIONAL_RELEASE_BBLS'] >= 5
    rows = []
    for label, m in [('all onshore Texas accidents with coordinates', slice(None)),
                     ('on the pipeline right-of-way', row),
                     ('on the right-of-way, line pipe or pipe parts', row & line_part),
                     ('on the right-of-way, 5 barrels or more', row & big)]:
        d = pts.loc[m, 'm_to_line']
        rows.append({'group': label, 'accidents': int(len(d)), 'within_100m_of_a_rrc_line': int((d <= 100).sum()),
                     'within_250m': int((d <= 250).sum()), 'within_500m': int((d <= 500).sum())})
    summary = pd.DataFrame(rows)
    summary.to_csv(out / 'phmsa_texas_summary.csv', index=False)
    print('\n' + summary.to_string(index=False))

    def table(col, name):
        t = pts.groupby(col, dropna=False).size().rename('accidents').sort_values(ascending=False)
        t.to_csv(out / f'phmsa_texas_by_{name}.csv')
        print(f'\nby {name}:\n' + t.head(15).to_string())
    table('IYEAR', 'year')
    table('COMMODITY_RELEASED_TYPE', 'commodity')
    table('SYSTEM_PART_INVOLVED', 'system_part')
    table('LOCATION_TYPE', 'location_type')
    table('US_L3NAME', 'ecoregion')
    table('CAUSE', 'cause')
    print('\nrelease size (barrels), right-of-way accidents:')
    print(pts.loc[row, 'UNINTENTIONAL_RELEASE_BBLS'].describe(percentiles=[.25, .5, .75, .9]).round(1).to_string())

    Path('outputs').mkdir(exist_ok=True)
    pts.drop(columns=[c for c in pts.columns if c.endswith('_NAME') and c != 'ONSHORE_COUNTY_NAME' and c != 'US_L3NAME']
             ).to_file('outputs/phmsa_texas_accidents.gpkg', driver='GPKG')


if __name__ == '__main__':
    main()
