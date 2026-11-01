/**
 * Jeux aimés ou non (favoris, « Je n'aime pas ») partagés avec ROMKADE Cloud pour le classement des plus aimés,
 * seulement avec l'accord donné pour les statistiques anonymes. Le moteur local envoie toute la liste, avec les
 * dates : envoyée après chaque changement, au démarrage, et retirée du cloud quand l'accord est retiré.
 * Sans session ROMKADE ou cloud injoignable : rien, le prochain envoi rattrape.
 */
import { likes } from "../auth/cloud";
import { getConsent, subscribeConsent } from "./analytics";

let timer: ReturnType<typeof setTimeout> | undefined;

/** Après un favori ou un « Je n'aime pas » : un seul envoi pour plusieurs clics rapprochés. */
export function shareLikesSoon(delay = 3000): void {
  if (getConsent() !== "on") return;
  clearTimeout(timer);
  timer = setTimeout(() => { likes.share().catch(() => undefined); }, delay);
}

/** Au chargement de l'application : envoi initial (favoris d'avant, autre ordinateur) et suivi de l'accord. */
export function initLikes(): void {
  let last = getConsent();
  if (last === "on") shareLikesSoon(10_000);
  subscribeConsent(() => {
    const now = getConsent();
    if (now === last) return;
    last = now;
    if (now === "on") shareLikesSoon(0);
    else if (now === "off") { clearTimeout(timer); likes.unshare().catch(() => undefined); }
  });
}
