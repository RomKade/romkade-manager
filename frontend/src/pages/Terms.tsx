import { ExternalLink } from "lucide-react";

import { PageHeader } from "../components/ui";
import { useT } from "../i18n";
import { REPO_URL } from "../lib/credits";

const SECTIONS = ["games", "device", "liability", "warranty", "services", "brands", "data", "source"] as const;

/** Conditions d'utilisation : ROMKADE ne fournit aucun jeu et ne répond pas des manipulations de l'utilisateur. */
export function TermsPage() {
  const t = useT();
  return (
    <div className="page terms">
      <PageHeader title={t("legal.title")} lead={t("legal.lead")} />
      {SECTIONS.map((k) => (
        <section key={k} className="block" aria-labelledby={`terms-${k}`}>
          <h2 id={`terms-${k}`}>{t(`legal.${k}.title`)}</h2>
          <p>{t(`legal.${k}.body`)}</p>
          {k === "source" && (
            <a href={REPO_URL} target="_blank" rel="noreferrer noopener" className="link">
              github.com/arnoweb/romkade-manager <ExternalLink size={12} aria-hidden />
            </a>
          )}
        </section>
      ))}
      <p className="muted">{t("legal.updated")}</p>
    </div>
  );
}
