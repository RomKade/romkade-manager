import { BarChart3 } from "lucide-react";
import { useSyncExternalStore } from "react";

import { useT } from "../i18n";
import { analyticsAvailable, getConsent, setConsent, subscribeConsent } from "../lib/analytics";

/** Choix de l'utilisateur pour les statistiques anonymes, partagé entre la question et le réglage. */
export function useAnalyticsConsent() {
  return useSyncExternalStore(subscribeConsent, getConsent, () => null);
}

/** Question du premier lancement : statistiques anonymes, refusées tant qu'il n'y a pas de réponse. */
export function AnalyticsNotice() {
  const t = useT();
  const consent = useAnalyticsConsent();
  if (!analyticsAvailable || consent !== null) return null;
  return (
    <section className="terms-notice" role="region" aria-label={t("settings.stats.title")}>
      <BarChart3 size={18} aria-hidden className="terms-notice__icon" />
      <p>{t("settings.stats.notice")}</p>
      <button type="button" className="button" onClick={() => setConsent("off")}>{t("settings.stats.decline")}</button>
      <button type="button" className="button button--primary" onClick={() => setConsent("on")}>{t("settings.stats.accept")}</button>
    </section>
  );
}

/** Réglage (Paramètres → À propos). */
export function AnalyticsPanel() {
  const t = useT();
  const consent = useAnalyticsConsent();
  if (!analyticsAvailable) return null;
  return (
    <section className="block form" aria-labelledby="stats-h">
      <h2 id="stats-h"><BarChart3 size={18} aria-hidden /> {t("settings.stats.title")}</h2>
      <p className="muted block__lead">{t("settings.stats.lead")}</p>
      <label className="toggle-inline toggle-inline--block">
        <input type="checkbox" checked={consent === "on"} onChange={(e) => setConsent(e.target.checked ? "on" : "off")} />
        {t("settings.stats.enable")}
      </label>
      <p className="muted">{t("settings.stats.never")}</p>
    </section>
  );
}
