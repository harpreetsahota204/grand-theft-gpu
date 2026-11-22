#!/usr/bin/env node
// Asset search + fetch tool for a Grand Theft GPU race workspace.
//
// Copied into every workspace as tools/assets.mjs next to tools/catalog.json
// (the same catalog `buildoff inventory` reads in the harness repo). Zero
// dependencies: Node 18+ only.
//
//   node tools/assets.mjs help
//   node tools/assets.mjs categories
//   node tools/assets.mjs search police car [--limit 5]
//   node tools/assets.mjs list [--category person] [--kind adult] [--tag vc] [--seeded|--not-seeded] [--limit N]
//   node tools/assets.mjs show <id> [<id> ...]
//   node tools/assets.mjs fetch <id> [<id> ...] [--tiers]
//
// Output: JSON on stdout. Errors: {"error", "hint"} JSON on stderr, exit 1
// (not found) or 2 (bad input). Deterministic: same catalog + same args =
// same output. Seeded assets are already under public/assets/gt-gpu/; `fetch`
// downloads anything else there from the pinned Hugging Face revision.

import { mkdirSync, readFileSync, existsSync, writeFileSync, renameSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const WORKSPACE = join(HERE, "..");
const CATALOG = JSON.parse(readFileSync(join(HERE, "catalog.json"), "utf8"));
const ASSET_ROOT = join(WORKSPACE, "public", "assets", "gt-gpu");

// Same weights and rules as harness/inventory.py, so both tools rank alike.
const W = { id: 5, name: 4, tag: 3, substring: 1, coverage: 4 };
const SUMMARY = ["id", "category", "kind", "name", "url", "seeded", "triangles", "size_m", "license"];

const tokens = (t) => t.toLowerCase().split(/[^a-z0-9]+/).filter(Boolean);
const stem = (w) => (w.length > 3 && w.endsWith("s") ? w.slice(0, -1) : w);
const sortKeys = (o) =>
  Array.isArray(o) ? o.map(sortKeys)
  : o && typeof o === "object" ? Object.fromEntries(Object.keys(o).sort().map((k) => [k, sortKeys(o[k])]))
  : o;
const out = (data) => process.stdout.write(JSON.stringify(sortKeys(data), null, 2) + "\n");
const fail = (error, hint, code = 1) => {
  process.stderr.write(JSON.stringify({ error, hint }) + "\n");
  process.exit(code);
};

function score(a, words) {
  const idT = new Set(tokens(a.id).map(stem));
  const nameT = new Set(tokens(a.name).map(stem));
  const tagT = new Set(a.tags.flatMap((t) => [t, ...tokens(t)]).map(stem));
  // Partial matches only at the start of a word ("walk" ≠ "sidewalk"), 3+ letters.
  const starts = new Set(tokens([a.id, a.name, ...a.tags].join(" ")));
  const prefix = (w) => w.length >= 3 && [...starts].some((t) => t.startsWith(w));
  let total = 0;
  for (const w of words) {
    const hit = W.id * idT.has(w) + W.name * nameT.has(w) + W.tag * tagT.has(w) + W.substring * prefix(w);
    if (hit === 0) return 0;
    total += hit;
  }
  const covered = [...idT].filter((t) => words.includes(t)).length / (idT.size || 1);
  return Math.round((total + W.coverage * covered) * 1000) / 1000;
}

function parse(argv) {
  const opts = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith("--")) {
      const key = a.slice(2);
      const flag = ["tiers", "seeded", "not-seeded", "full"].includes(key);
      opts[key] = flag ? true : argv[++i];
    } else opts._.push(a);
  }
  return opts;
}

// Exact, case-insensitive filters, matching harness/inventory.py's filter_assets.
function filter(assets, o) {
  const [category, kind, tag] = [o.category, o.kind, o.tag].map((v) => v?.toLowerCase());
  return assets.filter(
    (a) =>
      (!category || a.category === category) &&
      (!kind || a.kind === kind) &&
      (!tag || a.tags.includes(tag)) &&
      (!o.seeded || a.seeded) &&
      (!o["not-seeded"] || !a.seeded),
  );
}

const summarize = (a, full) => (full ? a : Object.fromEntries([...SUMMARY, "score"].filter((k) => k in a).map((k) => [k, a[k]])));

async function fetchIds(ids, tiers) {
  const byId = new Map(CATALOG.assets.map((a) => [a.id, a]));
  const missing = ids.filter((i) => !byId.has(i));
  if (missing.length) fail(`unknown id(s): ${missing.join(", ")}`, "find ids with `search`");
  const paths = new Set();
  for (const i of ids) {
    const a = byId.get(i);
    paths.add(a.hf_path);
    // Multi-file sets (sound variants, texture maps) list workspace URLs.
    [...(a.files || []), ...Object.values(a.maps || {})].forEach((u) => paths.add(u.slice(CATALOG.url_prefix.length + 1)));
    if (tiers) Object.values(a.optional_tiers || {}).forEach((p) => paths.add(p));
  }
  const results = [];
  for (const p of [...paths].sort()) {
    const dest = join(ASSET_ROOT, p);
    if (existsSync(dest)) {
      results.push({ hf_path: p, status: "already-present", url: `${CATALOG.url_prefix}/${p}` });
      continue;
    }
    const src = `https://huggingface.co/datasets/${CATALOG.dataset}/resolve/${CATALOG.revision}/${p}`;
    const res = await fetch(src);
    if (!res.ok) fail(`download failed (${res.status}) for ${p}`, "check network access and retry");
    mkdirSync(dirname(dest), { recursive: true });
    // Write then rename, so an interrupted download never leaves a truncated
    // file that later runs would report as already-present.
    writeFileSync(`${dest}.part`, Buffer.from(await res.arrayBuffer()));
    renameSync(`${dest}.part`, dest);
    results.push({ hf_path: p, status: "downloaded", url: `${CATALOG.url_prefix}/${p}` });
  }
  return results;
}

const HELP = {
  tool: "tools/assets.mjs: search and fetch Grand Theft GPU assets",
  dataset: CATALOG.dataset,
  revision: CATALOG.revision,
  assets: CATALOG.count,
  commands: {
    categories: "asset counts per category and kind",
    "search <words> [--limit N]": "rank assets by query words (all words must match)",
    "list [--category C] [--kind K] [--tag T] [--seeded|--not-seeded] [--limit N] [--full]": "filter assets",
    "show <id> [...]": "full record(s)",
    "fetch <id> [...] [--tiers]": "download non-seeded assets (--tiers adds optional_tiers: people's lods/mobile/collision, 2k skies) into public/assets/gt-gpu/",
  },
  notes: [
    "Load any model in the game from its `url` with three.js GLTFLoader.",
    "Vehicles and trees are real size in metres, standing on y = 0 and centred; vehicles face +z. `size_m` gives the box; `parts` names separate wheel meshes where a model has them.",
    "Files under objects/ (people, motions, Kenney, vehicles, trees) need loader.setMeshoptDecoder(MeshoptDecoder) from three/addons/libs/meshopt_decoder.module.js.",
    "Skies (category sky) are .hdr: RGBELoader, then PMREMGenerator for scene.environment and scene.background.",
    "Textures (category texture): load each URL in `maps` with TextureLoader; set wrapS/wrapT = RepeatWrapping and repeat = surface metres / tile_m. Night facades have an emission map (lit windows).",
    "sf-city UVs are in metres (see the map record's uv field), so a texture's repeat is 1 / tile_m.",
    "Sounds (category sound) are .ogg/.wav/.mp3 for AudioLoader; `files` lists every variant. Sprites (vfx) are transparent .png. Fonts are .ttf for CSS @font-face.",
    "Rocketbox motion clips play on any Rocketbox person (shared skeleton). Quaternius clips (walk/run) need retargeting.",
    "sf-city: buildings.json and streets.json (see the map record's data_files) give footprints, heights and a routable street graph.",
  ],
};

const [cmd = "help", ...rest] = process.argv.slice(2);
const o = parse(rest);
const limit = o.limit ? Number(o.limit) : 0;
const cut = (rows) => (limit ? rows.slice(0, limit) : rows);

switch (cmd) {
  case "help":
    out(HELP);
    break;
  case "categories": {
    const counts = new Map();
    for (const a of CATALOG.assets) {
      const k = `${a.category}\u0000${a.kind}`;
      counts.set(k, (counts.get(k) || 0) + 1);
    }
    out([...counts.entries()].sort().map(([k, n]) => ({ category: k.split("\u0000")[0], kind: k.split("\u0000")[1], count: n })));
    break;
  }
  case "list":
    out(cut(filter(CATALOG.assets, o).sort((a, b) => (a.id < b.id ? -1 : 1))).map((a) => summarize(a, o.full)));
    break;
  case "search": {
    const words = o._.flatMap(tokens).map(stem);
    if (!words.length) fail("empty query", "pass one or more words, e.g. `search police car`", 2);
    const hits = filter(CATALOG.assets, o)
      .map((a) => ({ ...a, score: score(a, words) }))
      .filter((a) => a.score > 0)
      .sort((a, b) => b.score - a.score || (a.id < b.id ? -1 : 1));
    out(cut(hits).map((a) => summarize(a, o.full)));
    break;
  }
  case "show": {
    if (!o._.length) fail("no ids given", "pass ids from `search`, e.g. `show kenney/car-kit__police`", 2);
    const byId = new Map(CATALOG.assets.map((a) => [a.id, a]));
    const missing = o._.filter((i) => !byId.has(i));
    if (missing.length) fail(`unknown id(s): ${missing.join(", ")}`, "find ids with `search`");
    out(o._.map((i) => byId.get(i)));
    break;
  }
  case "fetch":
    if (!o._.length) fail("no ids given", "pass ids from `search` or `list --not-seeded`", 2);
    out(await fetchIds(o._, o.tiers));
    break;
  default:
    fail(`unknown command: ${cmd}`, "run `node tools/assets.mjs help`", 2);
}
