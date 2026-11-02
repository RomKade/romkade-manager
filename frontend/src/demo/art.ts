/**
 * Images de la démo, dessinées en SVG : jaquettes et écrans des jeux inventés (aucune image d'un vrai jeu).
 * Servies en adresses data: terminées par « # » : le « ?size=… » que l'interface ajoute aux adresses d'images tombe
 * dans le fragment, que le navigateur ignore.
 */

export type Scene = "isles" | "city" | "peaks" | "forest" | "ruins" | "cave" | "space" | "track" | "sea" | "desert";

type Palette = { sky: [string, string]; far: string; near: string; ground: string; accent: string };

const PALETTES: Record<Scene, Palette> = {
  isles: { sky: ["#3fb6ff", "#bdeeff"], far: "#7fd3a8", near: "#2f9e6a", ground: "#f2d48b", accent: "#ffd23f" },
  city: { sky: ["#1a0b3d", "#ff3fa8"], far: "#3b1d6e", near: "#16123a", ground: "#0b0a1f", accent: "#00e5ff" },
  peaks: { sky: ["#7aa7ff", "#e6f0ff"], far: "#b9c9e8", near: "#ffffff", ground: "#dfe9f7", accent: "#ff6b3f" },
  forest: { sky: ["#244a3a", "#9fd9a0"], far: "#2f6b4a", near: "#163d2b", ground: "#3a2a1a", accent: "#ffd23f" },
  ruins: { sky: ["#ffb35c", "#ffe7b0"], far: "#c98b4f", near: "#8a5a2e", ground: "#e8c27a", accent: "#00b3a4" },
  cave: { sky: ["#0d0a1c", "#2b1b47"], far: "#3d2a63", near: "#1c1233", ground: "#120c22", accent: "#b06bff" },
  space: { sky: ["#03040f", "#16204a"], far: "#2b3a80", near: "#5b6bd6", ground: "#0a0d24", accent: "#ff3fa8" },
  track: { sky: ["#ff7a3f", "#ffd2a0"], far: "#9a4b8a", near: "#3b2b5a", ground: "#2a2a35", accent: "#ffffff" },
  sea: { sky: ["#0a4c8c", "#55c2ff"], far: "#1c6fb5", near: "#0b3d6e", ground: "#062a4d", accent: "#ffd23f" },
  desert: { sky: ["#ffcc66", "#fff1c9"], far: "#e8a65a", near: "#c97a35", ground: "#f0c27a", accent: "#2b8cff" },
};

/** Petit générateur déterministe : la même image pour le même jeu, à chaque chargement. */
function rand(seed: string) {
  let h = 2166136261;
  for (const c of seed) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
  return () => {
    h = Math.imul(h ^ (h >>> 15), 2246822507);
    h = Math.imul(h ^ (h >>> 13), 3266489909);
    return ((h ^= h >>> 16) >>> 0) / 4294967296;
  };
}

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

/** Décor « pixel » sur w×h : ciel, relief lointain, relief proche, sol, astre et quelques détails. */
function landscape(scene: Scene, w: number, h: number, seed: string): string {
  const p = PALETTES[scene];
  const r = rand(seed);
  const px = Math.max(4, Math.round(w / 60));
  const out: string[] = [
    `<defs><linearGradient id="s" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${p.sky[0]}"/>` +
      `<stop offset="1" stop-color="${p.sky[1]}"/></linearGradient></defs>`,
    `<rect width="${w}" height="${h}" fill="url(#s)"/>`,
  ];
  if (scene === "space" || scene === "city" || scene === "cave") {
    for (let i = 0; i < 40; i++) {
      out.push(`<rect x="${Math.floor(r() * w / px) * px}" y="${Math.floor(r() * h * 0.6 / px) * px}" width="${px / 2}" height="${px / 2}" fill="#fff" opacity="${(0.3 + r() * 0.7).toFixed(2)}"/>`);
    }
  }
  const sx = w * (0.2 + r() * 0.6), sy = h * (0.15 + r() * 0.15), sr = px * (3 + Math.floor(r() * 3));
  out.push(`<rect x="${sx - sr}" y="${sy - sr}" width="${sr * 2}" height="${sr * 2}" fill="${p.accent}" opacity="0.9"/>`);
  const ridge = (base: number, amp: number, step: number, fill: string, blocky: boolean) => {
    let d = `M0 ${h}`;
    for (let x = 0; x <= w + step; x += step) {
      const y = Math.round((base - r() * amp) / px) * px;
      d += blocky ? ` L${x} ${y} L${x + step} ${y}` : ` L${x} ${y}`;
    }
    out.push(`<path d="${d} L${w} ${h} Z" fill="${fill}"/>`);
  };
  const blocky = scene === "city" || scene === "ruins";
  ridge(h * 0.62, h * 0.22, blocky ? px * 5 : px * 8, p.far, blocky);
  ridge(h * 0.74, h * 0.16, blocky ? px * 4 : px * 6, p.near, blocky);
  out.push(`<rect y="${Math.round(h * 0.82 / px) * px}" width="${w}" height="${h}" fill="${p.ground}"/>`);
  for (let i = 0; i < 6; i++) {
    out.push(`<rect x="${Math.floor(r() * w / px) * px}" y="${Math.round((h * 0.84 + r() * h * 0.12) / px) * px}" width="${px * 2}" height="${px}" fill="${p.near}" opacity="0.5"/>`);
  }
  return out.join("");
}

/** Petit héros de pixels, posé sur le sol. */
function hero(x: number, y: number, px: number, color: string): string {
  const rows = ["..XX..", ".XXXX.", "..XX..", ".XXXX.", "X.XX.X", "..XX..", ".X..X.", ".X..X."];
  const cells: string[] = [];
  rows.forEach((row, j) => [...row].forEach((c, i) => {
    if (c === "X") cells.push(`<rect x="${x + i * px}" y="${y + j * px}" width="${px}" height="${px}"/>`);
  }));
  return `<g fill="${color}">${cells.join("")}</g>`;
}

const svgUrl = (w: number, h: number, body: string) =>
  `data:image/svg+xml;charset=utf-8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" shape-rendering="crispEdges">${body}</svg>`)}#`;

/** Jaquette 3:4 : décor, titre en gros caractères, bandeau de la plateforme. */
export function coverUrl(title: string, scene: Scene, platform: string): string {
  const w = 300, h = 400;
  const words = title.toUpperCase().split(" ");
  const lines: string[] = [];
  for (const word of words) {
    const last = lines[lines.length - 1];
    if (last && (last + " " + word).length <= 11) lines[lines.length - 1] = last + " " + word;
    else lines.push(word);
  }
  const size = lines.some((l) => l.length > 9) ? 30 : 36;
  const text = lines.map((l, i) =>
    `<text x="150" y="${92 + i * (size + 6)}" text-anchor="middle">${esc(l)}</text>`).join("");
  return svgUrl(w, h, landscape(scene, w, h, title) +
    hero(130, 268, 6, "#101018") +
    `<rect width="${w}" height="34" fill="#05070f"/><text x="12" y="23" fill="#fff" font-family="monospace" font-size="15" font-weight="700">${esc(platform)}</text>` +
    `<text x="288" y="23" fill="${PALETTES[scene].accent}" font-family="monospace" font-size="13" text-anchor="end">DEMO</text>` +
    `<g font-family="'Courier New',monospace" font-weight="900" font-size="${size}" fill="#fff" stroke="#05070f" stroke-width="6" paint-order="stroke">${text}</g>`);
}

/** Écran de jeu 4:3 (captures, « Je suis bloqué ») : décor, héros, score et vies. */
export function screenUrl(title: string, scene: Scene, variant: number): string {
  const w = 640, h = 480;
  const r = rand(`${title}#${variant}`);
  const score = String(Math.floor(r() * 90000) + 1000).padStart(6, "0");
  return svgUrl(w, h, landscape(scene, w, h, `${title}~${variant}`) +
    hero(Math.round((80 + r() * 440) / 8) * 8, 330, 8, "#101018") +
    `<g font-family="monospace" font-weight="700" font-size="22" fill="#fff" stroke="#05070f" stroke-width="4" paint-order="stroke">` +
    `<text x="24" y="40">SCORE ${score}</text><text x="616" y="40" text-anchor="end">LV ${1 + (variant % 5)}  ♥×${1 + Math.floor(r() * 4)}</text>` +
    `<text x="320" y="458" text-anchor="middle" font-size="16" opacity="0.8">${esc(title.toUpperCase())} · ROMKADE DEMO</text></g>`);
}

/** Écran de la console sans jeu lancé. */
export function menuUrl(): string {
  return svgUrl(640, 480, `<rect width="640" height="480" fill="#050c1c"/><rect x="24" y="24" width="592" height="432" fill="none" stroke="#00e5ff" stroke-width="3"/>` +
    `<g font-family="monospace" text-anchor="middle"><text x="320" y="225" fill="#fff" font-size="32" font-weight="700">Menu</text>` +
    `<text x="320" y="265" fill="#ff40a0" font-size="18">Choose a game</text></g>`);
}
