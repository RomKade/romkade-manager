import type { MouseEvent, ReactNode } from "react";

import type { Game } from "../api/client";
import { useYoutubeSettings } from "../api/queries";

/** Logo YouTube stylisé (rectangle arrondi, triangle évidé), à la couleur du texte qui l'entoure. */
export function YoutubeIcon({ size = 16, className = "" }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden className={`yt-icon ${className}`}>
      <path fill="currentColor" fillRule="evenodd"
        d="M21.6 7.2a2.5 2.5 0 0 0-1.76-1.77C18.27 5 12 5 12 5s-6.27 0-7.84.43A2.5 2.5 0 0 0 2.4 7.2 26 26 0 0 0 2 12a26 26 0 0 0 .4 4.8 2.5 2.5 0 0 0 1.76 1.77C5.73 19 12 19 12 19s6.27 0 7.84-.43a2.5 2.5 0 0 0 1.76-1.77A26 26 0 0 0 22 12a26 26 0 0 0-.4-4.8ZM10 15.1V8.9l5.3 3.1Z" />
    </svg>
  );
}

/**
 * Bouton « Bande-annonce » : sans clé d'API YouTube, ouvre directement la recherche YouTube du jeu dans un nouvel
 * onglet ; avec une clé, la fenêtre de lecture de Game Manager (`onVideo`).
 */
export function TrailerButton({ game, onVideo, className, label, title, children }: {
  game: Pick<Game, "id" | "title" | "platform" | "youtube_url">; onVideo?: (g: never) => void; className: string;
  label?: string; title?: string; children: ReactNode;
}) {
  const configured = useYoutubeSettings().data?.configured === true;
  const stop = (e: MouseEvent) => e.stopPropagation();
  if ((!configured || !onVideo) && game.youtube_url) {
    return (
      <a className={className} href={game.youtube_url} target="_blank" rel="noreferrer noopener" aria-label={label} title={title} onClick={stop}>
        {children}
      </a>
    );
  }
  if (!onVideo) return null;
  return (
    <button type="button" className={className} aria-label={label} title={title}
      onClick={(e) => { stop(e); (onVideo as (g: typeof game) => void)(game); }}>
      {children}
    </button>
  );
}
