import { useState } from "react";

import { imageUrl, type Game } from "../api/client";
import { initials } from "../lib/format";

export type Art = "box" | "card";

type Props = {
  game: Pick<Game, "title" | "image_url" | "boxart_url" | "platform">;
  size?: "thumb" | "full";
  /** box : jaquette (libretro-thumbnails) d'abord ; card : image du dossier Imgs de la carte d'abord. */
  art?: Art;
  /** false : n'affiche que l'image demandée, sans se rabattre sur l'autre. */
  fallback?: boolean;
  className?: string;
};

function sources(game: Props["game"], size: "thumb" | "full", art: Art, fallback: boolean): string[] {
  const box = game.boxart_url ? `${game.boxart_url}?size=${size}` : null;
  const card = imageUrl(game, size);
  const order = art === "box" ? [box, card] : [card, box];
  return (fallback ? order : order.slice(0, 1)).filter((s): s is string => !!s);
}

/**
 * Jaquette du jeu. L'image entière est toujours visible (contain), posée sur un fond flou de la même image
 * pour remplir la case quel que soit son format. Si la première source échoue (jaquette introuvable, console
 * éteinte), on passe à la suivante ; à défaut, les initiales.
 */
export function Cover({ game, size = "thumb", art = "box", fallback = true, className = "" }: Props) {
  const list = sources(game, size, art, fallback);
  const [index, setIndex] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const src = list[index];

  if (!src) {
    return (
      <div className={`cover cover--empty ${className}`} aria-hidden>
        <span className="cover__initials">{initials(game.title)}</span>
        <span className="cover__platform">{game.platform.directory}</span>
      </div>
    );
  }
  return (
    <div className={`cover ${loaded ? "is-loaded" : ""} ${className}`}>
      <img key={`b-${src}`} className="cover__backdrop" src={src} alt="" aria-hidden loading="lazy" decoding="async" />
      <img
        key={src}
        className="cover__img"
        src={src}
        alt=""
        loading="lazy"
        decoding="async"
        onLoad={() => setLoaded(true)}
        onError={() => { setLoaded(false); setIndex((i) => i + 1); }}
      />
    </div>
  );
}
