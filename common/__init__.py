"""Shared helpers for the project's scripts (REFACTOR_PLAN.md).

  config   where the project's files are (GEOG392_PROJECT) and the shared settings
  stats    the design-weighted median and the stratified bootstrap
  gaps     the calibration chain: a piece's median over the springs, the calibrated gap, the weighted median
  rings    zone and ring labels: "<segment_id>_r0-50", "0-50 m", the comparison ring
  codes    pipe diameter classes and NLCD land cover names

Scripts put the repository folder on the import path and import what they need, e.g.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from common.config import P, R
"""
