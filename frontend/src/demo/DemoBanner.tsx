import { ArrowLeft, Download, FlaskConical } from "lucide-react";

import { useLang } from "../i18n";

const SITE = "https://romkade.com";
const T = {
  fr: { tag: "Démo", text: "Console simulée et jeux inventés : rien n'est envoyé à une vraie console.", install: "Installer ROMKADE Manager",
    back: "romkade.com", installUrl: `${SITE}/installation/`, siteUrl: `${SITE}/` },
  en: { tag: "Demo", text: "Simulated console and made-up games: nothing is sent to a real console.", install: "Install ROMKADE Manager",
    back: "romkade.com", installUrl: `${SITE}/en/installation/`, siteUrl: `${SITE}/en/` },
  es: { tag: "Demo", text: "Consola simulada y juegos inventados: no se envía nada a una consola real.", install: "Instalar ROMKADE Manager",
    back: "romkade.com", installUrl: `${SITE}/es/instalacion/`, siteUrl: `${SITE}/es/` },
};

/** Bandeau de la démo publique (romkade.com/demo), en haut de chaque page. */
export function DemoBanner() {
  const t = T[useLang()];
  return (
    <div className="demo-banner" role="note">
      <span className="demo-banner__tag"><FlaskConical size={14} aria-hidden /> {t.tag}</span>
      <p>{t.text}</p>
      <a className="demo-banner__link" href={t.siteUrl}><ArrowLeft size={14} aria-hidden /> {t.back}</a>
      <a className="button button--primary demo-banner__cta" href={t.installUrl}><Download size={16} aria-hidden /> {t.install}</a>
    </div>
  );
}
