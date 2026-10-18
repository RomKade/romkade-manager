import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach } from "vitest";

// Sans les globals de vitest, Testing Library ne démonte pas le rendu entre deux tests.
afterEach(cleanup);
// Bandeau des conditions déjà lu, sauf dans son propre test.
beforeEach(() => localStorage.setItem("romkade-terms-v1", "1"));

// Les tests vérifient les textes français, quelle que soit la langue de l'environnement.
import { setLang } from "../i18n";
setLang("fr");
