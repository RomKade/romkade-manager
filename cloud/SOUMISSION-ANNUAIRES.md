# Soumission de ROMKADE aux annuaires Claude et ChatGPT

But : que n'importe qui trouve ROMKADE dans l'annuaire des connecteurs de Claude et dans l'annuaire des apps de
ChatGPT, et le connecte en un clic, sans copier d'adresse. Un seul serveur sert les deux : `https://mcp.romkade.com`
(MCP distant, OAuth Supabase, interface MCP Apps).

Dossier de soumission à Claude (fiche, captures, icône) : `docs/annuaire-claude/`.

État au 2026-10-24. ✅ fait · ⚠️ à reprendre · ❌ manque.

## 1. Bloquant pour les deux annuaires

| | Point | État | À faire |
|---|---|---|---|
| ✅ | **Compte de démonstration pour les relecteurs** | Compte demo@romkade.com (alias de contact@romkade.com, sans double authentification) et sa console de démo toujours en ligne (`demo_console.py`, service `romkade-demo`, homebrews gratuits). | Mot de passe à saisir seulement dans le portail. |
| ✅ | **Adresse à jeton** (`/<jeton>`) | Coupée dès qu'OAuth est configuré (`ROMKADE_TOKEN_URLS=1` pour la rouvrir) ; README à jour. | Déployer. Le connecteur ChatGPT encore sur l'adresse à jeton doit passer en OAuth (`https://mcp.romkade.com`). |
| ⚠️ | **Fiabilité du serveur** | Disque libéré (système 28 %, volume Docker 68 % le 2026-10-24) ; `/healthz` répond en 0,25 s. | Ajouter une surveillance de `/healthz` (alerte si le serveur tombe pendant la revue). |
| ⚠️ | **Anglais** | Serveur ✅ : titres des outils et erreurs en anglais, avec un code que l'interface traduit (fr, es). Site en français seulement. | Versions anglaises des pages confidentialité, conditions et support. |
| ⚠️ | **Politique de confidentialité** | Complétée (favoris, sauvegardes, statistiques du serveur MCP), non publiée. La page porte encore l'encadré « Version de travail… ne constitue pas une politique juridique définitive ». | Relire et valider, retirer l'encadré, publier. Version anglaise (relecteurs). |
| ⚠️ | **Page support et documentation** | Page de la documentation « ROMKADE in Claude and ChatGPT » (en, fr, es) : connexion, appairage, exemples, retrait de l'accès, suppression du compte, données, aide et contact. Non publiée. Adresse une fois publiée : `https://romkade.com/docs/guide/assistants/`. | Publier. La doc dit encore « no account, no analytics, no data sent to ROMKADE » (`index.md`, `administration/data-and-privacy.md`) : à mettre à jour avec la sortie des comptes et du cloud, sinon contradiction avec le connecteur. |
| ⚠️ | **Sujet ROMs et émulation** | Les instructions interdisent déjà d'aider à trouver ou télécharger des ROMs ; seuls les jeux de la console de l'utilisateur sont connus. | Le dire clairement dans la description de l'annuaire et dans les notes aux relecteurs : ROMKADE pilote la console de l'utilisateur et ses propres sauvegardes de jeux, n'héberge ni ne distribue aucun jeu. C'est le point le plus délicat face à la règle sur la propriété intellectuelle. Pour la démo, préférer des homebrews libres à des jeux commerciaux. |

## 2. Déjà en place ✅

- MCP distant en HTTPS public (`mcp.romkade.com`, Let's Encrypt), joignable sans VPN.
- OAuth 2.1 avec inscription automatique des clients (DCR) et PKCE : `/.well-known/oauth-protected-resource`, en-tête
  `WWW-Authenticate` sur 401, jetons ES256 vérifiés par JWKS, page de connexion et consentement sur
  `romkade.com/authentification/`.
- Annotations de tous les outils (`READ`, `ACT`, `SETTING`, `quit_game` marqué destructif), un titre par outil,
  descriptions en anglais.
- Interface MCP Apps (`ui://romkade/app.html`) avec CSP déclarée (`resource_domains`, `connect_domains`).
- Nom, titre, icône 512×512, `website_url`, instructions du serveur.
- Pas de collecte du contenu des conversations, ni de leur identifiant (PostHog) ; suppression du compte depuis le
  Manager (`DELETE /api/me`).
- `save_state` et `quit_game` marqués destructifs ; descriptions des outils sans consigne au modèle.
- Limitation des essais du code d'appairage (10 par heure).
- Conditions d'utilisation, mentions légales.

## 3. Claude : Connectors Directory

- **Droit de soumettre** ✅ : forfait payant (Pro, Max, Team ou Enterprise). Sur Pro et Max, on soumet depuis son
  propre compte, sans rôle à vérifier : le forfait Max suffit. La fiche appartient à l'organisation (le compte) qui
  soumet : soumettre depuis le compte qui doit la garder.
- Où : portail développeur [claude.ai/directory/manage](https://claude.ai/directory/manage) → **Submit new** →
  **MCP connector**. Pas de frais indiqués.
- Après l'envoi : analyse automatique de conformité, puis publication par défaut avec l'étiquette **Community**.
  Anthropic peut passer la fiche en revue **Verified** : un relecteur teste alors chaque outil avec le compte de démo.
  Suivi dans le portail ; recours : `mcp-review@anthropic.com`.
- Étapes du portail : connexion (URL `https://mcp.romkade.com`), outils (synchronisés depuis le serveur, titres et
  annotations vérifiés), fiche (nom ≤ 100 caractères, accroche ≤ 200, description ≤ 2 000, 1 à 5 catégories,
  documentation, confidentialité, support, icône, slug définitif), cas d'usage, société, authentification (OAuth
  obligatoire à la demande du serveur), données (API à nous), test et lancement (compte de démo, instructions,
  confirmation d'avoir appelé chaque outil), 7 engagements de conformité (dont la collecte de données des
  conversations : PostHog garde l'identifiant de conversation, à déclarer), relecture.
- **Captures pour une MCP App** : 3 à 5 PNG d'au moins 1 000 px de large, recadrées sur la réponse de l'app (sans
  la demande), avec le texte de la demande fourni à part ; pas de vidéo ni de GIF. Modèle Figma d'Anthropic
  (« MCP Apps for Claude »).
- Liens externes ouverts par l'interface (`ui/open-link`) : déclarer `https://romkade.com` (seulement des domaines à
  nous ; les liens libretro ou YouTube demanderont une confirmation).
- Tester avant : ajouter le serveur comme connecteur personnalisé et appeler chaque outil depuis claude.ai (web),
  l'app de bureau et mobile ; vérifier que la redirection `https://claude.ai/api/mcp/auth_callback` passe dans
  Supabase (DCR).

## 4. ChatGPT : app directory (Apps SDK)

- Comment : OpenAI Developer Platform → soumission de l'app, suivi de la revue au même endroit. Une seule version en
  revue à la fois.
- Avant : vérification de l'identité ou de l'organisation du développeur sur la plateforme OpenAI ; l'app testée en
  Developer Mode (déjà fait avec l'ancienne adresse à jeton, **à refaire en OAuth**).
- Dossier : adresse MCP, instructions de test (compte de démo), infos de l'annuaire, pays de disponibilité.
- Règles : usage policies d'OpenAI, contenu convenant à un public général (ados compris), politique de confidentialité
  et contact support, pas de publicité, propriété intellectuelle à soi ou autorisée, une fonction que ChatGPT ne sait
  pas faire seul (piloter une console : oui).
- Interface : vérifier le rendu dans ChatGPT (thème clair ou sombre, mobile), la CSP et le domaine du widget.

## 5. Ordre proposé

1. Libérer le disque de la droplet.
2. Console simulée et compte de démo.
3. Couper l'adresse à jeton ; titres et erreurs en anglais.
4. Site : page support, compléments de la confidentialité, versions anglaises (confidentialité, conditions, support).
5. Tests de bout en bout en OAuth : Claude (web, bureau, mobile) et ChatGPT (Developer Mode).
6. Captures d'écran et textes de l'annuaire (en, fr).
7. Soumission ChatGPT, puis Claude (ou les deux en parallèle).

## Sources

- [Claude : Submit a connector to the directory](https://claude.com/docs/connectors/building/submission)
- [Claude : Publish to the directory (qui peut soumettre)](https://claude.com/docs/directory/publish)
- [OpenAI Apps SDK : submission](https://developers.openai.com/apps-sdk/deploy/submission)
- [OpenAI Apps SDK : app submission guidelines](https://developers.openai.com/apps-sdk/app-submission-guidelines)
