"""Hyperspectral add-on: EMIT surface reflectance (ISS, 60 m, 285 bands, 381-2493 nm, Aug 2022 on) at the reported
spills and their same-line candidate spots, through NASA's AppEEARS point service.

  1. NASA's public catalog (CMR) finds the spills that EMIT imaged at least once before and once after the spill.
  2. One AppEEARS point request: the spill site and its 12 candidate spots on the same line (0.5 to 3 km each way,
     outputs/zones/statewide/spills_statewide.gpkg), every EMIT scene since Aug 2022, all 285 reflectance bands and
     EMIT's own cloud masks. The analysis applies the spill matching (strict or broad) afterwards.
  3. --fetch waits for the request and saves its tables in outputs/emit.
The Earthdata login comes from the user's saved _netrc (earthaccess.login(persist=True)); it is never printed.

Usage: python emit_points.py --submit      then      python emit_points.py --fetch
"""
import argparse
import json
import netrc
import time
import urllib.parse
import urllib.request
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

P = Path(r"C:\mydrive\Graduate School\Courses\GEOG_392\projects")
OUT = P / "outputs" / "emit"
API = "https://appeears.earthdatacloud.nasa.gov/api"
CMR = "https://cmr.earthdata.nasa.gov/search/granules.json"
START = "2022-08-09"


def token() -> str:
    for name in ("_netrc", ".netrc"):
        f = Path.home() / name
        if f.exists():
            user, _, password = netrc.netrc(f).authenticators("urs.earthdata.nasa.gov")
            r = requests.post(f"{API}/login", auth=(user, password), timeout=60)
            r.raise_for_status()
            return r.json()["token"]
    raise SystemExit("no saved Earthdata login: run earthaccess.login(strategy='interactive', persist=True) first")


def scene_dates(lon, lat) -> list[str]:
    q = urllib.parse.urlencode({"short_name": "EMITL2ARFL", "point": f"{lon},{lat}", "page_size": 2000,
                                "temporal": f"{START}T00:00:00Z,{pd.Timestamp.today():%Y-%m-%d}T23:59:59Z"})
    with urllib.request.urlopen(f"{CMR}?{q}", timeout=60) as r:
        return [e["time_start"][:10] for e in json.load(r)["feed"]["entry"]]


def submit(parts: int):
    OUT.mkdir(parents=True, exist_ok=True)
    sites = gpd.read_file(P / "outputs" / "zones" / "statewide" / "spills_statewide.gpkg", layer="sites").to_crs(4326)
    spills = pd.read_parquet(P / "outputs" / "agent" / "spills.parquet", columns=["spill_id", "date", "lon", "lat"])
    keep, cover = [], []
    for s in spills.itertuples():
        d = scene_dates(s.lon, s.lat)
        day = str(s.date)[:10]
        before, after = sum(x < day for x in d), sum(x > day for x in d)
        cover.append({"spill_id": s.spill_id, "date": day, "scenes": len(d), "before": before, "after": after})
        if before and after:
            keep.append(s.spill_id)
        time.sleep(0.2)
    pd.DataFrame(cover).to_csv(OUT / "emit_coverage.csv", index=False)
    layers = [{"product": "EMIT_L2A_RFL.001", "layer": f"B{i:03d}"} for i in range(1, 286)]
    layers += [{"product": "EMIT_L2A_MASK.001", "layer": m} for m in ("aggregate_flag", "dilated_cloud_flag", "cloud_flag")]
    dates = [{"startDate": pd.Timestamp(START).strftime("%m-%d-%Y"), "endDate": pd.Timestamp.today().strftime("%m-%d-%Y")}]
    head = {"Authorization": f"Bearer {token()}"}
    tasks = []
    for k in range(parts):                       # AppEEARS caps the values per request, so the spills go in parts
        group = keep[k::parts]
        pts = sites[sites["spill_id"].isin(group) & sites["site"].isin(["spill", "candidate"])]
        coords = [{"id": r.site_id, "category": r.spill_id, "latitude": round(r.geometry.y, 6),
                   "longitude": round(r.geometry.x, 6)} for r in pts.itertuples()]
        task = {"task_type": "point", "task_name": f"geog392_emit_spills_{k + 1}",
                "params": {"dates": dates, "layers": layers, "coordinates": coords}}
        r = requests.post(f"{API}/task", json=task, headers=head, timeout=120)
        if not r.ok:
            raise SystemExit(f"AppEEARS refused part {k + 1}: {r.status_code} {r.text[:500]}")
        tasks.append({"task_id": r.json()["task_id"], "spills": group, "points": len(coords)})
        print(f"submitted part {k + 1}: task {tasks[-1]['task_id']}, {len(group)} spills, {len(coords)} points")
    info = {"tasks": tasks, "layers": len(layers), "submitted": pd.Timestamp.now().isoformat()}
    (OUT / "task.json").write_text(json.dumps(info, indent=2))


def fetch(wait_minutes: int):
    info = json.loads((OUT / "task.json").read_text())
    head = {"Authorization": f"Bearer {token()}"}
    for k, t in enumerate(info["tasks"], 1):
        for _ in range(wait_minutes):
            st = requests.get(f"{API}/task/{t['task_id']}", headers=head, timeout=60).json()
            if st.get("status") in ("done", "error"):
                break
            time.sleep(60)
        print(f"part {k}: AppEEARS status {st.get('status')}")
        if st.get("status") != "done":
            continue
        files = requests.get(f"{API}/bundle/{t['task_id']}", headers=head, timeout=60).json()["files"]
        for f in files:
            if f["file_name"].endswith((".csv", ".json", ".txt")):
                r = requests.get(f"{API}/bundle/{t['task_id']}/{f['file_id']}", headers=head, timeout=900, allow_redirects=True)
                name = f"part{k}_{Path(f['file_name']).name}"
                (OUT / name).write_bytes(r.content)
                print("  saved", name, f"{len(r.content) / 1e6:.1f} MB")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--submit", action="store_true")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--parts", type=int, default=3, help="requests to split the spills into (AppEEARS caps each one)")
    ap.add_argument("--wait", type=int, default=600, help="minutes to wait for each AppEEARS request with --fetch")
    a = ap.parse_args()
    submit(a.parts) if a.submit else fetch(a.wait) if a.fetch else ap.print_help()
