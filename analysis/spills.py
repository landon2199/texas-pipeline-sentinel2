"""Part 3, the spill question (Q2): did vegetation at reported spills decline more than at matched comparison spots?

Analysis plan v1.7, Section 7. Reads the spill zones' image-by-image tables (extract/run_springs.py, 10 m), the
sites (zones/spill_zones.py) and the fixed values, then:
  1. measures every site's 50 m circle in every clear pass: its 0-25 and 25-50 m rings pooled by pixel count, all
     land cover together, one tile image per site and pass (D17);
  2. matches comparison spots (7.2). Same-line spots must lie in the same ecoregion, share the spill site's main land
     cover class (NLCD) and soil texture class, have similar terrain (height above drainage within --hand-m and slope
     within --slope-deg, D18), and have no other reported spill within 1 km. The nearest passing spots are kept, from
     0.5 km out to 3 km each way, up to 3 per side. Regional spots must pass the same land cover, soil, terrain and
     spill-free rules; up to 10 are kept at random;
  3. for every spill, spring and index: the spill circle minus the mean of its same-line spots in the same pass, then
     the median over the spring's passes (BACI from same-image pairs, 7.5). Each spring is labeled before, during or
     after the spill, with its years from the spill;
  4. the effect of each spill: the first spring after minus the mean of the springs before (E1), and all springs after
     minus all before (E_all). A negative NDVI effect means the site lost more green than its comparison spots;
  5. checks (7.3): whether the comparison spots tracked the spill site before the spill (flagged, never dropped);
  6. across all spills: the mean and median effect with bootstrap intervals and a Wilcoxon signed-rank test, overall
     and for spills of 50 barrels or more (H2), and a linear model of E1 on log barrels, commodity, cause and terrain;
  7. fake-spill tests (7.6) for permutation p-values: (a) each matched same-line spot treated as the spill, with the
     other matched spots as its comparison (placebo in space); (b) each matched regional spot treated as the spill on
     the real date, with the other regional spots as its comparison (spring values); (c) the real site with the date
     moved two years earlier.
Writes, in --out: site_passes.parquet, matches.csv, spill_springs.csv, effects.csv, placebos.csv and SUMMARY.md.

Usage: python spills.py [--out outputs/results/spills_9springs] [--hand-m 2] [--slope-deg 2]
"""
import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from corridor import one_image_per_pass  # noqa: E402

P = Path(r"C:\mydrive\Graduate School\Courses\GEOG_392\projects")
STATS = P / "outputs" / "geog392_zone_stats"
AGENT = P / "outputs" / "agent"
INDICES = ["NDVI", "NDMI", "NDRE", "BSI"]
CIRCLE = ["0-25", "25-50"]
SPRING = ("03-01", "05-01")


def site_passes() -> pd.DataFrame:
    """Every site's 50 m circle value in every clear pass, spring by spring (one export at a time)."""
    out = []
    for f in sorted(STATS.glob("spills_v1_per_image_*_10m.csv")):
        keep = {"zone_id", "landcover", "date", "image", "orbit"} | {f"{i}_{s}" for i in INDICES for s in ("mean", "count")}
        d = pd.read_csv(f, usecols=lambda c: c in keep)
        d[["site_id", "ring"]] = d["zone_id"].str.rsplit("_r", n=1, expand=True)
        d = d[d["ring"].isin(CIRCLE)]
        d = one_image_per_pass(d, "site_id")
        d = d.sort_values(["NDVI_count", "image"], ascending=[False, True], kind="stable").drop_duplicates(
            ["zone_id", "landcover", "date", "orbit"])
        lc = d.groupby(["site_id", "landcover"])["NDVI_count"].sum().rename("pixels").reset_index()
        g = d.assign(**{f"{i}_w": d[f"{i}_mean"] * d[f"{i}_count"] for i in INDICES}).groupby(["site_id", "date", "orbit"])
        v = pd.DataFrame({i: g[f"{i}_w"].sum() / g[f"{i}_count"].sum() for i in INDICES})
        v["pixels"] = g["NDVI_count"].sum()
        v = v[v["pixels"] >= 20].reset_index()
        v["year"] = v["date"].str[:4].astype(int)
        out.append((v, lc))
        print(f"  {f.name}: {v['site_id'].nunique():,} sites, {len(v):,} site passes", flush=True)
    passes = pd.concat([o[0] for o in out], ignore_index=True)
    landcover = pd.concat([o[1] for o in out]).groupby(["site_id", "landcover"])["pixels"].sum().reset_index()
    return passes, landcover


def site_traits(landcover: pd.DataFrame) -> pd.DataFrame:
    """Main land cover class, soil texture class, height above drainage and slope of every site's 50 m circle."""
    main = landcover.sort_values("pixels", ascending=False).drop_duplicates("site_id").set_index("site_id")["landcover"]
    fixed = pd.read_csv(STATS / "sample_v1_b50_and_spills_v1_fixed.csv")
    fixed = fixed[fixed["zone_id"].str.contains(r"_r(?:0-25|25-50)$")].copy()
    fixed[["site_id", "ring"]] = fixed["zone_id"].str.rsplit("_r", n=1, expand=True)
    area = fixed["ring"].map({"0-25": 1.0, "25-50": 3.0})                  # ring areas: pi*25^2 and pi*(50^2-25^2)
    num = fixed[["hand_m_mean", "slope_deg_mean"]].mul(area, axis=0).groupby(fixed["site_id"]).sum()
    terrain = num.div(area.groupby(fixed["site_id"]).sum(), axis=0).rename(columns={"hand_m_mean": "hand_m", "slope_deg_mean": "slope_deg"})
    soil = fixed[fixed["ring"] == "25-50"].set_index("site_id")["soil_texture_mode"].rename("soil")
    return terrain.join(soil).join(main.rename("landcover"))


def match(sites: pd.DataFrame, traits: pd.DataFrame, hand_m: float, slope_deg: float, seed: int = 392,
          broad_landcover: bool = False, soil: bool = True):
    """The comparison spots of every spill (7.2), and why the others were left out."""
    rng = np.random.default_rng(seed)
    s = sites.join(traits, on="site_id")
    rows, reasons = [], []
    for spill_id, g in s.groupby("spill_id"):
        me = g[g["site"] == "spill"]
        if me.empty or me[["landcover", "soil", "hand_m", "slope_deg"]].isna().any(axis=None):
            reasons.append({"spill_id": spill_id, "reason": "spill site not measured"})
            continue
        me = me.iloc[0]

        def why(r):
            if not r["same_ecoregion"]:
                return "other ecoregion"
            if r["other_spill_within_1km"]:
                return "another spill within 1 km"
            same_lc = (r["landcover"] // 10 == me["landcover"] // 10) if broad_landcover else (r["landcover"] == me["landcover"])
            if pd.isna(r["landcover"]) or not same_lc:          # broad: the NLCD group, such as any forest (41-43)
                return "other land cover"
            if soil and r["soil"] != me["soil"]:
                return "other soil texture"
            if abs(r["hand_m"] - me["hand_m"]) > hand_m or abs(r["slope_deg"] - me["slope_deg"]) > slope_deg:
                return "other terrain"
            return ""
        cand = g[g["site"] == "candidate"].copy()
        cand["why"] = cand.apply(why, axis=1)
        for side, part in cand.groupby(np.sign(cand["offset_m"])):
            ok = part[part["why"] == ""].sort_values("offset_m", key=np.abs).head(3)
            rows += [{"spill_id": spill_id, "site_id": x, "kind": "same line"} for x in ok["site_id"]]
        reg = g[g["site"] == "regional"].copy()
        reg["why"] = reg.apply(why, axis=1)
        ok = reg[reg["why"] == ""]
        pick = ok.iloc[rng.permutation(len(ok))[:10]] if len(ok) else ok
        rows += [{"spill_id": spill_id, "site_id": x, "kind": "regional"} for x in pick["site_id"]]
        reasons += [{"spill_id": spill_id, "reason": w} for w in pd.concat([cand["why"], reg["why"]]) if w]
    return pd.DataFrame(rows), pd.DataFrame(reasons)


def spring_status(year: int, date: pd.Timestamp) -> str:
    if pd.Timestamp(f"{year}-{SPRING[1]}") < date:
        return "before"
    if pd.Timestamp(f"{year}-{SPRING[0]}") > date:
        return "after"
    return "during"


def label(t: pd.DataFrame, date: pd.Timestamp) -> pd.DataFrame:
    t = t.copy()
    t["status"] = [spring_status(int(y), date) for y in t["year"]]
    first_after = t.loc[t["status"] == "after", "year"].min()
    last_before = t.loc[t["status"] == "before", "year"].max()
    t["years_from_spill"] = np.where(t["status"] == "after", t["year"] - first_after + 1,
                                     np.where(t["status"] == "before", t["year"] - last_before - 1, 0))
    return t


def effect(t: pd.DataFrame, col: str = "d") -> tuple[float, float, int, int]:
    """E1: the first spring after minus the mean of the springs before; E_all: all after minus all before."""
    before, after = t.loc[t["status"] == "before", col].dropna(), t[t["status"] == "after"].dropna(subset=[col])
    if before.empty or after.empty:
        return np.nan, np.nan, len(before), len(after)
    first = after.loc[after["years_from_spill"] == 1, col]
    e1 = float(first.iloc[0] - before.mean()) if len(first) else np.nan
    return e1, float(after[col].mean() - before.mean()), len(before), len(after)


def same_pass_springs(by_site, spill_site, spots, index):
    """Spill circle minus the mean of its spots in the same pass, then the median over each spring's passes."""
    empty = pd.DataFrame(columns=["year", "d", "passes"])
    if spill_site not in by_site or not any(s in by_site for s in spots):
        return empty
    a = by_site[spill_site][[index, "year"]]
    b = pd.concat([by_site[s][index] for s in spots if s in by_site]).groupby(level=["date", "orbit"]).mean().rename("spots")
    j = a.join(b, how="inner").dropna()
    if j.empty:
        return empty
    j["d"] = j[index] - j["spots"]
    return j.groupby("year")["d"].agg(["median", "size"]).rename(columns={"median": "d", "size": "passes"}).reset_index()


def spring_values(passes, index):
    return passes.groupby(["site_id", "year"])[index].median().unstack("year")


def main(a):
    a.out.mkdir(parents=True, exist_ok=True)
    print("measuring every site's 50 m circle in every pass:")
    passes, landcover = site_passes()
    passes.to_parquet(a.out / "site_passes.parquet", index=False)
    sites = pd.read_parquet(AGENT / "spill_sites.parquet")
    spills = pd.read_parquet(AGENT / "spills.parquet").set_index("spill_id")
    traits = site_traits(landcover)
    m, reasons = match(sites, traits, a.hand_m, a.slope_deg, broad_landcover=a.broad_landcover, soil=not a.no_soil)
    m.to_csv(a.out / "matches.csv", index=False)
    n_same = m[m["kind"] == "same line"].groupby("spill_id").size()
    print(f"matched: {int((n_same > 0).sum())} of {sites['spill_id'].nunique()} spills have same-line spots "
          f"(median {int(n_same.median()) if len(n_same) else 0} each); left out: "
          f"{reasons['reason'].value_counts().to_dict() if len(reasons) else {}}")

    springs_rows, effect_rows, placebo_rows = [], [], []
    spring_vals = {i: spring_values(passes, i) for i in INDICES}
    by_site = {s: g.set_index(["date", "orbit"]) for s, g in passes.groupby("site_id")}
    for spill_id, mine in m.groupby("spill_id"):
        site = f"{spill_id}_spill"
        date = pd.Timestamp(spills.loc[spill_id, "date"])
        same = mine.loc[mine["kind"] == "same line", "site_id"].tolist()
        regional = mine.loc[mine["kind"] == "regional", "site_id"].tolist()
        for index in INDICES:
            if same:
                t = label(same_pass_springs(by_site, site, same, index), date)
                springs_rows += [{"spill_id": spill_id, "index": index, **r} for r in t.to_dict("records")]
                e1, eall, nb, na = effect(t)
                pre = t[t["status"] == "before"]
                effect_rows.append({"spill_id": spill_id, "index": index, "E1": e1, "E_all": eall, "springs_before": nb,
                                    "springs_after": na, "spots": len(same),
                                    "pre_spread": float(pre["d"].std()) if len(pre) > 1 else np.nan})
                # (a) placebo in space: each matched spot as the spill, the other spots as its comparison
                for k, fake in enumerate(same):
                    others = [x for x in same if x != fake]
                    if others:
                        e1f, _, _, _ = effect(label(same_pass_springs(by_site, fake, others, index), date))
                        placebo_rows.append({"spill_id": spill_id, "index": index, "test": "same-line spot", "E1": e1f})
                # (c) the real site with the date moved two years earlier
                e1s, _, _, _ = effect(label(same_pass_springs(by_site, site, same, index), date - pd.DateOffset(years=2)))
                placebo_rows.append({"spill_id": spill_id, "index": index, "test": "date two years earlier", "E1": e1s})
            # (b) regional spots as if they spilled on the real date, against the other regional spots (spring values)
            V = spring_vals[index]
            for fake in regional:
                others = [x for x in regional if x != fake and x in V.index]
                if fake in V.index and others:
                    t = pd.DataFrame({"year": V.columns, "d": (V.loc[fake] - V.loc[others].mean()).to_numpy()})
                    e1f, _, _, _ = effect(label(t, date))
                    placebo_rows.append({"spill_id": spill_id, "index": index, "test": "regional spot", "E1": e1f})

    sp = pd.DataFrame(springs_rows)
    eff = pd.DataFrame(effect_rows).merge(spills[["barrels", "commodity_group", "cause", "ecoregion"]],
                                          left_on="spill_id", right_index=True, how="left")
    terrain = traits[["hand_m", "slope_deg"]].rename_axis("site_id").reset_index()
    terrain = terrain[terrain["site_id"].str.endswith("_spill")].assign(spill_id=lambda x: x["site_id"].str[:-len("_spill")])
    eff = eff.merge(terrain[["spill_id", "hand_m", "slope_deg"]], on="spill_id", how="left")
    pla = pd.DataFrame(placebo_rows)
    sp.to_csv(a.out / "spill_springs.csv", index=False)
    eff.to_csv(a.out / "effects.csv", index=False)
    pla.to_csv(a.out / "placebos.csv", index=False)
    summarize(eff, pla, a)


def summarize(eff, pla, a, draws=10000):
    from scipy import stats
    rng = np.random.default_rng(392)
    table = []
    lines = ["# Spill results: the spill site minus its matched same-line spots, before and after", "",
             f"Matching (D18): same ecoregion, {'land cover group (NLCD level 1)' if a.broad_landcover else 'land cover class'}"
             f"{'' if a.no_soil else ' and soil texture'}; height above drainage within {a.hand_m} m and slope "
             f"within {a.slope_deg} degrees; no other spill within 1 km. E1 = first spring after minus the mean of the "
             "springs before. Negative NDVI = lost more green than its comparison spots. First results, not findings.", ""]
    for index in INDICES:
        e = eff[(eff["index"] == index)].dropna(subset=["E1"])
        if e.empty:
            continue
        lines += [f"## {index}", "", "| spills | n | mean E1 [95% bootstrap] | median E1 | Wilcoxon p (two-sided) | "
                  "permutation p, same-line spots | permutation p, regional spots | date two years earlier: mean E1 |",
                  "|---|---|---|---|---|---|---|---|"]
        for label_, sub in [("all", e), ("50 barrels or more (H2)", e[e["barrels"] >= 50])]:
            if len(sub) < 3:
                continue
            boot = [rng.choice(sub["E1"].to_numpy(), len(sub)).mean() for _ in range(2000)]
            w = stats.wilcoxon(sub["E1"]).pvalue
            p_same = perm_p(sub, pla[(pla["index"] == index) & (pla["test"] == "same-line spot")], rng, draws)
            p_reg = perm_p(sub, pla[(pla["index"] == index) & (pla["test"] == "regional spot")], rng, draws)
            shift = pla[(pla["index"] == index) & (pla["test"] == "date two years earlier") & pla["spill_id"].isin(sub["spill_id"])]["E1"].dropna()
            table.append({"index": index, "spills": label_, "n": len(sub), "mean_E1": sub["E1"].mean(),
                          "lo95": float(np.quantile(boot, .025)), "hi95": float(np.quantile(boot, .975)),
                          "median_E1": sub["E1"].median(), "wilcoxon_p": w, "perm_p_same_line": p_same,
                          "perm_p_regional": p_reg, "date_shift_mean_E1": shift.mean(), "date_shift_n": len(shift)})
            lines.append(f"| {label_} | {len(sub)} | {sub['E1'].mean():+.4f} [{np.quantile(boot, .025):+.4f}, "
                         f"{np.quantile(boot, .975):+.4f}] | {sub['E1'].median():+.4f} | {w:.3f} | {p_same} | {p_reg} | "
                         f"{shift.mean():+.4f} (n={len(shift)}) |")
        lines.append("")
    e = eff[(eff["index"] == "NDVI")].dropna(subset=["E1"])
    if len(e) >= 12:
        import statsmodels.formula.api as smf
        d = e.assign(log_barrels=np.log10(e["barrels"].clip(lower=1)), excavation=e["cause"].str.contains("EXCAVATION", na=False))
        fit = smf.ols("E1 ~ log_barrels + C(commodity_group) + excavation + hand_m + slope_deg", data=d).fit(cov_type="HC3")
        lines += ["## What goes with a larger NDVI effect (linear model, robust errors)", "", "| term | estimate | 95% interval | p |",
                  "|---|---|---|---|"]
        ci = fit.conf_int()
        lines += [f"| {k} | {fit.params[k]:+.4f} | [{ci.loc[k, 0]:+.4f}, {ci.loc[k, 1]:+.4f}] | {fit.pvalues[k]:.3f} |"
                  for k in fit.params.index]
        lines += ["", f"n = {int(fit.nobs)} spills, R2 = {fit.rsquared:.2f}."]
    (a.out / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    pd.DataFrame(table).to_csv(a.out / "summary.csv", index=False)
    print(f"wrote {a.out}")


def perm_p(sub, fakes, rng, draws):
    """The share of fake sets (one fake per spill, drawn at random) whose mean E1 is at least as negative as the real mean."""
    pool = {s: g["E1"].dropna().to_numpy() for s, g in fakes.groupby("spill_id")}
    spills = [s for s in sub["spill_id"] if s in pool and len(pool[s])]
    if len(spills) < 3:
        return "n/a"
    real = sub.set_index("spill_id").loc[spills, "E1"].mean()
    sims = np.array([np.mean([pool[s][rng.integers(len(pool[s]))] for s in spills]) for _ in range(draws)])
    return f"{(np.sum(sims <= real) + 1) / (draws + 1):.4f} (n={len(spills)})"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=P / "outputs" / "results" / "spills_9springs")
    ap.add_argument("--hand-m", type=float, default=2.0)
    ap.add_argument("--slope-deg", type=float, default=2.0)
    ap.add_argument("--broad-landcover", action="store_true", help="match the NLCD group (any forest, any grassland) instead of the class")
    ap.add_argument("--no-soil", action="store_true", help="do not require the same soil texture class")
    main(ap.parse_args())
