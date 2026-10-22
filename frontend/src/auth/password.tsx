import { Check, X } from "lucide-react";

import { useT } from "../i18n";

/**
 * Force du mot de passe, vérifiée pendant la saisie. Règles obligatoires = celles de Supabase Auth
 * (10 caractères, minuscule, majuscule, chiffre) ; « Fort » demande en plus un caractère spécial ou 14 caractères.
 */
export const PASSWORD_RULES = [
  { key: "length", test: (p: string) => p.length >= 10 },
  { key: "lower", test: (p: string) => /[a-z]/.test(p) },
  { key: "upper", test: (p: string) => /[A-Z]/.test(p) },
  { key: "digit", test: (p: string) => /[0-9]/.test(p) },
] as const;

export type Strength = "empty" | "weak" | "medium" | "strong";

export function passwordStrength(p: string): Strength {
  if (!p) return "empty";
  if (!PASSWORD_RULES.every((r) => r.test(p))) return "weak";
  return /[^A-Za-z0-9]/.test(p) || p.length >= 14 ? "strong" : "medium";
}

export const passwordValid = (p: string) => PASSWORD_RULES.every((r) => r.test(p));

export function PasswordStrength({ password }: { password: string }) {
  const t = useT();
  const level = passwordStrength(password);
  if (level === "empty") return null;  // rien tant que le champ est vide
  const filled = { weak: 1, medium: 2, strong: 3 }[level];
  return (
    <div className={`pw-strength pw-strength--${level}`} aria-live="polite">
      <div className="pw-strength__bar" aria-hidden>
        {[0, 1, 2].map((i) => <span key={i} className={i < filled ? "is-on" : ""} />)}
      </div>
      <p className="pw-strength__label">{t("auth.strength.label")} : <strong>{t(`auth.strength.${level}`)}</strong></p>
      <ul className="pw-strength__rules">
        {PASSWORD_RULES.map((r) => {
          const ok = r.test(password);
          return (
            <li key={r.key} className={ok ? "is-ok" : ""}>
              {ok ? <Check size={14} aria-hidden /> : <X size={14} aria-hidden />}
              <span>{t(`auth.rule.${r.key}`)}</span>
              <span className="visually-hidden">{ok ? t("auth.rule.ok") : t("auth.rule.missing")}</span>
            </li>
          );
        })}
        <li className={`pw-strength__bonus ${level === "strong" ? "is-ok" : ""}`}>
          {level === "strong" ? <Check size={14} aria-hidden /> : <span className="pw-strength__plus" aria-hidden>+</span>}
          <span>{t("auth.rule.bonus")}</span>
        </li>
      </ul>
    </div>
  );
}
