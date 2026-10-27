# Annuaire de ChatGPT : dossier de soumission

ROMKADE dans l'annuaire des plugins de ChatGPT (platform.openai.com/plugins). Même serveur que pour Claude
(`https://mcp.romkade.com`, OAuth Supabase avec inscription automatique des clients), mêmes captures, même compte de
démo. OpenAI demande un paquet ZIP : manifeste, configuration MCP, icônes, captures, cas de test.

## Où on en est

| Étape | Qui | État |
|---|---|---|
| Paquet `romkade-chatgpt.zip` (manifeste validé par les schémas officiels) | Claude | ✅ |
| Annotations des 13 outils complètes (`readOnlyHint`, `destructiveHint`, `openWorldHint` explicites) | Claude | ✅ déployé |
| Adresse de vérification du domaine (`/.well-known/openai-apps-challenge`) | Claude | ✅ dans le code, jeton à recevoir |
| Test dans ChatGPT avec le compte de démo (serveur personnalisé, OAuth) | Claude | ✅ 2026-10-27 : les 5 cas de test passent |
| CSP et domaine de l'interface pour ChatGPT (`openai/widgetCSP`, `openai/widgetDomain`) | Claude | ✅ déployé (« CSP désactivée » en mode développeur est normal) |
| Vidéo de démonstration (`https://romkade.com/video/romkade-in-chatgpt.mp4`) | Claude | ✅ |
| Vérification d'identité OpenAI (Individual) | vous | ✅ |
| Envoi du ZIP, domaine vérifié, serveur connecté (13 outils, aucun relevé), identifiants, soumission | vous | ✅ soumis le 2026-10-27, version 1.0.0 en revue |
| Publication après acceptation (bouton **Publish plugin**) | vous | ⬜ |

## Contenu

- `paquet/plugin.json` : fiche (nom, sous-titre, description, catégorie Entertainment, adresses du site, du support,
  de la confidentialité et des conditions), 5 cas de test positifs et 3 négatifs, lien de la vidéo, notes de version,
  traductions fr et es.
- `paquet/mcp.json` : le serveur `https://mcp.romkade.com`. L'authentification (OAuth, inscription automatique) est
  découverte par le portail, comme dans Claude.
- `paquet/assets/` : logo et icône (512 × 512), 5 captures de 1 440 px (celles de `../annuaire-claude/captures/`).
- `romkade-chatgpt.zip` : le paquet à envoyer, refait par `sh outils/paquet.sh` après toute modification de
  `paquet/`.

## Identifiants pour les relecteurs

À saisir dans **Review details** seulement (jamais dans le ZIP ni dans ce dépôt) :

- Login URL : `https://romkade.com/authentification/` (ChatGPT l'ouvre lui-même à la connexion du plugin)
- Email : `demo@romkade.com`
- Password : le mot de passe du compte de démo
- Sign-in instructions :

> Connect the ROMKADE plugin: ChatGPT opens the ROMKADE sign-in page on romkade.com. Sign in with the email and
> password above (not "Continue with Google"), then select "Allow". No two-factor authentication.
>
> The account has a demo console that is always online: a virtual console with 8 homebrew games that their authors
> distribute for free (4 Game Boy, 4 NES, no commercial games). No hardware is needed. The test cases use Tobu Tobu
> Girl and Alter Ego. Please keep the console name "ROMKADE Demo".
>
> ROMKADE hosts and distributes no games: it only receives the file names of the games already on the user's own
> console.

## Points d'attention

- « Importer une archive de plugin » installe le paquet dans **Codex**, pas dans ChatGPT, et sans connexion OAuth :
  ça valide le paquet (accepté le 2026-10-27), pas le serveur. Le test se fait avec un serveur personnalisé sur chatgpt.com.

- Une seule version en revue à la fois ; tout changement de la fiche demande un nouveau ZIP. Les changements des
  outils sur le serveur sont repris automatiquement par l'analyse quotidienne d'OpenAI.
- L'adresse du serveur ne peut plus changer après la soumission (sauf demande au support).
- Après acceptation, la publication n'est pas automatique : bouton **Publish plugin**.
