# Docker Desktop extension

ROMKADE Manager installs from Docker Desktop, without a terminal: **Extensions > ROMKADE > Install**.
Docker Desktop then starts the same services as the root [compose.yaml](../compose.yaml) (the Manager and
Typesense), and the **ROMKADE** tab opens the Manager in the browser (`http://localhost:8765`).

| File | Role |
|---|---|
| `metadata.json` | declares the ROMKADE tab and the services to start |
| `docker-compose.yaml` | the services, started by Docker Desktop on install and stopped on uninstall |
| `ui/index.html` | the tab: Manager status, open button, first steps |
| `Dockerfile` | the extension image (no program, only these files) and its Marketplace labels |

## Try it locally

Docker Desktop > Settings > Extensions: check "Enable Docker Extensions", and uncheck "Allow only extensions
distributed through the Docker Marketplace" while the extension is not published.

```sh
./build.sh                # build and install, Manager on port 8765
./build.sh --port 8766    # next to a Manager already running on 8765
./build.sh --manager-image romkade-manager:main   # with a Manager built locally instead of the latest release
docker extension rm romkade/romkade-manager-extension   # uninstall
```

The data (catalogue, settings, secrets) lives in the extension's own volumes, separate from a `docker compose`
install. **Uninstalling the extension deletes them.**

## Publish to the Marketplace

`docker extension validate` lists what is missing: a semver tag (`0.1.0`, not `dev`) and a multi-arch image
(`docker buildx build --platform=linux/amd64,linux/arm64 --push`) on Docker Hub, then the publication request to
Docker.
