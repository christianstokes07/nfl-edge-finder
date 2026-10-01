// Cloudflare Pages Function: fetches current Kalshi prices server-side (no CORS issues, no API key).
// Sits behind the same Cloudflare Access login as the page.
export async function onRequestGet({ request }) {
  const tickers = new URL(request.url).searchParams.get("tickers") || "";
  const url = "https://api.elections.kalshi.com/trade-api/v2/markets?limit=1000&tickers=" + encodeURIComponent(tickers);
  const r = await fetch(url, { headers: { accept: "application/json" } });
  const json = (body, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "cache-control": "no-store" } });
  if (!r.ok) return json({ error: r.status }, 502);
  const d = await r.json();
  const cents = (m, k) => (m[k] != null ? Number(m[k]) : m[k + "_dollars"] != null ? Number(m[k + "_dollars"]) * 100 : null);
  const out = {};
  for (const m of d.markets || []) out[m.ticker] = { bid: cents(m, "yes_bid"), ask: cents(m, "yes_ask") };
  return json(out);
}
