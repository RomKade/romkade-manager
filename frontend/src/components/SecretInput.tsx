import { Eye, EyeOff } from "lucide-react";
import { useState, type InputHTMLAttributes } from "react";

import { useT } from "../i18n";

/** Champ secret (mot de passe, clé d'API) avec un œil pour afficher ou masquer ce qu'on tape. */
export function SecretInput(props: Omit<InputHTMLAttributes<HTMLInputElement>, "type">) {
  const t = useT();
  const [shown, setShown] = useState(false);
  const label = shown ? t("common.secret.hide") : t("common.secret.show");
  return (
    <span className="secret">
      <input {...props} type={shown ? "text" : "password"} />
      <button type="button" className="secret__toggle" onClick={() => setShown(!shown)}
        aria-label={label} title={label} aria-pressed={shown} aria-controls={props.id}>
        {shown ? <EyeOff size={16} aria-hidden /> : <Eye size={16} aria-hidden />}
      </button>
    </span>
  );
}
