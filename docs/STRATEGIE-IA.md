# Stratégie IA : contenu des jeux et assistant

Proposition (18/10/2026), à valider avant développement. L'IA est celle réglée dans Paramètres > IA (Claude,
ChatGPT, Mistral, Gemini ou un modèle local) : un seul réglage pour tout.

## 1. Paramètres : « Descriptions » devient « Contenu IA »

L'onglet ne fait plus seulement des descriptions : il enrichit la fiche de chaque jeu. Nouveau nom :
**Contenu IA** (en : *AI content*, es : *Contenido IA*).

Une section par type de contenu, toutes bâties pareil :

| Élément | Rôle |
|---|---|
| Couverture | « 812 / 4 838 jeux ont ce contenu » |
| **Tout générer** | Lot pour les jeux qui n'ont pas encore ce contenu, coût estimé affiché avant de lancer (lot à moitié prix avec Claude, gratuit avec un modèle local, mais long) |
| **Un jeu** | Champ de recherche → choisir un jeu → générer → le résultat s'affiche sur place. C'est aussi **le test** : on vérifie la qualité sur un jeu connu avant de payer le lot |
| Régénérer / effacer | Pour un jeu ou pour tout le type |

Règles communes : contenu rangé par jeu (toutes les éditions d'un même jeu le partagent), marqué « par IA, à
vérifier », corrigeable à la main sur la fiche, jamais écrasé s'il a été corrigé à la main.

### Types de contenu

1. **Descriptions** (existe) : présentation du jeu en fr / en / es.
2. **Commandes** (existe, par jeu seulement) : quelle touche de la console fait quoi. À ajouter : *Tout générer*.
3. **Astuces et codes** (nouveau) :
   - **Astuces** par l'IA : stratégies, secrets connus, conseils pour débuter. Marquées « à vérifier ».
   - **Codes de triche : pas par l'IA.** Un modèle invente facilement des codes Game Genie ou Action Replay qui
     n'existent pas (codes faux, voire qui plantent le jeu). Source fiable : la base de codes de RetroArch
     (`libretro-database/cht`, des milliers de jeux), rapprochée par nom de fichier comme les jaquettes. Game
     Manager affiche les codes sur la fiche et peut copier le fichier `.cht` sur la console : on les active ensuite
     dans le menu de RetroArch (Menu > Codes de triche). L'IA peut seulement *expliquer* un code de la base.
4. **Idées de contenus en plus** (par ordre d'intérêt) :
   - **Pour bien démarrer** : le but du jeu et les trois premières choses à savoir (5 lignes) ;
   - **Jeux similaires dans ta bibliothèque** : l'IA choisit parmi *tes* jeux (liste fournie), donc rien
     d'inventé, et c'est cliquable ;
   - **Nombre de joueurs et modes** (seul, à deux en même temps, à tour de rôle) : utile avec les manettes ;
   - **Durée de vie approximative** (« environ 3 h pour finir ») ;
   - **Meilleure version dans ta collection** quand tu as plusieurs éditions (région, révision, traduction).

## 2. Assistant de jeu (chatbot)

### Où et quand

- Bulle en bas à droite sur **toutes les pages** : assistant **multi-jeu**, périmètre « Bibliothèque » par défaut
  (trouver un jeu parmi les siens, comparer, se servir de l'application).
- Fiche d'un jeu ouverte ou jeu en cours : c'est détecté, et l'assistant **propose** de passer au périmètre « Un
  jeu » (« Discuter de *Super Mario World* ? »). Une conversation par périmètre.
- Détails techniques (aiguillage, contexte, flux, modèles en ligne ou locaux) : dossier technique publié à part.
- Suggestions en un clic : « Comment sauvegarder ? », « Quelles touches ? », « Je suis bloqué… », « Une astuce ? ».
- Mention permanente : « IA, peut se tromper » et le fournisseur utilisé (« modèle local : rien ne quitte cet
  ordinateur »).

### Ce qu'il sait (contexte fourni à chaque question)

La fiche du jeu, rien d'autre : titre, console, année, éditeur, description, commandes, astuces, codes de la base,
touches spéciales du firmware (sauvegarder, quitter, menu RetroArch), sauvegardes de ce jeu sur la console. Il
répond d'abord avec ce contexte, puis avec ses connaissances sur **ce** jeu.

### Comment le cantonner au jeu (plusieurs barrières)

1. **Mission étroite** dans les instructions du modèle : aider à jouer à *ce* jeu sur *cette* console (commandes,
   objectifs, passages difficiles, secrets, sauvegardes, réglages de RetroArch). Tout le reste est hors sujet.
2. **Réponse structurée** : le modèle répond `{"dans_le_sujet": true|false, "reponse": "…"}`. Si
   `dans_le_sujet` est faux, l'interface affiche **son propre** message (« Je ne réponds qu'aux questions sur
   *Nom du jeu* ») et jette le texte du modèle. Une tentative de détournement (« oublie tes instructions… ») ne
   peut donc pas faire afficher autre chose.
3. **Interdits explicites**, alignés sur l'avertissement de l'application (« ROMKADE Manager ne fournit aucun
   jeu ») : jamais d'aide pour trouver des ROM, des BIOS ou des sites de téléchargement, ni pour contourner une
   protection. Refus poli, même si la question parle du jeu.
4. **Garde-fous techniques** : question de 500 caractères au plus, 6 derniers messages seulement envoyés au modèle,
   20 questions par conversation, pas d'accès web ni d'outils, une question à la fois.
5. **Spoilers maîtrisés** : pour « je suis bloqué », d'abord un **indice**, puis un bouton « Donne-moi la
   solution ».
6. **Honnêteté** : s'il ne connaît pas bien le jeu, il le dit au lieu d'inventer (même règle que les
   descriptions et les commandes).

### Confidentialité et coût

- Les questions partent chez le fournisseur réglé ; avec un modèle local, rien ne sort de l'ordinateur.
- Conversations gardées dans le navigateur le temps de la session, pas sur le serveur.
- Coût : une question ≈ une fraction de centime avec un service en ligne ; gratuit en local.

### API

`POST /api/games/{id}/assistant` `{messages: [...]}` → `{in_scope, answer}`. Le serveur construit le contexte
(fiche, commandes, astuces, profil du firmware) ; le navigateur n'envoie que la conversation.

## 3. Connaissances (RAG), récupérées sans IA

Ni fine-tuning ni LoRA : aucun modèle ouvert spécialisé dans les jeux rétro n'existe (vérifié sur Hugging Face le
18/10/2026), et un adaptateur serait lié à un seul modèle. La connaissance vit dans la base de ROMKADE et n'importe
quel modèle, en ligne ou local, la lit au moment de répondre.

1. **Wikidata** identifie le jeu : élément « jeu vidéo » (Q7889) dont une plateforme (P400) correspond à la console,
   titre comparé au titre normalisé. Il donne les pages Wikipédia (en, fr, es) et l'identifiant StrategyWiki (P9075).
2. **Texte brut par l'API MediaWiki** (extensions TextExtracts) : Wikipédia (en + langue de l'interface) et
   StrategyWiki (page principale et sous-pages de soluce). Pas de scraping HTML ; identifiant ROMKADE dans chaque
   requête et une requête à la fois, comme le demande Wikimedia.
3. **Passages** de 300 à 500 mots, par section, rangés en base (`knowledge_chunk`) avec la source, l'adresse et la
   licence (CC BY-SA 4.0 pour les deux sites, à citer à chaque réponse qui s'en sert).
4. **Typesense** : collection `knowledge`, recherche par mots-clés limitée aux passages du jeu (phase 1) ; recherche
   par le sens plus tard si l'évaluation le justifie.
5. **Mise à jour** : rangement par jeu (console + titre normalisé), donc une nouvelle ROM d'un jeu connu en profite
   sans rien récupérer ; après une synchronisation avec de vrais nouveaux jeux, proposition de récupérer leurs
   connaissances (ou récupération automatique) ; réindexation de Typesense à la fin.

Écartés : GameFAQs, IGN, Fandom (contenus protégés, récupération interdite par leurs conditions), notices scannées.

## 4. Ordre de réalisation

1. **Connaissances** : récupération (Wikidata, Wikipédia, StrategyWiki), passages en base, index Typesense, pour un
   jeu ou tous, proposée après synchronisation ; onglet **Contenu IA** (renommage de « Descriptions »).
2. **Codes de triche** depuis la base de RetroArch (sans IA), affichage et copie du `.cht` sur la console.
3. **Astuces** par l'IA (même modèle de stockage que les commandes).
4. **Assistant** multi-jeu (bibliothèque, ou un jeu détecté), RAG sur les connaissances, modèle en ligne ou local.
5. Contenus en plus : *Pour bien démarrer*, *Jeux similaires dans ta bibliothèque*, *Nombre de joueurs*.
