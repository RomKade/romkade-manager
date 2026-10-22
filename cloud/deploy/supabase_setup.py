#!/usr/bin/env python3
"""Configuration de Supabase Auth pour ROMKADE (comptes, OAuth pour ChatGPT/Claude, e-mails). © 2026 ROMKADE.

Rejouable : applique toute la configuration par l'API de gestion de Supabase. Lit cloud/deploy/.env
(SUPABASE_ACCESS_TOKEN, MAILJET_API_KEY, MAILJET_SECRET_KEY) ; n'affiche jamais un secret.

    python3 cloud/deploy/supabase_setup.py            # applique
    python3 cloud/deploy/supabase_setup.py --dry-run  # montre ce qui serait envoyé (sans les secrets)

E-mails : un code à 6 chiffres plutôt qu'un lien (il marche quand l'e-mail est ouvert sur un autre appareil),
en français, anglais ou espagnol selon la langue du compte (métadonnée « locale », posée à l'inscription).
"""

import json
import sys
import urllib.request
from pathlib import Path

PROJECT = "urpvxqtyscuomkusqsiu"
SITE = "https://romkade.com"                      # page de connexion : romkade.com/authentification/
MCP = "https://mcp.romkade.com"                    # serveur MCP (logo des e-mails servi par lui)
LOGO = f"{MCP}/romkade-logo.png"
HERE = Path(__file__).resolve().parent


def env() -> dict:
    out = {}
    for line in (HERE / ".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


# ---------- e-mails ----------
LANG = '{{ $l := printf "%v" .Data.locale }}'


def tr(fr: str, en: str, es: str) -> str:
    return f'{{{{ if eq $l "fr" }}}}{fr}{{{{ else if eq $l "es" }}}}{es}{{{{ else }}}}{en}{{{{ end }}}}'


def mail(title: tuple, intro: tuple, code: bool = True, outro: tuple | None = None) -> str:
    code_block = ('<div style="margin:22px 0;text-align:center"><span style="display:inline-block;padding:14px 22px;'
                  'border-radius:12px;background:#102642;border:1px solid #11d9f5;color:#f5f8ff;font-size:32px;'
                  'font-weight:800;letter-spacing:10px;font-family:Arial,Helvetica,sans-serif">{{ .Token }}</span></div>'
                  ) if code else ""
    validity = tr("Ce code est valable 10 minutes.", "This code is valid for 10 minutes.", "Este código es válido 10 minutos.")
    ignore = tr("Si tu n'es pas à l'origine de cette demande, ignore cet e-mail : ton compte ne risque rien.",
                "If you didn't ask for this, ignore this email: your account is safe.",
                "Si no lo has solicitado, ignora este correo: tu cuenta está a salvo.")
    rights = tr("© 2026 ROMKADE · Tous droits réservés", "© 2026 ROMKADE · All rights reserved",
                "© 2026 ROMKADE · Todos los derechos reservados")
    return f"""{LANG}<!doctype html><html><body style="margin:0;padding:0;background:#050c1c">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#050c1c;padding:28px 12px">
<tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:480px;background:#0b1c35;border:1px solid #234362;border-radius:16px;font-family:Arial,Helvetica,sans-serif;color:#f5f8ff">
<tr><td style="padding:24px 24px 4px;text-align:center"><img src="{LOGO}" width="200" alt="ROMKADE" style="display:inline-block;border:0"></td></tr>
<tr><td style="padding:12px 28px 26px">
<h1 style="margin:8px 0 10px;font-size:22px;color:#f5f8ff">{tr(*title)}</h1>
<p style="margin:0 0 6px;font-size:15px;line-height:1.5;color:#a9bdd3">{tr(*intro)}</p>
{code_block}
{f'<p style="margin:0 0 6px;font-size:13px;color:#8aa1bb">{validity}</p>' if code else ''}
{f'<p style="margin:10px 0 0;font-size:15px;line-height:1.5;color:#a9bdd3">{tr(*outro)}</p>' if outro else ''}
<p style="margin:18px 0 0;font-size:12px;color:#8aa1bb">{ignore}</p>
</td></tr></table>
<p style="font-family:Arial,Helvetica,sans-serif;font-size:11px;color:#8aa1bb;margin:14px 0 0">{rights} · <a href="https://romkade.com" style="color:#11d9f5">romkade.com</a></p>
</td></tr></table></body></html>"""


def subject(fr: str, en: str, es: str) -> str:
    return LANG + tr(fr, en, es)


EMAILS = {
    "confirmation": (subject("{{ .Token }} — ton code ROMKADE", "{{ .Token }} — your ROMKADE code", "{{ .Token }} — tu código ROMKADE"),
                     mail(("Bienvenue sur ROMKADE", "Welcome to ROMKADE", "Bienvenido a ROMKADE"),
                          ("Saisis ce code pour vérifier ton adresse e-mail et activer ton compte :",
                           "Enter this code to verify your email address and activate your account:",
                           "Introduce este código para verificar tu correo y activar tu cuenta:"))),
    "recovery": (subject("{{ .Token }} — nouveau mot de passe ROMKADE", "{{ .Token }} — new ROMKADE password", "{{ .Token }} — nueva contraseña ROMKADE"),
                 mail(("Nouveau mot de passe", "New password", "Nueva contraseña"),
                      ("Saisis ce code pour choisir un nouveau mot de passe :", "Enter this code to choose a new password:",
                       "Introduce este código para elegir una nueva contraseña:"))),
    "magic_link": (subject("{{ .Token }} — ton code de connexion ROMKADE", "{{ .Token }} — your ROMKADE sign-in code", "{{ .Token }} — tu código de acceso ROMKADE"),
                   mail(("Ton code de connexion", "Your sign-in code", "Tu código de acceso"),
                        ("Saisis ce code pour te connecter à ROMKADE :", "Enter this code to sign in to ROMKADE:",
                         "Introduce este código para iniciar sesión en ROMKADE:"))),
    "reauthentication": (subject("{{ .Token }} — confirme ton identité", "{{ .Token }} — confirm it's you", "{{ .Token }} — confirma tu identidad"),
                         mail(("Confirme ton identité", "Confirm it's you", "Confirma tu identidad"),
                              ("Saisis ce code pour confirmer la modification de ton compte :", "Enter this code to confirm the change to your account:",
                               "Introduce este código para confirmar el cambio en tu cuenta:"))),
    "email_change": (subject("{{ .Token }} — confirme ta nouvelle adresse", "{{ .Token }} — confirm your new address", "{{ .Token }} — confirma tu nueva dirección"),
                     mail(("Nouvelle adresse e-mail", "New email address", "Nueva dirección de correo"),
                          ("Saisis ce code pour confirmer ta nouvelle adresse {{ .NewEmail }} :", "Enter this code to confirm your new address {{ .NewEmail }}:",
                           "Introduce este código para confirmar tu nueva dirección {{ .NewEmail }}:"))),
    "password_changed_notification": (subject("Ton mot de passe ROMKADE a été changé", "Your ROMKADE password was changed", "Tu contraseña ROMKADE ha cambiado"),
                                      mail(("Mot de passe changé", "Password changed", "Contraseña cambiada"),
                                           ("Le mot de passe de ton compte ROMKADE vient d'être changé.", "The password of your ROMKADE account was just changed.",
                                            "La contraseña de tu cuenta ROMKADE acaba de cambiar."), code=False,
                                           outro=("Si ce n'est pas toi, réinitialise ton mot de passe tout de suite.", "If this wasn't you, reset your password right away.",
                                                  "Si no has sido tú, restablece tu contraseña ahora mismo."))),
    "email_changed_notification": (subject("Ton adresse e-mail ROMKADE a été changée", "Your ROMKADE email address was changed", "Tu correo ROMKADE ha cambiado"),
                                   mail(("Adresse e-mail changée", "Email address changed", "Correo cambiado"),
                                        ("L'adresse e-mail de ton compte ROMKADE a été changée pour {{ .Email }}.", "The email address of your ROMKADE account was changed to {{ .Email }}.",
                                         "El correo de tu cuenta ROMKADE se ha cambiado a {{ .Email }}."), code=False)),
    "mfa_factor_enrolled_notification": (subject("Double authentification activée sur ROMKADE", "Two-factor authentication turned on for ROMKADE", "Verificación en dos pasos activada en ROMKADE"),
                                         mail(("Double authentification activée", "Two-factor authentication on", "Verificación en dos pasos activada"),
                                              ("Une méthode de vérification a été ajoutée à ton compte ROMKADE.", "A verification method was added to your ROMKADE account.",
                                               "Se ha añadido un método de verificación a tu cuenta ROMKADE."), code=False)),
    "mfa_factor_unenrolled_notification": (subject("Double authentification retirée de ROMKADE", "Two-factor authentication removed from ROMKADE", "Verificación en dos pasos eliminada de ROMKADE"),
                                           mail(("Méthode de vérification retirée", "Verification method removed", "Método de verificación eliminado"),
                                                ("Une méthode de vérification a été retirée de ton compte ROMKADE.", "A verification method was removed from your ROMKADE account.",
                                                 "Se ha eliminado un método de verificación de tu cuenta ROMKADE."), code=False,
                                                outro=("Si ce n'est pas toi, change ton mot de passe tout de suite.", "If this wasn't you, change your password right away.",
                                                       "Si no has sido tú, cambia tu contraseña ahora mismo."))),
}


def config(e: dict) -> dict:
    cfg = {
        "site_url": SITE,
        "uri_allow_list": f"{SITE}/**,{MCP}/**,http://127.0.0.1:8765/**,http://localhost:8765/**",
        "oauth_server_enabled": True,
        "oauth_server_allow_dynamic_registration": True,
        "oauth_server_authorization_path": "/authentification/",
        "smtp_host": "in-v3.mailjet.com", "smtp_port": "587",
        "smtp_user": e["MAILJET_API_KEY"], "smtp_pass": e["MAILJET_SECRET_KEY"],
        "smtp_admin_email": "noreply@romkade.com", "smtp_sender_name": "ROMKADE",
        "smtp_max_frequency": 30, "rate_limit_email_sent": 30,
        "mailer_otp_length": 6, "mailer_otp_exp": 600,
        "password_min_length": 10,
        "password_required_characters": "abcdefghijklmnopqrstuvwxyz:ABCDEFGHIJKLMNOPQRSTUVWXYZ:0123456789",
        "security_update_password_require_reauthentication": True,
        "mailer_notifications_password_changed_enabled": True,
        "mailer_notifications_email_changed_enabled": True,
        "mailer_notifications_mfa_factor_enrolled_enabled": True,
        "mailer_notifications_mfa_factor_unenrolled_enabled": True,
    }
    for name, (subj, body) in EMAILS.items():
        cfg[f"mailer_subjects_{name}"] = subj
        cfg[f"mailer_templates_{name}_content"] = body
    return cfg


def main() -> None:
    e = env()
    cfg = config(e)
    if "--dry-run" in sys.argv:
        print(json.dumps({k: ("***" if k in ("smtp_user", "smtp_pass") else v) for k, v in cfg.items()
                          if not k.startswith("mailer_templates")}, indent=1, ensure_ascii=False))
        return
    req = urllib.request.Request(f"https://api.supabase.com/v1/projects/{PROJECT}/config/auth", method="PATCH",
                                 data=json.dumps(cfg).encode(), headers={
                                     "Authorization": f"Bearer {e['SUPABASE_ACCESS_TOKEN']}",
                                     "Content-Type": "application/json"})
    try:  # Python de python.org sur macOS : pas de certificats système, ceux de certifi
        import certifi, ssl
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = None
    with urllib.request.urlopen(req, timeout=60, context=context) as r:
        out = json.load(r)
    ok = [k for k in cfg if k not in ("smtp_user", "smtp_pass") and out.get(k) != cfg[k] and str(out.get(k)) != str(cfg[k])]
    print("configuration appliquée" if not ok else f"différences : {ok}")


if __name__ == "__main__":
    main()
