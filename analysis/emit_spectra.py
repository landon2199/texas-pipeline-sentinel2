"""Gap 8: what does imaging spectroscopy add? NASA EMIT (60 m, 285 bands) at the spills, before and after.

Reads the AppEEARS point tables (extract/emit_points.py: the spill site and its 12 candidate spots on the same line,
every EMIT scene since Aug 2022, reflectance and EMIT's cloud masks). Scenes flagged cloudy (dilated cloud or the
aggregate flag) and the water-vapor bands EMIT marks unusable are dropped. In each clear scene, these are computed for
every point:
  - NDVI from 660 and 860 nm, to compare with Sentinel-2;
  - red-edge position, the four-point linear method (Guyot and Baret 1988);
  - water band index R900/R970 (Penuelas et al. 1997) and NDWI from 860 and 1240 nm (Gao 1996), true plant-water
    measures that Sentinel-2's bands can't make;
  - cellulose absorption index 0.5(R2000 + R2200) - R2100 (Nagler et al. 2003), dry plant matter and litter;
  - hydrocarbon index at 1705-1729-1741 nm (Kuhn et al. 2004), oil on bare ground;
  - absorption depth at 2310 nm against a 2260-2380 nm continuum.
Per spill and scene: the spill point minus the mean of its comparison spots in the same scene. The effect is the mean
after the spill minus the mean before. Comparison spots: the matched ones (strict, analysis/spills.py) where the spill
has them, and all 12 candidates as a second, larger comparison. Across spills only (plan 7.7).

Writes outputs/results/emit_spectra/SUMMARY.md, effects_across_spills.csv and figure_emit_difference_spectrum.png.
Usage: python emit_spectra.py
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

P = Path(r"C:\mydrive\Graduate School\Courses\GEOG_392\projects")
EMIT = P / "outputs" / "emit"


def load() -> tuple[pd.DataFrame, np.ndarray]:
    rfl = pd.concat([pd.read_csv(f, usecols=["Category", "ID", "Date", "wavelength", "reflectance", "good_wavelengths"])
                     for f in sorted(EMIT.glob("part*RFL-001-results.csv"))]).drop_duplicates(["ID", "Date", "wavelength"])
    water_vapor = rfl["wavelength"].between(1340, 1460) | rfl["wavelength"].between(1790, 1960) | (rfl["wavelength"] > 2450)
    rfl.loc[(rfl["good_wavelengths"] != 1) | water_vapor | (rfl["reflectance"] < 0) | (rfl["reflectance"] > 1.5), "reflectance"] = np.nan
    mask = pd.concat([pd.read_csv(f) for f in sorted(EMIT.glob("part*MASK-001-results.csv"))]).drop_duplicates(["ID", "Date"])
    bad = mask[(mask["dilated_cloud_flag"] == 1) | (mask["aggregate_flag"] == 1)][["ID", "Date"]]
    rfl = rfl.merge(bad.assign(bad=1), on=["ID", "Date"], how="left")
    rfl = rfl[rfl["bad"].isna()]
    wide = rfl.pivot_table(index=["Category", "ID", "Date"], columns="wavelength", values="reflectance", dropna=False)
    return wide, wide.columns.to_numpy(dtype=float)


def at(wide, wl, nm):
    return wide.iloc[:, int(np.argmin(np.abs(wl - nm)))]


def metrics(wide: pd.DataFrame, wl: np.ndarray) -> pd.DataFrame:
    R = lambda nm: at(wide, wl, nm)  # noqa: E731
    m = pd.DataFrame(index=wide.index)
    m["NDVI"] = (R(860) - R(660)) / (R(860) + R(660))
    m["red_edge_nm"] = 700 + 40 * (((R(670) + R(780)) / 2) - R(700)) / (R(740) - R(700))
    m["WBI"] = R(900) / R(970)
    m["NDWI_1240"] = (R(860) - R(1240)) / (R(860) + R(1240))
    m["CAI"] = 0.5 * (R(2000) + R(2200)) - R(2100)
    m["HI"] = (1729 - 1705) * (R(1741) - R(1705)) / (1741 - 1705) + R(1705) - R(1729)
    cont = R(2260) + (R(2380) - R(2260)) * (2310 - 2260) / (2380 - 2260)
    m["depth_2310"] = 1 - R(2310) / cont
    return m.replace([np.inf, -np.inf], np.nan)


def main(a):
    wide, wl = load()
    m = metrics(wide, wl).reset_index()
    m["site"] = np.where(m["ID"].str.endswith("_spill"), "spill", "spot")
    dates = pd.to_datetime(pd.read_parquet(P / "outputs" / "agent" / "spills.parquet").set_index("spill_id")["date"])
    matched = pd.read_csv(P / "outputs" / "results" / "spills_9springs" / "matches.csv")
    matched = set(matched[matched["kind"] == "same line"]["site_id"])
    cols = ["NDVI", "red_edge_nm", "WBI", "NDWI_1240", "CAI", "HI", "depth_2310"]
    rng = np.random.default_rng(392)
    out_rows, spectra = [], []
    for comparison in ("matched spots", "all candidate spots"):
        per = []
        for sid, g in m.groupby("Category"):
            spots = g[(g["site"] == "spot") & (g["ID"].isin(matched) if comparison == "matched spots" else True)]
            me = g[g["site"] == "spill"].set_index("Date")[cols]
            if me.empty or spots.empty:
                continue
            diff = (me - spots.groupby("Date")[cols].mean()).dropna(how="all")
            when = pd.to_datetime(pd.Index(diff.index).astype(str).str[:10]) > dates[sid]
            if when.sum() and (~when).sum():
                per.append((diff[when].mean() - diff[~when].mean()).rename(sid))
                if comparison == "all candidate spots":
                    sw = wide.xs(sid, level="Category")
                    me_s = sw[sw.index.get_level_values("ID").str.endswith("_spill")].droplevel("ID")
                    sp_s = sw[~sw.index.get_level_values("ID").str.endswith("_spill")].groupby(level="Date").mean()
                    d_s = (me_s - sp_s).dropna(how="all")
                    w_ = pd.to_datetime(pd.Index(d_s.index).astype(str).str[:10]) > dates[sid]
                    if w_.sum() and (~w_).sum():
                        spectra.append(d_s[w_].mean() - d_s[~w_].mean())
        if not per:
            continue
        e = pd.DataFrame(per)
        for c in cols:
            x = e[c].dropna().to_numpy()
            if len(x) < 3:
                continue
            b = x[rng.integers(0, len(x), (2000, len(x)))].mean(axis=1)
            out_rows.append({"comparison": comparison, "measure": c, "spills": len(x), "mean": x.mean(),
                             "lo95": np.percentile(b, 2.5), "hi95": np.percentile(b, 97.5), "wilcoxon_p": stats.wilcoxon(x).pvalue})
    t = pd.DataFrame(out_rows)
    out = P / "outputs" / "results" / "emit_spectra"
    out.mkdir(parents=True, exist_ok=True)
    t.to_csv(out / "effects_across_spills.csv", index=False)

    if spectra:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        s = pd.DataFrame(spectra)
        mean, lo, hi = s.mean(), s.quantile(0.25), s.quantile(0.75)
        fig, ax = plt.subplots(figsize=(6.5, 3.0), dpi=200)
        ax.fill_between(wl, lo, hi, color="#7a1f2b", alpha=0.15, linewidth=0)
        ax.plot(wl, mean, color="#7a1f2b", linewidth=1.2)
        ax.axhline(0, color="#444", linewidth=0.6)
        for nm, lab in [(705, "red edge"), (970, "water"), (1730, "C-H"), (2310, "C-H")]:
            ax.axvline(nm, color="#bbbbbb", linewidth=0.6, linestyle=":")
            ax.text(nm, ax.get_ylim()[1], lab, fontsize=6, ha="center", va="bottom", color="#666")
        ax.set_xlabel("wavelength (nm)")
        ax.set_ylabel("change in reflectance,\nspill minus spots")
        ax.set_title(f"EMIT: change in the spill sites' spectrum after the spill ({len(s)} spills)",
                     fontsize=8, loc="left")
        for sp_ in ("top", "right"):
            ax.spines[sp_].set_visible(False)
        fig.tight_layout()
        fig.savefig(out / "figure_emit_difference_spectrum.png", facecolor="white")
        plt.close(fig)

    names = {"NDVI": "NDVI (660/860 nm)", "red_edge_nm": "red-edge position (nm)", "WBI": "water band index R900/R970",
             "NDWI_1240": "NDWI 860/1240 nm", "CAI": "cellulose absorption index", "HI": "hydrocarbon index (1.73 um)",
             "depth_2310": "absorption depth at 2.31 um"}
    lines = [f"# EMIT imaging spectroscopy at the spills ({pd.Timestamp.today():%Y-%m-%d})", "",
             f"{m['Category'].nunique()} spills in the downloaded EMIT tables; clear scenes only. Effect = (spill minus spots) "
             "after the spill minus before. Across spills only.", "",
             "| Comparison | Measure | Spills | Effect [95% CI] | Wilcoxon p |", "|---|---|---|---|---|"] + \
            [f"| {r.comparison} | {names[r.measure]} | {r.spills} | {r.mean:+.4f} [{r.lo95:+.4f}, {r.hi95:+.4f}] | {r.wilcoxon_p:.3f} |"
             for r in t.itertuples()] + \
            ["", "Negative NDVI, red-edge and water effects mean the spill site lost green, shifted its red edge to shorter "
             "wavelengths or dried more than its spots. A positive hydrocarbon index or 2.31 um depth would point to oil "
             "on the ground. One 60 m EMIT pixel is about the size of the 50 m spill circle, so these are site-scale "
             "spectra. First results, not findings."]
    (out / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    main(ap.parse_args())
