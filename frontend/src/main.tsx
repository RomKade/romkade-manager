import "@fontsource-variable/archivo/wdth.css";
import "@fontsource-variable/atkinson-hyperlegible-next/wght.css";
import "./styles/tokens.css";
import "./styles/app.css";
import "./styles/auth.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { IS_DEMO } from "./demo/mode";
import { initAnalytics } from "./lib/analytics";
import { initLikes } from "./lib/likes";

const render = () => createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

// Démo publique (romkade.com/demo) : console simulée dans le navigateur, sans statistiques ni service worker.
// Test écrit en entier (pas IS_DEMO) : la compilation normale l'évalue à false et n'embarque pas la démo.
if (import.meta.env.MODE === "demo") import("./demo").then((demo) => { demo.installDemo(); render(); });
else render();

// Statistiques anonymes et jeux aimés partagés : seulement si l'utilisateur les a acceptés (lib/analytics.ts, lib/likes.ts).
if (!IS_DEMO) {
  initAnalytics();
  initLikes();
}

// Application installable : service worker (public/sw.js), seulement dans la version compilée.
if (import.meta.env.PROD && !IS_DEMO && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => undefined);
  });
}
