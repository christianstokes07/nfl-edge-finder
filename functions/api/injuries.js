// Cloudflare Pages Function: current NFL injury statuses from ESPN's public feed (free, no key), trimmed
// for the page. Same Cloudflare Access login as the page. Cached at the edge for 5 minutes.
export async function onRequestGet() {
  const json = (body, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "cache-control": "public, max-age=300" } });
  let d;
  try {
    const r = await fetch("https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries",
                          { headers: { accept: "application/json" }, cf: { cacheTtl: 300, cacheEverything: true } });
    if (!r.ok) return json({ error: r.status }, 502);
    d = await r.json();
  } catch (e) {
    return json({ error: "espn unavailable" }, 502);
  }
  return json(trim(d));
}

// {updated, teams: {"Philadelphia Eagles": [{n, pos, s, d, i, c}]}} — s = status, d = when it was updated,
// i = injury, c = latest news note (shortened). "Active" entries are dropped.
function trim(d) {
  const teams = {};
  for (const t of d.injuries || []) {
    const rows = [];
    for (const i of t.injuries || []) {
      if (!i.status || i.status === "Active") continue;
      const a = i.athlete || {};
      rows.push({ n: a.displayName, pos: (a.position || {}).abbreviation || "", s: i.status, d: i.date || null,
                  i: (i.details || {}).type || null, c: (i.shortComment || "").slice(0, 160) });
    }
    teams[t.displayName] = rows;
  }
  return { updated: d.timestamp || new Date().toISOString(), teams };
}
