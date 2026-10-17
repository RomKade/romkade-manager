import { Play } from "lucide-react";

import type { Save } from "../api/client";
import { useCaps, useLaunchGame } from "../api/queries";
import { useT } from "../i18n";
import { errorMessage } from "./ui";

/** « Reprendre ici » pour une instantanée RetroArch, « Jouer » sinon (le jeu charge sa propre sauvegarde). */
export function PlaySaveButton({ save }: { save: Save }) {
  const t = useT();
  const launch = useLaunchGame();
  const caps = useCaps();
  if (!save.game || !save.game.present || !caps.launch) return null;
  const resume = caps.resume_slot && save.kind === "state" && save.source === "retroarch";
  const label = resume ? t("saves.resume") : t("saves.play");
  return (
    <>
      <button type="button" className="button button--small" disabled={launch.isPending}
        onClick={() => launch.mutate({ id: save.game!.id, slot: resume ? save.slot : null })}
        title={resume ? t("saves.resumeHint") : t("saves.playHint")}>
        <Play size={13} fill="currentColor" aria-hidden /> {launch.isPending ? t("saves.launching") : launch.isSuccess ? t("saves.launched") : label}
      </button>
      {launch.isError && <span className="text-error" role="alert">{errorMessage(launch.error)}</span>}
    </>
  );
}
