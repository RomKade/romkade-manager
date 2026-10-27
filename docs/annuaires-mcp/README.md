# Annuaires MCP : registre officiel, Smithery, Glama, listes GitHub

Même serveur que pour Claude et ChatGPT : `https://mcp.romkade.com` (MCP distant, streamable HTTP, OAuth avec
inscription automatique des clients). Ces annuaires ne demandent ni ZIP ni revue humaine : ils lisent le serveur
lui-même (outils, icône) et une fiche courte.

## Où on en est

| Annuaire | Qui | État |
|---|---|---|
| Registre MCP officiel (`com.romkade/romkade`) : fiche `server.json` validée, preuve du domaine sur romkade.com | Claude | ✅ prêt, à publier |
| Smithery (smithery.ai) | vous (compte Smithery) | ⬜ |
| Glama (glama.ai) : repris du registre officiel, puis revendiqué | vous (compte Glama) + Claude (fichier de preuve) | ⬜ |
| awesome-remote-mcp-servers (GitHub) : proposition d'ajout | Claude, après votre accord | ⬜ |
| Le Chat (Mistral) | à étudier | ⬜ |

## Registre MCP officiel

Le catalogue de référence du protocole (registry.modelcontextprotocol.io) : d'autres annuaires (Glama, GitHub, VS Code)
s'en servent comme source.

- Fiche : `server.json` (nom `com.romkade/romkade`, description de 100 caractères au plus, icône, adresse du serveur).
  Vérifiée par `mcp-publisher validate`.
- Preuve du domaine (méthode HTTP, pas de DNS à toucher) : `https://romkade.com/.well-known/mcp-registry-auth`
  contient la clé publique (`v=MCPv1; k=ed25519; p=…`). Le fichier est dans le dépôt du site
  (`public/.well-known/`) ; le déploiement OVH envoie `.well-known/` sans effacer les fichiers de l'hébergement.
- Clé privée : `~/.config/romkade/mcp-registry-ed25519.pem` sur le Mac (hors dépôt, droits 600). Sans elle, plus de
  publication sous `com.romkade` : en garder une copie dans le trousseau ou un gestionnaire de mots de passe. Perdue,
  on en refait une et on remplace la clé publique sur le site.
- Publier (et republier à chaque nouvelle version : changer `version`) :

  ```sh
  cd docs/annuaires-mcp
  mcp-publisher login http --domain romkade.com --private-key "$(openssl pkey -in ~/.config/romkade/mcp-registry-ed25519.pem -outform DER | tail -c 32 | xxd -p -c 64)"
  mcp-publisher publish
  curl "https://registry.modelcontextprotocol.io/v0.1/servers?search=com.romkade/romkade"
  ```

## Smithery

1. Se connecter sur https://smithery.ai (compte GitHub `arnoweb`, ou l'organisation RomKade).
2. https://smithery.ai/new : adresse `https://mcp.romkade.com`.
3. Smithery analyse le serveur ; comme il demande OAuth, il propose de se connecter : `demo@romkade.com`, puis
   Autoriser. Il récupère alors les 13 outils.
4. Fiche : nom ROMKADE, description courte (voir plus bas), site https://romkade.com.
5. Puis **Settings → Verification** pour le badge d'éditeur officiel.

Le serveur répond bien 401 avec l'en-tête `WWW-Authenticate` (ce que Smithery attend pour détecter OAuth) et ne
bloque pas le robot `SmitheryBot`.

## Glama

Glama reprend les serveurs du registre officiel : après la publication, ROMKADE devrait y apparaître
(https://glama.ai/mcp/connectors, nom `com.romkade/romkade`). Sinon : **Add MCP Server → Connector**, adresse
`https://mcp.romkade.com`.

Revendiquer la fiche (pour la modifier) : sur la fiche, **Claim ownership** ; Glama donne un jeton `glama_claim_…`,
à placer dans `https://romkade.com/.well-known/glama.json` :

```json
{ "$schema": "https://glama.ai/mcp/schemas/connector.json", "claim": "glama_claim_…" }
```

(fichier `public/.well-known/glama.json` du site, envoyé par le déploiement).

## awesome-remote-mcp-servers

La liste `punkpeye/awesome-mcp-servers` ne prend que les serveurs à installer soi-même (dépôt public à lancer) ;
ROMKADE est un serveur distant : sa place est dans `jaw9c/awesome-remote-mcp-servers` (OAuth 2.0 exigé : c'est le
cas). Ligne à ajouter au tableau, catégorie « Other » (pas de catégorie jeux) :

```markdown
| ROMKADE | Other | `https://mcp.romkade.com` | OAuth2.1 | [ROMKADE](https://romkade.com) |
```

Exemple d'usage pour la proposition : « What's on my console? », « Launch Tobu Tobu Girl », « Cheat codes for Alter
Ego ».

## Textes

- Nom : ROMKADE
- Courte (100 caractères au plus) : Drive your retro handheld console: find your games, launch, save, set volume, get
  cheat codes.
- Longue : celle de l'annuaire ChatGPT (`../annuaire-chatgpt/paquet/plugin.json`, `longDescription`).
- Icône : https://mcp.romkade.com/icon.png (512 × 512)
- Catégorie : Entertainment / Gaming
