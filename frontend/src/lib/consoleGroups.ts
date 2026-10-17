/** Regroupement des dossiers de la carte par constructeur, pour l'accueil de la bibliothèque. */
export const CONSOLE_GROUPS: { label: string; dirs: string[] }[] = [
  { label: "Nintendo", dirs: ["FC", "FDS", "SFC", "N64", "GB", "GBC", "GBA", "NDS", "VB", "GW", "POKE"] },
  { label: "Sega", dirs: ["SMS", "MD", "MDCD", "SEGA32X", "GG", "SATURN", "DREAMCAST"] },
  { label: "Sony", dirs: ["PS", "PSP"] },
  { label: "NEC et SNK", dirs: ["PCE", "PCECD", "NEOGEO", "NEOCD", "NGP"] },
  { label: "Arcade", dirs: ["MAME", "FBNEO", "CPS1", "CPS2", "CPS3", "HBMAME", "NAOMI", "ATOMISWAVE", "PGM2", "VARCADE"] },
  { label: "Atari, Bandai et ordinateurs", dirs: ["A2600", "A5200", "A7800", "A800", "LYNX", "WS", "MSX", "AMIGA", "ATARIST", "C64", "VIC20", "DOS"] },
];
export const OTHER_GROUP = "Moteurs et autres";

export function groupOf(directory: string): string {
  return CONSOLE_GROUPS.find((g) => g.dirs.includes(directory.toUpperCase()))?.label ?? OTHER_GROUP;
}

/** Nom court affiché à côté du pictogramme de console (nom d'usage plutôt que le dossier de la carte). */
const SHORT_NAMES: Record<string, string> = {
  FC: "NES", FDS: "FDS", SFC: "SNES", N64: "N64", GB: "GB", GBC: "GBC", GBA: "GBA", NDS: "DS", VB: "VB", GW: "G&W",
  POKE: "PKMN mini", SMS: "Master Sys.", MD: "Mega Drive", MDCD: "Mega-CD", SEGA32X: "32X", GG: "Game Gear",
  SATURN: "Saturn", DREAMCAST: "Dreamcast", PS: "PS1", PSP: "PSP", PCE: "PC Engine", PCECD: "PCE CD",
  NEOGEO: "Neo Geo", NEOCD: "Neo Geo CD", NGP: "NGPC", MAME: "Arcade", FBNEO: "Arcade", HBMAME: "Arcade",
  CPS1: "CPS1", CPS2: "CPS2", CPS3: "CPS3", NAOMI: "Naomi", ATOMISWAVE: "Atomiswave", PGM2: "PGM2", VARCADE: "Arcade",
  A2600: "Atari 2600", A5200: "Atari 5200", A7800: "Atari 7800", A800: "Atari 800", LYNX: "Lynx", WS: "WonderSwan",
  MSX: "MSX", AMIGA: "Amiga", ATARIST: "Atari ST", C64: "C64", VIC20: "VIC-20", DOS: "DOS", SCUMMVM: "ScummVM",
  EASYRPG: "EasyRPG",
};

export function consoleShortName(code: string): string {
  return SHORT_NAMES[code.toUpperCase()] ?? code.toUpperCase();
}
