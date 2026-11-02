/**
 * Démo publique du Manager (romkade.com/demo, `npm run build:demo`) : la vraie interface, branchée sur une console
 * simulée dans le navigateur (server.ts). Pas de compte, pas de statistiques, pas d'application installable.
 */
import { TERMS_KEY } from "../components/TermsNotice";
import { installDemoServer } from "./server";

export function installDemo(): void {
  installDemoServer();
  // Bandeau des conditions du premier lancement : la démo a le sien (DemoBanner).
  try { localStorage.setItem(TERMS_KEY, "1"); } catch { /* navigation privée */ }
}
