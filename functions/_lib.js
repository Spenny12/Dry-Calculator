// Shared helpers for the Temple proxy functions.
const UA = 'Dry-Calculator/2.0 (+https://github.com/Spenny12/Dry-Calculator)';
const NAME_RE = /^[A-Za-z0-9 _-]{1,12}$/;

export function json(body, status = 200, extra = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8', ...extra },
  });
}

export function validName(raw) {
  const name = (raw || '').trim();
  return NAME_RE.test(name) ? name : null;
}

// Fetch upstream with the Cloudflare edge cache in front of it.
export async function cachedUpstream(context, url, ttl = 3600) {
  const cache = caches.default;
  const key = new Request(url, { method: 'GET' });
  const hit = await cache.match(key);
  if (hit) {
    const r = new Response(hit.body, hit);
    r.headers.set('x-cache', 'HIT');
    return r;
  }
  let upstream;
  try {
    upstream = await fetch(url, { headers: { 'user-agent': UA, accept: 'application/json' } });
  } catch (e) {
    return json({ error: 'Could not reach TempleOSRS' }, 502);
  }
  const text = await upstream.text();
  let parsed = null;
  try { parsed = JSON.parse(text); } catch { /* not json */ }
  if (!upstream.ok || parsed === null) {
    const msg = upstream.status === 404 ? 'Player not found on TempleOSRS (try updating them there first)' : `TempleOSRS returned ${upstream.status}`;
    return json({ error: msg }, upstream.status === 404 ? 404 : 502);
  }
  if (parsed && typeof parsed === 'object' && parsed.error) {
    return json({ error: String(parsed.error.Message || parsed.error) }, 404);
  }
  const res = json(parsed, 200, { 'cache-control': `public, max-age=${ttl}`, 'x-cache': 'MISS' });
  context.waitUntil(cache.put(key, res.clone()));
  return res;
}
