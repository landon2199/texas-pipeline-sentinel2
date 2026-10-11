"""Where the project's files are, and the settings every script shares.

The project folder is GEOG_392\\projects in the shared Google Drive folder. On another computer, or for a test copy, set
the environment variable GEOG392_PROJECT to that folder (the MCP servers in agent/ read the same variable):
    Windows:      set GEOG392_PROJECT=D:\\my copy\\projects
    Mac or Linux: export GEOG392_PROJECT=~/projects
"""
import os
from pathlib import Path

P = Path(os.environ.get("GEOG392_PROJECT", r"C:\mydrive\Graduate School\Courses\GEOG_392\projects"))
R = P / "outputs" / "results"                     # analysis results, one folder per step
Z = P / "outputs" / "zones"                       # zones, samples and their upload tables
S = Z / "statewide"                               # the statewide zones (one GeoPackage per ecoregion), stations, spills
STATS = P / "outputs" / "geog392_zone_stats"      # the Earth Engine exports, as collected from Drive
AGENT = P / "outputs" / "agent"                   # the tables the agents and the dashboard read
ECOREGIONS = P / "data" / "statewide" / "ecoregions_epa_l3_texas.gpkg"

SAMPLE = Z / "sample_v1"                          # the main sample (draw_sample.py)
SUPPLEMENT = Z / "sample_v2_supplement"           # the coverage supplement (draw_supplement.py)
CORRIDOR = R / "corridor_sample_v1_9springs_pooled"            # corridor.py on the main sample, nine springs
CORRIDOR_SUPPLEMENT = R / "corridor_supplement_9springs"       # corridor.py on the supplement, nine springs

CODE = Path(__file__).resolve().parents[1]        # this repository
JOBS_LOG = CODE / "extract" / "jobs_log.csv"      # every Earth Engine job submitted (kept out of git)

EE_PROJECT = "research-476723"                    # the Google Cloud project for Earth Engine
EE_ASSETS = f"projects/{EE_PROJECT}/assets/geog392"
DRIVE_FOLDER = "geog392_zone_stats"               # Drive folder for table exports (keep exactly one with this name)
ARCPY_PYTHON = Path(os.environ.get("ARCPY_PYTHON", "C:/Program Files/ArcGIS/Pro/bin/Python/envs/arcgispro-py3/python.exe"))
