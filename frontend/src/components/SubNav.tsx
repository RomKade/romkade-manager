import { ChevronLeft, ChevronRight } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { useT } from "../i18n";

/**
 * Sous-menu horizontal d'une page (onglets de Paramètres, de Mon compte). Quand les onglets dépassent la largeur :
 * flèches de chaque côté où il reste des onglets, glisser à la souris (un glisser n'ouvre pas l'onglet sous le
 * curseur), molette verticale convertie en défilement horizontal, et l'onglet actif ramené à l'écran.
 */
export function SubNav({ label, active, children }: { label: string; active: string; children: ReactNode }) {
  const t = useT();
  const ref = useRef<HTMLElement>(null);
  const [edges, setEdges] = useState({ start: true, end: true });
  const drag = useRef<{ x: number; left: number; moved: boolean } | null>(null);

  const update = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    setEdges({ start: el.scrollLeft <= 2, end: el.scrollLeft + el.clientWidth >= el.scrollWidth - 2 });
  }, []);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    update();
    el.addEventListener("scroll", update, { passive: true });
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(update) : null;
    ro?.observe(el);
    // Molette verticale : défile le menu de gauche à droite (sans bloquer la page s'il n'y a rien à faire défiler).
    const wheel = (e: WheelEvent) => {
      if (el.scrollWidth <= el.clientWidth || Math.abs(e.deltaX) > Math.abs(e.deltaY)) return;
      const before = el.scrollLeft;
      el.scrollLeft += e.deltaY;
      if (el.scrollLeft !== before) e.preventDefault();
    };
    el.addEventListener("wheel", wheel, { passive: false });
    return () => { el.removeEventListener("scroll", update); el.removeEventListener("wheel", wheel); ro?.disconnect(); };
  }, [update]);

  // Onglet actif visible, y compris en arrivant par un lien direct vers un onglet tout à droite.
  useEffect(() => {
    ref.current?.querySelector<HTMLElement>("[aria-current='page']")?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [active]);

  const page = (dir: 1 | -1) => {
    const el = ref.current;
    if (!el) return;
    const smooth = !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    el.scrollBy({ left: dir * el.clientWidth * 0.6, behavior: smooth ? "smooth" : "auto" });
  };

  return (
    <div className={`subnav-wrap ${edges.start ? "" : "has-prev"} ${edges.end ? "" : "has-next"}`}>
      {!edges.start && (
        <button type="button" className="subnav__arrow subnav__arrow--prev" onClick={() => page(-1)} aria-label={t("dashboard.scrollPrev")}>
          <ChevronLeft size={18} aria-hidden />
        </button>
      )}
      <nav ref={ref} className="subnav" aria-label={label}
        onPointerDown={(e) => {
          if (e.pointerType !== "mouse" || e.button !== 0 || !ref.current) return;
          drag.current = { x: e.clientX, left: ref.current.scrollLeft, moved: false };
        }}
        onPointerMove={(e) => {
          const d = drag.current;
          if (!d || !ref.current) return;
          if (Math.abs(e.clientX - d.x) > 5) d.moved = true;
          if (d.moved) ref.current.scrollLeft = d.left - (e.clientX - d.x);
        }}
        onPointerUp={() => { setTimeout(() => { drag.current = null; }); }}
        onPointerLeave={() => { drag.current = null; }}
        onClickCapture={(e) => { if (drag.current?.moved) { e.preventDefault(); e.stopPropagation(); } }}
        onDragStart={(e) => e.preventDefault()}>
        {children}
      </nav>
      {!edges.end && (
        <button type="button" className="subnav__arrow subnav__arrow--next" onClick={() => page(1)} aria-label={t("dashboard.scrollNext")}>
          <ChevronRight size={18} aria-hidden />
        </button>
      )}
    </div>
  );
}
