"""Figure 1 of the revised proposal: reported spills on a map of Texas pipelines, and the zone design.

    python leaks/figure_proposal.py --gdb "PATH/391 Research Phase 1/391 Research Phase 1.gdb"

Needs outputs/phmsa_texas_accidents.gpkg from leaks/phmsa_texas.py. Writes outputs/figure1_proposal.png.
"""
import argparse
import warnings

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyogrio
from matplotlib.patches import Circle, Rectangle

warnings.filterwarnings('ignore', message='.*GDAL_DATA.*')
EQUAL_AREA = 6579
SPILL, EARLY = '#7b1f2b', '#d9b3b8'
INK, LINES = '#222222', '#9a9a9a'
S2_START = '2018-06-01'  # a full year of Sentinel-2 surface reflectance over Texas exists before this date


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--gdb', required=True)
    ap.add_argument('--out', default='outputs/figure1_proposal.png')
    args = ap.parse_args()

    eco = pyogrio.read_dataframe(args.gdb, layer='ECOREGIONSWGS1984', columns=['US_L3NAME']).to_crs(EQUAL_AREA)
    lines = pyogrio.read_dataframe(args.gdb, layer='pipe235_merge_final_250', columns=[], use_arrow=True).to_crs(EQUAL_AREA)
    pts = gpd.read_file('outputs/phmsa_texas_accidents.gpkg')
    keep = (pts['LOCATION_TYPE'].fillna('').str.contains('RIGHT-OF-WAY')
            & pts['COMMODITY_RELEASED_TYPE'].fillna('').str.contains('CRUDE|REFINED|BIOFUEL')
            & (pts['UNINTENTIONAL_RELEASE_BBLS'] >= 5))
    spills = pts[keep].to_crs(EQUAL_AREA)
    recent = pd.to_datetime(spills['LOCAL_DATETIME'], errors='coerce') >= S2_START

    fig = plt.figure(figsize=(6.4, 2.75), dpi=250)
    ax = fig.add_axes([0.0, 0.0, 0.5, 0.88])
    lines.plot(ax=ax, color=LINES, linewidth=0.12, alpha=0.35, rasterized=True)
    eco.boundary.plot(ax=ax, color='#555555', linewidth=0.45)
    size = lambda s: 6 + 10 * np.log10(s['UNINTENTIONAL_RELEASE_BBLS'].clip(lower=5) / 5)
    early = spills[~recent]
    early.plot(ax=ax, color=EARLY, markersize=size(early), edgecolor='white', linewidth=0.3, zorder=4)
    late = spills[recent]
    late.plot(ax=ax, color=SPILL, markersize=size(late), alpha=0.9, edgecolor='white', linewidth=0.3, zorder=5)
    x0, y0, x1, y1 = eco.total_bounds  # frame Texas itself, so the title sits on the map
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    # Without this, the hidden y axis keeps a "1e6" offset label at the top left, which pushes the title up.
    ax.ticklabel_format(style='plain', useOffset=False)
    ax.set_axis_off()
    ax.set_title(f'a. Right-of-way spills of 5+ barrels\n'
                 f'dark: {recent.sum()} since mid-2018; light: {(~recent).sum()} earlier',
                 fontsize=8, color=INK, loc='left', pad=1)
    for bbl in (5, 100, 1000, 10000):
        ax.scatter([], [], s=6 + 10 * np.log10(bbl / 5), color=SPILL, edgecolor='white', linewidth=0.3, label=f'{bbl:,} bbl')
    ax.legend(loc='lower left', fontsize=7, frameon=False, handletextpad=0.2, borderaxespad=0.0, title='Spill size',
              title_fontsize=7.2, labelspacing=0.3)

    # b. The zones, drawn as a schematic: equal-height bands so the narrow rings can be read.
    bx = fig.add_axes([0.53, 0.0, 0.47, 0.88], anchor='N')  # top-aligned with panel a, so the titles line up
    bands = [('500 to 1,000 m: comparison', '#e9e4d8'), ('250 to 500 m', '#e4ecdc'), ('100 to 250 m', '#d6e6ca'),
             ('50 to 100 m', '#c6ddb4'), ('0 to 50 m: right-of-way', '#b0d29b')]
    h = 1.0
    for i, (label, colour) in enumerate(bands):
        y = (len(bands) - 1 - i) * h
        for sign in (1, -1):
            bx.add_patch(Rectangle((0, sign * y if sign > 0 else -y - h), 10, h, facecolor=colour,
                                   edgecolor='white', linewidth=0.6))
        bx.text(10.2, y + h / 2, label, fontsize=6.8, va='center', color=INK)
    bx.plot([0, 10], [0, 0], color=INK, linewidth=1.6)
    for x in (1.0, 9.0):
        bx.plot([x, x], [-0.25, 0.25], color=INK, linewidth=0.8)
    bx.text(2.6, -0.62, '1 km segment', fontsize=6.6, color=INK, ha='center', va='top')
    bx.add_patch(Circle((5.0, 0), 0.62, facecolor='none', edgecolor=SPILL, linewidth=0.9))
    bx.add_patch(Circle((5.0, 0), 0.31, facecolor=SPILL, edgecolor='white', linewidth=0.5, alpha=0.9, zorder=5))
    bx.text(5.0, 0.72, 'spill zones:\n50 and 100 m', fontsize=6.6, color=SPILL, ha='center', va='bottom')
    for x in (2.2, 7.8):
        bx.add_patch(Circle((x, 0), 0.31, facecolor='white', edgecolor=INK, linewidth=0.8, zorder=5))
    bx.text(7.8, -0.5, 'controls on\nthe same line', fontsize=6.6, color=INK, ha='center', va='top')
    bx.set_xlim(0, 16.2)
    bx.set_ylim(-5.15, 5.15)
    bx.set_aspect('equal')
    bx.set_axis_off()
    bx.set_title('b. Zones around each segment (not to scale)', fontsize=8, color=INK, loc='left', pad=1)
    fig.savefig(args.out, dpi=250, bbox_inches='tight', pad_inches=0.02, facecolor='white')
    print('wrote', args.out, '|', len(spills), 'spills,', int(recent.sum()), 'since', S2_START)


if __name__ == '__main__':
    main()
