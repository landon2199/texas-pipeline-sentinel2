# Can Satellites See Pipeline Leaks?

GEOG 392, Group 10, fall 2026.

## [Open the team dashboard](https://landon2199.github.io/texas-pipeline-sentinel2/)

The dashboard shows the plan, the groups, everyone's tasks and the dates.

**You do not need to know GitHub.** Everything you work with is in our shared Google Drive folder,
**projects**: open the **START HERE** file at the top of that folder.

---

## For the code

This repository keeps the project's Python code. We test whether Sentinel-2 imagery shows the
effects of Texas pipelines, and of reported spills, on vegetation from 2018 to 2026, comparing
strips of land beside each pipeline with similar land farther away. Everything runs in Python,
using the Earth Engine Python API for the imagery.

This repository is public, and so is the dashboard. Anyone can read what is here, so never commit
credentials or anything you would not want shared.

## What is where

| Folder or file | What it holds |
|---|---|
| `index.html`, `plan/`, `assets/` | The team dashboard: Home (what to do now) and Plan (groups, tasks, dates) |
| `team.json` | Everything the dashboard shows: notice, meetings, groups, tasks, known problems, timeline |
| `data/status.json` | Who has checked in. Rebuilt automatically; do not edit |
| `legacy-2025/` | Last year's Earth Engine script, notebook, sample tables, and a summary of what went wrong |
| `audit/` | Scripts that checked last year's tables and geodatabase, their results, and the findings in `audit/README.md` |
| `extract/` | The Earth Engine Python program (Sentinel-2, with Landsat as an option for earlier years) that computes vegetation and moisture for each polygon, and a check against last year |
| `leaks/` | Reported pipeline spills from PHMSA, matched to the Railroad Commission lines, and the proposal figure |
| `requirements.txt` | The Python packages to install: `pip install -r requirements.txt` |

Large data does not go in this repository. Last year's full project is in the shared Google Drive
folder `GEOG_392/projects/data`. New outputs go in that Drive folder or in Earth Engine assets.

## How we work together

1. **Get access.** Anyone can read the repository. To push branches, send Landon your GitHub
   username to be added as a collaborator. For Earth Engine, send Landon the Google account you
   use for Colab; Landon adds it to the team's Cloud project.
2. **Check in (optional).** Open a new issue with the **Check in** form. It puts you on the dashboard.
3. **Take a task.** Tasks are listed in `team.json` and on the Plan page. Say in the team chat
   which one you are starting.
4. **Work on a branch.** Never commit straight to `main`.

   ```
   git checkout -b ids-stable-segments
   git add .
   git commit -m "Give each segment one ID for all distances"
   git push -u origin ids-stable-segments
   ```

5. **Open a pull request** and ask one teammate to review it. Merge once they approve.
6. **Questions and bugs** go in GitHub issues, so the answer stays findable.

### Never commit

- Passwords, API keys, or Earth Engine credential and service account files.
- Large data: shapefiles, geodatabases, rasters, or tables over a few MB.

`.gitignore` blocks the common cases, but check `git status` before every commit.

## Viewing the dashboard

The pages load `team.json` and `data/status.json` from the same folder, so they work wherever the
folder is served.

- **As a website:** https://landon2199.github.io/texas-pipeline-sentinel2/ once GitHub Pages is
  turned on: Settings, then Pages, **Deploy from a branch**, `main`, root. Changes to `main` appear
  there within a couple of minutes.
- **On your own computer:** from the repository folder run `python -m http.server`, then open
  http://localhost:8000. Opening `index.html` directly from the file browser will not load the data.

## Editing `team.json`

**Put someone in a group and give them a task:**

```json
{ "github": "their-username", "name": "First name", "group": "A", "task": "Build the reference ring" }
```

`group` is the `key` of one of the entries under `groups` (`A`, `B` or `C`), or `Lead`.

**Move a task or a problem along:** change its `status`.

- Tasks: `todo`, `doing`, `done`.
- Problems: `found` (seen in the audit), `confirmed` (checked on the full data), `fixed` (the new
  pipeline handles it and a test shows it).

**Record a delivered report:** paste its link into that group's `report.url`.

**Change the notice:** edit the `notice` text, or set it to `""` to remove the bar.

**Meetings:** each meeting has its own poll and is numbered by its place in the list. Add a line for
a new meeting with its Rallly link. Once the time is set, fill in `when` and `where`. After the
meeting, set `done` to `true` and keep the line.

After any change, open Home and Plan and click every link and button. The old `tasks/` address redirects to Plan.

## The check-in refresh

`.github/workflows/status.yml` runs `scripts/build-status.mjs` whenever someone submits or edits a
check-in, or when `team.json` changes on `main`. It reads the issues labelled `join` and commits
`data/status.json`. It has no timed schedule because check-ins
trigger it on their own. To refresh by hand, open Actions, choose **Refresh dashboard data**, then **Run workflow**.
