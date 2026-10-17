import { Bluetooth, Gamepad2, Gauge, HardDriveUpload, Hourglass, Library, RefreshCw, Save, Settings as SettingsIcon } from "lucide-react";
import { NavLink } from "react-router-dom";

import { isActive, useCaps, useDeviceStatus, useSettings, useStatus, useSystem, useTransfers } from "../api/queries";
import { getLang, useT } from "../i18n";
import { has } from "../i18n/core";
import { gb } from "../lib/format";
import { GitHubStar } from "./GitHubStar";

const NAV = [
  { to: "/", label: "common.nav.dashboard", icon: Gauge, end: true },
  { to: "/bibliotheque", label: "common.nav.library", icon: Library },
  { to: "/ajouter-des-jeux", label: "common.nav.transfers", icon: HardDriveUpload },
  { to: "/temps-de-jeu", label: "common.nav.playtime", icon: Hourglass },
  { to: "/sauvegardes", label: "common.nav.saves", icon: Save },
  { to: "/manettes", label: "common.nav.players", icon: Gamepad2 },
  { to: "/bluetooth", label: "common.nav.bluetooth", icon: Bluetooth },
  { to: "/synchronisation", label: "common.nav.sync", icon: RefreshCw },
  { to: "/parametres", label: "common.nav.settings", icon: SettingsIcon },
];

export function Sidebar() {
  const t = useT();
  const active = (useTransfers().data ?? []).filter(isActive).length;
  const caps = useCaps();
  const system = useSystem().data;
  const nav = NAV.filter((n) => (n.to !== "/bluetooth" || caps.bluetooth) && (n.to !== "/manettes" || caps.players));
  return (
    <aside className="sidebar">
      <div className="brand">
        <svg className="brand__mark" viewBox="0 0 32 32" aria-hidden>
          <rect x="5" y="2" width="22" height="28" rx="4" className="brand__shell" />
          <rect x="8.5" y="5.5" width="15" height="11" rx="1.5" className="brand__screen" />
          <circle cx="21" cy="23" r="2.2" className="brand__button" />
          <path d="M9.5 23h5M12 20.5v5" className="brand__dpad" />
        </svg>
        <div>
          <p className="brand__name">Game Manager</p>
          <p className="brand__device">{system ? system.profile.label : "\u00a0"}</p>
        </div>
      </div>
      <nav aria-label={t("common.nav.main")}>
        <ul className="nav">
          {nav.map(({ to, label, icon: Icon, end }) => (
            <li key={to}>
              <NavLink to={to} end={end} className={({ isActive }) => `nav__link ${isActive ? "is-active" : ""}`}>
                <Icon aria-hidden size={18} strokeWidth={1.75} />
                <span>{t(label)}</span>
                {to === "/ajouter-des-jeux" && active > 0 && (
                  <span className="nav__badge num" aria-label={t("common.nav.activeCount", { count: active })}>{active}</span>
                )}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <DeviceCard />
      <GitHubStar className="sidebar__github" />
    </aside>
  );
}

function DeviceCard() {
  const t = useT();
  const device = useDeviceStatus();
  const status = useStatus();
  const settings = useSettings();
  const s = status.data;
  const connected = device.data?.connected;
  const state = device.isPending ? "checking" : connected ? "online" : "offline";
  const label = t(`common.device.${state}`);
  const usedPct =
    s?.storage_total_bytes && s.storage_free_bytes != null
      ? ((s.storage_total_bytes - s.storage_free_bytes) / s.storage_total_bytes) * 100
      : null;

  return (
    <section className="device-card" aria-label={t("common.device.state", { state: label })}>
      <p className={`device-card__state is-${state}`}>
        <span className="led" aria-hidden />
        <span className="device-card__label">{label}</span>
      </p>
      <p className="device-card__host">{settings.data ? settings.data.host : " "}</p>
      {state === "offline" && device.data?.error && (
        <p className="device-card__error">
          {getLang() !== "fr" && has(`common.error.${device.data.error.code}`) ? t(`common.error.${device.data.error.code}`) : device.data.error.message}
        </p>
      )}
      {usedPct != null && (
        <div className="device-card__storage">
          <div className="minibar" aria-hidden>
            <div style={{ width: `${usedPct}%` }} />
          </div>
          <p>{t("common.device.free", { free: gb(s!.storage_free_bytes), total: gb(s!.storage_total_bytes) })}</p>
        </div>
      )}
      {s?.sync_running && <p className="device-card__sync">{t("common.device.syncing")}</p>}
    </section>
  );
}

