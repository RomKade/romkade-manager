# Connectors Directory de Claude : dossier de soumission

Connecteur **ROMKADE** (serveur MCP distant avec interface MCP Apps) : on pilote sa console rétro depuis Claude. Le
code est dans `cloud/server/romkade_cloud/` (outils : `tools.py`, interface : `ui/app.html`).

- Portail : [claude.ai/directory/manage](https://claude.ai/directory/manage) → **Submit new** → **MCP connector**
  (forfait payant : Pro, Max, Team ou Enterprise ; Max suffit, depuis son propre compte)
- Guides officiels : [Submit a connector](https://claude.com/docs/connectors/building/submission),
  [Pre-submission checklist](https://claude.com/docs/connectors/building/review-criteria)
- Suivi détaillé des exigences : `cloud/SOUMISSION-ANNUAIRES.md`

## Où on en est

| Étape | État |
|---|---|
| Serveur distant HTTPS, OAuth 2.1 (Supabase, inscription automatique des clients) | ✅ mcp.romkade.com, en production |
| Titres et annotations des 13 outils, erreurs en anglais | ✅ |
| Documentation, confidentialité (fr, en), support | ✅ romkade.com/docs/guide/assistants/, romkade.com/en/privacy/, contact@romkade.com |
| Compte de démo `demo@romkade.com` et sa console toujours en ligne | ✅ 8 homebrews gratuits, aucune jaquette ni marque d'un tiers |
| Captures (3 à 5 PNG, ≥ 1 000 px) | ✅ 5 captures de 1 440 px, `captures/` |
| Icône 512 × 512 | ✅ `icon-512.png` |
| Surveillance du serveur | ✅ toutes les 10 minutes (GitHub Actions, dépôt romkade-website) |
| Déploiement de la console de démo à 8 jeux | ✅ 2026-10-26 |
| Test du parcours des relecteurs dans Claude avec le compte de démo | ✅ 2026-10-26, les 13 outils ; console renommée « ROMKADE Demo » |
| Soumission dans le portail | ✅ 2026-10-26, **en cours d'examen** (suivi : claude.ai/directory/manage, e-mails à contact@romkade.com). Ne pas changer le mot de passe du compte de démo ni le nom de sa console pendant la revue. |

## Captures

5 PNG de 1 440 px de large (widget de 720 px en double densité), recadrées sur la réponse ROMKADE, sans la demande.
Le portail demande le texte de la demande à part, pour chacune :

| Fichier | Demande à saisir avec la capture |
|---|---|
| `captures/1-library.png` | What's on my console? |
| `captures/2-games.png` | Show my Game Boy games |
| `captures/3-game-details.png` | Tell me about Tobu Tobu Girl. Do I have a save? |
| `captures/4-now-playing.png` | Launch Tobu Tobu Girl and set the volume to 60 % |
| `captures/5-favorites.png` | My favorite games |

Elles sont faites avec les vrais outils et le vrai widget, en local, sans compte : `outils/captures.py` (mode
d'emploi en tête du fichier) monte un serveur ROMKADE Cloud jetable, y branche la console de démo, appelle les
outils et photographie le widget dans `outils/host.html`, une page qui joue le rôle de Claude (dialogue MCP Apps).
À relancer après un changement de l'interface : `THEME=light` pour le thème clair.

Les jeux de la console de démo n'ont pas de jaquette : la banque libretro n'en a pas pour ces homebrews, et celle
de Nova the Squirrel (retiré) portait le logo et le sceau de Nintendo. Les vignettes à initiales sont le vrai rendu
de ROMKADE sans jaquette. Les dessins de consoles de la bibliothèque viennent de retroarch-assets (CC BY 4.0).

## Fiche à coller dans le portail

En anglais (relecteurs, annuaire). Le mot de passe du compte de démo ne figure nulle part ici : il se saisit
seulement dans le portail.

### 1. Connection

- Server URL: `https://mcp.romkade.com`
- Users connect to: the same URL (no per-customer URL)

### 2. Tools

Synchronisés depuis le serveur : 13 outils, titres et annotations prêts (`readOnlyHint` pour les lectures,
`destructiveHint` pour `quit_game` et `save_state`). Rien à saisir ; vérifier qu'aucun avertissement n'apparaît.

### 3. Listing

**Server name**

> ROMKADE

**One-liner** (≤ 200)

> Drive your retro handheld console from Claude: find your games, launch them, save, set the volume and get cheat codes.

**Description** (≤ 2 000)

> ROMKADE connects Claude to your retro handheld console (Anbernic and other Linux handhelds running RetroArch).
>
> Ask in plain words and ROMKADE does it on your console:
> - Find games in your library by title, system or genre, with box art: "my Game Boy RPGs", "platformers on Mega Drive".
> - Open a game sheet: year, genre, developer, summary, and whether you have saves for it on the console.
> - Launch a game, resume from its automatic save state, save your progress, quit back to the menu.
> - Set or mute the game volume.
> - Get cheat codes for a game from the libretro cheat database.
> - See your favorites and an overview of your library per system and genre.
>
> Results appear in an interactive ROMKADE view inside Claude, with buttons to play, save, quit and set the volume.
>
> The library and cheat codes work even when the console is off. Playing, saving, quitting and the volume need the
> console on and connected to Wi-Fi: the ROMKADE app on the console talks to ROMKADE Cloud, so no computer needs
> to be on.
>
> ROMKADE provides no games and never helps find or download them: it only knows the games already on the user's
> own SD card, and only receives their file names, never the games themselves.
>
> Requires a free ROMKADE account and the ROMKADE app on the console (installed in one click from ROMKADE Manager,
> or paired with a 6-character code).

**Categories** (1 à 5, selon la liste du portail) : Entertainment / Gaming, Productivity (si pas de catégorie jeux).

**Documentation URL**: `https://romkade.com/docs/guide/assistants/`

**Privacy policy URL**: `https://romkade.com/en/privacy/`

**Support contact**: `contact@romkade.com`

**Icon**: `icon-512.png` (dans ce dossier, 512 × 512)

**URL slug** (définitif) : `romkade`

**Allowed link URIs**: `https://romkade.com`

### 4. Use cases

**Primary use cases**

> 1. Find a game in the user's console library and see its box art and details.
> 2. Launch a game on the console, save the progress and quit, from a conversation.
> 3. Get cheat codes for a game.
> 4. Set the console's game volume.

**What users need before connecting**

> A free ROMKADE account (created during the first connection) and a supported retro handheld with Wi-Fi and the
> ROMKADE app (installed from ROMKADE Manager, or paired with the 6-character code shown by the app).

**Reads / writes**: both (reads the library; launches, saves, quits and sets the volume on the console).

### 5. Company

- Company name: ROMKADE
- Website: `https://romkade.com`
- Primary contact: (vous)

### 6. Authentication

- Authentication requirement: **Required**
- Method: **OAuth 2.0** (authorization code + PKCE, dynamic client registration; authorization server: Supabase
  Auth, discovered through `https://mcp.romkade.com/.well-known/oauth-protected-resource`)
- No client ID or secret to give Anthropic (dynamic registration).

### 7. Data handling

- API ownership: **our own API** (ROMKADE Cloud).
- Personal health data: **no**. Sponsored content: **no**.

### 8. Test & launch

**Test account**: `demo@romkade.com` / mot de passe (à saisir dans le portail seulement). No two-factor
authentication.

**Instructions for reviewers**

> 1. Add the connector and sign in with the test account on the ROMKADE page, then select "Allow".
> 2. The account has a demo console that is always online (a virtual console with 8 homebrew games that their authors
>    distribute for free, no commercial games). No hardware is needed.
> 3. Try, in order:
>    - "Which consoles do I have?" (list_consoles)
>    - "Rename my console to ROMKADE Demo" (rename_console; please keep this name)
>    - "What's on my console?" (library_overview)
>    - "Find Tobu Tobu Girl" then "Tell me about it, do I have a save?" (search_games, game_details)
>    - "My favorite games" (favorite_games)
>    - "Launch Tobu Tobu Girl" (launch_game), then "What's playing?" (console_status)
>    - "Save my game" (save_state, asks for confirmation), "Set the volume to 60 %" (set_volume)
>    - "Quit the game" (quit_game, asks for confirmation)
>    - "Cheat codes for Alter Ego" (get_cheats): 4 codes from the libretro cheat database.
> 4. pair_console needs a 6-character code shown on a real console. With the demo account, "Pair my console with
>    code ABC123" returns an expected error: the account already has its one console (the demo console).

Confirmer : chaque outil appelé dans Claude comme connecteur personnalisé.

### 9. Compliance

Les 7 engagements (directory guidelines, first-party API usage, financial transactions, AI media generation, prompt
injection, conversation data collection, public documentation) : tous applicables et respectés. Données de
conversation : ROMKADE ne reçoit que les arguments des outils ; les statistiques d'usage (PostHog) n'en gardent
ni le contenu ni l'identifiant de conversation.
