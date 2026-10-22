import { describe, expect, it } from "vitest";

import { passwordStrength, passwordValid } from "../auth/password";

describe("force du mot de passe", () => {
  it("suit les règles de Supabase Auth et le bonus « Fort »", () => {
    expect(passwordStrength("")).toBe("empty");
    expect(passwordStrength("court1A")).toBe("weak");          // moins de 10 caractères
    expect(passwordStrength("sansmajuscule1")).toBe("weak");
    expect(passwordStrength("Retrogame42")).toBe("medium");     // règles remplies
    expect(passwordStrength("Retrogame42!")).toBe("strong");    // + caractère spécial
    expect(passwordStrength("Retrogaming2026x")).toBe("strong"); // + 14 caractères
    expect(passwordValid("Retrogame42")).toBe(true);
    expect(passwordValid("retrogame42")).toBe(false);
  });
});
