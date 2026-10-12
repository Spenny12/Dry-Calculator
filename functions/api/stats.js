import { json, validName, cachedUpstream } from '../_lib.js';

export async function onRequestGet(context) {
  const url = new URL(context.request.url);
  const player = validName(url.searchParams.get('player'));
  if (!player) return json({ error: 'Invalid player name' }, 400);
  const target = `https://templeosrs.com/api/player_stats.php?player=${encodeURIComponent(player)}&bosses=1`;
  return cachedUpstream(context, target, 1800);
}
