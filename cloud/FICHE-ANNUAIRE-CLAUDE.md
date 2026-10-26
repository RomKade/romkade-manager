# Fiche ROMKADE pour le Connectors Directory de Claude

Textes à coller dans le portail [claude.ai/directory/manage](https://claude.ai/directory/manage) → **Submit new** →
**MCP connector**. En anglais (relecteurs, annuaire). Le mot de passe du compte de démo ne figure pas ici : il se
saisit seulement dans le portail.

## 1. Connection

- Server URL: `https://mcp.romkade.com`
- Users connect to: the same URL (no per-customer URL)

## 2. Tools

Synchronisés depuis le serveur : 13 outils, titres et annotations prêts (`readOnlyHint` pour les lectures,
`destructiveHint` pour `quit_game` et `save_state`). Rien à saisir ; vérifier qu'aucun avertissement n'apparaît.

## 3. Listing

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

**Icon**: `cloud/server/romkade_cloud/static/icon.png` (512 × 512)

**URL slug** (définitif) : `romkade`

**Allowed link URIs**: `https://romkade.com`

## 4. Use cases

**Primary use cases**

> 1. Find a game in the user's console library and see its box art and details.
> 2. Launch a game on the console, save the progress and quit, from a conversation.
> 3. Get cheat codes for a game.
> 4. Set the console's game volume.

**What users need before connecting**

> A free ROMKADE account (created during the first connection) and a supported retro handheld with Wi-Fi and the
> ROMKADE app (installed from ROMKADE Manager, or paired with the 6-character code shown by the app).

**Reads / writes**: both (reads the library; launches, saves, quits and sets the volume on the console).

## 5. Company

- Company name: ROMKADE
- Website: `https://romkade.com`
- Primary contact: (vous)

## 6. Authentication

- Authentication requirement: **Required**
- Method: **OAuth 2.0** (authorization code + PKCE, dynamic client registration; authorization server: Supabase
  Auth, discovered through `https://mcp.romkade.com/.well-known/oauth-protected-resource`)
- No client ID or secret to give Anthropic (dynamic registration).

## 7. Data handling

- API ownership: **our own API** (ROMKADE Cloud).
- Personal health data: **no**. Sponsored content: **no**.

## 8. Test & launch

**Test account**: `demo@romkade.com` / mot de passe (à saisir dans le portail seulement). No two-factor
authentication.

**Instructions for reviewers**

> 1. Add the connector and sign in with the test account on the ROMKADE page, then select "Allow".
> 2. The account has a demo console that is always online (a virtual console with homebrew games only, no
>    commercial releases of big publishers). No hardware is needed.
> 3. Try, in order:
>    - "What's on my console?" (library_overview)
>    - "Find Tobu Tobu Girl" then "Tell me about it, do I have a save?" (search_games, game_details)
>    - "My favorite games" (favorite_games)
>    - "Launch Tobu Tobu Girl" (launch_game), then "What's playing?" (console_status)
>    - "Save my game" (save_state, asks for confirmation), "Set the volume to 30 %" (set_volume)
>    - "Quit the game" (quit_game, asks for confirmation)
>    - "Cheat codes for Alter Ego" (get_cheats) may return no code: homebrew games are rarely in the
>      libretro cheat database, that is expected.
> 4. pair_console needs a 6-character code shown on a real console; with the demo account, "Pair my console with
>    code ABC123" returns the expected "Unknown or expired code" error.

Confirmer : chaque outil appelé dans Claude comme connecteur personnalisé.

## 9. Compliance

Les 7 engagements (directory guidelines, first-party API usage, financial transactions, AI media generation, prompt
injection, conversation data collection, public documentation) : tous applicables et respectés. Données de
conversation : ROMKADE ne reçoit que les arguments des outils ; les statistiques d'usage (PostHog) n'en gardent
ni le contenu ni l'identifiant de conversation.

## Captures (MCP App)

3 à 5 PNG, au moins 1 000 px de large, recadrées sur la réponse ROMKADE (sans la demande), texte de la demande
fourni à part :

| # | Demande (à fournir à part) | Vue |
|---|---|---|
| 1 | What's on my console? | Bibliothèque par console et genre |
| 2 | Find Tobu Tobu Girl | Grille de jaquettes |
| 3 | Tell me about Tobu Tobu Girl | Fiche du jeu avec sauvegardes |
| 4 | Launch Tobu Tobu Girl | « Now playing » avec volume, sauvegarder, quitter |
| 5 | Cheat codes for infinite lives in Alter Ego | Codes de triche (ou un jeu qui en a) |
