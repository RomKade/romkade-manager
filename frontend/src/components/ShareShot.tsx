import * as Dialog from "@radix-ui/react-dialog";
import { Share2, X as Close } from "lucide-react";
import { useEffect, useState } from "react";

import type { Shot } from "../api/client";
import { useT } from "../i18n";
import { errorMessage } from "./ui";

/**
 * Partage d'une capture sur les réseaux, sans compte ni clé : aucun réseau n'accepte une image par lien, on prépare
 * donc tout ce qui peut l'être et la personne publie elle-même.
 * - X et Bluesky : image copiée, éditeur du réseau ouvert avec le texte ; il reste à coller l'image.
 * - Reddit : image téléchargée, formulaire du subreddit ouvert avec le titre ; il reste à y ajouter l'image.
 * - Instagram (pas de lien d'écriture) : feuille de partage du téléphone ; sur ordinateur, image téléchargée,
 *   légende copiée, Instagram ouvert.
 * L'image est agrandie trois fois sans lissage : les réseaux floutent une petite image de pixel art.
 */
export type Network = "instagram" | "bluesky" | "x" | "reddit";
export const NETWORKS: Network[] = ["instagram", "bluesky", "x", "reddit"];
export const SUBREDDITS = ["SBCGaming", "retrogaming", "ANBERNIC", "RG35XX"];
const SCALE = 3;

/** Mot-dièse de la console : « Mega Drive / Genesis » → « MegaDrive ». */
export function consoleTag(label: string | null | undefined): string | null {
  const first = (label ?? "").split("/")[0]!.normalize("NFD").replace(/[̀-ͯ]/g, "");
  const tag = first.split(/[^A-Za-z0-9]+/).filter(Boolean).map((w) => w[0]!.toUpperCase() + w.slice(1)).join("");
  return tag || null;
}

export function defaultText(title: string, platform: string | null | undefined): string {
  const tag = consoleTag(platform);
  return `${title}${platform ? ` · ${platform}` : ""}\n#retrogaming${tag ? ` #${tag}` : ""}`;
}

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
export function ShareShotButton({ shot, title, platform }: { shot: Shot; title: string; platform?: string | null }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button type="button" className="icon-button" aria-label={t("screenshots.share.button")} title={t("screenshots.share.button")}>
          <Share2 size={14} aria-hidden />
        </button>
      </Dialog.Trigger>
      {open && <ShareDialog shot={shot} title={title} platform={platform} />}
    </Dialog.Root>
  );
}

function ShareDialog({ shot, title, platform }: { shot: Shot; title: string; platform?: string | null }) {
  const t = useT();
  const [text, setText] = useState(() => defaultText(title, platform));
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
      if (network === "system" || (network === "instagram" && isPhone() && canShareFile)) {
        if (network === "instagram") await copyText(text);  // Instagram ne reçoit pas le texte : légende à coller
        await navigator.share({ files: [file], text: network === "system" ? text : undefined });
        setDone({ network, how: network === "instagram" ? "instagramPhone" : "system" });
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
        <label className="field">
          <span className="field__label">{t("screenshots.share.text")}</span>
          <textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} />
        </label>
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
