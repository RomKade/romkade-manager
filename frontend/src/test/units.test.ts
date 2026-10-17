import { describe, expect, it } from "vitest";

import { qs } from "../api/client";
import { buildSegments } from "../components/StorageBar";
import { ago, bytes, gb, initials, plural } from "../lib/format";
import { groupOf } from "../lib/consoleGroups";
import {
  activeFilterCount, clearedFilters, parseLibrary, serializeLibrary, showsConsolePicker, showsGenrePicker, toApiQuery,
} from "../lib/libraryParams";

const nbsp = (s: string) => s.replace(/[  ]/g, " ");

describe("format", () => {
  it("affiche les tailles en unités françaises", () => {
    expect(bytes(512)).toBe("512 o");
    expect(nbsp(bytes(1536))).toBe("1,5 Ko");
    expect(nbsp(bytes(5 * 1024 ** 3))).toBe("5,0 Go");
    expect(bytes(null)).toBe("inconnue");
    expect(nbsp(gb(15_043_330_048))).toBe("15,0 Go");
  });
  it("accorde le pluriel", () => {
    expect(plural(1, "jeu", "jeux")).toBe("1 jeu");
    expect(nbsp(plural(4838, "jeu", "jeux"))).toBe("4 838 jeux");
  });
  it("donne des dates relatives", () => {
    const now = Date.parse("2026-10-16T12:00:00Z");
    expect(ago("2026-10-16T11:59:40Z", now)).toBe("à l'instant");
    expect(ago("2026-10-16T09:00:00Z", now)).toBe("il y a 3 heures");
    expect(ago(null, now)).toBe("jamais");
  });
  it("calcule les initiales d'une jaquette absente", () => {
    expect(initials("Super Mario World")).toBe("SM");
    expect(initials("1942")).toBe("19");
  });
});

describe("état de la bibliothèque dans l'URL", () => {
  it("relit et réécrit les filtres sans perte", () => {
    const sp = new URLSearchParams("q=zelda&platform=SFC&platform=GBA&extension=smc&sort=size&view=table");
    const st = parseLibrary(sp);
    expect(st).toMatchObject({ q: "zelda", platform: ["SFC", "GBA"], extension: ["smc"], sort: "size", order: "desc", view: "table" });
    expect(parseLibrary(serializeLibrary(st))).toEqual(st);
    expect(activeFilterCount(st)).toBe(4);
  });
  it("utilise des valeurs sûres si l'URL est fantaisiste", () => {
    const st = parseLibrary(new URLSearchParams("sort=random&order=sideways&view=3d"));
    expect(st).toMatchObject({ sort: "name", order: "asc", view: "grid" });
    expect(serializeLibrary(st).toString()).toBe("");
  });
  it("ne transmet pas la vue à l'API et omet les champs vides", () => {
    const q = toApiQuery(parseLibrary(new URLSearchParams("view=table&q=%20%20")));
    expect(qs(q)).toBe("?sort=name&order=asc");
  });
});

describe("barre d'occupation de la carte", () => {
  const p = (directory: string, total_bytes: number) => ({ directory, label: directory, total_bytes }) as never;
  it("garde 6 consoles, regroupe le reste et isole système et espace libre", () => {
    const plats = ["A", "B", "C", "D", "E", "F", "G", "H"].map((d, i) => p(d, (10 - i) * 1e9));
    const segs = buildSegments(plats, 100e9, 20e9);
    expect(segs.map((s) => s.key)).toEqual(["A", "B", "C", "D", "E", "F", "other", "system", "free"]);
    expect(segs.find((s) => s.key === "other")!.bytes).toBe(7e9);
    expect(segs.find((s) => s.key === "system")!.bytes).toBe(100e9 - 20e9 - 52e9);
    expect(segs[0]!.color).toBe("var(--series-1)");
  });
});

describe("accueil de la bibliothèque", () => {
  const st = (q: string) => parseLibrary(new URLSearchParams(q));
  it("montre le choix des consoles seulement sans console, recherche ni filtre", () => {
    expect(showsConsolePicker(st(""))).toBe(true);
    expect(showsConsolePicker(st("view=table"))).toBe(true);
    expect(showsConsolePicker(st("platform=MD"))).toBe(false);
    expect(showsConsolePicker(st("all=1"))).toBe(false);
    expect(showsConsolePicker(st("q=sonic"))).toBe(false);
    expect(showsConsolePicker(st("genre=sport"))).toBe(false);
  });
  it("propose le choix du genre une fois la console ouverte", () => {
    expect(showsGenrePicker(st("platform=MD"))).toBe(true);
    expect(showsGenrePicker(st("platform=MD&genre=sport"))).toBe(false);
    expect(showsGenrePicker(st("platform=MD&all=1"))).toBe(false);
    expect(showsGenrePicker(st("platform=MD&q=sonic"))).toBe(false);
    expect(showsGenrePicker(st("platform=MD&platform=SFC"))).toBe(false);
  });
  it("garde la console ouverte quand on efface les filtres", () => {
    const one = st("platform=MD&genre=sport&region=Europe&view=table");
    expect(activeFilterCount(one)).toBe(2);
    expect(serializeLibrary(clearedFilters(one)).toString()).toBe("platform=MD&all=1&view=table");
    expect(serializeLibrary(clearedFilters(st("all=1&platform=MD&platform=SFC&genre=tir"))).toString()).toBe("all=1");
    expect(parseLibrary(serializeLibrary(one))).toEqual(one);
    expect(toApiQuery(one).genre).toEqual(["sport"]);
  });
  it("range les dossiers par constructeur", () => {
    expect(groupOf("SFC")).toBe("Nintendo");
    expect(groupOf("fbneo")).toBe("Arcade");
    expect(groupOf("OPENBOR")).toBe("Moteurs et autres");
  });
});
