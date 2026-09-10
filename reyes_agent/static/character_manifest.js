// Detects whether real ZENO sprite art has been supplied yet.
//
// Convention (living-character master prompt, Stage A): once cropped
// expression sprites exist, they are described by a manifest at
// /static/character_assets/manifest.json:
//
//   {
//     "version": 1,
//     "sprites": {
//       "neutral": "/static/character_assets/sprites/neutral.png",
//       "happy": "/static/character_assets/sprites/happy.png",
//       ... one entry per sprite category (see resolveSpriteCategory in
//       character_renderers.js for the full category list) ...
//       "_pointing": "/static/character_assets/sprites/pointing.png"
//     }
//   }
//
// Until that file exists, this resolves to null and character.js keeps
// using its built-in CSS/DOM placeholder body -- exactly today's
// behavior, unchanged. Dropping the manifest + PNGs in is the ONLY step
// needed to activate the sprite renderer; no code changes required.
const MANIFEST_URL = "/static/character_assets/manifest.json";

export async function loadCharacterManifest(fetchImpl) {
  const doFetch = fetchImpl || (typeof fetch !== "undefined" ? fetch : null);
  if (!doFetch) return null;
  try {
    const res = await doFetch(MANIFEST_URL, { cache: "no-store" });
    if (!res || !res.ok) return null;
    const data = await res.json();
    if (!data || typeof data !== "object" || !data.sprites || typeof data.sprites !== "object") return null;
    return data;
  } catch (_e) {
    return null;
  }
}
