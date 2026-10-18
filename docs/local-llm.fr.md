# Installer un LLM local et le connecter à ROMKADE Manager

<p align="center"><a href="local-llm.md">English</a> · <strong>Français</strong> · <a href="local-llm.es.md">Español</a></p>

ROMKADE Manager utilise une IA pour les **descriptions des jeux** et les **commandes des jeux** (quelle touche fait
quoi). Au lieu d'un service en ligne payant (Claude, ChatGPT, Mistral, Gemini), tu peux faire tourner un modèle **à
poids ouverts** sur ton ordinateur, Mac, Windows ou Linux :

- **gratuit** : aucune clé d'API, aucun coût à l'usage ;
- **privé** : rien ne quitte ton ordinateur (ou ton réseau) ;
- **hors ligne**, une fois le modèle téléchargé.

En contrepartie, c'est plus lent, et un petit modèle se trompe plus souvent qu'un grand modèle en ligne : vérifie les
commandes en jeu.

## De quoi as-tu besoin ?

| Taille du modèle | Mémoire conseillée | Pour |
|---|---|---|
| 3 à 4 milliards de paramètres (3B–4B) | 8 Go | essayer ; réponses approximatives |
| 7 à 8 milliards (7B–8B) | 16 Go | bon compromis |
| 12 à 14 milliards (12B–14B) | 16 à 32 Go | meilleurs résultats en local |

Un Mac Apple Silicon ou un PC avec une carte graphique récente répond en quelques secondes ; sans carte graphique,
compte plutôt une minute par réponse.

Choisis un modèle qui parle bien **français et espagnol** (les textes sont rédigés en trois langues), par exemple
`qwen2.5:7b`, `mistral-nemo` (12B) ou `llama3.1:8b`.

## Option A : Ollama (le plus simple)

1. Télécharge et installe Ollama : <https://ollama.com/download> (macOS, Windows, Linux). Sous Linux :
   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   ```
2. Télécharge un modèle, dans un terminal :
   ```bash
   ollama pull qwen2.5:7b
   ```
3. Vérifie qu'il est là :
   ```bash
   ollama list
   ```

Ollama démarre son serveur tout seul, à l'adresse `http://localhost:11434/v1`.

## Option B : LM Studio (avec une interface)

1. Télécharge et installe LM Studio : <https://lmstudio.ai/>.
2. Onglet **Discover** : cherche et télécharge un modèle (par exemple Qwen2.5 7B Instruct).
3. Onglet **Developer** : charge le modèle et clique sur **Start Server**.

Le serveur répond à l'adresse `http://localhost:1234/v1`.

## Connecter le modèle dans ROMKADE Manager

1. Ouvre **Paramètres > IA**.
2. Choisis **Ollama, LM Studio, autre…**.
3. Clique sur l'adresse : **Ollama** ou **LM Studio** (ou **Ollama (Docker)**, voir plus bas).
4. Clique sur le modèle dans la liste.

La connexion est vérifiée toute seule : le voyant passe au **vert** (« Connectée »). Le premier essai peut prendre
une minute, le temps de charger le modèle en mémoire.

Les descriptions partent ensuite **jeu par jeu**, en arrière-plan (Paramètres > Descriptions) ; les commandes se
demandent depuis la fiche d'un jeu.

## ROMKADE Manager dans Docker

Dans un conteneur, `localhost` désigne le conteneur lui-même, pas ton ordinateur. Utilise l'adresse
**Ollama (Docker)** : `http://host.docker.internal:11434/v1`.

- macOS et Windows (Docker Desktop) : rien d'autre à faire.
- Linux : le `compose.yaml` fourni déclare `host.docker.internal`. Ollama n'écoute par défaut que sur la machine
  elle-même : fais-le écouter aussi pour les conteneurs, puis redémarre-le :
  ```bash
  sudo systemctl edit ollama      # ajoute :  [Service]  Environment="OLLAMA_HOST=0.0.0.0:11434"
  sudo systemctl restart ollama
  ```

## Un modèle sur un autre ordinateur du réseau

Tu peux faire tourner le modèle sur une machine plus puissante de la maison. Sur cette machine, fais écouter Ollama
sur le réseau (`OLLAMA_HOST=0.0.0.0:11434`), puis dans ROMKADE Manager saisis son adresse, par exemple
`http://192.168.1.20:11434/v1`, et clique sur **Utiliser cette adresse**.

Ollama n'a pas de mot de passe : ne l'ouvre que sur un réseau de confiance, jamais sur Internet.

## Autres services compatibles OpenAI

Toute API qui parle le protocole d'OpenAI (`/v1/chat/completions`) fonctionne : saisis son adresse (en général
terminée par `/v1`) et, s'il en demande une, sa clé d'API dans « Le service demande une clé d'API ? ». Par exemple
OpenRouter (`https://openrouter.ai/api/v1`) ou Groq (`https://api.groq.com/openai/v1`). Ces services sont en ligne et
facturés selon leurs propres conditions.

## En cas de problème

| Voyant rouge, message | Solution |
|---|---|
| « Aucun service ne répond sur … » | Ollama ou LM Studio n'est pas lancé, ou le serveur n'est pas démarré (LM Studio : Start Server). Vérifie l'adresse et le port. |
| Idem, avec ROMKADE dans Docker | Utilise `http://host.docker.internal:11434/v1` ; sous Linux, voir plus haut. |
| « Aucun modèle trouvé » | Télécharge un modèle (`ollama pull …`), puis recharge la liste. |
| « Le modèle répond, mais pas dans le format attendu » | Le modèle est trop petit pour suivre la consigne : prends un 7B ou plus. |
| Réponses très lentes | Normal au premier appel (chargement) ; sinon prends un modèle plus petit. |

Si le modèle ne répond plus pendant les descriptions, la génération s'arrête après 5 échecs d'affilée ; relance-la
quand il est de nouveau disponible : les jeux déjà décrits sont gardés.
