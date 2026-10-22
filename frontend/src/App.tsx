import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { BrowserRouter, Navigate, Outlet, Route, Routes } from "react-router-dom";

import { ApiError } from "./api/client";
import { AuthGate } from "./auth/AuthContext";
import { useStatus, useTransfersLive } from "./api/queries";
import { AnalyticsNotice } from "./components/AnalyticsNotice";
import { AssistantBubble } from "./components/AssistantBubble";
import { GameSheet } from "./components/GameSheet";
import { Sidebar } from "./components/Sidebar";
import { PlayAlerts } from "./components/PlayAlerts";
import { TermsNotice } from "./components/TermsNotice";
import { TopBar } from "./components/TopBar";
import { t, useLang } from "./i18n";
import { Empty } from "./components/ui";
import { DashboardPage } from "./pages/Dashboard";
import { LibraryPage } from "./pages/Library";
import { BluetoothPage } from "./pages/Bluetooth";
import { ControllersPage } from "./pages/Controllers";
import { PlaytimePage } from "./pages/Playtime";
import { SavesPage } from "./pages/Saves";
import { ScreenshotsPage } from "./pages/Screenshots";
import { SettingsPage } from "./pages/Settings";
import { SyncPage } from "./pages/Sync";
import { TermsPage } from "./pages/Terms";
import { TransfersPage } from "./pages/Transfers";

export function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        refetchOnWindowFocus: false,
        // Une erreur métier (console injoignable, 4xx) ne se corrige pas en réessayant.
        retry: (n, err) => !(err instanceof ApiError && err.status >= 400) && n < 2,
      },
    },
  });
}

/**
 * Quand une synchronisation démarre, se termine ou échoue, tout ce qui dépend du catalogue est rafraîchi.
 * On suit l'identifiant et l'état de la dernière synchronisation : une synchro qui échoue en moins d'une
 * seconde (console éteinte) n'est jamais vue « en cours », mais son état final change quand même la clé.
 */
function SyncWatcher() {
  const qc = useQueryClient();
  const run = useStatus().data?.last_run;
  const key = run ? `${run.id}:${run.status}` : "";
  const prev = useRef(key);
  useEffect(() => {
    if (prev.current && key !== prev.current) {
      for (const k of ["platforms", "games", "facets", "syncs", "changes", "duplicates", "game", "device-status", "saves"]) {
        qc.invalidateQueries({ queryKey: [k] });
      }
    }
    prev.current = key;
  }, [key, qc]);
  return null;
}

function Layout() {
  useTransfersLive();
  // Jeu ouvert depuis l'assistant (pastille d'une réponse) : la fiche s'ouvre par-dessus la page en cours.
  const [assistantGame, setAssistantGame] = useState<number | null>(null);
  return (
    <div className="app">
      <a href="#main" className="skip-link">{t("common.nav.skip")}</a>
      <Sidebar />
      <main id="main" className="main" tabIndex={-1}>
        <TopBar />
        <PlayAlerts />
        <TermsNotice />
        <AnalyticsNotice />
        <div className="main__content">
          <Outlet />
        </div>
      </main>
      <SyncWatcher />
      <AssistantBubble placement="page" onOpenGame={setAssistantGame} />
      <GameSheet id={assistantGame} onClose={() => setAssistantGame(null)} onOpen={setAssistantGame} />
    </div>
  );
}

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="bibliotheque" element={<LibraryPage />} />
        {/* L'ancienne page Consoles : ses informations sont dans la Bibliothèque. */}
        <Route path="consoles" element={<Navigate to="/bibliotheque" replace />} />
        <Route path="ajouter-des-jeux" element={<TransfersPage />} />
        <Route path="transferts" element={<Navigate to="/ajouter-des-jeux" replace />} />
        <Route path="synchronisation" element={<SyncPage />} />
        <Route path="sauvegardes" element={<SavesPage />} />
        <Route path="captures" element={<ScreenshotsPage />} />
        <Route path="manettes" element={<ControllersPage />} />
        <Route path="bluetooth" element={<BluetoothPage />} />
        <Route path="temps-de-jeu" element={<PlaytimePage />} />
        <Route path="parametres" element={<SettingsPage />} />
        <Route path="parametres/:tab" element={<SettingsPage />} />
        <Route path="conditions" element={<TermsPage />} />
        <Route path="*" element={<div className="page"><Empty title={t("common.nav.notFound")} /></div>} />
      </Route>
    </Routes>
  );
}

export function App() {
  const [client] = useState(makeQueryClient);
  // Changer de langue redessine toute l'interface (dates et nombres compris) ; le cache des requêtes est gardé.
  const lang = useLang();
  return (
    <QueryClientProvider client={client}>
      {/* Compte ROMKADE obligatoire : sans connexion, l'écran de connexion remplace tout le Manager. */}
      <AuthGate>
        <BrowserRouter key={lang}>
          <AppRoutes />
        </BrowserRouter>
      </AuthGate>
    </QueryClientProvider>
  );
}
