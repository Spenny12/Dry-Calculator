import test from 'node:test';
import assert from 'node:assert/strict';

const store = new Map();
globalThis.caches = { default: { match: async (r) => store.get(r.url)?.clone(), put: async (r, res) => { store.set(r.url, res); } } };

test('stats proxy validates, fetches and caches', async () => {
  const { onRequestGet } = await import('../functions/api/stats.js');
  let calls = 0;
  globalThis.fetch = async (url) => { calls++; assert.match(String(url), /player_stats\.php\?player=Zezima&bosses=1/); return new Response(JSON.stringify({ data: { Zulrah: 5 } }), { status: 200 }); };
  const ctx = (u) => ({ request: new Request(u), waitUntil: (p) => p });
  const bad = await onRequestGet(ctx('https://x.test/api/stats?player=../../etc'));
  assert.equal(bad.status, 400);
  const a = await onRequestGet(ctx('https://x.test/api/stats?player=Zezima'));
  assert.equal(a.status, 200);
  await new Promise((r) => setTimeout(r, 10));
  const b = await onRequestGet(ctx('https://x.test/api/stats?player=Zezima'));
  assert.equal(b.headers.get('x-cache'), 'HIT');
  assert.equal(calls, 1);
});

test('clog proxy rejects bad categories and forwards flags', async () => {
  const { onRequestGet } = await import('../functions/api/clog.js');
  globalThis.fetch = async (url) => { assert.match(String(url), /includenames=1/); assert.match(String(url), /includemissingitems=1/); return new Response('{"data":{}}', { status: 200 }); };
  const ctx = (u) => ({ request: new Request(u), waitUntil: (p) => p });
  assert.equal((await onRequestGet(ctx('https://x.test/api/clog?player=A&categories=a;b'))).status, 400);
  assert.equal((await onRequestGet(ctx('https://x.test/api/clog?player=A&categories=zulrah,vorkath'))).status, 200);
});

test('upstream 404 becomes friendly error', async () => {
  const { onRequestGet } = await import('../functions/api/stats.js');
  globalThis.fetch = async () => new Response('nope', { status: 404 });
  const r = await onRequestGet({ request: new Request('https://x.test/api/stats?player=Ghost'), waitUntil: (p) => p });
  assert.equal(r.status, 404);
});
