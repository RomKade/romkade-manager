/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

import pkg from "./package.json" with { type: "json" };

const API_PORT = (globalThis as { process?: { env: Record<string, string | undefined> } }).process?.env.ROMKADE_API_PORT ?? "8765";

// Version affichée dans l'application (barre latérale, À propos) : celle de package.json, alignée sur le backend
// (pyproject.toml), ce que vérifie backend/tests/test_version.py.

// Démo publique (`npm run build:demo`, servie sur romkade.com/demo/) : toutes les pages renvoient vers index.html
// (routeur) ; elle n'est ni indexée par les moteurs de recherche ni installable.
const demoSite: Plugin = {
  name: "romkade-demo-site",
  transformIndexHtml: (html) => html
    .replace("<head>", '<head>\n    <meta name="robots" content="noindex" />')
    .replace(/\s*<link rel="manifest"[^>]*>/, ""),  // pas d'application installable depuis la démo
  generateBundle() {
    // FallbackResource (mod_dir) plutôt qu'une règle de réécriture : celles du site (HTTPS, www) restent appliquées.
    this.emitFile({ type: "asset", fileName: ".htaccess", source: "FallbackResource /demo/index.html\n" });
  },
};

// En développement, l'interface tourne sur 5173 et relaie /api vers le backend FastAPI.
// En production, FastAPI sert directement le dossier dist/ sur le port 8765.
export default defineConfig(({ mode }) => ({
  base: mode === "demo" ? "/demo/" : "/",
  plugins: [react(), ...(mode === "demo" ? [demoSite] : [])],
  define: { __APP_VERSION__: JSON.stringify(pkg.version) },
  server: {
    host: "127.0.0.1",
    port: 5173,
    // ROMKADE_API_PORT : moteur sur un autre port (instance de test à côté du Manager habituel).
    proxy: { "/api": { target: `http://127.0.0.1:${API_PORT}`, ws: true } },  // ws : manette à distance
  },
  build: { outDir: mode === "demo" ? "dist-demo" : "dist", sourcemap: false, chunkSizeWarningLimit: 700 },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
}));
