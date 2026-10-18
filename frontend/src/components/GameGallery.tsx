import { ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import { useState, type KeyboardEvent, type ReactNode } from "react";

import { imageUrl, type Game } from "../api/client";
import { useT } from "../i18n";
import { creditUrl } from "../lib/credits";
import { Cover } from "./Cover";

type Slide = { kind: "box" | "card"; src: string };

/**
 * Images de la fiche d'un jeu en diaporama : la jaquette (libretro-thumbnails) d'abord, puis l'image de la carte
 * (dossier Imgs, lue sur la console en SSH : une à trois secondes). Toutes les images sont chargées dès l'ouverture,
 * en arrière-plan ; une image qui ne se charge pas sort du diaporama ; sans aucune image, les initiales du jeu.
 * Sous les images : `left` à gauche (lien Bande-annonce), la source de la jaquette à droite quand elle est affichée.
 */
export function GameGallery({ game, left }: {
  game: Pick<Game, "title" | "image_url" | "boxart_url" | "platform">; left?: ReactNode;
}) {
  const t = useT();
  const all: Slide[] = [
    ...(game.boxart_url ? [{ kind: "box" as const, src: `${game.boxart_url}?size=full` }] : []),
    ...(imageUrl(game, "full") ? [{ kind: "card" as const, src: imageUrl(game, "full")! }] : []),
  ];
  const [failed, setFailed] = useState<string[]>([]);
  const [loaded, setLoaded] = useState<string[]>([]);
  const [current, setCurrent] = useState(0);
  const slides = all.filter((s) => !failed.includes(s.src));
  const index = Math.min(current, Math.max(slides.length - 1, 0));
  const slide = slides[index];
  const go = (n: number) => setCurrent((n + slides.length) % slides.length);
  const onKey = (e: KeyboardEvent) => {
    if (slides.length < 2) return;
    if (e.key === "ArrowRight") { e.preventDefault(); go(index + 1); }
    if (e.key === "ArrowLeft") { e.preventDefault(); go(index - 1); }
  };
  const label = (s: Slide) => t(s.kind === "box" ? "sheet.gallery.box" : "sheet.gallery.card");

  return (
    <div className="gallery">
      <section className="gallery__stage" aria-roledescription={t("sheet.gallery.role")} aria-label={t("sheet.gallery.label")}
        tabIndex={slides.length > 1 ? 0 : undefined} onKeyDown={onKey}>
        {slide ? (
          <div className="cover cover--large is-loaded gallery__frame" role="group" aria-roledescription={t("sheet.gallery.slide")}
            aria-label={t("sheet.gallery.position", { n: index + 1, total: slides.length, label: label(slide) })}>
            <img key={`b-${slide.src}`} className="cover__backdrop" src={slide.src} alt="" aria-hidden decoding="async" />
            <img key={slide.src} className="cover__img" src={slide.src} alt={label(slide)} decoding="async" />
            {!loaded.includes(slide.src) && <Loader2 size={22} aria-hidden className="spin gallery__loading" />}
          </div>
        ) : (
          <Cover game={{ ...game, boxart_url: null, image_url: null }} size="full" className="cover--large" />
        )}
        {/* Préchargement de toutes les images : chargées (roue retirée) ou en échec (retirées du diaporama). */}
        {all.map((s) => (
          <img key={`p-${s.src}`} src={s.src} alt="" aria-hidden hidden
            onLoad={() => setLoaded((l) => [...l, s.src])} onError={() => setFailed((f) => [...f, s.src])} />
        ))}
        {slides.length > 1 && (
          <>
            <button type="button" className="gallery__arrow gallery__arrow--prev" onClick={() => go(index - 1)}
              aria-label={t("sheet.gallery.prev")}><ChevronLeft size={20} aria-hidden /></button>
            <button type="button" className="gallery__arrow gallery__arrow--next" onClick={() => go(index + 1)}
              aria-label={t("sheet.gallery.next")}><ChevronRight size={20} aria-hidden /></button>
            <div className="gallery__dots">
              {slides.map((s, i) => (
                <button key={s.src} type="button" className={`gallery__dot ${i === index ? "is-active" : ""}`}
                  aria-label={label(s)} aria-current={i === index ? "true" : undefined} onClick={() => setCurrent(i)} />
              ))}
            </div>
          </>
        )}
      </section>
      <div className="gallery__under">
        <span>{left}</span>
        {slide?.kind === "box" && (
          <small className="gallery__credit">
            {t("sheet.coverCredit")} <a href={creditUrl("thumbnails")} target="_blank" rel="noreferrer noopener">libretro-thumbnails</a>
          </small>
        )}
      </div>
    </div>
  );
}
