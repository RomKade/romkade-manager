import { Gamepad2 } from "lucide-react";
import { useState } from "react";

/**
 * Illustration de la console (frontend/public/consoles/<CODE>.webp, retroarch-assets, CC-BY 4.0). `code` : code de
 * console commun à tous les firmwares (platform.code : « snes » -> « SFC »). Sans illustration : une manette.
 */
export function ConsoleIcon({ code, className = "" }: { code: string; className?: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) {
    return <span className={`console-icon console-icon--generic ${className}`} aria-hidden><Gamepad2 size={28} strokeWidth={1.5} /></span>;
  }
  return (
    <img className={`console-icon ${className}`} src={`/consoles/${code.toUpperCase()}.webp`} alt="" aria-hidden
      loading="lazy" decoding="async" onError={() => setFailed(true)} />
  );
}
