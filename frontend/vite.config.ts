/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

import pkg from "./package.json" with { type: "json" };

// Version affichée dans l'application (barre latérale, À propos) : celle de package.json, alignée sur le backend
// (pyproject.toml), ce que vérifie backend/tests/test_version.py.

// En développement, l'interface tourne sur 5173 et relaie /api vers le backend FastAPI.
// En production, FastAPI sert directement le dossier dist/ sur le port 8765.
export default defineConfig({
  plugins: [react()],
  define: { __APP_VERSION__: JSON.stringify(pkg.version) },
  server: {
    host: "127.0.0.1",
    port: 5173,
    // ROMKADE_API_PORT : moteur sur un autre port (instance de test à côté du Manager habituel).
    proxy: { "/api": { target: `http://127.0.0.1:${process.env.ROMKADE_API_PORT ?? 8765}`, ws: true } },  // ws : manette à distance
  },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 700 },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
