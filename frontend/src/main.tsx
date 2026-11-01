import "@fontsource-variable/archivo/wdth.css";
import "@fontsource-variable/atkinson-hyperlegible-next/wght.css";
import "./styles/tokens.css";
import "./styles/app.css";
import "./styles/auth.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { initAnalytics } from "./lib/analytics";
import { initLikes } from "./lib/likes";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

// Statistiques anonymes et jeux aimés partagés : seulement si l'utilisateur les a acceptés (lib/analytics.ts, lib/likes.ts).
initAnalytics();
initLikes();

// Application installable : service worker (public/sw.js), seulement dans la version compilée.
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => undefined);
  });
}
