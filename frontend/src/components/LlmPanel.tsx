import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, CheckCircle2, Cloud, ExternalLink, HardDrive, KeyRound, Loader2, PlugZap, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, type LlmProvider, type LlmSettings } from "../api/client";
import { useLlmSettings } from "../api/queries";
import { useT } from "../i18n";
import { ErrorNotice, Spinner } from "./ui";

/**
 * Paramètres > IA : la connexion à un modèle de langage, partagée par tout ce qui utilise l'IA (descriptions et
 * commandes des jeux). Service en ligne avec une clé d'API (Claude, ChatGPT, Mistral, Gemini, autre service
 * compatible OpenAI), ou modèle à poids ouverts sur ce Mac (Ollama, LM Studio). Voir backend app/services/llm.py.
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
  const [provider, setProvider] = useState(settings.provider);
  const [model, setModel] = useState(settings.model ?? "");
  const [baseUrl, setBaseUrl] = useState(settings.base_url ?? "");
  useEffect(() => {
    setProvider(settings.provider);
    setModel(settings.model ?? "");
    setBaseUrl(settings.base_url ?? "");
  }, [settings]);

  const p = settings.providers.find((x) => x.id === provider)!;
  const pick = (id: string) => {
    const next = settings.providers.find((x) => x.id === id)!;
    setProvider(id);
    setModel(id === settings.provider ? settings.model ?? "" : next.default_model ?? "");
    setBaseUrl(id === settings.provider ? settings.base_url ?? "" : "");
  };
  const refresh = () => {
    for (const k of ["llm-settings", "descriptions", "game-controls", "llm-models"]) qc.invalidateQueries({ queryKey: [k] });
  };
  const save = useMutation({
    mutationFn: () => api.saveLlmSettings({ provider, model: model.trim() || null, base_url: baseUrl.trim() || null }),
    onSuccess: (s) => { qc.setQueryData(["llm-settings"], s); refresh(); },
  });
  const test = useMutation({ mutationFn: api.testLlm });
  const dirty = provider !== settings.provider || (model.trim() || null) !== (settings.model ?? null)
    || (baseUrl.trim() || null) !== (settings.base_url ?? null);
  const groups: { kind: "cloud" | "local"; icon: typeof Cloud }[] = [{ kind: "cloud", icon: Cloud }, { kind: "local", icon: HardDrive }];

  return (
    <>
      <section className="block llm" aria-labelledby="llm-h">
        <h2 id="llm-h"><Bot size={18} aria-hidden /> {t("settings.ai.title")}</h2>
        <p className="muted block__lead">{t("settings.ai.lead")}</p>
        <div>
          <p>{t("settings.ai.usesTitle")}</p>
          <ul className="ai-uses">
            <li><Link to="/parametres/descriptions">{t("settings.ai.useDescriptions")}</Link></li>
            <li>{t("settings.ai.useControls")}</li>
          </ul>
        </div>
        <ReadyLine settings={settings} />
      </section>

      <form className="block form llm" aria-labelledby="llm-p-h" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        <h2 id="llm-p-h"><span className="step-badge" aria-hidden>1</span> {t("settings.ai.providerTitle")}</h2>
        {groups.map(({ kind, icon: Icon }) => (
          <fieldset key={kind} className="llm__group">
            <legend><Icon size={16} aria-hidden /> {t(`settings.ai.kind.${kind}`)}</legend>
            <p className="muted">{t(`settings.ai.kind.${kind}Hint`)}</p>
            <div className="auth-choice__options" role="radiogroup">
              {settings.providers.filter((x) => x.kind === kind).map((x) => (
                <label key={x.id} className={`auth-choice__option ${provider === x.id ? "is-on" : ""}`}>
                  <input type="radio" name="llm-provider" value={x.id} checked={provider === x.id} onChange={() => pick(x.id)} />
                  {t(`settings.ai.provider.${x.id}`)}
                  {x.key_source && <KeyRound size={13} aria-label={t("settings.ai.keySaved")} />}
                </label>
              ))}
            </div>
          </fieldset>
        ))}

        <div className="auth-choice__panel llm__panel">
          {p.key !== "none" && <KeyField provider={p} onChange={refresh} />}
          {(p.kind === "local" || p.id === "custom") && (
            <AddressField provider={p} value={baseUrl} onChange={setBaseUrl} presets={settings.local_presets} />
          )}
          <ModelField provider={p} baseUrl={baseUrl} value={model} onChange={setModel} />
          {p.kind === "local" && <LocalHelp />}
        </div>

        <div className="form__actions">
          <button type="submit" className="button button--primary" disabled={!dirty || save.isPending}>{t("settings.save")}</button>
          {save.isSuccess && !dirty && <span className="ok-text" role="status"><CheckCircle2 size={16} aria-hidden /> {t("settings.saved")}</span>}
        </div>
        {save.isError && <ErrorNotice error={save.error} />}
        <p className="muted">{t(p.kind === "local" ? "settings.ai.costLocal" : p.batch ? "settings.ai.costBatch" : "settings.ai.cost")}</p>
      </form>

      <section className="block llm" aria-labelledby="llm-t-h">
        <h2 id="llm-t-h"><span className="step-badge" aria-hidden>2</span> {t("settings.ai.testTitle")}</h2>
        <p className="muted">{t("settings.ai.testLead")}</p>
        <div className="form__actions">
          <button type="button" className="button" onClick={() => test.mutate()} disabled={!settings.ready || dirty || test.isPending}>
            {test.isPending ? <Loader2 size={16} aria-hidden className="spin" /> : <PlugZap size={16} aria-hidden />} {t("settings.ai.test")}
          </button>
          {dirty && <span className="muted">{t("settings.ai.saveFirst")}</span>}
          {test.data && (test.data.ok
            ? <span className="ok-text" role="status"><CheckCircle2 size={16} aria-hidden /> {t("settings.ai.testOk", { model: test.data.model, seconds: test.data.seconds.toLocaleString() })}</span>
            : <span className="text-error" role="status">{t("settings.ai.testBad")}</span>)}
        </div>
        {test.isError && <ErrorNotice error={test.error} />}
      </section>
    </>
  );
}

function ReadyLine({ settings }: { settings: LlmSettings }) {
  const t = useT();
  const label = t(`settings.ai.provider.${settings.provider}`);
  return settings.ready
    ? <p className="ok-text" role="status"><CheckCircle2 size={16} aria-hidden /> {t("settings.ai.ready", { provider: label, model: settings.model ?? "" })}</p>
    : <p className="text-warning" role="status">{t(`settings.ai.problem.${settings.problem ?? "llm_no_model"}`, { provider: label })}</p>;
}

/** Clé d'API du fournisseur choisi, gardée dans le trousseau macOS (une par fournisseur). */
function KeyField({ provider, onChange }: { provider: LlmProvider; onChange: () => void }) {
  const t = useT();
  const [key, setKey] = useState("");
  useEffect(() => setKey(""), [provider.id]);
  const done = () => { setKey(""); onChange(); };
  const save = useMutation({ mutationFn: () => api.saveLlmKey(provider.id, key.trim()), onSuccess: done });
  const remove = useMutation({ mutationFn: () => api.deleteLlmKey(provider.id), onSuccess: done });
  const src = provider.key_source;
  const id = `llm-key-${provider.id}`;
  return (
    <div className="llm__key">
      <p className="muted">
        {src === "keychain" ? t("settings.ai.keyKeychain") : src === "environment" ? t("settings.ai.keyEnv")
          : provider.key === "optional" ? t("settings.ai.keyOptional") : t("settings.ai.keyNone")}
        {provider.keys_url && <> {" "}<a href={provider.keys_url} target="_blank" rel="noreferrer noopener" className="link">
          {t("settings.ai.keyCreate")} <ExternalLink size={12} aria-hidden /></a></>}
      </p>
      <div className="field">
        <label htmlFor={id}>{src === "keychain" ? t("settings.yt.replace") : t("settings.ai.keyLabel", { provider: t(`settings.ai.provider.${provider.id}`) })}</label>
        <div className="llm__inline">
          <input id={id} type="password" value={key} onChange={(e) => setKey(e.target.value)} autoComplete="off" spellCheck={false} />
          <button type="button" className="button" disabled={!key.trim() || save.isPending} onClick={() => save.mutate()}>{t("settings.saveKeychain")}</button>
        </div>
      </div>
      {src === "keychain" && (
        <button type="button" className="link-button" onClick={() => remove.mutate()} disabled={remove.isPending}>{t("settings.yt.remove")}</button>
      )}
      {save.isSuccess && <span className="ok-text" role="status"><CheckCircle2 size={16} aria-hidden /> {t("settings.savedF")}</span>}
      {(save.isError || remove.isError) && <ErrorNotice error={save.error ?? remove.error} />}
    </div>
  );
}

function AddressField({ provider, value, onChange, presets }: {
  provider: LlmProvider; value: string; onChange: (v: string) => void; presets: Record<string, string>;
}) {
  const t = useT();
  const current = value || provider.base_url || "";
  return (
    <div className="field">
      <label htmlFor="llm-url">{t("settings.ai.address")}</label>
      {provider.kind === "local" && (
        <div className="auth-choice__options llm__presets">
          {Object.entries(presets).map(([name, url]) => (
            <button key={name} type="button" className={`chip ${current === url ? "is-on" : ""}`} aria-pressed={current === url}
              onClick={() => onChange(url === provider.base_url ? "" : url)}>{name}</button>
          ))}
        </div>
      )}
      <input id="llm-url" value={value} placeholder={provider.base_url ?? "https://…/v1"} onChange={(e) => onChange(e.target.value)} spellCheck={false} />
      <p className="field__hint">{t(provider.kind === "local" ? "settings.ai.addressLocalHint" : "settings.ai.addressHint")}</p>
    </div>
  );
}

/** Modèle : choisi dans la liste du fournisseur (jamais deviné), ou saisi à la main. */
function ModelField({ provider, baseUrl, value, onChange }: {
  provider: LlmProvider; baseUrl: string; value: string; onChange: (v: string) => void;
}) {
  const t = useT();
  const canList = provider.key === "required" ? !!provider.key_source : true;
  const models = useQuery({
    queryKey: ["llm-models", provider.id, baseUrl.trim()],
    queryFn: () => api.llmModels(provider.id, baseUrl.trim() || null),
    enabled: canList && (provider.id !== "custom" || !!baseUrl.trim()),
    retry: false, staleTime: 5 * 60_000,
  });
  const list = models.data ?? [];
  return (
    <div className="field">
      <label htmlFor="llm-model">{t("settings.ai.model")}</label>
      <div className="llm__inline">
        <input id="llm-model" list="llm-models" value={value} onChange={(e) => onChange(e.target.value)}
          placeholder={provider.default_model ?? t("settings.ai.modelPlaceholder")} spellCheck={false} autoComplete="off" />
        <button type="button" className="button" onClick={() => models.refetch()} disabled={!canList || models.isFetching}
          title={t("settings.ai.modelsReload")} aria-label={t("settings.ai.modelsReload")}>
          {models.isFetching ? <Loader2 size={16} aria-hidden className="spin" /> : <RefreshCw size={16} aria-hidden />}
        </button>
      </div>
      <datalist id="llm-models">{list.map((m) => <option key={m} value={m} />)}</datalist>
      {list.length > 0 && (
        <div className="llm__models" role="listbox" aria-label={t("settings.ai.modelsList")}>
          {list.slice(0, 40).map((m) => (
            <button key={m} type="button" role="option" aria-selected={m === value} className={`chip ${m === value ? "is-on" : ""}`}
              onClick={() => onChange(m)}>{m}</button>
          ))}
        </div>
      )}
      <p className="field__hint">
        {!canList ? t("settings.ai.modelsNeedKey") : models.isError ? "" : list.length ? t("settings.ai.modelsHint", { count: list.length })
          : models.isFetching ? t("common.loading") : t("settings.ai.modelsNone")}
      </p>
      {models.isError && <ErrorNotice error={models.error} />}
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
          {t("settings.ai.localStep1Or")} <a href="https://lmstudio.ai/" target="_blank" rel="noreferrer noopener" className="link">LM Studio</a>.</li>
        <li>{t("settings.ai.localStep2")} <code>ollama pull qwen2.5:7b</code></li>
        <li>{t("settings.ai.localStep3")}</li>
      </ol>
    </div>
  );
}
