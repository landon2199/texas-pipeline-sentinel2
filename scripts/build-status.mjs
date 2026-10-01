// Builds data/status.json for the team dashboard: the list of people who have checked in.
// Reads this repository's issues labelled "join" from the GitHub API (read-only) and writes one
// JSON file the pages load. Run by .github/workflows/status.yml.
// Drafted with Claude (Anthropic), 2026-10-01.
import { writeFile, mkdir } from 'node:fs/promises';

const SELF = process.env.GITHUB_REPOSITORY || 'landon2199/texas-pipeline-sentinel2';
const TOKEN = process.env.GITHUB_TOKEN;

async function api(path) {
  const res = await fetch(`https://api.github.com/${path}`, {
    headers: {
      Accept: 'application/vnd.github+json',
      'User-Agent': 'group10-dashboard',
      ...(TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {})
    }
  });
  if (!res.ok) {
    console.warn(`GitHub answered ${res.status} for ${path}`);
    return null;
  }
  return res.json();
}

// Who has checked in: issues labelled "join" in this repository. Pull requests are excluded.
const joinIssues = await api(`repos/${SELF}/issues?labels=join&state=all&per_page=100`);
if (!joinIssues) {
  // Keep the last good file rather than publishing an empty team.
  console.error('Could not read the check-ins; leaving data/status.json as it is.');
  process.exit(0);
}
const joined = joinIssues
  .filter((i) => !i.pull_request)
  .map((i) => ({ github: i.user.login, body: i.body ?? '', at: i.created_at, url: i.html_url }));

await mkdir('data', { recursive: true });
await writeFile('data/status.json', JSON.stringify({ generated: new Date().toISOString(), joined }, null, 2) + '\n');
console.log(`status.json written: ${joined.length} check-ins`);
