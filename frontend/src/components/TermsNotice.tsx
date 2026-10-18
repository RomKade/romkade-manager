import { ShieldAlert } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { useT } from "../i18n";

/** Clé du navigateur : changer de numéro quand les conditions changent, pour les montrer de nouveau. */
export const TERMS_KEY = "romkade-terms-v1";

function seen(): boolean {
  try {
    return localStorage.getItem(TERMS_KEY) === "1";
  } catch {
    return false;
  }
}

/** Bandeau du premier lancement : aucun jeu fourni, responsabilité de l'utilisateur ; disparaît une fois lu. */
export function TermsNotice() {
  const t = useT();
  const [hidden, setHidden] = useState(seen);
  if (hidden) return null;
  const ok = () => {
    try { localStorage.setItem(TERMS_KEY, "1"); } catch { /* navigation privée : le bandeau reviendra */ }
    setHidden(true);
  };
  return (
    <section className="terms-notice" role="region" aria-label={t("legal.link")}>
      <ShieldAlert size={18} aria-hidden className="terms-notice__icon" />
      <p>{t("legal.notice.text")} <Link to="/conditions" className="link">{t("legal.notice.read")}</Link></p>
      <button type="button" className="button button--primary" onClick={ok}>{t("legal.notice.ok")}</button>
    </section>
  );
}
