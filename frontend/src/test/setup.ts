import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Sans les globals de vitest, Testing Library ne démonte pas le rendu entre deux tests.
afterEach(cleanup);

// Les tests vérifient les textes français, quelle que soit la langue de l'environnement.
import { setLang } from "../i18n";
setLang("fr");
