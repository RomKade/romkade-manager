import { t as translate } from "../i18n";

/** Libellé d'une sauvegarde : « Sauvegarde en jeu », « Instantanée 2 », « Instantanée auto ». */
export function saveLabel(t: typeof translate, s: { kind: string; slot?: string | null }): string {
  if (s.kind === "sram") return t("saves.kind.sram");
  if (s.slot === "auto") return t("saves.kind.auto");
  return t("saves.kind.state", { slot: s.slot ?? "0" });
}
