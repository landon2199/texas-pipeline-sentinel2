"""Measure the agents (analysis plan 9.4): a bank of questions with known answers, asked through the running dashboard.

The right answers are computed here straight from the tables with pandas, independently of the tools, and recomputed
on every run, so the bank stays right when new results arrive. Following current GIS-agent benchmarks (GeoBenchX 2025,
GeoAgentBench 2026), the bank also has questions with no valid answer (outside the data: years not measured, places
outside Texas, distances beyond the rings, data we don't have), where the right behavior is to say so without making
numbers up. Each answerable question is scored on:
  tool    the agent called the tool a careful analyst would (any of the accepted ones)
  args    that call used the right parameters (for example index="NDMI" or by="ecoregion"), when the question names them
  answer  the written answer contains every expected value: numbers at the precision given, names, IDs
  numbers the app's number check found no number in the answer that no tool gave
and each question with no valid answer on:
  decline the answer says the data doesn't cover it, and the number check found no made-up number.
Writes outputs/discovery/agent_eval_<model>.csv and adds a line to outputs/discovery/agent_eval_summary.csv.

Usage: start the dashboard (start_dashboard.bat, or GEOAI_MODEL=<model> python ai_dashboard.py), then
       python evaluate_agents.py [--url http://127.0.0.1:8392] [--only 1 2 3]
"""
import argparse
import json
import re
import time
import urllib.request
from pathlib import Path

import pandas as pd

P = Path(r"C:\mydrive\Graduate School\Courses\GEOG_392\projects")
AGENT, DISC = P / "outputs" / "agent", P / "outputs" / "discovery"
DECLINE = re.compile(r"not available|no data|n['’]t have|do not have|does not have|not measured|wasn['’]t measured|"
                     r"was not measured|can['’]t|cannot|unable|outside|only covers?|no information|not in (the|our)|beyond|"
                     r"not part of|n['’]t include|does not include|no tool|not possible|isn['’]t possible|only (from|for)|"
                     r"starts? in 2018|2018 (to|through|-|–) ?2026|only texas|texas only|not covered|no record|not included|"
                     r"don['’]t know|do not know|not yet", re.I)


def tables():
    t = {n: pd.read_parquet(AGENT / f"{n}.parquet") for n in
         ["statewide", "segments", "band_profile", "spills", "coverage", "spill_summary"]}
    for n in ["catalog", "spill_reports"]:
        f = DISC / f"{n}.parquet"
        t[n] = pd.read_parquet(f) if f.exists() else None
    return t


def Q(question, tools, expected=(), args=None, kind="answer"):
    return {"question": question, "tools": tools, "expected": list(expected), "args": args or {}, "kind": kind}


def bank(t):
    """Questions with accepted tools, expected values and parameters. A float is matched at 4 decimals unless given as
    (value, places); a list inside expected means any one of its items is right."""
    s = t["statewide"]
    base = s[(s["measure"] == "same land cover") & (s["springs"] == "all springs")]
    z = base[base["ring"] == "0-50 m"]

    def one(scope="statewide", index="NDVI", group=None, ring="0-50 m", springs="all springs"):
        d = s[(s["measure"] == "same land cover") & (s["springs"] == springs) & (s["ring"] == ring) &
              (s["scope"] == scope) & (s["index"] == index)]
        return d[d["group"] == group].iloc[0] if group else d.iloc[0]
    eco = z[(z["scope"] == "ecoregion") & (z["index"] == "NDVI")].sort_values("weighted_median")
    comm = z[(z["scope"] == "commodity_group") & (z["index"] == "NDVI")].sort_values("weighted_median")
    diam = z[(z["scope"] == "diameter_class") & (z["index"] == "NDVI") & (z["group"] != "Not recorded")].sort_values("weighted_median")
    years = s[(s["measure"] == "same land cover") & (s["ring"] == "0-50 m") & (s["scope"] == "statewide") &
              (s["index"] == "NDVI") & s["springs"].astype(str).str.fullmatch(r"\d{4}")].sort_values("weighted_median")
    bp = t["band_profile"]
    b50 = bp[(bp["springs"] == "all springs") & (bp["scope"] == "statewide") & (bp["index"] == "NDVI") &
             (bp["measure"] == "same land cover") & (bp["ring"].astype(str).str.startswith("50-100"))]
    seg, sp, ss = t["segments"], t["spills"], t["spill_summary"]
    least = seg.nsmallest(5, "NDVI_gap_0_50")["segment_id"].tolist()
    one_seg = seg[seg["segment_id"] == "147-000014-32-0-1"].iloc[0]

    def summ(index, matching="strict", spills="all"):
        return float(ss[(ss["index"] == index) & (ss["matching"] == matching) & (ss["spills"] == spills)].iloc[0]["mean_E1"])
    q = [
        Q("What is the statewide NDVI gap in the 0-50 m band beside the pipe, with its 95% interval?", ["corridor_summary"],
          [one().weighted_median, one().lo95, one().hi95], {"index": "NDVI"}),
        Q("What is the statewide NDMI gap in the 0-50 m band, and is it different from zero?", ["corridor_summary"],
          [one(index="NDMI").weighted_median], {"index": "NDMI"}),
        Q("What is the statewide NDRE gap in the 0-50 m band?", ["corridor_summary"], [one(index="NDRE").weighted_median],
          {"index": "NDRE"}),
        Q("What is the statewide SAVI gap in the 0-50 m band?", ["corridor_summary"], [one(index="SAVI").weighted_median],
          {"index": "SAVI"}),
        Q("What is the statewide NDVI gap in the 50-100 m ring?", ["corridor_summary"],
          [one(ring="50-100 m").weighted_median], {"ring": "50-100 m"}),
        Q("Which ecoregion has the most negative NDVI gap in the 0-50 m band?", ["corridor_summary"], [eco.iloc[0]["group"]],
          {"by": "ecoregion"}),
        Q("Which ecoregion has the NDVI gap closest to zero, or positive, in the 0-50 m band?", ["corridor_summary"],
          [eco.iloc[-1]["group"]], {"by": "ecoregion"}),
        Q("What is the NDVI gap in the 0-50 m band in the Edwards Plateau?", ["corridor_summary"],
          [one(scope="ecoregion", group="Edwards Plateau").weighted_median], {"by": "ecoregion"}),
        Q("Which commodity group has the most negative NDVI gap in the 0-50 m band?", ["corridor_summary"],
          [comm.iloc[0]["group"]], {"by": "commodity_group"}),
        Q("Which pipe size class has the most negative NDVI gap in the 0-50 m band?", ["corridor_summary"],
          [diam.iloc[0]["group"]], {"by": "diameter_class"}),
        Q("What is the NDVI gap in the 0-50 m band for lines mapped within 50 ft?", ["corridor_summary"],
          [one(scope="location_accuracy", group="Within 50 ft").weighted_median], {"by": "location_accuracy"}),
        Q("What was the statewide NDVI gap in the 0-50 m band in spring 2020?", ["corridor_summary"],
          [one(springs="2020").weighted_median], {"springs": "2020"}),
        Q("Which spring from 2018 to 2026 had the most negative statewide NDVI gap in the 0-50 m band?",
          ["corridor_summary", "query_zones"], [str(years.iloc[0]["springs"])]),
        Q("How far from the pipe does the NDVI gap reach?", ["distance_profile"], ["50-100"]),
        Q("What is the NDVI gap in the 50-100 m band of the distance profile?", ["distance_profile"],
          [float(b50.iloc[0]["weighted_median"])] if len(b50) else []),
        Q("List the 5 sampled segments with the most negative NDVI gap in the 0-50 m band.", ["query_zones"], least),
        Q("How many sampled segments are in the Southern Texas Plains?", ["query_zones"],
          [(int((seg["ecoregion"] == "Southern Texas Plains").sum()), 0)]),
        Q("How many sampled segments are in the High Plains?", ["query_zones"], [(int((seg["ecoregion"] == "High Plains").sum()), 0)]),
        Q("How many sampled segments are mapped within 50 ft?", ["query_zones"],
          [(int((seg["location_accuracy"] == "Within 50 ft").sum()), 0)]),
        Q("How many segments are in the statewide sample?", ["query_zones", "list_tables"], [(len(seg), 0)]),
        Q("How many sampled segments have pipe over 36 inches?", ["query_zones"], [(int((seg["diameter_class"] == "Over 36 in").sum()), 0)]),
        Q("How many reported spills are in the study?", ["query_zones", "list_tables"], [(len(sp), 0)]),
        Q("How many of the study's spills released 50 barrels or more?", ["query_zones"], [(int((sp["barrels"] >= 50).sum()), 0)]),
        Q("What is the most common cause of the study's spills?", ["query_zones"], [sp["cause"].value_counts().index[0].split()[0]]),
        Q("How many barrels did the largest spill in the study release?", ["query_zones"], [(float(sp["barrels"].max()), 0)]),
        Q("Tell me about segment 147-000014-32-0-1: what does it carry and how big is the pipe?", ["segment"],
          [(float(one_seg["diameter_in"]), 0)], {"segment_id": "147-000014-32-0-1"}),
        Q("What commodity does segment 147-000014-32-0-1 carry?", ["segment"], [str(one_seg["commodity"]).split()[0]],
          {"segment_id": "147-000014-32-0-1"}),
        Q("How many kilometers of Railroad Commission pipe are there in all, and what does the build leave out?",
          ["left_out"], [(round(t["coverage"]["km"].sum()), 0)]),
        Q("What data do we have on land surface temperature, and where does it come from?",
          ["search_catalog", "describe_dataset"], ["Landsat"]),
        Q("Where do the spill locations come from?", ["search_catalog", "describe_dataset"], ["PHMSA"]),
        Q("Which dataset gives the drought index?", ["search_catalog", "describe_dataset"], ["gridMET"]),
        Q("What satellite imagery does the project use for vegetation?", ["search_catalog", "describe_dataset"], ["Sentinel-2"]),
        Q("Show the vegetation history of segment 147-000014-32-0-1.", ["vegetation_history"], [],
          {"segment_id": "147-000014-32-0-1"}),
        Q("Across all the spills, did vegetation at the spill sites drop after the spill compared with nearby spots?",
          ["spill_summary"], [summ("NDVI")], {"index": "NDVI"}),
        Q("Across all spills, what is the NDRE effect of a spill?", ["spill_summary"], [summ("NDRE")], {"index": "NDRE"}),
        Q("Do spills change NDMI, the moisture index, compared with nearby spots?", ["spill_summary"], [summ("NDMI")],
          {"index": "NDMI"}),
        Q("With the broader matching of comparison spots, what is the NDVI spill effect?", ["spill_summary"],
          [summ("NDVI", "broader")], {"matching": "broader"}),
        Q("For spills of 50 barrels or more, what is the NDVI effect?", ["spill_summary"],
          [summ("NDVI", spills="50 barrels or more (H2)")], {"index": "NDVI"}),
    ]
    r = t["spill_reports"]
    if r is not None:
        dug = int(r["cleanup_actions"].fillna("").str.contains("excavated soil").sum())
        q += [Q("How many right-of-way spill reports say contaminated soil was removed?", ["search_spill_reports"],
                [[(int((r["soil_removed"] == "yes").sum()), 0), (dug, 0)]]),
              Q("How many spill reports say the oil reached water?", ["search_spill_reports"],
                [(int((r["reached_water"] == "yes").sum()), 0)]),
              Q("Find spill reports where a landowner or farmer found the oil.", ["search_spill_reports"])]
    q += [Q(x, [], kind="decline") for x in [
        "What was the statewide NDVI gap beside the pipe in spring 2015?",
        "What was the NDVI gap beside the pipe in spring 2027?",
        "What is the NDVI gap beside pipelines in Oklahoma?",
        "What is the NDVI gap 2 km from the pipe?",
        "What was the methane emission rate at spill S024?",
        "How many people live within 1 km of each spill?",
        "Which segment will have the next spill?"]]
    return q


def matches(answer: str, expected) -> bool:
    if isinstance(expected, list):                 # accepted alternatives: any one is right
        return any(matches(answer, e) for e in expected)
    if isinstance(expected, str):
        return expected.lower().replace("-", " ") in answer.lower().replace("-", " ").replace("–", " ")
    value, places = expected if isinstance(expected, tuple) else (expected, 4)
    nums = [float(x.replace(",", "").replace("−", "-"))
            for x in re.findall(r"[-−]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?", answer)]
    tol = 0.5 * 10 ** -places + 1e-9
    return any(abs(abs(n) - abs(value)) <= tol for n in nums)    # the sign may be said in words ("less green")


def args_ok(steps, tools, want: dict) -> bool:
    if not want:
        return True
    for s in steps:
        if s["tool"] in tools and all(str(s.get("args", {}).get(k, "")).strip().lower() == str(v).lower() for k, v in want.items()):
            return True
    return False


def ask(url: str, question: str) -> dict:
    req = urllib.request.Request(url + "/api/ask", data=json.dumps({"question": question}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1800) as r:
        return json.loads(r.read())


def main(a):
    t = tables()
    model = json.loads(urllib.request.urlopen(a.url + "/api/status", timeout=10).read())["model"]
    rows = []
    for k, item in enumerate(bank(t), 1):
        if a.only and k not in a.only:
            continue
        t0 = time.time()
        try:
            res = ask(a.url, item["question"])
        except Exception as e:
            res = {"answer": "", "steps": [], "numbers": {"unsupported": ["(error)"]}, "error": str(e)}
        steps, got = res.get("steps", []), res.get("answer", "")
        used = [s["tool"] for s in steps]
        ok_numbers = not res.get("numbers", {}).get("unsupported")
        row = {"k": k, "kind": item["kind"], "question": item["question"], "tools_used": " ".join(used),
               "numbers_ok": ok_numbers, "unsupported": " ".join(res.get("numbers", {}).get("unsupported", [])),
               "seconds": round(time.time() - t0, 1), "answer": got}
        if item["kind"] == "decline":
            row["decline_ok"] = bool(DECLINE.search(got)) and ok_numbers
            mark = f"decline {'ok' if row['decline_ok'] else '--'}"
        else:
            row["tool_ok"] = any(x in used for x in item["tools"])
            row["args_ok"] = row["tool_ok"] and args_ok(steps, item["tools"], item["args"])
            # with nothing specific to check, an answer counts only if it came from the right tool
            row["answer_ok"] = all(matches(got, e) for e in item["expected"]) if item["expected"] else row["tool_ok"]
            mark = (f"tool {'ok' if row['tool_ok'] else '--'} | args {'ok' if row['args_ok'] else '--'} | "
                    f"answer {'ok' if row['answer_ok'] else '--'}")
        rows.append(row)
        print(f"{k:2d} {mark} | numbers {'ok' if ok_numbers else '--'} | {row['seconds']:5.1f} s | {item['question'][:60]}", flush=True)
    out = pd.DataFrame(rows)
    DISC.mkdir(parents=True, exist_ok=True)
    out.to_csv(DISC / f"agent_eval_{model.replace(':', '_')}.csv", index=False)
    ans, dec = out[out["kind"] == "answer"], out[out["kind"] == "decline"]
    summary = {"model": model, "date": time.strftime("%Y-%m-%d %H:%M"), "questions": len(out),
               "tool_ok": round(ans["tool_ok"].mean(), 3) if len(ans) else None,
               "args_ok": round(ans["args_ok"].mean(), 3) if len(ans) else None,
               "answer_ok": round(ans["answer_ok"].mean(), 3) if len(ans) else None,
               "numbers_ok": round(out["numbers_ok"].mean(), 3),
               "decline_ok": round(dec["decline_ok"].mean(), 3) if len(dec) else None,
               "median_seconds": float(out["seconds"].median())}
    f = DISC / "agent_eval_summary.csv"
    previous = [pd.read_csv(f)] if f.exists() else []
    pd.concat(previous + [pd.DataFrame([summary])], ignore_index=True).to_csv(f, index=False)
    print(json.dumps(summary))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default="http://127.0.0.1:8392")
    ap.add_argument("--only", nargs="*", type=int)
    main(ap.parse_args())
