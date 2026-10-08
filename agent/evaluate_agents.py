"""Measure the agents (analysis plan 9.4): a bank of questions with known answers, asked through the running dashboard.

The right answers are computed here straight from the tables with pandas, independently of the tools, and recomputed
on every run, so the bank stays right when new springs arrive. For each question the score has three parts:
  tool    the agent called the tool a careful analyst would (any of the accepted ones)
  answer  the written answer contains every expected value: numbers at the precision given, names, IDs
  numbers the app's number check found no number in the answer that no tool gave
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


def tables():
    t = {n: pd.read_parquet(AGENT / f"{n}.parquet") for n in ["statewide", "segments", "band_profile", "spills", "coverage"]}
    for n in ["catalog", "spill_reports"]:
        f = DISC / f"{n}.parquet"
        t[n] = pd.read_parquet(f) if f.exists() else None
    return t


def bank(t):
    """(question, accepted tools, expected values). A float is matched at 4 decimals unless given as (value, places)."""
    s = t["statewide"]
    pick = (s["springs"] == "all springs") & (s["measure"] == "same land cover")
    zero = s[pick & (s["ring"] == "0-50 m")]
    state = zero[(zero["scope"] == "statewide") & (zero["index"] == "NDVI")].iloc[0]
    ndmi = zero[(zero["scope"] == "statewide") & (zero["index"] == "NDMI")].iloc[0]
    eco = zero[(zero["scope"] == "ecoregion") & (zero["index"] == "NDVI")].sort_values("weighted_median")
    comm = zero[(zero["scope"] == "commodity_group") & (zero["index"] == "NDVI")].sort_values("weighted_median")
    seg = t["segments"]
    least = seg.nsmallest(5, "NDVI_gap_0_50")["segment_id"].tolist()
    stp = int((seg["ecoregion"] == "Southern Texas Plains").sum())
    within50 = int((seg["location_accuracy"] == "Within 50 ft").sum())
    one = seg[seg["segment_id"] == "147-000014-32-0-1"].iloc[0]
    total_km = t["coverage"]["km"].sum()
    q = [
        ("What is the statewide NDVI gap in the 0-50 m band beside the pipe, with its 95% interval?",
         ["corridor_summary"], [state.weighted_median, state.lo95, state.hi95]),
        ("What is the statewide NDMI gap in the 0-50 m band, and is it different from zero?",
         ["corridor_summary"], [ndmi.weighted_median]),
        ("Which ecoregion has the most negative NDVI gap in the 0-50 m band?",
         ["corridor_summary"], [eco.iloc[0]["group"]]),
        ("Which commodity group has the most negative NDVI gap in the 0-50 m band?",
         ["corridor_summary"], [comm.iloc[0]["group"]]),
        ("How far from the pipe does the NDVI gap reach?", ["distance_profile"], ["50-100"]),
        ("List the 5 sampled segments with the most negative NDVI gap in the 0-50 m band.", ["query_zones"], least),
        ("How many sampled segments are in the Southern Texas Plains?", ["query_zones"], [(stp, 0)]),
        ("How many sampled segments are mapped within 50 ft?", ["query_zones"], [(within50, 0)]),
        ("How many reported spills are in the study?", ["query_zones", "list_tables"], [(len(t["spills"]), 0)]),
        ("Tell me about segment 147-000014-32-0-1: what does it carry and how big is the pipe?", ["segment"],
         [(float(one["diameter_in"]), 0)]),
        ("How many kilometers of Railroad Commission pipe are there in all, and what does the build leave out?",
         ["left_out"], [(round(total_km), 0)]),
        ("What data do we have on land surface temperature, and where does it come from?",
         ["search_catalog", "describe_dataset"], ["Landsat"]),
        ("Where do the spill locations come from?", ["search_catalog", "describe_dataset"], ["PHMSA"]),
        ("Show the vegetation history of segment 147-000014-32-0-1.", ["vegetation_history"], []),
    ]
    ss = pd.read_parquet(AGENT / "spill_summary.parquet") if (AGENT / "spill_summary.parquet").exists() else None
    if ss is not None:
        row = ss[(ss["index"] == "NDVI") & (ss["matching"] == "strict") & (ss["spills"] == "all")].iloc[0]
        q.append(("Across all the spills, did vegetation at the spill sites drop after the spill compared with nearby spots?",
                  ["spill_summary"], [float(row["mean_E1"])]))
    r = t["spill_reports"]
    if r is not None:
        dug = int(r["cleanup_actions"].fillna("").str.contains("excavated soil").sum())
        q += [("How many right-of-way spill reports say contaminated soil was removed?", ["search_spill_reports"],
               [[(int((r["soil_removed"] == "yes").sum()), 0), (dug, 0)]]),        # soil removed, or excavated soil
              ("Find spill reports where a landowner or farmer found the oil.", ["search_spill_reports"], [])]
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


def ask(url: str, question: str) -> dict:
    req = urllib.request.Request(url + "/api/ask", data=json.dumps({"question": question}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1800) as r:
        return json.loads(r.read())


def main(a):
    t = tables()
    model = json.loads(urllib.request.urlopen(a.url + "/api/status", timeout=10).read())["model"]
    rows = []
    for k, (question, tools, expected) in enumerate(bank(t), 1):
        if a.only and k not in a.only:
            continue
        t0 = time.time()
        try:
            res = ask(a.url, question)
        except Exception as e:
            res = {"answer": "", "steps": [], "numbers": {"unsupported": ["(error)"]}, "error": str(e)}
        used = [s["tool"] for s in res.get("steps", [])]
        got = res.get("answer", "")
        ok_tool = any(x in used for x in tools)
        ok_answer = all(matches(got, e) for e in expected)
        ok_numbers = not res.get("numbers", {}).get("unsupported")
        rows.append({"k": k, "question": question, "tools_used": " ".join(used), "tool_ok": ok_tool, "answer_ok": ok_answer,
                     "numbers_ok": ok_numbers, "unsupported": " ".join(res.get("numbers", {}).get("unsupported", [])),
                     "seconds": round(time.time() - t0, 1), "answer": got})
        print(f"{k:2d} tool {'ok' if ok_tool else '--'} | answer {'ok' if ok_answer else '--'} | numbers "
              f"{'ok' if ok_numbers else '--'} | {rows[-1]['seconds']:5.1f} s | {question[:70]}", flush=True)
    out = pd.DataFrame(rows)
    DISC.mkdir(parents=True, exist_ok=True)
    out.to_csv(DISC / f"agent_eval_{model.replace(':', '_')}.csv", index=False)
    summary = {"model": model, "date": time.strftime("%Y-%m-%d %H:%M"), "questions": len(out),
               "tool_ok": round(out["tool_ok"].mean(), 3), "answer_ok": round(out["answer_ok"].mean(), 3),
               "numbers_ok": round(out["numbers_ok"].mean(), 3), "median_seconds": float(out["seconds"].median())}
    f = DISC / "agent_eval_summary.csv"
    previous = [pd.read_csv(f)] if f.exists() else []
    pd.concat(previous + [pd.DataFrame([summary])], ignore_index=True).to_csv(f, index=False)
    print(json.dumps(summary))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default="http://127.0.0.1:8392")
    ap.add_argument("--only", nargs="*", type=int)
    main(ap.parse_args())
