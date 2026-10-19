import { BellRing, Bluetooth, BluetoothSearching, Gamepad2, Headphones, Keyboard, Link2, Link2Off, RotateCcw, Smartphone, Speaker, Trash2, Volume2 } from "lucide-react";

import { useRef, useState } from "react";

import type { BtDevice, NowPlaying, SoundTest } from "../api/client";
import { useBluetooth, useBluetoothActions, useCaps, useDeviceStatus, useLaunchGame, useNowPlaying } from "../api/queries";
import { ErrorNotice, PageHeader, Spinner, errorMessage } from "../components/ui";
import { useT } from "../i18n";

const KIND_ICON = { audio: Speaker, controller: Gamepad2, input: Keyboard, other: Smartphone } as const;

export function BluetoothPage() {
  const t = useT();
  const online = useDeviceStatus().data?.connected === true;
  const q = useBluetooth(online);
  const a = useBluetoothActions();
  const audioOk = useCaps().bluetooth_audio;
  const now = useNowPlaying(online).data;
  const busy = a.connect.isPending || a.disconnect.isPending || a.forget.isPending || a.audio.isPending;
  const pendingAddress = (a.connect.isPending && a.connect.variables) || (a.disconnect.isPending && a.disconnect.variables)
    || (a.forget.isPending && a.forget.variables) || null;
  const error = a.connect.error ?? a.disconnect.error ?? a.forget.error ?? a.audio.error ?? a.scan.error;
  const st = q.data;
  // Appareil sur lequel on vient de cliquer : il remonte en tête de « Mes appareils », même s'il n'a pas pu être
  // appairé, pour ne pas le chercher au milieu de dizaines d'appareils à portée.
  const [focus, setFocus] = useState<string | null>(null);
  const knownRef = useRef<HTMLElement>(null);
  const mine = (d: BtDevice) => d.paired || d.connected || d.address === focus;
  const known = (st?.devices ?? []).filter(mine)
    .sort((x, y) => Number(y.address === focus) - Number(x.address === focus) || Number(y.connected) - Number(x.connected));
  const connect = (address: string) => {
    setFocus(address);
    a.connect.mutate(address);
    knownRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  };
  // Sans nom (adresse affichée à la place) : objets du voisinage, rarement ce qu'on cherche.
  const unnamed = (d: BtDevice) => d.name.replace(/-/g, ":").toUpperCase() === d.address;
  const nearbyAll = (st?.devices ?? []).filter((d) => !mine(d))
    .sort((x, y) => (y.rssi ?? -999) - (x.rssi ?? -999));
  const [showUnnamed, setShowUnnamed] = useState(false);
  const hidden = nearbyAll.filter(unnamed).length;
  const nearby = showUnnamed ? nearbyAll : nearbyAll.filter((d) => !unnamed(d));
  // Un jeu déjà lancé garde la sortie du son qu'il a ouverte au démarrage : on retient le jeu en cours au moment
  // où l'on change la sortie, et on propose de le relancer tant qu'il tourne encore.
  const [staleRom, setStaleRom] = useState<string | null>(null);
  const setAudio = (address: string | null) => {
    setStaleRom(now?.playing ? now.rom_path ?? now.process ?? "" : null);
    a.audio.mutate(address);
  };
  // Test sonore : un carillon sur l'enceinte ; résultat affiché sur la ligne de l'appareil testé.
  const tested = a.testSound.variables;
  const sound = (d: BtDevice): SoundCheck | undefined => audioOk && d.kind === "audio" ? {
    run: () => a.testSound.mutate(d.address), testing: a.testSound.isPending && tested === d.address,
    result: tested === d.address && !a.testSound.isPending ? a.testSound.data?.result ?? a.testSound.error : undefined,
  } : undefined;
  const stale = staleRom !== null && now?.playing && (now.rom_path ?? now.process ?? "") === staleRom ? now : null;

  return (
    <div className="page bluetooth">
      <PageHeader title={t("bluetooth.title")} lead={t("bluetooth.lead")}>
        <button type="button" className="button button--primary" onClick={() => a.scan.mutate()} disabled={!online || a.scan.isPending}>
          <BluetoothSearching size={16} aria-hidden className={a.scan.isPending ? "pulse" : ""} />
          {a.scan.isPending ? t("bluetooth.scanning") : t("bluetooth.scan")}
        </button>
      </PageHeader>

      {!online ? (
        <p className="muted">{t("bluetooth.offline")}</p>
      ) : q.isPending ? (
        <Spinner label={t("bluetooth.reading")} />
      ) : q.isError ? (
        <ErrorNotice error={q.error} />
      ) : st && (
        <>
          <section className="block bt-adapter" aria-label={t("bluetooth.adapter")}>
            <Bluetooth size={22} aria-hidden className={st.adapter.powered ? "bt-on" : "muted"} />
            <div>
              <p><strong>{st.adapter.name ?? "Console"}</strong> · {st.adapter.powered ? t("bluetooth.on") : t("bluetooth.off")}</p>
              {audioOk && <p className="muted">
                {st.bluealsa ? t("bluetooth.audioReady") : t("bluetooth.audioNotReady")}
                {" · "}
                {st.audio_output
                  ? t("bluetooth.soundTo", { name: st.devices.find((d) => d.address === st.audio_output)?.name ?? st.audio_output })
                  : t("bluetooth.soundConsole")}
              </p>}
            </div>
            {st.audio_output && (
              <button type="button" className="button button--small" onClick={() => setAudio(null)} disabled={busy}>
                <Volume2 size={14} aria-hidden /> {t("bluetooth.backToConsole")}
              </button>
            )}
          </section>

          {stale && <RelaunchNotice now={stale} onDone={() => setStaleRom(null)} />}

          {error && <ErrorNotice error={error} />}

          <section className="block" aria-labelledby="bt-known" ref={knownRef}>
            <h2 id="bt-known">{t("bluetooth.known")}</h2>
            {known.length === 0 ? <p className="muted">{t("bluetooth.noneKnown")}</p> : (
              <ul className="bt-list">
                {known.map((d) => (
                  <DeviceRow key={d.address} d={d} audioOutput={st.audio_output} busy={busy} pending={pendingAddress === d.address}
                    onConnect={() => connect(d.address)} onDisconnect={() => a.disconnect.mutate(d.address)}
                    onForget={() => a.forget.mutate(d.address)} onAudio={audioOk ? () => setAudio(d.address) : undefined}
                    sound={sound(d)} />
                ))}
              </ul>
            )}
          </section>

          <section className="block" aria-labelledby="bt-near">
            <h2 id="bt-near">{t("bluetooth.nearby")}</h2>
            {hidden > 0 && (
              <button type="button" className="link-button" onClick={() => setShowUnnamed(!showUnnamed)}>
                {showUnnamed ? t("bluetooth.hideUnnamed") : t("bluetooth.showUnnamed", { count: hidden })}
              </button>
            )}
            {nearby.length === 0 ? <p className="muted">{t("bluetooth.noneNearby")}</p> : (
              <ul className="bt-list">
                {nearby.map((d) => (
                  <DeviceRow key={d.address} d={d} audioOutput={st.audio_output} busy={busy} pending={pendingAddress === d.address}
                    onConnect={() => connect(d.address)} onDisconnect={() => a.disconnect.mutate(d.address)}
                    onForget={() => a.forget.mutate(d.address)} onAudio={audioOk ? () => setAudio(d.address) : undefined}
                    sound={sound(d)} />
                ))}
              </ul>
            )}
          </section>

          <section className="block howto" aria-labelledby="bt-help">
            <h2 id="bt-help">{t("bluetooth.help.title")}</h2>
            <div className="howto__cols">
              <div><h3><Gamepad2 size={16} aria-hidden /> {t("bluetooth.help.padTitle")}</h3><p>{t("bluetooth.help.pad")}</p></div>
              <div><h3><Headphones size={16} aria-hidden /> {t("bluetooth.help.audioTitle")}</h3><p>{t("bluetooth.help.audio")}</p></div>
              <div><h3>{t("bluetooth.help.rebootTitle")}</h3><p>{t("bluetooth.help.reboot")}</p></div>
            </div>
          </section>
        </>
      )}
    </div>
  );
}

/**
 * Le son vient de changer de sortie alors qu'un jeu tourne : RetroArch garde la sortie ouverte au démarrage. Un jeu
 * RetroArch de la bibliothèque se relance d'un clic (launch.sh le quitte proprement puis reprend la partie).
 */
function RelaunchNotice({ now, onDone }: { now: NowPlaying; onDone: () => void }) {
  const t = useT();
  const caps = useCaps();
  const launch = useLaunchGame();
  const title = now.game?.title ?? now.rom_path?.split("/").pop() ?? now.process ?? "";
  const game = now.process === "retroarch" ? now.game : null;
  const body = !game ? "bluetooth.relaunch.bodyConsole" : caps.resume_slot ? "bluetooth.relaunch.body" : "bluetooth.relaunch.bodyNoResume";
  const relaunch = () => game && launch.mutate({ id: game.id, slot: caps.resume_slot ? "auto" : null }, { onSuccess: onDone });
  return (
    <section className="block bt-relaunch" role="status" aria-labelledby="bt-relaunch">
      <RotateCcw size={20} aria-hidden />
      <div>
        <h2 id="bt-relaunch">{t("bluetooth.relaunch.title")}</h2>
        <p>{t(body, { title })}</p>
        {launch.isError && <p className="text-error">{errorMessage(launch.error)}</p>}
      </div>
      {game && caps.launch && (
        <button type="button" className="button button--primary" onClick={relaunch} disabled={launch.isPending}>
          <RotateCcw size={16} aria-hidden /> {launch.isPending ? t("bluetooth.relaunch.working") : t("bluetooth.relaunch.button")}
        </button>
      )}
    </section>
  );
}

/** Test sonore d'une enceinte : lancer, en cours, résultat (« played », « in_use » ou l'erreur). */
type SoundCheck = { run: () => void; testing: boolean; result?: SoundTest["result"] | Error | null };

function DeviceRow({ d, audioOutput, busy, pending, onConnect, onDisconnect, onForget, onAudio, sound }: {
  d: BtDevice; audioOutput: string | null; busy: boolean; pending: boolean;
  onConnect: () => void; onDisconnect: () => void; onForget: () => void; onAudio?: () => void; sound?: SoundCheck;
}) {
  const t = useT();
  const Icon = KIND_ICON[d.kind as keyof typeof KIND_ICON] ?? Smartphone;
  const isOutput = audioOutput === d.address;
  return (
    <li className={`bt-device ${d.connected ? "is-connected" : ""} ${pending ? "is-pending" : ""}`}>
      <Icon size={22} aria-hidden className="bt-device__icon" />
      <div className="bt-device__text">
        <p className="bt-device__name">{d.name}</p>
        <p className="muted">
          {t(`bluetooth.kind.${d.kind}`)} · <code>{d.address}</code>
          {d.rssi != null && ` · ${t("bluetooth.signal", { rssi: d.rssi })}`}
        </p>
        {d.connected && sound?.result && (sound.result instanceof Error
          ? <p className="text-error" role="status">{errorMessage(sound.result)}</p>
          : <p className="bt-device__test" role="status"><BellRing size={14} aria-hidden /> {t(`bluetooth.test.${sound.result}`)}</p>)}
      </div>
      <div className="bt-device__state">
        {d.connected ? <span className="bt-status is-on">{t("bluetooth.connected")}</span>
          : d.paired ? <span className="bt-status">{t("bluetooth.pairedOnly")}</span> : null}
        {isOutput && <span className="bt-sound"><Volume2 size={14} aria-hidden /> {t("bluetooth.gameSound")}</span>}
      </div>
      <div className="bt-device__actions">
        {pending ? <Spinner label={t("bluetooth.working")} /> : d.connected ? (
          <>
            {d.kind === "audio" && !isOutput && onAudio && (
              <button type="button" className="button button--small button--primary" onClick={onAudio} disabled={busy}>
                <Volume2 size={14} aria-hidden /> {t("bluetooth.useForSound")}
              </button>
            )}
            {sound && (
              <button type="button" className="button button--small" onClick={sound.run} disabled={busy || sound.testing}>
                <BellRing size={14} aria-hidden /> {sound.testing ? t("bluetooth.test.working") : t("bluetooth.test.button")}
              </button>
            )}
            <button type="button" className="button button--small" onClick={onDisconnect} disabled={busy}>
              <Link2Off size={14} aria-hidden /> {t("bluetooth.disconnect")}
            </button>
          </>
        ) : (
          <button type="button" className="button button--small button--primary" onClick={onConnect} disabled={busy}>
            <Link2 size={14} aria-hidden /> {d.paired ? t("bluetooth.connect") : t("bluetooth.pair")}
          </button>
        )}
        {d.paired && !pending && (
          <button type="button" className="icon-button" onClick={onForget} disabled={busy} title={t("bluetooth.forget")} aria-label={t("bluetooth.forget")}>
            <Trash2 size={15} aria-hidden />
          </button>
        )}
      </div>
    </li>
  );
}
