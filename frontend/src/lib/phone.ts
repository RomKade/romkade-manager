/** Ouvert sur un téléphone associé par QR code (cookie posé par le serveur du réseau local, app.services.phone). */
export function onPhone(): boolean {
  return typeof document !== "undefined" && /(?:^|;\s*)romkade_device=phone(?:;|$)/.test(document.cookie);
}
