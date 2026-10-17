import { Gamepad2 } from "lucide-react";
import { useState } from "react";

import { consoleShortName } from "../lib/consoleGroups";

/**
 * Pictogramme + nom court de la console d'un jeu (« GBA », « SNES »…), nom complet au survol. Repère rapide dans
 * les listes de jeux. `code` : code de console commun aux firmwares (platform.code, à défaut le dossier).
 */
export function ConsoleBadge({ code, label, className = "" }: { code: string; label?: string | null; className?: string }) {
  const [failed, setFailed] = useState(false);
  const short = consoleShortName(code);
  return (
    <span className={`console-badge ${className}`} title={label ?? short}>
      {failed ? <Gamepad2 size={14} aria-hidden className="console-badge__icon" /> : (
        <img className="console-badge__icon" src={`/consoles/${code.toUpperCase()}.webp`} alt="" aria-hidden
          loading="lazy" decoding="async" onError={() => setFailed(true)} />
      )}
      <span className="console-badge__name">{short}</span>
      {label && label !== short && <span className="visually-hidden"> ({label})</span>}
    </span>
  );
}
