import * as Dialog from "@radix-ui/react-dialog";
import { useQueryClient } from "@tanstack/react-query";
import { ExternalLink, RefreshCw, SkipForward, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, type Game } from "../api/client";
import { useGameVideo } from "../api/queries";
import { useT } from "../i18n";
import { ErrorNotice, Spinner } from "./ui";

/** Bande-annonce d'un jeu : la vidéo YouTube la plus pertinente, et les suivantes à la demande. */
export function VideoDialog({ game, onClose }: { game: Pick<Game, "id" | "title" | "platform"> | null; onClose: () => void }) {
  const t = useT();
  const q = useGameVideo(game?.id ?? null);
  const qc = useQueryClient();
  const [index, setIndex] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  useEffect(() => setIndex(0), [game?.id]);

  const data = q.data;
  const videos = data?.videos ?? [];
  const video = videos[index];
  const refresh = async () => {
    if (!game) return;
    setRefreshing(true);
    try {
      qc.setQueryData(["game-video", game.id], await api.gameVideo(game.id, true));
      setIndex(0);
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <Dialog.Root open={game != null} onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="sheet-overlay" />
        <Dialog.Content className="video-dialog" aria-describedby={undefined}>
          <header className="video-dialog__head">
            <div>
              <p className="sheet__platform">{game?.platform.label ?? game?.platform.directory}</p>
              <Dialog.Title className="video-dialog__title">{game?.title}</Dialog.Title>
            </div>
            <Dialog.Close className="icon-button" aria-label={t("sheet.video.close")}><X size={18} aria-hidden /></Dialog.Close>
          </header>

          <div className="video-dialog__frame">
            {q.isPending ? (
              <Spinner label={t("sheet.video.searching")} />
            ) : q.isError ? (
              <div className="video-dialog__msg"><ErrorNotice error={q.error} title={t("sheet.video.error")} /></div>
            ) : data?.status === "no_key" ? (
              <div className="video-dialog__msg">
                <p>{t("sheet.video.noKeyBefore")}<Link to="/parametres/catalogue">{t("sheet.video.noKeyLink")}</Link>{t("sheet.video.noKeyAfter")}</p>
                <a className="button" href={data.search_url} target="_blank" rel="noreferrer noopener">
                  <ExternalLink size={16} aria-hidden /> {t("sheet.video.searchYoutube")}
                </a>
              </div>
            ) : !video ? (
              <div className="video-dialog__msg">
                <p>{t("sheet.video.none")}</p>
                {data && (
                  <a className="button" href={data.search_url} target="_blank" rel="noreferrer noopener">
                    <ExternalLink size={16} aria-hidden /> {t("sheet.video.searchYoutube")}
                  </a>
                )}
              </div>
            ) : (
              <iframe
                key={video.id}
                src={`https://www.youtube-nocookie.com/embed/${encodeURIComponent(video.id)}?autoplay=1&rel=0&modestbranding=1`}
                title={t("sheet.video.frameTitle", { title: video.title })}
                allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
                allowFullScreen
                referrerPolicy="strict-origin-when-cross-origin"
              />
            )}
          </div>

          {video && data && (
            <footer className="video-dialog__foot">
              <p className="video-dialog__meta">
                <span className="video-dialog__vtitle">{video.title}</span>
                <span className="muted">{video.channel}</span>
              </p>
              <div className="video-dialog__actions">
                {videos.length > 1 && (
                  <button type="button" className="button" onClick={() => setIndex((index + 1) % videos.length)}>
                    <SkipForward size={16} aria-hidden /> {t("sheet.video.next")} <span className="num muted">{index + 1}/{videos.length}</span>
                  </button>
                )}
                <button type="button" className="icon-button" onClick={refresh} disabled={refreshing}
                  aria-label={t("sheet.video.refresh")} title={t("sheet.video.refreshTitle")}>
                  <RefreshCw size={16} aria-hidden />
                </button>
                <a className="icon-button" href={`https://www.youtube.com/watch?v=${encodeURIComponent(video.id)}`}
                  target="_blank" rel="noreferrer noopener" aria-label={t("sheet.video.open")} title={t("sheet.video.open")}>
                  <ExternalLink size={16} aria-hidden />
                </a>
              </div>
            </footer>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
