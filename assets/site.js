// Shared helpers for the team dashboard pages. Drafted with Claude (Anthropic), 2026-10-01.
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const day = (d) => new Date(d + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
const pill = (text, cls = '') => `<span class="pill ${cls}">${esc(text)}</span>`;

// The words and colours for each `status` value used in team.json.
const STATES = {
  found: ['Found', ''], confirmed: ['Confirmed', 'warn'], fixed: ['Fixed', 'good'], handed: ['Handed over', 'good'],
  todo: ['To do', ''], doing: ['In progress', 'warn'], done: ['Done', 'good']
};
const state = (s) => pill(...(STATES[s] ?? [s, '']));

// Issue forms store answers as "### Label\n\nanswer".
function formAnswers(body) {
  const out = {};
  for (const part of String(body).split(/^### /m).slice(1)) {
    const [label, ...rest] = part.split('\n');
    out[label.trim()] = rest.join('\n').trim();
  }
  return out;
}

function repoSlug() {
  return location.hostname.endsWith('github.io')
    ? `${location.hostname.split('.')[0]}/${location.pathname.split('/')[1]}`
    : 'landon2199/texas-pipeline-sentinel2';
}

// Draws the top bar. `base` is '' on the home page and '../' on the deeper pages.
function topBar(active, base) {
  const link = (key, href, text) => `<a class="${active === key ? 'on' : ''}" href="${href}">${text}</a>`;
  document.getElementById('top').innerHTML = `<div class="wrap">
    <a class="brand" href="${base || './'}">GEOG 392 <span>· Pipeline Monitoring</span></a>
    <nav>${link('home', base || './', 'Home')}${link('plan', base + 'plan/', 'Plan')}</nav>
  </div>`;
  // A site-wide notice: shown on every page while team.json has a `notice`; empty it to remove it.
  fetch(base + 'team.json?t=' + Date.now()).then((r) => r.json()).then((team) => {
    if (!team.notice) return;
    const bar = document.createElement('div');
    bar.className = 'notice';
    bar.innerHTML = `<div class="wrap">${esc(team.notice)}</div>`;
    document.getElementById('top').after(bar);
  }).catch(() => {});
}

// Loads team.json and data/status.json and merges the roster with everyone who checked in.
async function loadData(base) {
  const bust = '?t=' + Date.now();
  const team = await (await fetch(base + 'team.json' + bust)).json();
  let status = { joined: [] };
  try { status = await (await fetch(base + 'data/status.json' + bust)).json(); } catch (e) { /* before the first refresh */ }

  const people = new Map();
  for (const m of team.members) people.set(m.github.toLowerCase(), { ...m });
  for (const j of status.joined ?? []) {
    const key = j.github.toLowerCase();
    const a = formAnswers(j.body);
    const p = people.get(key) ?? { github: j.github, group: 'Unassigned' };
    people.set(key, { ...p, name: p.name || a['Name to show'] || j.github, checkedIn: true,
      interest: a['Which work interests you most'], computer: a['Computer'], ee: a['Earth Engine account'] });
  }

  const today = new Date(); today.setHours(12, 0, 0, 0);
  return { team, status, people: [...people.values()], today, iso: today.toISOString().slice(0, 10) };
}

const groupName = (team, key) => (team.groups ?? []).find((g) => g.key === key)?.name ?? key;

// The four numbers that sum up the team's impact, all read from team.json. A problem counts as
// confirmed once its status has moved past "found"; a report counts once its `url` is filled in.
function impactTiles(team) {
  const problems = team.problems ?? [];
  const reports = (team.groups ?? []).filter((g) => g.report);
  const tiles = [
    [problems.length, 'known problems to fix'],
    [problems.filter((p) => p.status !== 'found').length, 'confirmed on the full data'],
    [problems.filter((p) => p.status === 'fixed' || p.status === 'handed').length, 'fixed in the new pipeline'],
    [`${reports.filter((g) => g.report.url).length} of ${reports.length}`, 'reports delivered']
  ];
  return tiles.map(([n, label]) => `<div><b>${esc(n)}</b><span class="small">${esc(label)}</span></div>`).join('');
}

// One line for a group's report: a link once it is posted, otherwise just its name.
function reportLine(g) {
  if (!g.report) return '';
  const r = g.report;
  return /^https:\/\//.test(r.url ?? '')
    ? `<p class="small report">${pill('Posted', 'good')} <a href="${esc(r.url)}">${esc(r.name)}</a></p>`
    : `<p class="small report">${pill('Report')} ${esc(r.name)}</p>`;
}

// One row for a person: picture, name and what they are working on.
function personRow(p) {
  return `<div class="person">
    <img src="https://github.com/${esc(p.github)}.png?size=80" alt="">
    <div class="who"><b>${esc(p.name || p.github)}</b><span>${esc(p.task || 'No task yet')}</span></div>
  </div>`;
}
