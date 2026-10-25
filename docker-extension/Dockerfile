# Extension Docker Desktop de ROMKADE Manager : une image sans programme, qui ne contient que la description
# de l'extension (metadata.json), les services à démarrer (docker-compose.yaml) et l'onglet ROMKADE (ui/).
# Construire et installer : ./build.sh (voir README.md).
FROM alpine:3.20

LABEL org.opencontainers.image.title="ROMKADE Manager" \
      org.opencontainers.image.description="Pilotez votre console rétro (Anbernic…) depuis l'ordinateur, et parlez-lui depuis ChatGPT ou Claude." \
      org.opencontainers.image.vendor="ROMKADE" \
      org.opencontainers.image.source="https://github.com/RomKade/romkade-manager" \
      com.docker.desktop.extension.api.version=">= 0.3.4" \
      com.docker.desktop.extension.icon="https://raw.githubusercontent.com/RomKade/romkade-manager/main/frontend/public/icon-192.png" \
      com.docker.extension.categories="utility-tools" \
      com.docker.extension.publisher-url="https://romkade.com" \
      com.docker.extension.additional-urls='[{"title":"Guide d'"'"'installation","url":"https://romkade.com/installation/"},{"title":"Code source","url":"https://github.com/RomKade/romkade-manager"}]' \
      com.docker.extension.detailed-description="ROMKADE Manager gère la bibliothèque de votre console rétro et la pilote par le réseau : lancer un jeu, sauvegarder, copier des jeux. Reliez ensuite la console à votre compte ROMKADE pour lui parler depuis ChatGPT ou Claude." \
      com.docker.extension.screenshots='[{"alt":"ROMKADE Manager","url":"https://romkade.com/og-image.jpg"}]' \
      com.docker.extension.changelog="Première version de l'extension."

COPY metadata.json docker-compose.yaml romkade.png /
COPY ui /ui
