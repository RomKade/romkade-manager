import { useId } from "react";

import type { Lang } from "../i18n";

/** Petits drapeaux en SVG (les drapeaux emoji ne s'affichent pas partout). */
export function Flag({ lang }: { lang: Lang }) {
  const id = useId();
  if (lang === "fr") {
    return (
      <svg className="flag" viewBox="0 0 3 2" aria-hidden>
        <rect width="1" height="2" fill="#0055A4" /><rect x="1" width="1" height="2" fill="#fff" /><rect x="2" width="1" height="2" fill="#EF4135" />
      </svg>
    );
  }
  if (lang === "es") {
    return (
      <svg className="flag" viewBox="0 0 3 2" aria-hidden>
        <rect width="3" height="2" fill="#AA151B" /><rect y="0.5" width="3" height="1" fill="#F1BF00" />
      </svg>
    );
  }
  return (
    <svg className="flag" viewBox="0 0 60 30" aria-hidden>
      <clipPath id={`${id}s`}><path d="M0,0 v30 h60 v-30 z" /></clipPath>
      <clipPath id={`${id}t`}><path d="M30,15 h30 v15 z v15 h-30 z h-30 v-15 z v-15 h30 z" /></clipPath>
      <g clipPath={`url(#${id}s)`}>
        <path d="M0,0 v30 h60 v-30 z" fill="#012169" />
        <path d="M0,0 L60,30 M60,0 L0,30" stroke="#fff" strokeWidth="6" />
        <path d="M0,0 L60,30 M60,0 L0,30" clipPath={`url(#${id}t)`} stroke="#C8102E" strokeWidth="4" />
        <path d="M30,0 v30 M0,15 h60" stroke="#fff" strokeWidth="10" />
        <path d="M30,0 v30 M0,15 h60" stroke="#C8102E" strokeWidth="6" />
      </g>
    </svg>
  );
}
