"""Download the Railroad Commission's pipeline layers by county (one zip per county) from its GoAnywhere file site.

The site (linked from rrc.texas.gov, "Data Sets Available for Download", "Pipeline Layers by County") is a JSF/PrimeFaces
page. Each file link posts the page's `fileList` form back with that row's link id, and the server answers with the zip.
This script does the same, one file at a time with a pause between files, and writes a manifest (file, the size and date
the site lists, bytes received, SHA-256, time) so the download can be cited and checked later.

Usage: python download_rrc_pipelines.py <output folder>
"""
import csv
import datetime as dt
import hashlib
import html
import http.cookiejar
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

LINK = "https://mft.rrc.texas.gov/link/c7cbab0c-afe2-4f6f-91ae-e6ed7d3a7ab6"
ACTION = "https://mft.rrc.texas.gov/webclient/godrive/PublicGoDrive.xhtml"
UA = "Mozilla/5.0 (compatible; Texas A&M GEOG 392 student research)"
PAUSE = 1.5           # seconds between requests, to be gentle with the site
PAGE_ROWS = 250
ROW = re.compile(r'<a id="(fileTable:\d+:j_id_\w+)"[^>]*>([^<]+)</a></td><td role="gridcell" class="ModifiedOnColumn">'
                 r'([^<]+)</td><td role="gridcell" class="SizeColumn">([^<]+)</td>')
VIEWSTATE = re.compile(r'name="javax\.faces\.ViewState"[^>]*value="([^"]+)"')
PARTIAL_VIEWSTATE = re.compile(r'<update id="[^"]*javax\.faces\.ViewState[^"]*"><!\[CDATA\[(.*?)\]\]>', re.S)
TOTAL = re.compile(r"Showing \d+ - \d+ of (\d+)")


def make_opener():
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    op.addheaders = [("User-Agent", UA)]
    return op


def post(op, fields: dict, ajax: bool = False):
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(ACTION, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    if ajax:
        req.add_header("Faces-Request", "partial/ajax")
        req.add_header("X-Requested-With", "XMLHttpRequest")
    return op.open(req, timeout=300)


def rows_of(text: str) -> list[tuple[str, str, str, str]]:
    return [(i, html.unescape(n), m, s) for i, n, m, s in ROW.findall(text)]


def open_listing(op) -> tuple[str, list, int]:
    page = op.open(LINK, timeout=120).read().decode("utf-8", errors="replace")
    total = int(TOTAL.search(page).group(1))
    return VIEWSTATE.search(page).group(1), rows_of(page), total


def next_page(op, viewstate: str, first: int) -> tuple[str, list]:
    """Ask the table for the rows starting at `first`, the way its paginator does."""
    fields = {"javax.faces.partial.ajax": "true", "javax.faces.source": "fileTable",
              "javax.faces.partial.execute": "fileTable", "javax.faces.partial.render": "fileTable",
              "javax.faces.behavior.event": "page", "javax.faces.partial.event": "page",
              "fileTable_pagination": "true", "fileTable_first": str(first), "fileTable_rows": str(PAGE_ROWS),
              "fileTable_skipChildren": "true", "fileTable_encodeFeature": "true",
              "fileList": "fileList", "fileList_SUBMIT": "1", "javax.faces.ViewState": viewstate}
    text = post(op, fields, ajax=True).read().decode("utf-8", errors="replace")
    vs = PARTIAL_VIEWSTATE.search(text)
    return (vs.group(1) if vs else viewstate), rows_of(text)


def fetch(op, viewstate: str, link_id: str, name: str, out: Path) -> tuple[int, str]:
    resp = post(op, {"fileList": "fileList", "fileList_SUBMIT": "1", "javax.faces.ViewState": viewstate, link_id: link_id})
    kind = resp.headers.get("Content-Type", "")
    disposition = resp.headers.get("Content-Disposition", "")
    body = resp.read()
    if "html" in kind or not body.startswith(b"PK") or (disposition and name not in disposition):
        raise RuntimeError(f"{name}: the site answered with {kind or 'something else'}, not the zip")
    out.write_bytes(body)
    return len(body), hashlib.sha256(body).hexdigest()


def main(folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    op = make_opener()
    viewstate, rows, total = open_listing(op)
    print(f"{total} files listed; {len(rows)} on the first page", flush=True)
    manifest, done = [], 0
    pages = [(0, rows)]
    first = PAGE_ROWS
    while sum(len(r) for _, r in pages) < total:
        time.sleep(PAUSE)
        viewstate, more = next_page(op, viewstate, first)
        if not more:
            raise RuntimeError(f"could not read the rows from {first}")
        pages.append((first, more))
        first += PAGE_ROWS
    # Download page by page: the server's table state must be on the page whose links we post.
    for start, page_rows in pages:
        if start:
            time.sleep(PAUSE)
            viewstate, _ = next_page(op, viewstate, start)
        else:
            viewstate, _, _ = open_listing(op)
        for link_id, name, modified, size in page_rows:
            target = folder / name
            for attempt in (1, 2):
                try:
                    nbytes, sha = fetch(op, viewstate, link_id, name, target)
                    break
                except Exception as e:
                    if attempt == 2:
                        raise
                    print(f"  retrying {name}: {e}", flush=True)
                    time.sleep(5)
                    viewstate, _, _ = open_listing(op) if not start else (next_page(op, viewstate, start)[0], None, None)
            manifest.append({"file": name, "listed_modified": modified, "listed_size": size, "bytes": nbytes,
                             "sha256": sha, "downloaded_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")})
            done += 1
            if done % 25 == 0 or done == total:
                print(f"  {done}/{total} files", flush=True)
            time.sleep(PAUSE)
    with open(folder / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(manifest[0]))
        w.writeheader()
        w.writerows(manifest)
    print(f"done: {len(manifest)} files, {sum(m['bytes'] for m in manifest) / 1e6:,.1f} MB, manifest at {folder / 'manifest.csv'}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
