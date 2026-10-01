// Cloudflare Pages Function: fetches current Kalshi prices server-side (no CORS issues, no API key).
// Sits behind the same Cloudflare Access login as the page. Free: this is Kalshi's public API, not The Odds API.
const CHUNK = 100;

export async function onRequestGet({ request }) {
  const tickers = (new URL(request.url).searchParams.get("tickers") || "").split(",").map(t => t.trim()).filter(Boolean);
  const json = (body, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "cache-control": "no-store" } });
  if (!tickers.length) return json({});
  const cents = (m, k) => (m[k] != null ? Number(m[k]) : m[k + "_dollars"] != null ? Number(m[k + "_dollars"]) * 100 : null);
  const out = {};
  const chunks = [];
  for (let i = 0; i < tickers.length; i += CHUNK) chunks.push(tickers.slice(i, i + CHUNK));
  const results = await Promise.all(chunks.map(async c => {
    const url = "https://api.elections.kalshi.com/trade-api/v2/markets?limit=1000&tickers=" + encodeURIComponent(c.join(","));
    const r = await fetch(url, { headers: { accept: "application/json" } });
    return r.ok ? r.json() : null;
  }));
  if (results.every(d => d == null)) return json({ error: "kalshi unavailable" }, 502);
  for (const d of results) for (const m of (d && d.markets) || []) out[m.ticker] = { bid: cents(m, "yes_bid"), ask: cents(m, "yes_ask") };
  return json(out);
}
