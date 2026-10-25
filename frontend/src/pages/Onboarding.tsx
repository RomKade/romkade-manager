import { Check, CheckCircle2, ChevronLeft, ChevronRight, Loader2, RefreshCw } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useDeviceStatus, useLlmSettings, useSettings, useStartSync, useStatus } from "../api/queries";
import logo240 from "../assets/brand/romkade-manager-logo-240.webp";
import logo480 from "../assets/brand/romkade-manager-logo-480.webp";
import { LlmPanel } from "../components/LlmPanel";
import { LanguageSwitcher } from "../components/TopBar";
import { ErrorNotice, Spinner } from "../components/ui";
import { useT } from "../i18n";
import { ConnectionForm, HostKeyPanel, TestPanel } from "./Settings";

/** Installation terminée ou remise à plus tard : l'accueil n'y renvoie plus (navigateur seulement). */
const DONE_KEY = "romkade-onboarding-done";

export function onboardingDone(): boolean {
  try {
    return localStorage.getItem(DONE_KEY) === "1";
  } catch {
    return false;
  }
}

function markDone() {
  try { localStorage.setItem(DONE_KEY, "1"); } catch { /* navigation privée : l'installation sera reproposée */ }
}

const STEPS = ["console", "identity", "test", "library", "ai"] as const;

/**
 * Installation du premier lancement, sur une page à part (ni barre latérale, ni bandeaux, ni bulle de Duke) :
 * 1. la console (trouvée sur le réseau, mot de passe) ; 2. son empreinte ; 3. le test ; 4. la lecture de la
 * bibliothèque ; 5. Duke, l'assistant IA, facultatif. Chaque étape faite est cochée et reste consultable ; l'étape
 * en cours est la première qui reste à faire. Le tableau de bord y renvoie tant que la bibliothèque n'a jamais été
 * lue et que l'installation n'a pas été terminée (ou remise à plus tard).
 */
export function OnboardingPage() {
  const t = useT();
  const navigate = useNavigate();
  const settings = useSettings();
  const device = useDeviceStatus();
  const status = useStatus();
  const llm = useLlmSettings();
  const [picked, setPicked] = useState<number | null>(null);
  const [aiSkipped, setAiSkipped] = useState(false);

  const finish = () => { markDone(); navigate("/", { replace: true }); };

  if (settings.isPending || status.isPending) return <div className="onboarding"><Spinner label={t("common.loading")} /></div>;
  if (settings.isError) return <div className="onboarding"><ErrorNotice error={settings.error} /></div>;
  if (status.isError) return <div className="onboarding"><ErrorNotice error={status.error} /></div>;
  const s = settings.data;
  const st = status.data;
  const auth = s.auth_method === "password" ? s.has_password : !!s.key_path;
  // Bibliothèque déjà lue : la connexion a forcément réussi, même si la console dort en ce moment.
  const done = [!!s.host && auth, s.host_key_trusted, device.data?.connected === true || st.synced, st.synced,
    llm.data?.state === "connected" || aiSkipped];
  const first = done.findIndex((d) => !d);
  const auto = first === -1 ? STEPS.length : first;  // STEPS.length : écran final
  const current = picked !== null && picked <= auto ? picked : auto;
  const go = (i: number) => setPicked(i >= auto ? null : i);

  return (
    <div className="onboarding">
      <header className="onboarding__top">
        <img className="onboarding__logo" src={logo240} srcSet={`${logo240} 240w, ${logo480} 480w`} sizes="190px" width={190} height={42}
          alt="ROMKADE Manager" />
        <div className="onboarding__top-actions">
          <LanguageSwitcher />
          {current < STEPS.length && <button type="button" className="link-button" onClick={finish}>{t("onboarding.later")}</button>}
        </div>
      </header>

      <main className="onboarding__main" id="main">
        <h1 className="onboarding__title">{t("onboarding.title")}</h1>
        <p className="onboarding__lead">{t("onboarding.lead")}</p>

        <nav aria-label={t("onboarding.steps")}>
          <ol className="stepper">
            {STEPS.map((key, i) => {
              const state = i === current ? "current" : done[i] ? "done" : "todo";
              return (
                <li key={key} className={`stepper__step is-${state}`}>
                  <button type="button" className="stepper__btn" onClick={() => go(i)} disabled={i > auto}
                    aria-current={i === current ? "step" : undefined}>
                    <span className="stepper__dot" aria-hidden>{state === "done" ? <Check size={15} /> : i + 1}</span>
                    <span className="stepper__label">
                      {t(`onboarding.step.${key}`)}
                      {key === "ai" && <small>{t("onboarding.optional")}</small>}
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
        </nav>

        <section className="onboarding__panel" aria-live="polite">
          {current < STEPS.length && (
            <p className="onboarding__count">{t("onboarding.stepOf", { n: current + 1, total: STEPS.length })}</p>
          )}
          {current === 0 && <><p className="onboarding__intro">{t("onboarding.console.intro")}</p>
            <ConnectionForm initial={s} hasPassword={s.has_password} /></>}
          {current === 1 && <><p className="onboarding__intro">{t("onboarding.identity.intro")}</p>
            <HostKeyPanel trusted={s.host_key_trusted} host={s.host} /></>}
          {current === 2 && <><p className="onboarding__intro">{t("onboarding.test.intro")}</p>
            {done[2] ? <p className="ok-text"><CheckCircle2 size={16} aria-hidden /> {t("onboarding.test.ok")}</p> : <TestPanel auto />}</>}
          {current === 3 && <LibraryStep />}
          {current === 4 && <AiStep ready={llm.data?.state === "connected"} onSkip={() => { setAiSkipped(true); setPicked(null); }} />}
          {current === STEPS.length && <DoneStep games={st.game_count} consoles={st.platform_count}
            ai={llm.data?.state === "connected"} onOpen={finish} />}

          {current < STEPS.length && (
            <div className="onboarding__nav">
              {current > 0 && (
                <button type="button" className="button" onClick={() => go(current - 1)}><ChevronLeft size={16} aria-hidden /> {t("onboarding.back")}</button>
              )}
              {done[current] && (
                <button type="button" className="button button--primary onboarding__next" onClick={() => go(current + 1)}>
                  {t("onboarding.next")} <ChevronRight size={16} aria-hidden />
                </button>
              )}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}

/** Étape 4 : première lecture de la carte, avec sa progression console par console. */
function LibraryStep() {
  const t = useT();
  const status = useStatus().data!;
  const start = useStartSync(() => undefined);
  const run = status.last_run;
  const failed = run?.status === "failed" && !status.sync_running;
  return (
    <div className="block">
      <h2>{t("onboarding.library.title")}</h2>
      <p className="muted block__lead">{t("onboarding.library.intro")}</p>
      {status.synced ? (
        <p className="ok-text"><CheckCircle2 size={16} aria-hidden /> {t("onboarding.library.done", { games: status.game_count, consoles: status.platform_count })}</p>
      ) : status.sync_running || start.isPending ? (
        <p className="onboarding__progress" role="status">
          <Loader2 size={16} aria-hidden className="spin" />
          {run && run.platforms_total ? t("onboarding.library.running", { done: run.platforms_done, total: run.platforms_total }) : t("onboarding.library.starting")}
        </p>
      ) : (
        <>
          {failed && <p className="text-error">{t("onboarding.library.failed")}</p>}
          <button type="button" className="button button--primary" onClick={() => start.mutate()}>
            <RefreshCw size={16} aria-hidden /> {t(failed ? "onboarding.library.again" : "onboarding.library.start")}
          </button>
        </>
      )}
      {start.isError && <ErrorNotice error={start.error} />}
    </div>
  );
}

/** Étape 5, facultative : brancher une IA pour Duke (même panneau que Paramètres > Assistant IA). */
function AiStep({ ready, onSkip }: { ready: boolean; onSkip: () => void }) {
  const t = useT();
  return (
    <>
      <div className="onboarding__ai-head">
        <h2>{t("onboarding.ai.title")}</h2>
        <p className="muted">{t("onboarding.ai.intro")}</p>
        {ready && <p className="ok-text"><CheckCircle2 size={16} aria-hidden /> {t("onboarding.ai.ready")}</p>}
      </div>
      <LlmPanel />
      {!ready && <button type="button" className="button onboarding__skip" onClick={onSkip}>{t("onboarding.ai.skip")}</button>}
    </>
  );
}

function DoneStep({ games, consoles, ai, onOpen }: { games: number; consoles: number; ai: boolean; onOpen: () => void }) {
  const t = useT();
  return (
    <div className="onboarding__done">
      <CheckCircle2 size={44} aria-hidden className="onboarding__done-icon" />
      <h2>{t("onboarding.done.title")}</h2>
      <p className="muted">{t("onboarding.done.lead")}</p>
      <ul className="onboarding__summary">
        <li><Check size={16} aria-hidden /> {t("onboarding.done.games", { games, consoles })}</li>
        <li className={ai ? "" : "is-off"}>
          {ai ? <Check size={16} aria-hidden /> : <span className="onboarding__dash" aria-hidden>–</span>}
          {t("onboarding.done.ai")} : {t(ai ? "onboarding.done.aiOn" : "onboarding.done.aiOff")}
        </li>
      </ul>
      <p className="muted small">{t("onboarding.done.remote")}</p>
      <button type="button" className="button button--primary onboarding__open" onClick={onOpen}>{t("onboarding.done.open")}</button>
    </div>
  );
}
