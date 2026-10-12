import { json, validName, cachedUpstream } from '../_lib.js';

const CAT_RE = /^[a-z0-9_']+$/;

export async function onRequestGet(context) {
  const url = new URL(context.request.url);
  const player = validName(url.searchParams.get('player'));
  if (!player) return json({ error: 'Invalid player name' }, 400);
  const cats = (url.searchParams.get('categories') || '').split(',').map((c) => c.trim().toLowerCase()).filter(Boolean);
  if (!cats.length || cats.length > 200 || cats.some((c) => !CAT_RE.test(c))) return json({ error: 'Invalid categories' }, 400);
  const target = new URL('https://templeosrs.com/api/collection-log/player_collection_log.php');
  target.searchParams.set('player', player);
  target.searchParams.set('categories', [...new Set(cats)].sort().join(','));
  target.searchParams.set('includenames', '1');
  target.searchParams.set('includemissingitems', '1');
  return cachedUpstream(context, target.toString(), 1800);
}
