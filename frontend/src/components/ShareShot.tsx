import * as Dialog from "@radix-ui/react-dialog";
import { Loader2, RefreshCw, Share2, Sparkles, X as Close } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { api, type Shot } from "../api/client";
import { useLlmSettings } from "../api/queries";
import { getLang, useT } from "../i18n";
import { errorMessage } from "./ui";

/**
 * Partage d'une capture sur les réseaux, sans compte ni clé : aucun réseau n'accepte une image par lien, on prépare
 * donc tout ce qui peut l'être et la personne publie elle-même.
 * - X et Bluesky : image copiée, éditeur du réseau ouvert avec le texte ; il reste à coller l'image.
 * - Reddit : image téléchargée, formulaire du subreddit ouvert avec le titre ; il reste à y ajouter l'image.
 * - Instagram (pas de lien d'écriture) : sur ordinateur, image téléchargée, légende copiée, Instagram ouvert.
 * - Téléphone (feuille de partage avec fichiers) : chaque réseau passe par la feuille de partage, qui envoie l'image
 *   et le texte à l'application choisie (texte aussi copié : Instagram ne le reprend pas).
 * Texte : vide au départ ; « Générer avec l'IA » le fait écrire par l'IA réglée (faits du jeu, passages de référence,
 * capture), dans le ton choisi, puis « Régénérer ».
 * L'image est agrandie trois fois sans lissage : les réseaux floutent une petite image de pixel art.
 */
export type Network = "instagram" | "bluesky" | "x" | "reddit";
export const NETWORKS: Network[] = ["instagram", "bluesky", "x", "reddit"];
export const SUBREDDITS = ["SBCGaming", "retrogaming", "ANBERNIC", "RG35XX"];
export const TONES = ["nostalgic", "fun", "challenge", "story"] as const;
type Tone = (typeof TONES)[number];

/** Jeu et nom de la capture, lus dans son adresse (/api/screenshots/<jeu>/<nom>). */
export function shotRef(url: string): { gameId: number; name: string } | null {
  const m = url.match(/\/screenshots\/(\d+)\/([^/?#]+)/);
  return m ? { gameId: Number(m[1]), name: decodeURIComponent(m[2]!) } : null;
}
const SCALE = 3;

/** Titre Reddit : le texte sans mots-dièse, sur une ligne. */
export const redditTitle = (text: string) => text.replace(/#\S+/g, "").replace(/\s+/g, " ").trim();

export function composeUrl(network: Exclude<Network, "instagram">, text: string, subreddit = SUBREDDITS[0]): string {
  const q = encodeURIComponent;
  if (network === "x") return `https://x.com/intent/post?text=${q(text)}`;
  if (network === "bluesky") return `https://bsky.app/intent/compose?text=${q(text)}`;
  return `https://www.reddit.com/r/${q(subreddit!)}/submit?type=IMAGE&title=${q(redditTitle(text))}`;
}

/** Capture agrandie sans lissage, en PNG (l'original si le navigateur ne sait pas dessiner). */
async function upscaled(url: string): Promise<Blob> {
  const original = await (await fetch(url)).blob();
  try {
    const img = await createImageBitmap(original);
    const canvas = document.createElement("canvas");
    canvas.width = img.width * SCALE;
    canvas.height = img.height * SCALE;
    const ctx = canvas.getContext("2d");
    if (!ctx) return original;
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    return await new Promise<Blob>((ok) => canvas.toBlob((b) => ok(b ?? original), "image/png"));
  } catch {
    return original;
  }
}

function download(blob: Blob, name: string) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

async function copyImage(blob: Blob): Promise<boolean> {
  try {
    await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
    return true;
  } catch {
    return false;
  }
}

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

const isPhone = () => typeof matchMedia === "function" && matchMedia("(pointer: coarse)").matches;

/** Bouton « Partager » d'une capture et sa fenêtre de partage. */
export function ShareShotButton({ shot, title }: { shot: Shot; title: string }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button type="button" className="icon-button" aria-label={t("screenshots.share.button")} title={t("screenshots.share.button")}>
          <Share2 size={14} aria-hidden />
        </button>
      </Dialog.Trigger>
      {open && <ShareDialog shot={shot} title={title} />}
    </Dialog.Root>
  );
}

function ShareDialog({ shot, title }: { shot: Shot; title: string }) {
  const t = useT();
  const [text, setText] = useState("");  // vide : la personne écrit, ou « Générer avec l'IA »
  const ai = useCaption(shot, setText);
  const [subreddit, setSubreddit] = useState(SUBREDDITS[0]!);
  const [blob, setBlob] = useState<Blob | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState<{ network: Network | "system"; how: string; link?: string } | null>(null);
  const name = `${title} ${shot.name}`.replace(/[\\/:*?"<>|]/g, "-");
  // Image préparée dès l'ouverture : copier ou partager doit suivre le clic sans attente (sinon refusé).
  useEffect(() => {
    let alive = true;
    upscaled(shot.url).then((b) => alive && setBlob(b), (e) => alive && setError(e));
    return () => { alive = false; };
  }, [shot.url]);
  const file = blob ? new File([blob], name, { type: "image/png" }) : null;
  const canShareFile = !!file && !!navigator.canShare?.({ files: [file] });

  // Sans « noopener » dans les options : avec, window.open renvoie toujours null (onglet ouvert ou non).
  const openTab = (url: string) => {
    const w = window.open(url, "_blank");
    if (w) w.opener = null;
    return !!w;
  };
  const share = async (network: Network | "system") => {
    if (!blob || !file) return;
    setError(null);
    try {
      if (network === "system" || (isPhone() && canShareFile)) {
        // Téléphone : la feuille de partage envoie l'image (et le texte) à l'application choisie. Texte copié aussi :
        // Instagram ne le reprend pas.
        if (network !== "system") await copyText(text);
        await navigator.share({ files: [file], text: network === "instagram" ? undefined : text });
        setDone({ network, how: network === "system" ? "system" : network === "instagram" ? "instagramPhone" : "phone" });
      } else if (network === "instagram") {
        download(blob, name);
        await copyText(text);
        const link = "https://www.instagram.com/";
        setDone({ network, how: openTab(link) ? "instagram" : "instagramNoTab", link });
      } else if (network === "reddit") {
        download(blob, name);
        const link = composeUrl("reddit", text, subreddit);
        setDone({ network, how: openTab(link) ? "reddit" : "redditNoTab", link });
      } else {
        const copied = await copyImage(blob);
        if (!copied) download(blob, name);
        const link = composeUrl(network, text);
        setDone({ network, how: `${copied ? "pasted" : "attach"}${openTab(link) ? "" : "NoTab"}`, link });
      }
    } catch (e) {
      if ((e as Error)?.name !== "AbortError") setError(e);  // feuille de partage fermée : rien à signaler
    }
  };

  return (
    <Dialog.Portal>
      <Dialog.Overlay className="share-overlay" />
      <Dialog.Content className="share-dialog" aria-describedby={undefined}>
        <Dialog.Close className="icon-button share-dialog__close" aria-label={t("screenshots.share.close")}>
          <Close size={18} aria-hidden />
        </Dialog.Close>
        <Dialog.Title className="share-dialog__title">{t("screenshots.share.title")}</Dialog.Title>
        <img className="share-dialog__img" src={shot.url} alt={title} />
        <div className="field">
          <div className="share-dialog__text-head">
            <label htmlFor="share-text" className="field__label">{t("screenshots.share.text")}</label>
            {ai.ready && (
              <div className="share-dialog__ai">
                <select aria-label={t("screenshots.share.tone")} value={ai.tone} disabled={ai.busy}
                  onChange={(e) => (ai.drafts ? ai.generate(e.target.value as Tone) : ai.setTone(e.target.value as Tone))}>
                  {TONES.map((x) => <option key={x} value={x}>{t(`screenshots.share.tone.${x}`)}</option>)}
                </select>
                <button type="button" className="button button--small" onClick={() => ai.generate()} disabled={ai.busy}>
                  {ai.busy ? <Loader2 size={14} className="spin" aria-hidden />
                    : ai.drafts ? <RefreshCw size={14} aria-hidden /> : <Sparkles size={14} aria-hidden />}
                  {" "}{t(ai.drafts ? "screenshots.share.regenerate" : "screenshots.share.write")}
                </button>
              </div>
            )}
          </div>
          <textarea id="share-text" rows={5} value={text} onChange={(e) => setText(e.target.value)} aria-busy={ai.busy}
            placeholder={t(ai.ready ? "screenshots.share.placeholderAi" : "screenshots.share.placeholder")} />
          <p className="muted small share-dialog__ai-note" role="status">
            {ai.busy ? t("screenshots.share.writing")
              : ai.error ? <span className="text-error">{errorMessage(ai.error)}</span>
              : !ai.ready ? t("screenshots.share.noAi") : null}
          </p>
        </div>
        <div className="share-dialog__networks">
          {NETWORKS.map((n) => (
            <button key={n} type="button" className={`button share-btn share-btn--${n}`} disabled={!blob} onClick={() => share(n)}>
              <span className="share-btn__dot" aria-hidden /> {t(`screenshots.share.${n}`)}
            </button>
          ))}
          {canShareFile && (
            <button type="button" className="button" onClick={() => share("system")}>
              <Share2 size={16} aria-hidden /> {t("screenshots.share.system")}
            </button>
          )}
        </div>
        <label className="field share-dialog__sub">
          <span className="field__label">{t("screenshots.share.subreddit")}</span>
          <select value={subreddit} onChange={(e) => setSubreddit(e.target.value)}>
            {SUBREDDITS.map((s) => <option key={s} value={s}>r/{s}</option>)}
          </select>
        </label>
        {done && (
          <p className="share-dialog__done" role="status">
            {t(`screenshots.share.done.${done.how}`, { network: t(`screenshots.share.${done.network}`) })}
            {done.link && done.how.endsWith("NoTab") && <> <a href={done.link} target="_blank" rel="noreferrer noopener">{t("screenshots.share.openLink")}</a></>}
          </p>
        )}
        {error ? <p className="text-error">{errorMessage(error)}</p> : null}
        <p className="muted small">{t("screenshots.share.help")}</p>
      </Dialog.Content>
    </Dialog.Portal>
  );
}

/**
 * Texte du post écrit par l'IA réglée (POST …/caption), à la demande : « Générer avec l'IA », puis « Régénérer » ou
 * changement de ton, en lui donnant les brouillons déjà proposés pour qu'il change d'idée.
 */
function useCaption(shot: Shot, setText: (text: string) => void) {
  const llm = useLlmSettings();
  const ready = llm.data?.ready === true;
  const ref = shotRef(shot.url);
  const [tone, setTone] = useState<Tone>("nostalgic");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [drafts, setDrafts] = useState(0);
  const previous = useRef<string[]>([]);
  const generate = useCallback(async (next?: Tone) => {
    if (!ref) return;
    const chosen = next ?? tone;
    setTone(chosen);
    setBusy(true);
    setError(null);
    try {
      const r = await api.captionScreenshot(ref.gameId, ref.name, { lang: getLang(), tone: chosen, previous: previous.current });
      previous.current = [...previous.current, r.text].slice(-5);
      setText(r.text);
      setDrafts((n) => n + 1);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }, [ref?.gameId, ref?.name, tone, setText]);  // eslint-disable-line react-hooks/exhaustive-deps
  return { ready: ready && !!ref, tone, setTone, busy, error, generate, drafts: drafts > 0 };
}
