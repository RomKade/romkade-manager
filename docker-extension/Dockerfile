# Extension Docker Desktop de ROMKADE Manager : une image sans programme, qui ne contient que la description
# de l'extension (metadata.json), les services à démarrer (docker-compose.yaml) et l'onglet ROMKADE (ui/).
# Construire et installer : ./build.sh (voir README.md).
FROM alpine:3.20

LABEL org.opencontainers.image.title="ROMKADE Manager" \
      org.opencontainers.image.description="Manage your retro handheld (Anbernic…) from your computer, and talk to it from ChatGPT or Claude." \
      org.opencontainers.image.vendor="ROMKADE" \
      org.opencontainers.image.source="https://github.com/RomKade/romkade-manager" \
      com.docker.desktop.extension.api.version=">= 0.3.4" \
      com.docker.desktop.extension.icon="https://raw.githubusercontent.com/RomKade/romkade-manager/main/frontend/public/icon-192.png" \
      com.docker.extension.categories="utility-tools" \
      com.docker.extension.publisher-url="https://romkade.com" \
      com.docker.extension.additional-urls='[{"title":"Installation guide","url":"https://github.com/RomKade/romkade-manager#install-with-docker-macos-windows-linux"},{"title":"Source code","url":"https://github.com/RomKade/romkade-manager"},{"title":"Website","url":"https://romkade.com"}]' \
      com.docker.extension.detailed-description="ROMKADE Manager organizes your retro handheld's library and controls it over Wi-Fi: launch a game, save, copy games. Then link the console to your ROMKADE account to talk to it from ChatGPT or Claude." \
      com.docker.extension.screenshots='[{"alt":"ROMKADE Manager","url":"https://romkade.com/og-image.jpg"}]' \
      com.docker.extension.changelog="First version of the extension."

COPY metadata.json docker-compose.yaml romkade.png /
COPY ui /ui
