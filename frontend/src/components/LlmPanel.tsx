import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Cloud, ExternalLink, HardDrive, Loader2, PlugZap, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { api, type LlmProvider, type LlmSettings } from "../api/client";
import { useLlmSettings } from "../api/queries";
import { dateTime } from "../lib/format";
import { REPO_URL } from "../lib/credits";
import { getLang, useT } from "../i18n";
import { assistant, useAssistant } from "../lib/assistant";
import { DEFAULT_ASSISTANT_NAME, isValidName } from "../lib/assistantNames";
import { DukeAvatar } from "./DukeAvatar";
import { SecretInput } from "./SecretInput";
import { StepCards } from "./StepCards";
import { ErrorNotice, Spinner } from "./ui";

/** Guide d'installation d'un LLM local (Ollama, LM Studio) et de sa connexion, dans la langue de l'interface. */
export const localLlmDoc = () => `${REPO_URL}/blob/main/docs/local-llm${getLang() === "en" ? "" : `.${getLang()}`}.md`;

/**
 * Paramètres > Assistant IA : la connexion à un modèle de langage, partagée par tout ce qui utilise l'IA (assistant,
 * descriptions et commandes des jeux), en trois étapes comme la connexion à la console : 1. type d'IA (service en
 * ligne ou modèle local) ; 2. connexion et modèle (clé du fournisseur, ou adresse d'Ollama / LM Studio, puis modèle) ;
 * 3. test. L'état (connectée ou non) reste affiché en haut, avec l'option d'afficher la bulle. Voir app/services/llm.py.
 */
export function LlmPanel() {
  const t = useT();
  const q = useLlmSettings();
  if (q.isPending) return <Spinner label={t("common.loading")} />;
  if (q.isError) return <ErrorNotice error={q.error} />;
  return <LlmForm settings={q.data} />;
}

type Kind = "cloud" | "local";

function LlmForm({ settings }: { settings: LlmSettings }) {
  const t = useT();
  const qc = useQueryClient();
  const apply = (s: LlmSettings) => {
    qc.setQueryData(["llm-settings"], s);
    for (const k of ["descriptions", "game-controls"]) qc.invalidateQueries({ queryKey: [k] });
  };
  const save = useMutation({ mutationFn: api.saveLlmSettings, onSuccess: apply });
  const test = useMutation({
    mutationFn: api.testLlm,
    onSettled: () => qc.invalidateQueries({ queryKey: ["llm-settings"] }),
  });

  // Prête mais pas encore vérifiée avec ces réglages : on vérifie tout de suite (une fois par réglage).
  const checked = useRef("");
  const signature = `${settings.provider}|${settings.model}|${settings.base_url}`;
  useEffect(() => {
    if (settings.state === "untested" && checked.current !== signature && !test.isPending) {
      checked.current = signature;
      test.mutate();
    }
  }, [settings.state, signature, test]);

  const p = settings.providers.find((x) => x.id === settings.provider);
  // Type choisi à l'étape 1 : celui du fournisseur enregistré, ou « en ligne » choisi sans fournisseur encore.
  const [kind, setKind] = useState<Kind | null>((p?.kind as Kind | undefined) ?? null);
  useEffect(() => { if (p) setKind(p.kind as Kind); }, [p]);
  const choose = (id: string) => {
    if (id !== settings.provider) save.mutate({ provider: id });
  };
  const cloud = settings.providers.filter((x) => x.kind === "cloud");
  const local = settings.providers.find((x) => x.kind === "local")!;
  const pickKind = (k: Kind) => {
    setKind(k);
    if (k === "local") choose(local.id);
  };
  const providerName = settings.provider ? t(`settings.ai.provider.${settings.provider}`) : "";
  const checking = test.isPending;
  const connected = settings.state === "connected" && !checking;
  const where = (() => {
    try { return settings.base_url ? new URL(settings.base_url).host : ""; } catch { return settings.base_url ?? ""; }
  })();

  return (
    <>
      {test.isError && settings.state !== "error" && <ErrorNotice error={test.error} />}

      <StepCards label={t("settings.ai.steps.label")} steps={[
        { n: 1, label: t("settings.ai.steps.kind"), done: !!p, target: "ai-1",
          sub: p ? t(p.kind === "cloud" ? "settings.ai.steps.kindCloud" : "settings.ai.steps.kindLocal", { provider: providerName })
            : t("settings.ai.steps.kindTodo"),
          action: t(p ? "settings.steps.edit" : "settings.ai.steps.choose") },
        { n: 2, label: t("settings.ai.steps.connect"), done: settings.ready, target: "ai-2",
          sub: settings.ready ? `${p?.kind === "local" ? where : providerName} · ${settings.model ?? ""}`
            : settings.provider ? t(`settings.ai.problem.${settings.problem ?? "llm_no_model"}`, { provider: providerName })
            : t("settings.ai.steps.connectTodo"),
          action: t(settings.ready ? "settings.steps.edit" : "settings.steps.open") },
        { n: 3, label: t("settings.ai.steps.test"), done: connected, target: "ai-3",
          sub: connected && settings.tested_at ? t("settings.ai.checkedAt", { date: dateTime(settings.tested_at) })
            : settings.state === "error" ? t("settings.ai.steps.testFailed") : t("settings.ai.steps.testTodo"),
          action: t("settings.steps.run") },
      ]} />

      <section className="block llm" aria-labelledby="ai-1">
        <h2 id="ai-1"><span className="step-badge" aria-hidden>1</span> {t("settings.ai.steps.kind")}</h2>
        <div className="llm__kinds" role="radiogroup" aria-labelledby="ai-1">
          <KindOption on={kind === "cloud"} onPick={() => pickKind("cloud")} icon={<Cloud size={20} aria-hidden />}
            title={t("settings.ai.kind.cloud")} hint={t("settings.ai.kind.cloudHint")} />
          <KindOption on={kind === "local"} onPick={() => pickKind("local")} icon={<HardDrive size={20} aria-hidden />}
            title={t("settings.ai.kind.local")} hint={t("settings.ai.kind.localHint")} />
        </div>
        {save.isError && <ErrorNotice error={save.error} />}
      </section>

      <section className="block llm" aria-labelledby="ai-2">
        <h2 id="ai-2"><span className="step-badge" aria-hidden>2</span> {t("settings.ai.steps.connect")}</h2>
        {!kind ? <p className="muted">{t("settings.ai.steps.kindFirst")}</p> : kind === "cloud" ? (
          <>
            <div className="auth-choice__options" role="radiogroup" aria-label={t("settings.ai.providerTitle")}>
              {cloud.map((x) => <ProviderOption key={x.id} provider={x} on={settings.provider === x.id} onPick={choose} />)}
            </div>
            {p?.kind === "cloud" ? (
              <div className="auth-choice__panel llm__panel">
                <KeyField provider={p} onSaved={apply} />
                <ModelField settings={settings} provider={p} onPick={(m) => save.mutate({ provider: p.id, model: m })} />
                <p className="muted">{t(p.batch ? "settings.ai.costBatch" : "settings.ai.cost")}</p>
              </div>
            ) : <p className="muted">{t("settings.ai.steps.pickProvider")}</p>}
          </>
        ) : p && (
          <div className="auth-choice__panel llm__panel">
            <LocalHelp />
            <AddressField settings={settings} provider={p}
              onPick={(url) => save.mutate({ provider: p.id, base_url: url, model: null })} />
            <ModelField settings={settings} provider={p}
              onPick={(m) => save.mutate({ provider: p.id, model: m, base_url: settings.base_url })} />
            <details className="llm__optional">
              <summary>{t("settings.ai.keyOptionalTitle")}</summary>
              <KeyField provider={p} onSaved={apply} />
            </details>
            <p className="muted">{t("settings.ai.costLocal")}</p>
          </div>
        )}
      </section>

      <section className="block llm" aria-labelledby="ai-3">
        <h2 id="ai-3"><span className="step-badge" aria-hidden>3</span> {t("settings.ai.steps.test")}</h2>
        <p className="muted">{t("settings.ai.steps.testLead")}</p>
        <div className="form__actions">
          <button type="button" className="button button--primary" onClick={() => test.mutate()} disabled={!settings.ready || checking}>
            {checking ? <Loader2 size={16} aria-hidden className="spin" /> : <PlugZap size={16} aria-hidden />} {t("settings.ai.steps.testButton")}
          </button>
          {!settings.ready && <span className="muted">{t("settings.ai.steps.testNeedsStep2")}</span>}
        </div>
        <div className="llm-status__row">
          <StatusLine settings={settings} checking={checking} />
          {settings.provider && (
            <button type="button" className="link-button" onClick={() => { setKind(null); save.mutate({ provider: null }); }}>
              {t("settings.ai.disconnect")}
            </button>
          )}
        </div>
      </section>

      <NameAndDisplay />
    </>
  );
}

function KindOption({ on, onPick, icon, title, hint }: { on: boolean; onPick: () => void; icon: ReactNode; title: string; hint: string }) {
  return (
    <label className={`llm__kind ${on ? "is-on" : ""}`}>
      <input type="radio" name="llm-kind" checked={on} onChange={onPick} />
      <span className="llm__kind-title">{icon} {title}</span>
      <span className="llm__kind-hint">{hint}</span>
    </label>
  );
}

/** Voyant d'état (aucune IA, incomplète, vérification, connectée, erreur) : une ligne, réutilisée en haut et à l'étape 3. */
function StatusLine({ settings, checking }: { settings: LlmSettings; checking: boolean }) {
  const t = useT();
  const provider = settings.provider ? t(`settings.ai.provider.${settings.provider}`) : "";
  const state = checking ? "checking" : settings.state;
  const title = t(`settings.ai.state.${state}`, { provider, model: settings.model ?? "" });
  const detail = checking ? null
    : state === "connected" && settings.tested_at ? t("settings.ai.checkedAt", { date: dateTime(settings.tested_at) })
    : state === "error" ? settings.last_error
    : state === "incomplete" ? t(`settings.ai.problem.${settings.problem ?? "llm_no_model"}`, { provider })
    : state === "none" ? t("settings.ai.noneHint") : null;
  return (
    <div className={`llm-status__line is-${state}`} role="status">
      <span className="status-dot" aria-hidden />
      <div>
        <p className="llm-status__title">{title}</p>
        {detail && <p className="muted">{detail}</p>}
      </div>
    </div>
  );
}

/** Après les étapes : prénom de l'assistant (Duke par défaut, modifiable) et affichage de la bulle. */
function NameAndDisplay() {
  const t = useT();
  const { name, hidden } = useAssistant();
  const [value, setValue] = useState(name);
  useEffect(() => setValue(name), [name]);
  const valid = isValidName(value);
  return (
    <section className="block llm" aria-labelledby="ai-name">
      <h2 id="ai-name">{t("settings.as.nameSection")}</h2>
      <div className="llm__persona">
        <span className="assistant__face"><DukeAvatar size={44} /></span>
        <p className="muted small">{t("settings.as.faceHint", { name })}</p>
      </div>
      <form className="names__other" onSubmit={(e) => { e.preventDefault(); if (valid) assistant.setName(value); }}>
        <label className="field">
          <span className="field__label">{t("settings.as.nameTitle")}</span>
          <input value={value} maxLength={20} onChange={(e) => setValue(e.target.value)} aria-invalid={!valid} />
        </label>
        <button type="submit" className="button button--small" disabled={!valid || value.trim() === name}>{t("settings.as.nameUse")}</button>
        {name !== DEFAULT_ASSISTANT_NAME && (
          <button type="button" className="link-button" onClick={() => assistant.setName(DEFAULT_ASSISTANT_NAME)}>
            {t("settings.as.nameDefault", { name: DEFAULT_ASSISTANT_NAME })}
          </button>
        )}
      </form>
      {!valid && <p className="text-error small">{t("settings.as.nameInvalid")}</p>}
      <label className="toggle-inline">
        <input type="checkbox" checked={!hidden} onChange={(e) => assistant.setHidden(!e.target.checked)} />
        {t("settings.as.show")}
      </label>
      <p className="muted small">{t("settings.ai.uses")} <Link to="/parametres/catalogue">{t("settings.as.knowledge")}</Link></p>
    </section>
  );
}

function ProviderOption({ provider, on, onPick }: { provider: LlmProvider; on: boolean; onPick: (id: string) => void }) {
  const t = useT();
  return (
    <label className={`auth-choice__option ${on ? "is-on" : ""}`}>
      <input type="radio" name="llm-provider" value={provider.id} checked={on} onChange={() => onPick(provider.id)} />
      {t(`settings.ai.provider.${provider.id}`)}
      {provider.key_source && <span className="llm__keytag">{t("settings.ai.keySaved")}</span>}
    </label>
  );
}

/** Clé d'API du fournisseur choisi, gardée dans le trousseau du système (une par fournisseur). */
function KeyField({ provider, onSaved }: { provider: LlmProvider; onSaved: (s: LlmSettings) => void }) {
  const t = useT();
  const [key, setKey] = useState("");
  useEffect(() => setKey(""), [provider.id]);
  const save = useMutation({ mutationFn: () => api.saveLlmKey(provider.id, key.trim()), onSuccess: (s) => { setKey(""); onSaved(s); } });
  const remove = useMutation({ mutationFn: () => api.deleteLlmKey(provider.id), onSuccess: onSaved });
  const src = provider.key_source;
  const id = `llm-key-${provider.id}`;
  const name = t(`settings.ai.provider.${provider.id}`);
  return (
    <form className="llm__key" onSubmit={(e) => { e.preventDefault(); if (key.trim()) save.mutate(); }}>
      <p className="muted">
        {src === "keychain" ? t("settings.ai.keyKeychain") : src === "environment" ? t("settings.ai.keyEnv")
          : provider.key === "optional" ? t("settings.ai.keyOptional") : t("settings.ai.keyNone", { provider: name })}
        {provider.keys_url && <> {" "}<a href={provider.keys_url} target="_blank" rel="noreferrer noopener" className="link">
          {t("settings.ai.keyCreate", { provider: name })} <ExternalLink size={12} aria-hidden /></a></>}
      </p>
      <div className="field">
        <label htmlFor={id}>{src === "keychain" ? t("settings.yt.replace") : t("settings.ai.keyLabel", { provider: name })}</label>
        <div className="llm__inline">
          <SecretInput id={id} value={key} onChange={(e) => setKey(e.target.value)} autoComplete="off" spellCheck={false} />
          <button type="submit" className="button button--primary" disabled={!key.trim() || save.isPending}>
            {save.isPending ? <Loader2 size={16} aria-hidden className="spin" /> : null} {t("settings.saveKeychain")}
          </button>
        </div>
      </div>
      {src === "keychain" && (
        <button type="button" className="link-button" onClick={() => remove.mutate()} disabled={remove.isPending}>{t("settings.yt.remove")}</button>
      )}
      {(save.isError || remove.isError) && <ErrorNotice error={save.error ?? remove.error} />}
    </form>
  );
}

function AddressField({ settings, provider, onPick }: { settings: LlmSettings; provider: LlmProvider; onPick: (url: string | null) => void }) {
  const t = useT();
  const current = settings.base_url || provider.base_url || "";
  const [url, setUrl] = useState(current);
  useEffect(() => setUrl(current), [current]);
  return (
    <div className="field">
      <label htmlFor="llm-url">{t("settings.ai.address")}</label>
      <div className="auth-choice__options llm__presets">
        {Object.entries(settings.local_presets).map(([name, u]) => (
          <button key={name} type="button" className={`chip ${current === u ? "is-on" : ""}`} aria-pressed={current === u}
            onClick={() => onPick(u === provider.base_url ? null : u)}>{name}</button>
        ))}
      </div>
      <form className="llm__inline" onSubmit={(e) => { e.preventDefault(); onPick(url.trim() || null); }}>
        <input id="llm-url" value={url} placeholder={provider.base_url ?? "https://…/v1"} onChange={(e) => setUrl(e.target.value)} spellCheck={false} />
        <button type="submit" className="button" disabled={url.trim() === current}>{t("settings.ai.useAddress")}</button>
      </form>
      <p className="field__hint">{t("settings.ai.addressHint")}</p>
    </div>
  );
}

/** Modèle : proposé d'après la liste du fournisseur (jamais inventé), modifiable d'un clic. */
function ModelField({ settings, provider, onPick }: { settings: LlmSettings; provider: LlmProvider; onPick: (m: string) => void }) {
  const t = useT();
  const canList = provider.key === "required" ? !!provider.key_source : true;
  const [open, setOpen] = useState(provider.kind === "local" || !settings.model);
  const models = useQuery({
    queryKey: ["llm-models", provider.id, settings.base_url ?? ""],
    queryFn: () => api.llmModels(provider.id, settings.base_url),
    enabled: canList && open, retry: false, staleTime: 5 * 60_000,
  });
  const list = models.data ?? [];
  if (!canList) return <p className="field__hint">{t("settings.ai.modelsNeedKey")}</p>;
  return (
    <div className="field">
      <p className="llm__model">
        <span>{t("settings.ai.model")} : </span>
        {settings.model ? <strong>{settings.model}</strong> : <span className="muted">{t("settings.ai.modelNone")}</span>}
        {!open && <button type="button" className="link-button" onClick={() => setOpen(true)}>{t("settings.ai.modelChange")}</button>}
      </p>
      {open && (
        <>
          <div className="llm__models" role="listbox" aria-label={t("settings.ai.modelsList")}>
            {list.slice(0, 60).map((m) => (
              <button key={m} type="button" role="option" aria-selected={m === settings.model} className={`chip ${m === settings.model ? "is-on" : ""}`}
                onClick={() => onPick(m)}>{m}</button>
            ))}
            <button type="button" className="chip" onClick={() => models.refetch()} disabled={models.isFetching}
              aria-label={t("settings.ai.modelsReload")} title={t("settings.ai.modelsReload")}>
              {models.isFetching ? <Loader2 size={14} aria-hidden className="spin" /> : <RefreshCw size={14} aria-hidden />}
            </button>
          </div>
          <p className="field__hint">
            {models.isError ? "" : list.length ? t("settings.ai.modelsHint", { count: list.length })
              : models.isFetching ? t("common.loading") : t("settings.ai.modelsNone")}
          </p>
          {models.isError && <ErrorNotice error={models.error} />}
        </>
      )}
    </div>
  );
}

function LocalHelp() {
  const t = useT();
  return (
    <div className="llm__help">
      <p>{t("settings.ai.localHelp")}</p>
      <ol>
        <li>{t("settings.ai.localStep1Before")} <a href="https://ollama.com/download" target="_blank" rel="noreferrer noopener" className="link">Ollama</a>{" "}
          {t("settings.ai.localStep1Or")} <a href="https://lmstudio.ai/" target="_blank" rel="noreferrer noopener" className="link">LM Studio</a>{" "}
          {t("settings.ai.localStep1After")}</li>
        <li>{t("settings.ai.localStep2")} <code>ollama pull qwen2.5:7b</code></li>
        <li>{t("settings.ai.localStep3")}</li>
      </ol>
      <a href={localLlmDoc()} target="_blank" rel="noreferrer noopener" className="link llm__doc">
        <BookOpen size={14} aria-hidden /> {t("settings.ai.localDoc")} <ExternalLink size={12} aria-hidden />
      </a>
    </div>
  );
}
