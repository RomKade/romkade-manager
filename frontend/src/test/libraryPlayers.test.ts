import { describe, expect, it } from "vitest";

import { activeFilterCount, parseLibrary, serializeLibrary, showsConsolePicker, toApiQuery } from "../lib/libraryParams";

describe("Filtre « Joueurs » de la bibliothèque", () => {
  it("passe par l'adresse et par l'API, compte comme un filtre", () => {
    const s = parseLibrary(new URLSearchParams("players=2"));
    expect(s.players).toBe("2");
    expect(serializeLibrary(s).get("players")).toBe("2");
    expect(toApiQuery(s).players).toBe("2");
    expect(activeFilterCount(s)).toBe(1);
    expect(showsConsolePicker(s)).toBe(false);  // liste des jeux à deux, sans passer par le choix de console
  });

  it("ignore une valeur inconnue", () => {
    const s = parseLibrary(new URLSearchParams("players=3"));
    expect(s.players).toBe("");
    expect(toApiQuery(s).players).toBeUndefined();
  });
});
