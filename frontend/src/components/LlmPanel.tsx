import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Bot, Cloud, ExternalLink, HardDrive, Loader2, PlugZap, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api, type LlmProvider, type LlmSettings } from "../api/client";
import { useLlmSettings } from "../api/queries";
import { dateTime } from "../lib/format";
import { REPO_URL } from "../lib/credits";
import { getLang, useT } from "../i18n";
import { SecretInput } from "./SecretInput";
import { ErrorNotice, Spinner } from "./ui";

/** Guide d'installation d'un LLM local (Ollama, LM Studio) et de sa connexion, dans la langue de l'interface. */
export const localLlmDoc = () => `${REPO_URL}/blob/main/docs/local-llm${getLang() === "en" ? "" : `.${getLang()}`}.md`;

/**
 * Paramètres > Assistant : la connexion à un modèle de langage, partagée par tout ce qui utilise l'IA (assistant, descriptions et
 * commandes des jeux). Service en ligne : choisir le fournisseur, coller la clé, c'est tout (modèle proposé d'après
 * la liste du fournisseur, connexion vérifiée d'elle-même). Modèle local ou service compatible OpenAI : adresse
 * (Ollama, LM Studio, Docker) et modèle. Voir backend app/services/llm.py.
 */
export function LlmPanel() {
  const t = useT();
  const q = useLlmSettings();
  if (q.isPending) return <Spinner label={t("common.loading")} />;
  if (q.isError) return <ErrorNotice error={q.error} />;
  return <LlmForm settings={q.data} />;
}

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
  const choose = (id: string) => {
    if (id !== settings.provider) save.mutate({ provider: id });
  };
  const cloud = settings.providers.filter((x) => x.kind === "cloud");
  const local = settings.providers.find((x) => x.kind === "local")!;

  return (
    <>
      <StatusCard settings={settings} checking={test.isPending} onCheck={() => test.mutate()}
        onDisconnect={() => save.mutate({ provider: null })} />
      {test.isError && settings.state !== "error" && <ErrorNotice error={test.error} />}

      <section className="block llm" aria-labelledby="llm-p-h">
        <h2 id="llm-p-h">{t("settings.ai.providerTitle")}</h2>
        <fieldset className="llm__group">
          <legend><Cloud size={16} aria-hidden /> {t("settings.ai.kind.cloud")}</legend>
          <p className="muted">{t("settings.ai.kind.cloudHint")}</p>
          <div className="auth-choice__options" role="radiogroup">
            {cloud.map((x) => <ProviderOption key={x.id} provider={x} on={settings.provider === x.id} onPick={choose} />)}
          </div>
        </fieldset>
        <fieldset className="llm__group">
          <legend><HardDrive size={16} aria-hidden /> {t("settings.ai.kind.local")}</legend>
          <p className="muted">{t("settings.ai.kind.localHint")}</p>
          <div className="auth-choice__options" role="radiogroup">
            <ProviderOption provider={local} on={settings.provider === local.id} onPick={choose} />
          </div>
        </fieldset>
        {save.isError && <ErrorNotice error={save.error} />}

        {p && (
          <div className="auth-choice__panel llm__panel">
            {p.kind === "cloud" ? (
              <>
                <KeyField provider={p} onSaved={apply} />
                <ModelField settings={settings} provider={p} onPick={(m) => save.mutate({ provider: p.id, model: m })} />
              </>
            ) : (
              <>
                <LocalHelp />
                <AddressField settings={settings} provider={p}
                  onPick={(url) => save.mutate({ provider: p.id, base_url: url, model: null })} />
                <ModelField settings={settings} provider={p}
                  onPick={(m) => save.mutate({ provider: p.id, model: m, base_url: settings.base_url })} />
                <details className="llm__optional">
                  <summary>{t("settings.ai.keyOptionalTitle")}</summary>
                  <KeyField provider={p} onSaved={apply} />
                </details>
              </>
            )}
            <p className="muted">{t(settings.local ? "settings.ai.costLocal" : p.batch ? "settings.ai.costBatch" : "settings.ai.cost")}</p>
          </div>
        )}
      </section>
    </>
  );
}

/** Voyant d'état : aucune IA, incomplète, vérification, connectée, erreur ; et les deux actions utiles. */
function StatusCard({ settings, checking, onCheck, onDisconnect }: {
  settings: LlmSettings; checking: boolean; onCheck: () => void; onDisconnect: () => void;
}) {
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
    <section className="block llm llm-status" aria-labelledby="llm-h">
      <h2 id="llm-h"><Bot size={18} aria-hidden /> {t("settings.ai.title")}</h2>
      <div className={`llm-status__line is-${state}`} role="status">
        <span className="status-dot" aria-hidden />
        <div>
          <p className="llm-status__title">{title}</p>
          {detail && <p className="muted">{detail}</p>}
        </div>
        <div className="llm-status__actions">
          {settings.ready && (
            <button type="button" className="button" onClick={onCheck} disabled={checking}>
              {checking ? <Loader2 size={16} aria-hidden className="spin" /> : <PlugZap size={16} aria-hidden />} {t("settings.ai.test")}
            </button>
          )}
          {settings.provider && (
            <button type="button" className="link-button" onClick={onDisconnect}>{t("settings.ai.disconnect")}</button>
          )}
        </div>
      </div>
      <p className="muted">{t("settings.ai.uses")}</p>
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
