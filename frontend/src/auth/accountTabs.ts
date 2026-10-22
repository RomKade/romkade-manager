import { AppWindow, Cloud, ShieldAlert, ShieldCheck, UserRound } from "lucide-react";

/** Rubriques de Mon compte : onglets de la page et sous-menu du compte dans la barre latérale. */
export const ACCOUNT_TABS = [
  { slug: "", label: "account.tab.profile", icon: UserRound },
  { slug: "securite", label: "account.tab.security", icon: ShieldCheck },
  { slug: "console", label: "account.tab.consoles", icon: Cloud },
  { slug: "applications", label: "account.tab.apps", icon: AppWindow },
  { slug: "zone-dangereuse", label: "account.tab.danger", icon: ShieldAlert },
] as const;

export const accountPath = (slug: string) => (slug ? `/compte/${slug}` : "/compte");
