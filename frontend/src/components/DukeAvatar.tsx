/**
 * Visage de l'assistant (Duke par défaut), en pixel art 16 × 16 : coupe en brosse blonde, lunettes noires avec un
 * reflet cyan ROMKADE, mâchoire carrée mal rasée, sourire en coin, débardeur rose. Dessin original, dans l'esprit
 * des héros d'action des jeux des années 90.
 */
const ROWS = [
  "....HHHHHHHH....",
  "...HHHHHHHHHH...",
  "...HhHhHhHhHh...",
  "..OhSSSSSSSShO..",
  "..OSSSSSSSSSSO..",
  "..OGGGGSSGGGGO..",
  "..OGgGGGGGgGGO..",
  "..OSGGGSSGGGSO..",
  "..OSSSSssSSSSO..",
  "...OSSSSSSSSO...",
  "...OSSJMMMMSO...",
  "...OJJJJJJJJO...",
  "....OJJJJJJO....",
  "......SssS......",
  "...TTTSssSTTT...",
  "..TTTTTTTTTTTT..",
];

const COLORS: Record<string, string> = {
  H: "#f6c945", // cheveux
  h: "#c99525", // cheveux, ombre
  S: "#e9b48c", // peau
  s: "#c98d66", // peau, ombre
  J: "#b98463", // barbe de trois jours
  M: "#6b2d22", // bouche
  G: "#0d1324", // lunettes
  g: "#4fd1e8", // reflet des lunettes (cyan ROMKADE)
  O: "#1c2440", // contour
  T: "#e0399b", // débardeur (rose ROMKADE)
};

// Un rectangle par suite de pixels de même couleur sur une ligne : moins d'éléments, rendu net.
const RECTS = ROWS.flatMap((row, y) => {
  const out: { x: number; y: number; w: number; c: string }[] = [];
  let x = 0;
  while (x < row.length) {
    const ch = row[x]!;
    let w = 1;
    while (row[x + w] === ch) w++;
    if (COLORS[ch]) out.push({ x, y, w, c: COLORS[ch]! });
    x += w;
  }
  return out;
});

export function DukeAvatar({ size = 20, className = "" }: { size?: number; className?: string }) {
  return (
    <svg className={`duke-avatar ${className}`} width={size} height={size} viewBox="0 0 16 16" shapeRendering="crispEdges"
      aria-hidden focusable="false">
      {RECTS.map((r, i) => <rect key={i} x={r.x} y={r.y} width={r.w} height={1} fill={r.c} />)}
    </svg>
  );
}
