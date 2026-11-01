import { ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import { useState, type KeyboardEvent } from "react";

import { imageUrl, type Game } from "../api/client";
import { useT } from "../i18n";
import { creditUrl } from "../lib/credits";

type Slide = { kind: "snap" | "title" | "card"; src: string };

/**
 * Tête de la fiche d'un jeu, en pleine largeur : le jeu en images, en diaporama — capture d'écran puis écran titre
 * (libretro-thumbnails, comme la jaquette), puis l'image de la carte (dossier Imgs, lue sur la console en SSH).
 * Toutes les images sont chargées dès l'ouverture, en arrière-plan ; une image qui ne se charge pas sort du
 * diaporama. Sans aucune image, la jaquette floutée tient lieu de fond. En bas à droite, le compteur et les
 * miniatures ; en bas à gauche, la source des images libretro.
 */
export function GameGallery({ game }: { game: Pick<Game, "title" | "image_url" | "boxart_url" | "platform"> }) {
  const t = useT();
  const bank = game.boxart_url ? `${game.boxart_url}?size=full` : null;
  const all: Slide[] = [
    ...(bank ? [{ kind: "snap" as const, src: `${bank}&kind=snap` }, { kind: "title" as const, src: `${bank}&kind=title` }] : []),
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
  const label = (s: Slide) => t(`sheet.gallery.${s.kind}`);

  return (
    <section className="sheet-hero" aria-roledescription={t("sheet.gallery.role")} aria-label={t("sheet.gallery.label")}
      tabIndex={slides.length > 1 ? 0 : undefined} onKeyDown={onKey}>
      {slide ? (
        <div className={`sheet-hero__frame ${loaded.includes(slide.src) ? "is-loaded" : ""}`} role="group"
          aria-roledescription={t("sheet.gallery.slide")}
          aria-label={t("sheet.gallery.position", { n: index + 1, total: slides.length, label: label(slide) })}>
          <img key={`b-${slide.src}`} className="sheet-hero__backdrop" src={slide.src} alt="" aria-hidden decoding="async" />
          <img key={slide.src} className="sheet-hero__img" src={slide.src} alt={label(slide)} decoding="async" />
          {!loaded.includes(slide.src) && <Loader2 size={22} aria-hidden className="spin sheet-hero__loading" />}
        </div>
      ) : bank ? (
        <img className="sheet-hero__fallback" src={bank} alt="" aria-hidden decoding="async" />
      ) : null}
      {/* Préchargement de toutes les images : chargées (roue retirée) ou en échec (retirées du diaporama). */}
      {all.map((s) => (
        <img key={`p-${s.src}`} src={s.src} alt="" aria-hidden hidden
          onLoad={() => setLoaded((l) => [...l, s.src])} onError={() => setFailed((f) => [...f, s.src])} />
      ))}
      {slides.length > 1 && (
        <>
          <button type="button" className="sheet-hero__arrow sheet-hero__arrow--prev" onClick={() => go(index - 1)}
            aria-label={t("sheet.gallery.prev")}><ChevronLeft size={20} aria-hidden /></button>
          <button type="button" className="sheet-hero__arrow sheet-hero__arrow--next" onClick={() => go(index + 1)}
            aria-label={t("sheet.gallery.next")}><ChevronRight size={20} aria-hidden /></button>
          <div className="sheet-hero__thumbs">
            <span className="sheet-hero__count num" aria-hidden>{index + 1} / {slides.length}</span>
            {slides.map((s, i) => (
              <button key={s.src} type="button" className={`sheet-hero__thumb ${i === index ? "is-active" : ""}`}
                aria-label={label(s)} aria-current={i === index ? "true" : undefined} onClick={() => setCurrent(i)}>
                <img src={s.src} alt="" aria-hidden decoding="async" />
              </button>
            ))}
          </div>
        </>
      )}
      {bank && (
        <small className="sheet-hero__credit">
          {t("sheet.coverCredit")} <a href={creditUrl("thumbnails")} target="_blank" rel="noreferrer noopener">libretro-thumbnails</a>
        </small>
      )}
    </section>
  );
}
