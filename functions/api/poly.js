// Cloudflare Pages Function: live Polymarket prices (public API, no key) for the page's markets.
// /api/poly?ids=123,456 -> {"123": {bid: 20, ask: 21}} in cents, for each market's FIRST outcome.
const CHUNK = 50;

export async function onRequestGet({ request }) {
  const ids = (new URL(request.url).searchParams.get("ids") || "").split(",").map(t => t.trim()).filter(t => /^\d+$/.test(t));
  const json = (body, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "cache-control": "no-store" } });
  if (!ids.length) return json({});
  const get = async c => {
    const url = "https://gamma-api.polymarket.com/markets?limit=" + c.length + "&" + c.map(i => "id=" + i).join("&");
    for (let i = 0; i < 3; i++) {
      const r = await fetch(url, { headers: { accept: "application/json" } });
      if (r.ok) return r.json();
      if (r.status !== 429) return null;
      await new Promise(res => setTimeout(res, 600 * (i + 1)));
    }
    return null;
  };
  const chunks = [];
  for (let i = 0; i < ids.length; i += CHUNK) chunks.push(ids.slice(i, i + CHUNK));
  const results = [];
  for (let i = 0; i < chunks.length; i += 3) results.push(...await Promise.all(chunks.slice(i, i + 3).map(get)));
  if (results.every(d => d == null)) return json({ error: "polymarket unavailable" }, 502);
  const out = {};
  for (const d of results) for (const m of d || []) {
    if (m.bestBid == null && m.bestAsk == null) continue;
    out[m.id] = { bid: m.bestBid != null ? Math.round(Number(m.bestBid) * 1000) / 10 : 0, ask: m.bestAsk != null ? Math.round(Number(m.bestAsk) * 1000) / 10 : 100 };
  }
  return json(out);
}
