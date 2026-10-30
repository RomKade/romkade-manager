import { Bluetooth, BookOpen, Camera, ChevronDown, ExternalLink, Gamepad2, Globe, Gauge, HardDriveUpload, Hourglass, Library, Loader2, LogOut, RefreshCw, RotateCw, Save, Settings as SettingsIcon, Volume2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";

import { isActive, useCaps, useDeviceStatus, useSettings, useStatus, useSystem, useTransfers } from "../api/queries";
import { getLang, useT } from "../i18n";
import { has } from "../i18n/core";
import { gb } from "../lib/format";
import icon80 from "../assets/brand/romkade-manager-icon-80.webp";
import logo240 from "../assets/brand/romkade-manager-logo-240.webp";
import logo480 from "../assets/brand/romkade-manager-logo-480.webp";
import { docsUrl } from "../lib/credits";
import { APP_VERSION } from "../version";
import { GitHubStar } from "./GitHubStar";
import { ACCOUNT_TABS, accountPath } from "../auth/accountTabs";
import { useAuth } from "../auth/AuthContext";

const NAV = [
  { to: "/", label: "common.nav.dashboard", icon: Gauge, end: true },
  { to: "/bibliotheque", label: "common.nav.library", icon: Library },
  { to: "/ajouter-des-jeux", label: "common.nav.transfers", icon: HardDriveUpload },
  { to: "/temps-de-jeu", label: "common.nav.playtime", icon: Hourglass },
  { to: "/sauvegardes", label: "common.nav.saves", icon: Save },
  { to: "/captures", label: "common.nav.screenshots", icon: Camera },
  { to: "/manettes", label: "common.nav.players", icon: Gamepad2 },
  { to: "/son", label: "common.nav.sound", icon: Volume2 },
  { to: "/bluetooth", label: "common.nav.bluetooth", icon: Bluetooth },
  { to: "/synchronisation", label: "common.nav.sync", icon: RefreshCw },
  { to: "/parametres", label: "common.nav.settings", icon: SettingsIcon },
];

export function Sidebar() {
  const t = useT();
  const active = (useTransfers().data ?? []).filter(isActive).length;
  const caps = useCaps();
  const system = useSystem().data;
  const nav = NAV.filter((n) => (n.to !== "/bluetooth" || caps.bluetooth) && (n.to !== "/son" || caps.bluetooth_audio) && (n.to !== "/manettes" || caps.players));
  return (
    <aside className="sidebar">
      <div className="brand">
        <Link to="/" className="brand__home" aria-label={t("common.nav.home")}>
          <img className="brand__logo" src={logo240} srcSet={`${logo240} 240w, ${logo480} 480w`} sizes="196px"
            width={196} height={43} alt="" />
          <img className="brand__icon" src={icon80} width={34} height={34} alt="" />
        </Link>
        <p className="brand__device">{system ? system.profile.label : "\u00a0"}</p>
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
          <li>
            <a href={docsUrl()} target="_blank" rel="noreferrer noopener" className="nav__link">
              <BookOpen aria-hidden size={18} strokeWidth={1.75} />
              <span>{t("common.nav.docs")}</span>
              <ExternalLink aria-hidden size={13} className="nav__external" />
              <span className="visually-hidden"> {t("common.nav.newTab")}</span>
            </a>
          </li>
          <li>
            <a href="https://romkade.com" target="_blank" rel="noreferrer noopener" className="nav__link">
              <Globe aria-hidden size={18} strokeWidth={1.75} />
              <span>romkade.com</span>
              <ExternalLink aria-hidden size={13} className="nav__external" />
              <span className="visually-hidden"> {t("common.nav.newTab")}</span>
            </a>
          </li>
        </ul>
      </nav>
      <DeviceCard />
      <AccountChip />
      <GitHubStar className="sidebar__github" />
      <p className="sidebar__meta">
        <Link to="/conditions">{t("legal.link")}</Link>
        <span aria-hidden> · </span>
        <Link to="/parametres/a-propos" title={t("legal.version", { version: APP_VERSION })}>v{APP_VERSION}</Link>
      </p>
    </aside>
  );
}

/** Console pas encore (ou plus) réglée : l'installation guidée (/bienvenue) reprend la mise en route. */
const SETUP_ERRORS = new Set(["console_not_configured", "credentials_missing", "key_path_missing", "host_key_unknown"]);

function DeviceCard() {
  const t = useT();
  const device = useDeviceStatus();
  const status = useStatus();
  const settings = useSettings();
  const s = status.data;
  const connected = device.data?.connected;
  // Une tentative en cours alors que la console n'est pas (encore) connectée : on le montre tout de suite.
  const state = connected ? "online" : device.isFetching || device.isPending ? "checking" : "offline";
  const label = t(`common.device.${state}`);
  const usedPct =
    s?.storage_total_bytes && s.storage_free_bytes != null
      ? ((s.storage_total_bytes - s.storage_free_bytes) / s.storage_total_bytes) * 100
      : null;

  return (
    <section className="device-card" aria-label={t("common.device.state", { state: label })}>
      <p className={`device-card__state is-${state}`}>
        {state === "checking" ? <Loader2 size={12} aria-hidden className="spin device-card__spinner" /> : <span className="led" aria-hidden />}
        <span className="device-card__label">{label}</span>
        {state === "offline" && (
          <button type="button" className="device-card__retry" onClick={() => device.refetch()}
            title={t("common.device.retry")} aria-label={t("common.device.retry")}>
            <RotateCw size={13} aria-hidden />
          </button>
        )}
      </p>
      <p className="device-card__host">{settings.data ? settings.data.host : " "}</p>
      {!connected && device.data?.error && (
        <p className="device-card__error">
          {getLang() !== "fr" && has(`common.error.${device.data.error.code}`) ? t(`common.error.${device.data.error.code}`) : device.data.error.message}
          {SETUP_ERRORS.has(device.data.error.code) && <> <Link to="/bienvenue">{t("common.device.setup")}</Link></>}
        </p>
      )}
      {usedPct != null && (
        <div className="device-card__storage">
          <div className="minibar" aria-hidden>
            <div style={{ width: `${usedPct}%` }} />
          </div>
          {/* La barre montre la place occupée : le texte dit la même chose. */}
          <p>{t("common.device.used", { used: gb(s!.storage_total_bytes! - s!.storage_free_bytes!), total: gb(s!.storage_total_bytes) })}</p>
        </div>
      )}
      {s?.sync_running && <p className="device-card__sync">{t("common.device.syncing")}</p>}
    </section>
  );
}


/** Compte ROMKADE connecté (nom ou e-mail) et déconnexion. Rien hors de la barrière de connexion (tests). */
function AccountChip() {
  const t = useT();
  const { session, signOut } = useAuth();
  const inAccount = useLocation().pathname.startsWith("/compte");
  const [open, setOpen] = useState(inAccount);
  useEffect(() => { if (inAccount) setOpen(true); }, [inAccount]);
  if (!session) return null;
  const meta = session.user.user_metadata as { name?: string } | undefined;
  const email = session.user.email ?? "";
  return (
    <div className={`account-chip ${open ? "is-open" : ""}`}>
      <div className="account-chip__row">
        <span className="account-chip__avatar" aria-hidden>{(meta?.name || email || "?").slice(0, 1).toUpperCase()}</span>
        <button type="button" className="account-chip__who" aria-expanded={open} aria-controls="account-menu"
          onClick={() => setOpen((o) => !o)}>
          <span className="account-chip__name">{meta?.name || email}</span>
          <ChevronDown size={15} aria-hidden className="account-chip__chevron" />
        </button>
        <button type="button" className="account-chip__out" onClick={() => signOut()} aria-label={t("auth.signout")} title={t("auth.signout")}>
          <LogOut size={16} aria-hidden />
        </button>
      </div>
      {open && (
        <ul id="account-menu" className="account-chip__menu" aria-label={t("account.open")}>
          {ACCOUNT_TABS.map(({ slug, label, icon: Icon }) => (
            <li key={slug}>
              <NavLink to={accountPath(slug)} end className={({ isActive }) => `account-chip__item ${isActive ? "is-active" : ""} ${slug === "zone-dangereuse" ? "account-chip__item--danger" : ""}`}>
                <Icon size={15} aria-hidden /> {t(label)}
              </NavLink>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
