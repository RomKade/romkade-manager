import { CheckCircle2, ChevronRight } from "lucide-react";
import type { MouseEvent } from "react";
import { Link } from "react-router-dom";

import { useT } from "../i18n";

export type StepCard = {
  n: number;
  label: string;
  /** Ce qui est réglé, ou ce qu'il reste à faire. */
  sub: string;
  done: boolean;
  /** Texte de l'action, écrit en toutes lettres (« Modifier », « Faire le test »…). */
  action: string;
  /** Section de la page (id) : la page y glisse et la signale ; ou page à ouvrir (`to`). */
  target?: string;
  to?: string;
};

/** Fait glisser la page jusqu'à la section `id` et la signale un instant (halo). */
export function goToSection(id: string, e?: MouseEvent) {
  const target = document.getElementById(id);
  if (!target) return;
  e?.preventDefault();
  const block = target.closest<HTMLElement>(".block") ?? target;
  block.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  block.classList.remove("is-flash");
  void block.offsetWidth;  // relance l'animation si on clique deux fois
  block.classList.add("is-flash");
  history.replaceState(null, "", `#${id}`);
}

/**
 * Étapes de mise en route (Connexion, Assistant IA) : une carte cliquable par étape, faite ou non. Numéro et
 * « Étape N » en haut, titre dessous (aligné d'une carte à l'autre), résumé, puis l'action en toutes lettres.
 */
export function StepCards({ label, steps }: { label: string; steps: StepCard[] }) {
  const t = useT();
  const current = steps.find((s) => !s.done)?.n ?? steps.at(-1)?.n;
  return (
    <nav className="steps" aria-label={label}>
      <ol style={{ gridTemplateColumns: `repeat(${steps.length}, minmax(0, 1fr))` }}>
        {steps.map((s) => {
          const body = (
            <>
              <span className="steps__top">
                <span className="steps__num" aria-hidden>{s.done ? <CheckCircle2 size={18} /> : s.n}</span>
                <span className="steps__index">{t("settings.steps.index", { n: s.n })}</span>
              </span>
              <span className="steps__label">{s.label}</span>
              <span className="steps__sub">{s.sub}</span>
              <span className="steps__action">{s.action} <ChevronRight size={16} aria-hidden /></span>
              <span className="visually-hidden"> — {t(s.done ? "settings.steps.done" : s.n === current ? "settings.steps.current" : "settings.steps.todo")}</span>
            </>
          );
          const cls = `steps__item ${s.done ? "is-done" : ""} ${s.n === current ? "is-current" : ""}`;
          return (
            <li key={s.n}>
              {s.to ? <Link to={s.to} className={cls}>{body}</Link>
                : <a href={`#${s.target}`} className={cls} onClick={(e) => goToSection(s.target!, e)}>{body}</a>}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
