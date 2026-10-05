"""Audit last year's Earth Engine result tables.

Reads every CSV in the three Hydrocarbon_Diameter_eco_<distance> folders of the 2025 project and
answers four questions:

  1. How many rows, blank rows and duplicate IDs does each table have?
  2. Were rows lost when the per-ecoregion tables were combined into the "master" tables?
  3. Do the tables match the shapefiles that were uploaded to Earth Engine?
  4. Do IDs line up between the 100, 250 and 500 m buffers?

It only reads the data folder. Results go to audit/results/ as small CSV files plus one
Markdown summary of the numbers.

Run it from the repository folder:

    python audit/01_audit_tables.py --data "D:/path/to/391 Research Phase 1"

Needs pandas.
"""
import argparse
import re
import struct
from pathlib import Path

import pandas as pd

ID = 'PipelineEcoID'


def norm_id(s):
    """'2347 Deserts' and '2347_Deserts' are the same piece; write both as '2347_Deserts'."""
    return re.sub(r'^(\d+)[ _]', r'\1_', s.strip())


def read_table(path):
    df = pd.read_csv(path, dtype={ID: str}, keep_default_na=True)
    df[ID] = df[ID].fillna('')
    df['id'] = df[ID].map(norm_id)
    df['oid'] = df['id'].str.extract(r'^(\d+)_')[0]
    df['region'] = df['id'].str.replace(r'^\d+_', '', regex=True)
    return df


def kind_of(name):
    """A table is either one ecoregion's export or a combination of several."""
    return 'combined' if re.search(r'combined|master', name, re.I) else 'region'


def table_stats(path, df):
    sep = df[ID].str.extract(r'^\d+([ _])')[0]
    blank = df['NDVI'].isna() | df['NDWI'].isna()
    return {
        'distance': path.parent.name.rsplit('_', 1)[-1],
        'file': path.name,
        'kind': kind_of(path.name),
        'bytes': path.stat().st_size,
        'rows': len(df),
        'regions': ' | '.join(f'{k}: {v}' for k, v in df['region'].value_counts().items()),
        'blank_rows': int(blank.sum()),
        'blank_pct': round(100 * blank.mean(), 2) if len(df) else 0,
        'duplicate_ids': int(df['id'].duplicated().sum()),
        'ids_with_space': int((sep == ' ').sum()),
        'ids_with_underscore': int((sep == '_').sum()),
        'ndvi_min': df['NDVI'].min(),
        'ndvi_mean': df['NDVI'].mean(),
        'ndvi_max': df['NDVI'].max(),
        'ndwi_min': df['NDWI'].min(),
        'ndwi_mean': df['NDWI'].mean(),
        'ndwi_max': df['NDWI'].max(),
        'longest_number': int(df['NDVI'].dropna().astype(str).str.len().max()) if df['NDVI'].notna().any() else 0,
    }


def lineage(distance, combined_name, combined, parts):
    """Compare one combined table with the per-ecoregion tables, ID by ID."""
    rows = []
    in_parts = set()
    for part_name, part in parts.items():
        in_parts |= set(part['id'])
        both = combined.merge(part, on='id', suffixes=('_c', '_p'))
        diff = (both['NDVI_c'] - both['NDVI_p']).abs().max() if len(both) else float('nan')
        rows.append({
            'distance': distance, 'combined': combined_name, 'region_table': part_name,
            'region_rows': len(part), 'found_in_combined': part['id'].isin(combined['id']).sum(),
            'missing_from_combined': (~part['id'].isin(combined['id'])).sum(),
            'largest_ndvi_difference': diff,
        })
    rows.append({
        'distance': distance, 'combined': combined_name, 'region_table': '(all region tables together)',
        'region_rows': sum(len(p) for p in parts.values()), 'found_in_combined': combined['id'].isin(in_parts).sum(),
        'missing_from_combined': len(in_parts - set(combined['id'])),
        'largest_ndvi_difference': float('nan'),
        'combined_rows': len(combined), 'combined_rows_in_no_region_table': (~combined['id'].isin(in_parts)).sum(),
    })
    return rows


def shapefile_counts(shp):
    """Feature counts straight from the file headers, without loading any geometry."""
    out = {'distance': shp.parent.parent.name.rsplit('_', 1)[-1], 'shapefile': f'{shp.parent.name}/{shp.name}'}
    shx, dbf = shp.with_suffix('.shx'), shp.with_suffix('.dbf')
    out['shapes_in_shx'] = (shx.stat().st_size - 100) // 8 if shx.exists() else None
    if dbf.exists():
        with open(dbf, 'rb') as f:
            head = f.read(32)
            n, header_len, record_len = struct.unpack('<IHH', head[4:12])
            fields = []
            while True:
                d = f.read(32)
                if not d or d[0] == 0x0D:
                    break
                fields.append(d[:11].split(b'\0')[0].decode('ascii', 'replace'))
        size = dbf.stat().st_size
        out.update({
            'records_in_dbf_header': n, 'dbf_bytes': size, 'dbf_record_bytes': record_len,
            # A complete table is header + records (+ one end byte). Fewer bytes means it was cut off.
            'records_that_fit_in_file': (size - header_len) // record_len,
            'dbf_fields': ' '.join(fields),
        })
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--data', required=True, help='folder holding Hydrocarbon_Diameter_eco_100m, _250m and _500m')
    ap.add_argument('--out', default='audit/results', help='where to write the result files')
    args = ap.parse_args()
    data, out = Path(args.data), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    stats, lin, shapes, region_ids = [], [], [], {}
    for folder in sorted(data.glob('Hydrocarbon_Diameter_eco_*')):
        distance = folder.name.rsplit('_', 1)[-1]
        tables = {p.name: read_table(p) for p in sorted(folder.glob('*.csv'))}
        for p in sorted(folder.glob('*.csv')):
            stats.append(table_stats(p, tables[p.name]))
        parts = {n: t for n, t in tables.items() if kind_of(n) == 'region'}
        for name, t in tables.items():
            if kind_of(name) == 'combined':
                lin += lineage(distance, name, t, parts)
        region_ids[distance] = pd.concat(parts.values())[['id', 'oid', 'region']] if parts else pd.DataFrame()
        shapes += [shapefile_counts(s) for s in sorted(folder.glob('*/*.shp'))]

    stats = pd.DataFrame(stats)
    lin = pd.DataFrame(lin)
    shapes = pd.DataFrame(shapes)

    # Match each uploaded shapefile to the table Earth Engine returned for it, by ecoregion name.
    def region_key(text):
        t = re.sub(r'[^a-z]', '', text.lower()).replace('desserts', 'deserts')
        for key in ('semiaridprairies', 'semiaridplains', 'deserts', 'plains'):
            if key in t:
                return key
    stats['region_key'] = [region_key(f) if k == 'region' else None for f, k in zip(stats['file'], stats['kind'])]
    shapes['region_key'] = shapes['shapefile'].map(lambda s: region_key(s.split('/')[0]))
    shapes = shapes.merge(
        stats.loc[stats['kind'] == 'region', ['distance', 'region_key', 'file', 'rows']]
             .rename(columns={'file': 'result_table', 'rows': 'result_rows'}),
        on=['distance', 'region_key'], how='left')
    shapes['rows_minus_shapes'] = shapes['result_rows'] - shapes['shapes_in_shx']

    # Do the same IDs appear at two distances? If IDs were stable, nearly all would.
    cross = []
    dists = sorted(region_ids, key=lambda d: int(re.sub(r'\D', '', d)))
    for i, a in enumerate(dists):
        for b in dists[i + 1:]:
            A, B = region_ids[a], region_ids[b]
            for region in sorted(set(A['region']) | set(B['region'])):
                ia, ib = set(A.loc[A['region'] == region, 'id']), set(B.loc[B['region'] == region, 'id'])
                cross.append({'region': region, 'a': a, 'b': b, 'ids_a': len(ia), 'ids_b': len(ib), 'ids_in_both': len(ia & ib)})
    cross = pd.DataFrame(cross)

    stats.drop(columns='region_key').to_csv(out / 'tables_per_file.csv', index=False)
    lin.to_csv(out / 'tables_lineage.csv', index=False)
    shapes.drop(columns='region_key').to_csv(out / 'tables_vs_shapefiles.csv', index=False)
    cross.to_csv(out / 'ids_across_distances.csv', index=False)

    def md(df, cols):
        """A Markdown table of the chosen columns."""
        def cell(v):
            if pd.isna(v):
                return ''
            return f'{v:.4g}' if isinstance(v, float) else f'{v:,}' if isinstance(v, int) else str(v)
        lines = ['| ' + ' | '.join(cols) + ' |', '|' + '---|' * len(cols)]
        for row in df[cols].itertuples(index=False):
            lines.append('| ' + ' | '.join(cell(v) for v in row) + ' |')
        return '\n'.join(lines)

    text = [
        '# Audit of the 2025 result tables: the numbers', '',
        'Written by `audit/01_audit_tables.py`. Do not edit by hand; rerun the script.', '',
        '## Every table', '',
        md(stats, ['distance', 'file', 'kind', 'rows', 'blank_rows', 'blank_pct', 'duplicate_ids',
                   'ids_with_space', 'ids_with_underscore', 'longest_number']), '',
        '`longest_number` is the most characters used to write one NDVI value. Shorter numbers in a',
        'combined table mean the values were rounded when it was saved, which makes the file smaller',
        'without losing any rows.', '',
        '## Combined tables against the ecoregion tables they were built from', '',
        md(lin, ['distance', 'combined', 'region_table', 'region_rows', 'found_in_combined',
                 'missing_from_combined', 'largest_ndvi_difference']), '',
        '## Result tables against the shapefiles uploaded to Earth Engine', '',
        md(shapes, ['distance', 'shapefile', 'shapes_in_shx', 'records_in_dbf_header',
                    'records_that_fit_in_file', 'result_table', 'result_rows', 'rows_minus_shapes']), '',
        '`records_that_fit_in_file` below `records_in_dbf_header` means the attribute table was cut off.', '',
        '## The same ID at two distances', '',
        md(cross, ['region', 'a', 'b', 'ids_a', 'ids_b', 'ids_in_both']), '',
    ]
    (out / 'tables_audit.md').write_text('\n'.join(text), encoding='utf-8')
    print('\n'.join(text))


if __name__ == '__main__':
    main()
