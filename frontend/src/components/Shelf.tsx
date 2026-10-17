import { ChevronLeft, ChevronRight } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { useT } from "../i18n";

/**
 * Rangée horizontale de jaquettes. Le défilement reste natif (molette, glisser au doigt, Tab d'une jaquette
 * à l'autre) ; les flèches n'apparaissent que s'il reste quelque chose à voir de leur côté.
 */
export function Shelf({ label, children }: { label: string; children: ReactNode }) {
  const t = useT();
  const ref = useRef<HTMLDivElement>(null);
  const [edges, setEdges] = useState({ start: true, end: true });

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
    return () => { el.removeEventListener("scroll", update); ro?.disconnect(); };
  }, [update, children]);

  const page = (dir: 1 | -1) => {
    const el = ref.current;
    if (!el) return;
    const smooth = !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    el.scrollBy({ left: dir * el.clientWidth * 0.8, behavior: smooth ? "smooth" : "auto" });
  };

  return (
    <div className="shelf-wrap">
      <button type="button" className="shelf__nav shelf__nav--prev" onClick={() => page(-1)} disabled={edges.start}
        aria-label={t("dashboard.scrollPrev")}>
        <ChevronLeft size={22} aria-hidden />
      </button>
      <div ref={ref} className="shelf" role="group" aria-label={label}>
        {children}
      </div>
      <button type="button" className="shelf__nav shelf__nav--next" onClick={() => page(1)} disabled={edges.end}
        aria-label={t("dashboard.scrollNext")}>
        <ChevronRight size={22} aria-hidden />
      </button>
    </div>
  );
}
