"""List every geoprocessing tool run recorded in last year's ArcGIS Pro project.

An .aprx file is a zip. Its GISProject.json keeps one record per tool run, with the tool name,
the time it ran, whether it failed, and every parameter. This script reads a copy of the .aprx
and writes audit/results/arcgis_tool_history.csv: one row per run, with input and output dataset
names shortened to the last part of their paths.

    python audit/02_tool_history.py --aprx "D:/path/to/391 Research Phase 1.aprx"

Needs only the Python standard library.
"""
import argparse
import csv
import json
import re
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

# Parameters worth keeping, by tool. Everything else is dropped to keep the table readable.
KEEP = {
    'Buffer': ['in_features', 'out_feature_class', 'buffer_distance_or_field', 'dissolve_option', 'method'],
    'Intersect': ['in_features', 'out_feature_class', 'join_attributes', 'output_type'],
    'SimplifyPolygon': ['in_features', 'out_feature_class', 'algorithm', 'tolerance', 'minimum_area',
                        'error_option', 'collapsed_point_option'],
    'Project': ['in_dataset', 'out_dataset', 'out_coor_system'],
}


def short(value):
    """'C:\\a\\b.gdb\\layer' -> 'layer'; keeps short values as they are."""
    parts = [re.split(r'[\\/]', v.strip("'"))[-1] for v in value.split(';')]
    text = ';'.join(parts)
    return text if len(text) < 300 else text[:297] + '...'


def ticks_to_time(ticks):
    return datetime(1, 1, 1) + timedelta(microseconds=int(ticks) // 10)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--aprx', required=True)
    ap.add_argument('--out', default='audit/results/arcgis_tool_history.csv')
    args = ap.parse_args()

    with zipfile.ZipFile(args.aprx) as z:
        project = json.loads(z.read('GISProject.json').decode('utf-8'))

    rows = []
    for item in project['projectItems']:
        if item.get('itemType') != 'GPHistory':
            continue
        root = ET.fromstring(item['propertiesXML'])
        tool = root.find('tool')
        name = tool.get('name') if tool is not None else item.get('name')
        params = {}
        for p in root.iter('param'):
            text = (p.text or '').strip()
            if text:
                params[p.get('name')] = text
        keep = KEEP.get(name)
        if keep:
            shown = {k: short(params[k]) if k.startswith(('in_', 'out_')) else params[k] for k in keep if k in params}
        else:
            # For other tools, keep the first input and output so the chain can be followed.
            ins = [k for k in params if k.startswith('in') and 'field' not in k]
            outs = [k for k in params if k.startswith('out') and 'field' not in k]
            shown = {k: short(params[k]) for k in (ins[:1] + outs[:1])}
            for k in ('expression', 'where_clause', 'field', 'field_name'):
                if k in params:
                    shown[k] = params[k][:200]
        messages = [m.text or '' for m in root.iter('msg')]
        warn = [m for m in messages if re.search(r'WARNING|ERROR|failure', m)]
        rows.append({
            'time': ticks_to_time(root.get('ticks')).strftime('%Y-%m-%d %H:%M'),
            'tool': name,
            'failed': root.get('has_error') == 'true',
            'parameters': json.dumps(shown, ensure_ascii=False),
            'warnings_or_errors': ' || '.join(sorted(set(re.sub(r'\d+', '#', w)[:160] for w in warn)))[:600],
        })

    rows.sort(key=lambda r: r['time'])
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f'{len(rows)} tool runs from {rows[0]["time"]} to {rows[-1]["time"]} -> {out}')


if __name__ == '__main__':
    main()
