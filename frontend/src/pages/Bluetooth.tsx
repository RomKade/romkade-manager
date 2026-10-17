import { Bluetooth, BluetoothSearching, Gamepad2, Headphones, Keyboard, Link2, Link2Off, Smartphone, Speaker, Trash2, Volume2 } from "lucide-react";

import { useRef, useState } from "react";

import type { BtDevice } from "../api/client";
import { useBluetooth, useBluetoothActions, useCaps, useDeviceStatus } from "../api/queries";
import { ErrorNotice, PageHeader, Spinner } from "../components/ui";
import { useT } from "../i18n";

const KIND_ICON = { audio: Speaker, controller: Gamepad2, input: Keyboard, other: Smartphone } as const;

export function BluetoothPage() {
  const t = useT();
  const online = useDeviceStatus().data?.connected === true;
  const q = useBluetooth(online);
  const a = useBluetoothActions();
  const audioOk = useCaps().bluetooth_audio;
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
              <button type="button" className="button button--small" onClick={() => a.audio.mutate(null)} disabled={busy}>
                <Volume2 size={14} aria-hidden /> {t("bluetooth.backToConsole")}
              </button>
            )}
          </section>

          {error && <ErrorNotice error={error} />}

          <section className="block" aria-labelledby="bt-known" ref={knownRef}>
            <h2 id="bt-known">{t("bluetooth.known")}</h2>
            {known.length === 0 ? <p className="muted">{t("bluetooth.noneKnown")}</p> : (
              <ul className="bt-list">
                {known.map((d) => (
                  <DeviceRow key={d.address} d={d} audioOutput={st.audio_output} busy={busy} pending={pendingAddress === d.address}
                    onConnect={() => connect(d.address)} onDisconnect={() => a.disconnect.mutate(d.address)}
                    onForget={() => a.forget.mutate(d.address)} onAudio={audioOk ? () => a.audio.mutate(d.address) : undefined} />
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
                    onForget={() => a.forget.mutate(d.address)} onAudio={audioOk ? () => a.audio.mutate(d.address) : undefined} />
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

function DeviceRow({ d, audioOutput, busy, pending, onConnect, onDisconnect, onForget, onAudio }: {
  d: BtDevice; audioOutput: string | null; busy: boolean; pending: boolean;
  onConnect: () => void; onDisconnect: () => void; onForget: () => void; onAudio?: () => void;
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
