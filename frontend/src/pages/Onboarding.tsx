import { Check, CheckCircle2, ChevronLeft, ChevronRight, Loader2, RefreshCw } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useDeviceStatus, useLlmSettings, useSettings, useStartSync, useStatus } from "../api/queries";
import logo240 from "../assets/brand/romkade-manager-logo-240.webp";
import logo480 from "../assets/brand/romkade-manager-logo-480.webp";
import { useCloudConsoles } from "../auth/cloud";
import { LlmPanel } from "../components/LlmPanel";
import { LanguageSwitcher } from "../components/TopBar";
import { ErrorNotice, Spinner } from "../components/ui";
import { useT } from "../i18n";
import { RemoteControl } from "./Account";
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

const STEPS = ["console", "identity", "test", "library", "ai", "remote"] as const;
/** Étapes facultatives : « Plus tard » les passe. */
const OPTIONAL = new Set<string>(["ai", "remote"]);

/**
 * Installation du premier lancement, sur une page à part (ni barre latérale, ni bandeaux, ni bulle de Duke) :
 * 1. la console (trouvée sur le réseau, mot de passe) ; 2. son empreinte ; 3. le test ; 4. la lecture de la
 * bibliothèque ; 5. Duke, l'assistant IA, et 6. parler à la console depuis ChatGPT, Claude ou Google Home (ROMKADE
 * Cloud), tous deux facultatifs. Chaque étape faite est cochée et reste consultable ; l'étape
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
  const remote = useCloudConsoles();
  const [picked, setPicked] = useState<number | null>(null);
  const [skipped, setSkipped] = useState<Set<string>>(new Set());

  const finish = () => { markDone(); navigate("/", { replace: true }); };

  if (settings.isPending || status.isPending) return <div className="onboarding"><Spinner label={t("common.loading")} /></div>;
  if (settings.isError) return <div className="onboarding"><ErrorNotice error={settings.error} /></div>;
  if (status.isError) return <div className="onboarding"><ErrorNotice error={status.error} /></div>;
  const s = settings.data;
  const st = status.data;
  const auth = s.auth_method === "password" ? s.has_password : !!s.key_path;
  // Bibliothèque déjà lue : la connexion a forcément réussi, même si la console dort en ce moment.
  const aiOn = llm.data?.state === "connected";
  const remoteOn = (remote.data?.length ?? 0) > 0;
  const done = [!!s.host && auth, s.host_key_trusted, device.data?.connected === true || st.synced, st.synced,
    aiOn || skipped.has("ai"), remoteOn || skipped.has("remote")];
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
                      {OPTIONAL.has(key) && <small> · {t("onboarding.optional")}</small>}
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
        </nav>

        {current < STEPS.length ? (
          <section className="onboarding__panel" aria-labelledby="ob-card-h">
            <p className="onboarding__count">{t("onboarding.stepOf", { n: current + 1, total: STEPS.length })}</p>
            {/* Une carte par étape : titre, phrase, état « fait », action, puis « À quoi sert cette étape ? » à déplier. */}
            <div className="onboarding__card" aria-live="polite">
              <h2 id="ob-card-h">{t(`onboarding.card.${STEPS[current]}.title`)}</h2>
              <p className="onboarding__desc">{t(`onboarding.card.${STEPS[current]}.desc`)}</p>
              {done[current] && (
                <div className="onboarding__ok" role="status">
                  <CheckCircle2 size={40} aria-hidden />
                  <div>
                    <p className="onboarding__ok-title">{t(`onboarding.ok.${STEPS[current]}`)}</p>
                    <p className="onboarding__ok-sub">{current === 3
                      ? t("onboarding.library.done", { games: st.game_count, consoles: st.platform_count })
                      : t("onboarding.okNext")}</p>
                  </div>
                </div>
              )}
              <div className={`onboarding__embed ${OPTIONAL.has(STEPS[current]!) ? "onboarding__embed--ai" : ""}`}>
                {current === 0 && <ConnectionForm initial={s} hasPassword={s.has_password} />}
                {current === 1 && <HostKeyPanel trusted={s.host_key_trusted} host={s.host} />}
                {current === 2 && !done[2] && <TestPanel auto />}
                {current === 3 && !done[3] && <LibraryStep />}
                {current === 4 && <LlmPanel />}
                {current === 5 && <RemoteControl />}
              </div>
              <details className="onboarding__why">
                <summary>{t("onboarding.why")}</summary>
                <p>{t(`onboarding.${STEPS[current]}.intro`)}</p>
              </details>
            </div>

            {/* Sous la carte, collée en bas de l'écran quand l'étape est longue : toujours visible. */}
            <div className="onboarding__nav">
              {current > 0 ? (
                <button type="button" className="button" onClick={() => go(current - 1)}><ChevronLeft size={16} aria-hidden /> {t("onboarding.back")}</button>
              ) : <span />}
              <div className="onboarding__forward">
                {done[current] ? (
                  <button type="button" className="button button--primary" onClick={() => go(current + 1)}>
                    {t("onboarding.next")} <ChevronRight size={16} aria-hidden />
                  </button>
                ) : OPTIONAL.has(STEPS[current]!) ? (
                  <button type="button" className="button" onClick={() => { setSkipped((x) => new Set(x).add(STEPS[current]!)); setPicked(null); }}>
                    {t("onboarding.ai.skip")}
                  </button>
                ) : null}
              </div>
            </div>
          </section>
        ) : (
          <DoneStep games={st.game_count} consoles={st.platform_count} ai={aiOn} remote={remoteOn} onOpen={finish} />
        )}
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
    <div className="onboarding__library">
      {status.sync_running || start.isPending ? (
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

function DoneStep({ games, consoles, ai, remote, onOpen }: { games: number; consoles: number; ai: boolean; remote: boolean; onOpen: () => void }) {
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
        <li className={remote ? "" : "is-off"}>
          {remote ? <Check size={16} aria-hidden /> : <span className="onboarding__dash" aria-hidden>–</span>}
          {t("onboarding.done.remoteLabel")} : {t(remote ? "onboarding.done.remoteOn" : "onboarding.done.remoteOff")}
        </li>
      </ul>
      <button type="button" className="button button--primary onboarding__open" onClick={onOpen}>{t("onboarding.done.open")}</button>
    </div>
  );
}
