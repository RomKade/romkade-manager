#!/usr/bin/env python3
"""Annonce de chaque nouvel utilisateur ROMKADE sur Discord. © 2026 ROMKADE.

Un déclencheur sur auth.users (Supabase) poste un message dans un salon Discord quand un compte est confirmé :
code e-mail validé, ou première connexion avec Google (compte confirmé dès sa création). Les comptes jamais
confirmés (robots, fautes de frappe) ne sont pas annoncés. Le message donne le numéro du compte, le moyen
d'inscription et la langue, jamais l'adresse e-mail (le salon peut être vu par la communauté).

L'appel part de la base elle-même (extension pg_net, asynchrone) : il marche quelle que soit la page d'inscription
(Manager, romkade.com, ChatGPT, Claude) et une panne de Discord ne bloque jamais une inscription. L'adresse du
webhook est rangée dans le coffre de Supabase (Vault), jamais dans le code.

Rejouable. Lit cloud/deploy/.env : SUPABASE_ACCESS_TOKEN et DISCORD_SIGNUPS_WEBHOOK (Modifier le salon →
Intégrations → Webhooks → Copier l'URL du webhook) ; n'affiche jamais un secret.

    python3 cloud/deploy/supabase_signups.py           # installe ou met à jour
    python3 cloud/deploy/supabase_signups.py --test    # poste un message d'essai par le même chemin
    python3 cloud/deploy/supabase_signups.py --remove  # retire le déclencheur et l'adresse du webhook
"""

import json
import sys
import urllib.error
import urllib.request

from supabase_setup import PROJECT, env

SECRET = "discord_signups_webhook"
COLOR = 0x11D9F5  # cyan de la charte

FUNCTION = f"""
create extension if not exists pg_net;

create schema if not exists romkade;
revoke all on schema romkade from public, anon, authenticated;

create or replace function romkade.notify_signup() returns trigger
language plpgsql security definer set search_path = pg_catalog, public as $$
declare
  hook text;
  n bigint;
  via text;
  lang text;
begin
  if new.email_confirmed_at is null or coalesce(new.is_anonymous, false) then return new; end if;
  if tg_op = 'UPDATE' and old.email_confirmed_at is not null then return new; end if;
  select decrypted_secret into hook from vault.decrypted_secrets where name = '{SECRET}' limit 1;
  if hook is null then return new; end if;
  select count(*) into n from auth.users where email_confirmed_at is not null;
  via := case coalesce(new.raw_app_meta_data->>'provider', 'email')
           when 'email' then 'e-mail' when 'google' then 'Google'
           else new.raw_app_meta_data->>'provider' end;
  lang := coalesce(nullif(new.raw_user_meta_data->>'locale', ''), '?');
  perform net.http_post(
    url := hook,
    headers := '{{"Content-Type": "application/json"}}'::jsonb,
    body := jsonb_build_object(
      'username', 'ROMKADE',
      'allowed_mentions', jsonb_build_object('parse', jsonb_build_array()),
      'embeds', jsonb_build_array(jsonb_build_object(
        'title', '🎉 Nouvel utilisateur',
        'description', format('Compte n° **%s** · inscrit avec %s · langue %s', n, via, lang),
        'color', {COLOR},
        'timestamp', to_char(now() at time zone 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')))));
  return new;
exception when others then
  return new;  -- jamais une inscription bloquée par la notification
end $$;

revoke all on function romkade.notify_signup() from public, anon, authenticated;

drop trigger if exists romkade_notify_signup on auth.users;
create trigger romkade_notify_signup
  after insert or update of email_confirmed_at on auth.users
  for each row execute function romkade.notify_signup();
"""

TEST = f"""
select net.http_post(
  url := (select decrypted_secret from vault.decrypted_secrets where name = '{SECRET}' limit 1),
  headers := '{{"Content-Type": "application/json"}}'::jsonb,
  body := jsonb_build_object('username', 'ROMKADE', 'embeds', jsonb_build_array(jsonb_build_object(
    'title', '🔧 Essai', 'description',
    format('Les nouveaux utilisateurs seront annoncés ici (%s comptes confirmés aujourd''hui).',
           (select count(*) from auth.users where email_confirmed_at is not null)),
    'color', {COLOR})))) as request_id;
"""

REMOVE = f"""
drop trigger if exists romkade_notify_signup on auth.users;
drop function if exists romkade.notify_signup();
delete from vault.secrets where name = '{SECRET}';
"""


def literal(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def query(token: str, sql: str) -> list:
    req = urllib.request.Request(f"https://api.supabase.com/v1/projects/{PROJECT}/database/query", method="POST",
                                 data=json.dumps({"query": sql}).encode(), headers={
                                     "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:  # Python de python.org sur macOS : pas de certificats système, ceux de certifi
        import certifi, ssl
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = None
    try:
        with urllib.request.urlopen(req, timeout=60, context=context) as r:
            return json.load(r)
    except urllib.error.HTTPError as err:
        sys.exit(f"Supabase a refusé la requête ({err.code}) : {err.read().decode()[:500]}")


def main() -> None:
    e = env()
    token = e["SUPABASE_ACCESS_TOKEN"]
    if "--remove" in sys.argv:
        query(token, REMOVE)
        print("déclencheur et webhook retirés")
        return
    if "--test" in sys.argv:
        print("message d'essai envoyé", query(token, TEST))
        return
    hook = e.get("DISCORD_SIGNUPS_WEBHOOK", "")
    if not hook.startswith("https://discord.com/api/webhooks/"):
        sys.exit("DISCORD_SIGNUPS_WEBHOOK manquant ou invalide dans cloud/deploy/.env")
    query(token, f"""
delete from vault.secrets where name = '{SECRET}';
select vault.create_secret({literal(hook)}, '{SECRET}', 'Webhook Discord : nouveaux utilisateurs ROMKADE');
""")
    query(token, FUNCTION)
    print("annonce des nouveaux utilisateurs installée")


if __name__ == "__main__":
    main()
