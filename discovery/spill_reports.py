"""Discovery, spill reports: read the PHMSA narratives with a local language model and make them searchable.

For each Texas right-of-way spill of crude or refined fuel (5 barrels or more, the proposal's set) this:
  1. keeps the report's facts and its narrative, without the names and contact details of the people who filed it;
  2. asks a local model (Ollama, qwen2.5:14b by default) for fixed fields: a one-sentence summary, how the spill was
     found, the cleanup actions, whether soil was removed, whether it reached water and whether plants or crops are
     mentioned, each with a short quote from the narrative as evidence;
  3. checks every quote against the narrative: an answer whose quote is not in the text is marked unsupported;
  4. embeds each narrative with nomic-embed-text, so the agents can search them by meaning.
Runs on this computer only: the narratives never leave it.

Usage: python spill_reports.py [--limit 3] [--model qwen2.5:14b]
"""
import argparse
import json
import os
import re
import time
import urllib.request
from pathlib import Path

import pandas as pd

PROJECT = Path(r"C:\mydrive\Graduate School\Courses\GEOG_392\projects")
RAW = PROJECT / "data" / "phmsa" / "accident_hazardous_liquid_jan2010_present.txt"
SPILLS = PROJECT / "outputs" / "agent" / "spills.parquet"
OUT = PROJECT / "outputs" / "discovery" / "spill_reports.parquet"
KEEP = ["REPORT_NUMBER", "LOCAL_DATETIME", "NAME", "COMMODITY_RELEASED_TYPE", "UNINTENTIONAL_RELEASE_BBLS",
        "RECOVERED_BBLS", "LOCATION_TYPE", "ONSHORE_COUNTY_NAME", "CAUSE", "CAUSE_DETAILS", "LOCATION_LATITUDE",
        "LOCATION_LONGITUDE", "NARRATIVE"]          # NAME is the operator; no preparer or contact fields
FOUND = ["operator patrol or personnel", "control room or alarm", "landowner or public", "third party contractor",
         "inspection or testing", "unknown"]
ACTIONS = ["excavated soil", "vacuum truck", "absorbent", "booms", "burned", "soil treated on site",
           "water recovered", "repaired or replaced pipe", "none stated"]
YES_NO = ["yes", "no", "unknown"]
EVIDENCE = ["how_found", "cleanup_actions", "soil_removed", "reached_water", "plants_or_crops_mentioned"]
SCHEMA = {                      # each field: a quote copied from the narrative first, then the answer it supports
    "type": "object",
    "properties": {
        **{k: {"type": "object", "properties": {"quote": {"type": "string"}, "answer": v}, "required": ["quote", "answer"]}
           for k, v in {"how_found": {"type": "string", "enum": FOUND},
                        "cleanup_actions": {"type": "array", "items": {"type": "string", "enum": ACTIONS}, "maxItems": len(ACTIONS)},
                        "soil_removed": {"type": "string", "enum": YES_NO},
                        "reached_water": {"type": "string", "enum": YES_NO},
                        "plants_or_crops_mentioned": {"type": "string", "enum": YES_NO}}.items()},
        "summary": {"type": "string"},
    },
    "required": EVIDENCE + ["summary"],
}
PROMPT = """You read pipeline spill reports filed with PHMSA. Answer only from the narrative below.

Every field has a "quote" and an "answer". The quote is a few words copied character for character from the
narrative that support the answer: words from the report, never the answer itself. Use "" when the narrative does not
say. The answers:
- how_found: who or what first detected the release. If several are mentioned, choose the one that detected it first.
  "operator patrol or personnel" = company employees, patrols or technicians found it on site;
  "control room or alarm" = a control center, SCADA, a pressure drop, a leak detection system or an alarm;
  "landowner or public" = a landowner, resident, rancher, farmer, passerby or a 911 call;
  "third party contractor" = a crew not working for the operator, for example one that struck the line;
  "inspection or testing" = in-line inspection, a hydrostatic test or an aerial survey;
  "unknown" = the narrative does not say.
- cleanup_actions: every cleanup action the narrative states; several may apply. Use "excavated soil" only when
  contaminated soil was dug up or removed, not when the pipe was only exposed for repair. Use "repaired or replaced
  pipe" when the pipe was clamped, repaired or a section replaced. Use ["none stated"] only when no action is stated,
  never together with other actions.
- soil_removed: "yes" if contaminated soil was removed or excavated, "no" if the narrative says none was, else "unknown".
- reached_water: "yes" if product reached a creek, river, pond, lake or groundwater, "no" if the narrative says it did
  not, else "unknown".
- plants_or_crops_mentioned: "yes" if vegetation, grass, crops, pasture or trees are mentioned as affected, else "unknown".
- summary: one plain sentence under 30 words on what happened and what was done.

Narrative:
{text}"""


def ollama_url() -> str:
    host = os.environ.get("OLLAMA_HOST") or (Path.home() / ".geog392" / "ollama_host.txt").read_text().strip()
    host = host if host.startswith("http") else "http://" + host
    return host.rstrip("/")


def post(path: str, body: dict, timeout=600) -> dict:
    req = urllib.request.Request(ollama_url() + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def supported(quote: str, text: str) -> bool:
    """A quote counts only if it appears in the narrative (ignoring case, spacing and punctuation)."""
    q = norm(quote)
    return bool(q) and q in norm(text)


def extract(text: str, model: str) -> dict:
    r = post("/api/chat", {"model": model, "stream": False, "format": SCHEMA,
                           "options": {"temperature": 0, "seed": 392, "num_ctx": 8192, "num_predict": 700},   # a stuck list cannot run forever
                           "messages": [{"role": "user", "content": PROMPT.format(text=text[:6000])}]})
    raw = json.loads(r["message"]["content"])
    out = {"summary": raw.get("summary", ""), "evidence": {}}
    for field in EVIDENCE:
        part = raw.get(field) or {}
        answer, quote = part.get("answer"), part.get("quote", "")
        out[field], out["evidence"][field] = answer, quote
        claims = answer not in ("unknown", ["none stated"], [], None)
        out[f"{field}_supported"] = (not claims) or supported(quote, text)
    return out


def main(a):
    raw = pd.read_csv(RAW, sep="\t", encoding="latin-1", low_memory=False, usecols=lambda c: c in KEEP + ["ONSHORE_STATE_ABBREVIATION"])
    tx = raw[raw["ONSHORE_STATE_ABBREVIATION"].astype(str).eq("TX")].drop(columns="ONSHORE_STATE_ABBREVIATION")
    row = (tx["LOCATION_TYPE"].fillna("").str.contains("RIGHT-OF-WAY")
           & tx["COMMODITY_RELEASED_TYPE"].fillna("").str.contains("CRUDE|REFINED|BIOFUEL")
           & (tx["UNINTENTIONAL_RELEASE_BBLS"] >= 5))
    d = tx[row].copy()
    d["date"] = pd.to_datetime(d["LOCAL_DATETIME"], errors="coerce")
    spills = pd.read_parquet(SPILLS)[["spill_id", "report_number"]]
    as_text = lambda s: s.astype(str).str.replace(r"\.0$", "", regex=True)       # noqa: E731  (numbers in one file, text in the other)
    d["REPORT_NUMBER"], spills["report_number"] = as_text(d["REPORT_NUMBER"]), as_text(spills["report_number"])
    d = d.merge(spills, left_on="REPORT_NUMBER", right_on="report_number", how="left").drop(columns="report_number")
    d = d.sort_values("date", ascending=False).reset_index(drop=True)
    if a.limit:
        d = d.head(a.limit)
    print(f"{len(d)} right-of-way spills of 5+ barrels; {d['spill_id'].notna().sum()} of them are in our spill study")
    rows, t0 = [], time.time()
    for i, r in d.iterrows():
        text = str(r["NARRATIVE"] or "")
        try:
            ex = extract(text, a.model) if text.strip() else {"summary": "", "how_found": "unknown", "cleanup_actions": []}
        except Exception as e:                 # one bad report is recorded and skipped, not the whole run
            ex = {"summary": "", "extraction_error": f"{type(e).__name__}: {str(e)[:200]}"}
            print(f"  {r['REPORT_NUMBER']}: {ex['extraction_error']}", flush=True)
        rows.append({**r.to_dict(), **{k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in ex.items()}})
        if a.limit or (i + 1) % 10 == 0:
            print(f"  {i + 1}/{len(d)} ({time.time() - t0:.0f} s)", (ex.get("summary") or "")[:110], flush=True)
    out = pd.DataFrame(rows)
    texts = ["search_document: " + str(t) for t in out["NARRATIVE"].fillna("")]
    vecs = []
    for k in range(0, len(texts), 32):
        vecs += post("/api/embed", {"model": "nomic-embed-text", "input": texts[k:k + 32]})["embeddings"]
    out["embedding"] = vecs
    OUT.parent.mkdir(parents=True, exist_ok=True)
    target = OUT.with_name(OUT.stem + "_test.parquet") if a.limit else OUT
    out.to_parquet(target, index=False)
    flags = [c for c in out.columns if c.endswith("_supported")]
    print(f"wrote {target}: {len(out)} reports; answers with a matching quote: "
          f"{out[flags].mean().mean():.0%}; model {a.model}; {time.time() - t0:.0f} s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, default=0, help="only the newest N reports, written to a _test file")
    ap.add_argument("--model", default="qwen2.5:14b")
    main(ap.parse_args())
