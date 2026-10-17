import { afterEach, describe, expect, it } from "vitest";

import { NAMESPACES, setLang, t } from "../i18n/core";
import { bytes } from "../lib/format";

const placeholders = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

afterEach(() => setLang("fr"));

describe("traductions", () => {
  for (const [ns, messages] of Object.entries(NAMESPACES)) {
    it(`${ns} : mêmes clés et mêmes variables en français, anglais et espagnol`, () => {
      const fr = Object.keys(messages.fr).sort();
      for (const lang of ["en", "es"] as const) {
        const other = messages[lang];
        // (common.error.* n'existe qu'en anglais et en espagnol : en français, le message du serveur sert tel quel)
        expect(fr.filter((k) => !(k in other)), `${ns} : clés absentes en ${lang}`).toEqual([]);
        for (const k of fr) {
          expect(placeholders(other[k]!), `${ns}.${k} (${lang})`).toEqual(placeholders(messages.fr[k]!));
        }
      }
    });
  }

  it("accorde les pluriels selon la langue et formate les nombres", () => {
    setLang("en");
    expect(t("common.nav.activeCount", { count: 1200 })).toBe("1,200 in progress");
    expect(bytes(5 * 1024 * 1024)).toBe("5.0 MB");
    setLang("es");
    expect(t("common.genre.sport")).toBe("Deportes");
    setLang("fr");
    expect(bytes(5 * 1024 * 1024)).toBe("5,0 Mo");
    expect(t("clé.inconnue")).toBe("clé.inconnue");
  });
});
