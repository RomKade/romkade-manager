import { BellRing, Bluetooth as BluetoothIcon, Headphones, Speaker, Tv } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import type { BtDevice, SoundOutput } from "../api/client";
import { useCaps, useDeviceStatus, useNowPlaying, useSound, useSoundActions, useVolume } from "../api/queries";
import { ErrorNotice, PageHeader, Spinner, errorMessage } from "../components/ui";
import { VolumeControl } from "../components/VolumeControl";
import { useT } from "../i18n";
import { RelaunchNotice } from "./Bluetooth";

/** Une sortie possible : haut-parleurs, TV, ou une enceinte Bluetooth (par son adresse). */
type Choice = { output: SoundOutput; address?: string };
const key = (c: Choice) => c.address ?? c.output;

/**
 * Son des jeux : volume, et sortie (haut-parleurs de la console, TV branchée en HDMI, ou une enceinte / un casque
 * déjà appairé sur la page Bluetooth). La sortie vaut à partir du prochain jeu lancé depuis le Manager.
 */
export function SoundPage() {
  const t = useT();
  const online = useDeviceStatus().data?.connected === true;
  const q = useSound(online);
  const a = useSoundActions();
  const now = useNowPlaying(online).data;
  const caps = useCaps();
  const audioOk = caps.bluetooth_audio;
  const vol = useVolume(caps.volume && online).data;  // même requête que VolumeControl : rien à régler sans jeu ni réglage
  const st = q.data;
  // Comme sur la page Bluetooth : un jeu déjà lancé garde l'ancienne sortie, on propose de le relancer.
  const [staleRom, setStaleRom] = useState<string | null>(null);
  const stale = staleRom !== null && now?.playing && (now.rom_path ?? now.process ?? "") === staleRom ? now : null;
  const [tested, setTested] = useState<string | null>(null);
  const pick = (c: Choice) => {
    setStaleRom(now?.playing ? now.rom_path ?? now.process ?? "" : null);
    a.set.mutate({ output: c.output, address: c.address ?? null });
  };
  const test = (c: Choice) => {
    setTested(key(c));
    a.test.mutate({ output: c.output, address: c.address ?? null });
  };

  // Enceinte choisie que la console a oubliée (elle efface les appairages à chaque démarrage).
  const lost = st?.output === "bluetooth" && st.address && !st.devices.some((d) => d.address === st.address) ? st.address : null;
  const current = st ? key({ output: st.output, address: st.address ?? undefined }) : null;
  const pending = a.set.isPending && a.set.variables ? key({ output: a.set.variables.output, address: a.set.variables.address ?? undefined }) : null;

  const option = (c: Choice, icon: ReactNode, title: string, hint: string) => {
    const k = key(c);
    const on = (pending ?? current) === k;
    const result = tested === k && !a.test.isPending ? a.test.data?.result ?? a.test.error : undefined;
    return (
      <div key={k} className={`llm__kind sound__option ${on ? "is-on" : ""}`}>
        <label className="sound__pick">
          <input type="radio" name="sound-output" checked={on} onChange={() => pick(c)} disabled={a.set.isPending} />
          <span className="llm__kind-title">{icon} {title}</span>
          <span className="llm__kind-hint">{hint}</span>
        </label>
        {pending === k && <Spinner label={c.address ? t("sound.connecting") : t("sound.working")} />}
        {on && !a.set.isPending && current === k && (
          <button type="button" className="button button--small sound__test" onClick={() => test(c)}
            disabled={a.test.isPending}>
            <BellRing size={14} aria-hidden /> {a.test.isPending && tested === k ? t("bluetooth.test.working") : t("bluetooth.test.button")}
          </button>
        )}
        {result && (result instanceof Error
          ? <p className="text-error" role="status">{errorMessage(result)}</p>
          : <p className="bt-device__test" role="status"><BellRing size={14} aria-hidden /> {t(`${c.address ? "bluetooth" : "sound"}.test.${result}`)}</p>)}
      </div>
    );
  };
  const deviceHint = (d: BtDevice) => d.connected ? t("bluetooth.connected") : t("sound.willConnect");

  return (
    <div className="page sound">
      <PageHeader title={t("sound.title")} lead={t("sound.lead")} />
      {!online ? (
        <p className="muted">{t("sound.offline")}</p>
      ) : q.isPending ? (
        <Spinner label={t("sound.reading")} />
      ) : q.isError ? (
        <ErrorNotice error={q.error} />
      ) : st && (
        <>
          {vol && vol.mode !== "none" && (
            <section className="block" aria-labelledby="sound-vol">
              <h2 id="sound-vol">{t("sound.volume")}</h2>
              <VolumeControl online={online} />
            </section>
          )}

          {stale && <RelaunchNotice now={stale} onDone={() => setStaleRom(null)} />}

          <section className="block" aria-labelledby="sound-out">
            <h2 id="sound-out">{t("sound.output")}</h2>
            <p className="muted">{t("sound.outputLead")}</p>
            {a.set.error && <ErrorNotice error={a.set.error} />}
            <div className="llm__kinds sound__options" role="radiogroup" aria-labelledby="sound-out">
              {option({ output: "speakers" }, <Speaker size={20} aria-hidden />, t("sound.speakers"), t("sound.speakersHint"))}
              {option({ output: "tv" }, <Tv size={20} aria-hidden />, t("sound.tv"), t(st.hdmi ? "sound.tvOn" : "sound.tvOff"))}
              {audioOk && st.devices.map((d) => option({ output: "bluetooth", address: d.address },
                d.icon.includes("headset") || d.icon.includes("headphone") ? <Headphones size={20} aria-hidden /> : <BluetoothIcon size={20} aria-hidden />,
                d.name, deviceHint(d)))}
              {lost && option({ output: "bluetooth", address: lost }, <BluetoothIcon size={20} aria-hidden />, lost, t("sound.lost"))}
            </div>
            {audioOk && (
              <p className="field__hint">
                {st.devices.length === 0 ? t("sound.noDevice") : t("sound.moreDevices")}{" "}
                <Link to="/bluetooth">{t("sound.toBluetooth")}</Link>
              </p>
            )}
          </section>
        </>
      )}
    </div>
  );
}
