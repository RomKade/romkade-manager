# Extension Docker Desktop

ROMKADE Manager s'installe depuis Docker Desktop, sans terminal : **Extensions > ROMKADE > Installer**.
Docker Desktop démarre alors les mêmes services que le [compose.yaml](../compose.yaml) de la racine (le Manager et
Typesense), et l'onglet **ROMKADE** ouvre le Manager dans le navigateur (`http://localhost:8765`).

| Fichier | Rôle |
|---|---|
| `metadata.json` | déclare l'onglet ROMKADE et les services à démarrer |
| `docker-compose.yaml` | les services, démarrés par Docker Desktop à l'installation et arrêtés à la désinstallation |
| `ui/index.html` | l'onglet : état du Manager, bouton d'ouverture, premières étapes |
| `Dockerfile` | l'image de l'extension (aucun programme, seulement ces fichiers) et ses étiquettes pour le Marketplace |

## Essayer en local

Docker Desktop > Settings > Extensions : cocher « Enable Docker Extensions ».

```sh
./build.sh                # construit et installe, Manager sur le port 8765
./build.sh --port 8766    # à côté d'un Manager déjà lancé sur 8765
docker extension rm romkade/romkade-manager-extension   # désinstalle
```

Les données (catalogue, réglages, secrets) vivent dans les volumes de l'extension, distincts de ceux d'une
installation par `docker compose`.

## Publier dans le Marketplace

`docker extension validate` liste ce qui manque : une version semver (`0.1.0`, pas `dev`) et une image
multi-architecture (`docker buildx build --platform=linux/amd64,linux/arm64 --push`) sur Docker Hub, puis la
demande de publication auprès de Docker.
