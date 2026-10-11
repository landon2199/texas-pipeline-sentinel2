"""Plan v1.10, D29: the detection test. Can a single spill be flagged, and how often does a normal spot look like one?

The spill test (spills.py) shows spills lose green on average. This asks the question in the project's title for one
spill at a time. Every strictly matched spill and every one of its matched same-line spots (as a fake spill) gets the
same series: its 50 m circle minus the mean of the other sites in the same passes, median per spring (spills.py's
same_pass_springs), labeled before / during / after the real spill date. Then:
  score = (first spring after - median of the springs before) / pooled spread,
  pooled spread = 1.4826 x median absolute deviation of every site's before-springs around its own before-median.
Flagged when score <= -2. Reported: detection rate (real spills flagged), false-alarm rate (fake spills flagged), and
the ROC area (chance a real spill scores lower than a fake one), with 95% intervals from a bootstrap over spills;
for all spills, spills of 50 barrels or more, NDVI and NDRE.
Each spill's own score stays in scores_hidden_until_photo_check.csv, not to be opened before Group B's photo check.
Writes outputs/results/spill_detection/: SUMMARY.md (across spills only), roc.csv, scores_hidden_until_photo_check.csv.
Usage: python spill_detection.py [--threshold -2] [--boot 2000]
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from spills import AGENT, label, same_pass_springs  # noqa: E402

P = Path(r"C:\mydrive\Graduate School\Courses\GEOG_392\projects")
SRC = P / "outputs" / "results" / "spills_9springs"
OUT = P / "outputs" / "results" / "spill_detection"


def series(by_site, matches, spills, index):
    rows = []
    for spill_id, mine in matches[matches["kind"] == "same line"].groupby("spill_id"):
        date = pd.Timestamp(spills.loc[spill_id, "date"])
        spots = mine["site_id"].tolist()
        cases = [(f"{spill_id}_spill", spots, "spill")] + [(s, [o for o in spots if o != s], "fake") for s in spots]
        for site, others, kind in cases:
            if not others:
                continue
            t = label(same_pass_springs(by_site, site, others, index), date)
            before = t.loc[t["status"] == "before", "d"].dropna()
            first = t.loc[(t["status"] == "after") & (t["years_from_spill"] == 1), "d"].dropna()
            rows.append({"spill_id": spill_id, "site_id": site, "kind": kind, "index": index,
                         "barrels": spills.loc[spill_id, "barrels"], "springs_before": len(before),
                         "before_median": before.median() if len(before) else np.nan,
                         "first_after": first.iloc[0] if len(first) else np.nan,
                         "before_values": before.tolist()})
    return pd.DataFrame(rows)


def auc(real, fake):
    """Chance a real spill scores lower than a fake one (ties count half)."""
    if len(real) == 0 or len(fake) == 0:
        return np.nan
    r, f = np.asarray(real)[:, None], np.asarray(fake)[None, :]
    return float(((r < f).sum() + 0.5 * (r == f).sum()) / (r.size * f.size))


def rates(s, thr):
    real, fake = s[s["kind"] == "spill"], s[s["kind"] == "fake"]
    return ((real["score"] <= thr).mean(), (fake["score"] <= thr).mean(), auc(real["score"], fake["score"]),
            len(real), len(fake))


def main(a):
    passes = pd.read_parquet(SRC / "site_passes.parquet")
    matches = pd.read_csv(SRC / "matches.csv")
    spills = pd.read_parquet(AGENT / "spills.parquet").set_index("spill_id")
    by_site = {s: g.set_index(["date", "orbit"]) for s, g in passes.groupby("site_id")}
    rng = np.random.default_rng(392)
    out, rows = [], []
    for index in ("NDVI", "NDRE"):
        s = series(by_site, matches, spills, index)
        s = s[(s["springs_before"] >= 2) & s["first_after"].notna()].copy()
        dev = np.concatenate([np.abs(np.asarray(v) - m) for v, m in zip(s["before_values"], s["before_median"])])
        spread = 1.4826 * np.median(dev)
        s["score"] = (s["first_after"] - s["before_median"]) / spread
        out.append(s.drop(columns="before_values").assign(pooled_spread=spread))
        for subset, part in (("all spills", s), ("50 barrels or more", s[s["barrels"] >= 50])):
            det, fa, area, n_real, n_fake = rates(part, a.threshold)
            ids = part["spill_id"].unique()
            boot = []
            for _ in range(a.boot):
                pick = rng.choice(ids, len(ids))
                bs = pd.concat([part[part["spill_id"] == i] for i in pick])
                boot.append(rates(bs, a.threshold)[:3])
            lo, hi = np.nanpercentile(np.array(boot, float), [2.5, 97.5], axis=0)
            rows.append({"index": index, "spills": subset, "real_spills": n_real, "fake_spills": n_fake,
                         "pooled_spread": spread, "detection_rate": det, "det_lo": lo[0], "det_hi": hi[0],
                         "false_alarm_rate": fa, "fa_lo": lo[1], "fa_hi": hi[1], "roc_area": area,
                         "auc_lo": lo[2], "auc_hi": hi[2]})
    t = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    pd.concat(out).to_csv(OUT / "scores_hidden_until_photo_check.csv", index=False)
    roc = []
    for sc in out:
        for thr in np.arange(-4, 0.01, 0.25):
            det, fa, *_ = rates(sc, thr)
            roc.append({"index": sc["index"].iloc[0], "threshold": thr, "detection_rate": det, "false_alarm_rate": fa})
    pd.DataFrame(roc).to_csv(OUT / "roc.csv", index=False)
    t.to_csv(OUT / "summary.csv", index=False)
    lines = [f"# Detection test: can one spill be flagged? (plan D29; {pd.Timestamp.today():%Y-%m-%d})", "",
             f"Flag: the first spring after the spill drops {abs(a.threshold):g} or more pooled spreads below the site's own "
             "springs before (site = 50 m circle minus its matched same-line spots). Fake spills are the matched spots "
             "themselves, on the real spill date. Across spills only; each spill's score stays hidden until the photo check.", "",
             "| Index | Spills | Real / fake | Detection rate [95% CI] | False-alarm rate [95% CI] | ROC area [95% CI] |",
             "|---|---|---|---|---|---|"]
    for r in t.itertuples():
        lines.append(f"| {r.index} | {r.spills} | {r.real_spills} / {r.fake_spills} | {r.detection_rate:.0%} [{r.det_lo:.0%}, {r.det_hi:.0%}] | "
                     f"{r.false_alarm_rate:.0%} [{r.fa_lo:.0%}, {r.fa_hi:.0%}] | {r.roc_area:.2f} [{r.auc_lo:.2f}, {r.auc_hi:.2f}] |")
    lines += ["", "ROC area 0.5 = no better than chance; 1.0 = every real spill scores below every fake one. roc.csv has "
              "the detection and false-alarm rates at every threshold. First results, not findings."]
    (OUT / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--threshold", type=float, default=-2.0)
    ap.add_argument("--boot", type=int, default=2000)
    main(ap.parse_args())
