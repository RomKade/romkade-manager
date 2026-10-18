import { Bot, ExternalLink, Gamepad2, Send, Sparkles, Trash2, X } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { useDeviceStatus, useLlmSettings, useNowPlaying } from "../api/queries";
import { getLang, useT } from "../i18n";
import { askAssistant, assistant, type AssistantGame, type ChatMessage, type Scope, useAssistant } from "../lib/assistant";

const MAX_QUESTION = 500;
const MAX_USER_TURNS = 20;

/**
 * Assistant de jeu (voir docs/STRATEGIE-IA.md) : une bulle en bas à droite. Périmètre « Bibliothèque » par défaut ;
 * quand une fiche est ouverte ou qu'un jeu tourne, il propose de discuter de ce jeu. `placement="sheet"` : rendu
 * dans la fiche (fenêtre modale), la bulle de la page est alors masquée ; la conversation est la même.
 */
export function AssistantBubble({ placement, onOpenGame }: { placement: "page" | "sheet"; onOpenGame?: (id: number) => void }) {
  const t = useT();
  const st = useAssistant();
  const online = useDeviceStatus().data?.connected === true;
  const now = useNowPlaying(online).data;
  const llm = useLlmSettings().data;
  if (placement === "page" && st.sheetOpen) return null;
  if (placement === "sheet" && !st.sheetOpen) return null;

  const playing: AssistantGame | null = now?.playing && now.game
    ? { id: now.game.id, title: now.game.title, platform: now.game.platform.label ?? now.game.platform.directory } : null;
  const detected = st.sheetGame ?? playing;
  return (
    <div className={`assistant assistant--${placement}`}>
      {st.open ? (
        <Panel detected={detected} ready={llm?.ready ?? false} local={llm?.local ?? false} provider={llm?.provider ?? null}
          onOpenGame={onOpenGame} />
      ) : (
        <button type="button" className="assistant__fab" onClick={() => assistant.setOpen(true)}>
          <Bot size={18} aria-hidden /> {t("assistant.fab")}
        </button>
      )}
    </div>
  );
}

function Panel({ detected, ready, local, provider, onOpenGame }: {
  detected: AssistantGame | null; ready: boolean; local: boolean; provider: string | null; onOpenGame?: (id: number) => void;
}) {
  const t = useT();
  const st = useAssistant();
  const scope = st.scope;
  const messages = assistant.messages(scope);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const abort = useRef<AbortController | null>(null);
  useEffect(() => endRef.current?.scrollIntoView?.({ block: "end" }), [messages.length, messages.at(-1)]);
  useEffect(() => () => abort.current?.abort(), []);

  const offer = detected && !(scope.kind === "game" && scope.game.id === detected.id) ? detected : null;
  const userTurns = messages.filter((m) => m.role === "user").length;
  const gameScope = scope.kind === "game" ? scope.game : null;

  const send = async (question: string) => {
    const q = question.trim().slice(0, MAX_QUESTION);
    if (!q || busy) return;
    const target: Scope = scope;
    const history = [...assistant.messages(target), { role: "user", content: q } as ChatMessage];
    assistant.setMessages(target, [...history, { role: "assistant", content: "", pending: true }]);
    setText("");
    setBusy(true);
    const update = (fn: (m: Extract<ChatMessage, { role: "assistant" }>) => ChatMessage) => {
      const list = assistant.messages(target);
      const last = list.at(-1);
      if (last?.role === "assistant") assistant.setMessages(target, [...list.slice(0, -1), fn(last)]);
    };
    abort.current = new AbortController();
    try {
      await askAssistant({
        scope: target.kind, game_id: target.kind === "game" ? target.game.id : undefined, lang: getLang(),
        messages: history.flatMap((m) => (m.role === "user" || (m.role === "assistant" && m.content)
          ? [{ role: m.role, content: m.content }] : [])),
      }, (e) => {
        if (e.type === "meta") {
          if (!e.in_scope) {
            const list = assistant.messages(target);
            assistant.setMessages(target, [...list.slice(0, -1), { role: "refusal", reason: e.reason ?? "off_topic" }]);
          } else update((m) => ({ ...m, intent: e.intent, games: e.games, sources: e.sources }));
        } else if (e.type === "delta") update((m) => ({ ...m, content: m.content + e.text }));
        else if (e.type === "error") {
          const list = assistant.messages(target);
          assistant.setMessages(target, [...list.slice(0, -1), { role: "error", message: e.message }]);
        }
      }, abort.current.signal);
      update((m) => ({ ...m, pending: false }));
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        const list = assistant.messages(target);
        assistant.setMessages(target, [...list.slice(0, -1), { role: "error", message: (err as Error).message }]);
      }
    } finally {
      setBusy(false);
    }
  };
  const submit = (e: FormEvent) => { e.preventDefault(); send(text); };
  const suggestions = gameScope
    ? ["assistant.ask.controls", "assistant.ask.save", "assistant.ask.stuck", "assistant.ask.tip"]
    : ["assistant.ask.twoPlayers", "assistant.ask.racing", "assistant.ask.addGames"];
  const last = messages.at(-1);
  const offerSolution = gameScope && !busy && last?.role === "assistant" && last.intent === "game_help" && last.content;

  return (
    <section className="assistant__panel" aria-label={t("assistant.title")}>
      <header className="assistant__head">
        <span className="assistant__title"><Bot size={16} aria-hidden /> {t("assistant.title")}</span>
        <div className="assistant__scope" role="group" aria-label={t("assistant.scope")}>
          <button type="button" aria-pressed={scope.kind === "library"} onClick={() => assistant.setScope({ kind: "library" })}>
            {t("assistant.library")}
          </button>
          {(gameScope || detected) && (
            <button type="button" aria-pressed={scope.kind === "game"}
              onClick={() => assistant.setScope({ kind: "game", game: gameScope ?? detected! })}>
              {(gameScope ?? detected)!.title}
            </button>
          )}
        </div>
        <button type="button" className="icon-button" aria-label={t("assistant.clear")} title={t("assistant.clear")}
          disabled={busy || messages.length === 0} onClick={() => assistant.setMessages(scope, [])}>
          <Trash2 size={15} aria-hidden />
        </button>
        <button type="button" className="icon-button" aria-label={t("assistant.close")} onClick={() => assistant.setOpen(false)}>
          <X size={16} aria-hidden />
        </button>
      </header>

      <div className="assistant__body">
        {offer && (
          <div className="assistant__offer">
            <p>{t("assistant.offer", { title: offer.title })}</p>
            <div className="assistant__offer-actions">
              <button type="button" className="button button--primary button--small"
                onClick={() => assistant.setScope({ kind: "game", game: offer })}>{t("assistant.offerYes")}</button>
              {scope.kind === "game" && (
                <button type="button" className="button button--small" onClick={() => assistant.setScope({ kind: "library" })}>
                  {t("assistant.library")}
                </button>
              )}
            </div>
          </div>
        )}
        {!ready && (
          <p className="assistant__note">{t("assistant.noAi")} <Link to="/parametres/ia" onClick={() => assistant.setOpen(false)}>{t("assistant.connectAi")}</Link></p>
        )}
        {messages.length === 0 && ready && (
          <p className="assistant__note">{t(gameScope ? "assistant.introGame" : "assistant.introLibrary", { title: gameScope?.title ?? "" })}</p>
        )}
        <ol className="assistant__messages">
          {messages.map((m, i) => <Message key={i} m={m} game={gameScope} onOpenGame={onOpenGame} />)}
        </ol>
        <div ref={endRef} />
      </div>

      <footer className="assistant__foot">
        {ready && messages.length === 0 && (
          <div className="assistant__chips">
            {suggestions.map((k) => <button key={k} type="button" className="chip" onClick={() => send(t(k))}>{t(k)}</button>)}
          </div>
        )}
        {offerSolution && (
          <div className="assistant__chips">
            <button type="button" className="chip" onClick={() => send(t("assistant.solution"))}>
              <Sparkles size={13} aria-hidden /> {t("assistant.solution")}
            </button>
          </div>
        )}
        {userTurns >= MAX_USER_TURNS ? <p className="assistant__note">{t("assistant.tooMany")}</p> : (
          <form className="assistant__form" onSubmit={submit}>
            <input value={text} maxLength={MAX_QUESTION} disabled={!ready || busy} aria-label={t("assistant.input")}
              placeholder={gameScope ? t("assistant.placeholderGame", { title: gameScope.title }) : t("assistant.placeholderLibrary")}
              onChange={(e) => setText(e.target.value)} />
            <button type="submit" className="button button--primary button--small" disabled={!ready || busy || !text.trim()}
              aria-label={t("assistant.send")}>
              <Send size={14} aria-hidden />
            </button>
          </form>
        )}
        <p className="assistant__disclaimer">
          {t("assistant.disclaimer")} · {local ? t("assistant.local") : provider ? t("assistant.online", { provider: t(`settings.ai.provider.${provider}`) }) : ""}
        </p>
      </footer>
    </section>
  );
}

function Message({ m, game, onOpenGame }: { m: ChatMessage; game: AssistantGame | null; onOpenGame?: (id: number) => void }) {
  const t = useT();
  if (m.role === "user") return <li className="assistant__msg assistant__msg--user">{m.content}</li>;
  if (m.role === "refusal") {
    return (
      <li className="assistant__msg assistant__msg--refusal">
        {t(`assistant.refusal.${m.reason}`, { title: game?.title ?? "" })}
      </li>
    );
  }
  if (m.role === "error") return <li className="assistant__msg assistant__msg--error" role="alert">{m.message}</li>;
  return (
    <li className="assistant__msg assistant__msg--bot" aria-busy={m.pending}>
      {m.content || (m.pending && <span className="assistant__typing">{t("assistant.thinking")}</span>)}
      {(m.games ?? []).length > 0 && !game && (
        <span className="assistant__games">
          {m.games!.map((g) => (
            <button key={g.id} type="button" className="assistant__game" onClick={() => onOpenGame?.(g.id)} disabled={!onOpenGame}>
              <Gamepad2 size={12} aria-hidden /> {g.title} <em>{g.platform}</em>
            </button>
          ))}
        </span>
      )}
      {(m.sources ?? []).length > 0 && !m.pending && (
        <span className="assistant__sources">
          {m.sources!.map((s) => (
            <a key={s.url} href={s.url} target="_blank" rel="noreferrer noopener">
              {s.source === "wikipedia" ? "Wikipédia" : "StrategyWiki"} · {s.license} <ExternalLink size={11} aria-hidden />
            </a>
          ))}
        </span>
      )}
    </li>
  );
}
