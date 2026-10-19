<p align="center">
  <a href="https://romkade.com"><img src="frontend/src/assets/brand/romkade-manager-logo-480.webp" alt="ROMKADE Manager" width="360"></a>
</p>

<p align="center"><strong>🌐 <a href="https://romkade.com">romkade.com</a></strong> · <a href="https://romkade.com/docs/es/">Documentación</a> · <a href="https://github.com/RomKade/romkade-manager/releases/latest">Última versión</a></p>

<p align="center"><a href="README.md">English</a> · <a href="README.fr.md">Français</a> · <strong>Español</strong></p>

# ROMKADE Manager

Gestiona y controla tus consolas retro portátiles (Anbernic, Miyoo, TrimUI…) desde el navegador de tu ordenador, en
macOS, Windows o Linux: biblioteca, añadir juegos, lanzamiento en la consola, partidas guardadas, tiempo de juego,
mandos, Bluetooth. **La consola solo se modifica mediante acciones que lanzas tú: añadir juegos, restaurar o eliminar
una partida guardada, ajustes de Bluetooth y mandos de los jugadores.**

Guía de uso: **[romkade.com/docs](https://romkade.com/docs/es/)**. Arquitectura, modelo de datos y decisiones técnicas:
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Índice

- **Instalación**:
  - [Instalar con Docker (macOS, Windows, Linux)](#instalar-con-docker-macos-windows-linux) — [Actualizar, hacer copia, desinstalar](#actualizar-hacer-copia-desinstalar) · [Clave SSH e IA local con Docker](#clave-ssh-e-ia-local-con-docker) · [Publicar una versión](#publicar-una-versión)
  - [Ejecutar desde el código fuente (macOS)](#ejecutar-desde-el-código-fuente-macos)
- **Desarrollo**: [1. Diagnóstico de la consola real (recomendado primero)](#1-diagnóstico-de-la-consola-real-recomendado-primero) · [2. Sincronizar el catálogo (fase 2)](#2-sincronizar-el-catálogo-fase-2) · [3. Lanzar la aplicación](#3-lanzar-la-aplicación) · [Modificar la interfaz (Node 20 o superior: brew install node)](#modificar-la-interfaz-node-20-o-superior-brew-install-node) · [4. Primera conexión mediante la API (innecesario si se ha lanzado catalog_report.py)](#4-primera-conexión-mediante-la-api-innecesario-si-se-ha-lanzado-catalog_reportpy) · [5. Uso](#5-uso)
- **Funciones**: [Añadir juegos](#añadir-juegos) · [Géneros](#géneros) · [Ilustraciones de las consolas](#ilustraciones-de-las-consolas) · [Tráileres](#tráileres) · [Carátulas](#carátulas) · [Jugar en la consola desde la interfaz](#jugar-en-la-consola-desde-la-interfaz) · [Idiomas](#idiomas) · [Partidas guardadas](#partidas-guardadas) · [Retomar una partida desde un guardado](#retomar-una-partida-desde-un-guardado) · [Bluetooth](#bluetooth) · [Mandos](#mandos) · [Volumen](#volumen) · [Desde el móvil (ngrok)](#desde-el-móvil-ngrok) · [Información sobre los juegos](#información-sobre-los-juegos) · [Controles de los juegos](#controles-de-los-juegos) · [Conexión a una IA (LLM)](#conexión-a-una-ia-llm) · [Asistente de juego](#asistente-de-juego) · [Favoritos](#favoritos) · [Tiempo de juego](#tiempo-de-juego) · [Panel](#panel)
- **Funcionamiento**: [Garantías](#garantías) · [Búsqueda (Typesense)](#búsqueda-typesense) · [Conexión a la consola](#conexión-a-la-consola) · [Otras consolas y sistemas](#otras-consolas-y-sistemas)
- **Proyecto**: [Versión, condiciones de uso](#versión-condiciones-de-uso) · [Fuentes y créditos](#fuentes-y-créditos)

## Instalar con Docker (macOS, Windows, Linux)

La instalación recomendada, idéntica en los tres sistemas, en procesadores Intel/AMD y ARM (Apple Silicon,
Raspberry Pi).

1. Instala Docker: [Docker Desktop](https://docs.docker.com/desktop/) en macOS y Windows, o
   [Docker Engine](https://docs.docker.com/engine/install/) con el plugin Compose en Linux.
2. Descarga el archivo `compose.yaml` de la última versión e inicia ROMKADE Manager:

   macOS y Linux:

   ```bash
   mkdir romkade && cd romkade
   curl -fsSLO https://github.com/RomKade/romkade-manager/releases/latest/download/compose.yaml
   docker compose up -d
   ```

   Windows (PowerShell):

   ```powershell
   mkdir romkade; cd romkade
   curl.exe -fsSLO https://github.com/RomKade/romkade-manager/releases/latest/download/compose.yaml
   docker compose up -d
   ```

3. Abre http://localhost:8765 y luego **Ajustes > Conexión**: dirección IP de la consola, usuario SSH y contraseña,
   aprobación de la clave de la consola, prueba de conexión y sincronización.

Imagen: `ghcr.io/romkade/romkade-manager` (`latest`, o una versión como `0.4.0`). La búsqueda (Typesense) es un
segundo servicio del mismo archivo, sin puerto publicado. La interfaz solo escucha en este ordenador (`127.0.0.1`): no
la expongas a Internet, controla tu consola. El contenedor accede a la consola por la red local mediante SSH:
ordenador y consola en la misma red.

### Actualizar, hacer copia, desinstalar

En la carpeta `romkade`:

| Acción | Comando |
|---|---|
| Actualizar | `docker compose pull && docker compose up -d` |
| Registros | `docker compose logs -f` |
| Detener | `docker compose down` (datos conservados) |
| Copia de los datos | `docker run --rm -v romkade_romkade-data:/data -v "$PWD":/backup alpine tar czf /backup/romkade-data.tgz -C /data .` |
| Borrarlo todo | `docker compose down` y luego `docker volume rm romkade_romkade-data romkade_typesense-data` |

El volumen `romkade-data` guarda el catálogo, los ajustes, las copias de partidas y los secretos (`secrets.json`,
legible solo por la cuenta del contenedor). Nunca `docker compose down -v` por costumbre: borra los volúmenes.

Opciones, en un archivo `.env` junto a `compose.yaml`: `ROMKADE_PORT` (por defecto `8765`), `ROMKADE_VERSION` (por
defecto `latest`), `TZ` (por defecto `Europe/Paris`).

### Clave SSH e IA local con Docker

- **Clave SSH** en lugar de contraseña: el contenedor solo ve su volumen. Copia la clave en él una vez e indica
  `/data/id_ed25519` como ruta de la clave privada:

  ```bash
  docker compose exec -T romkade sh -c 'cat > /data/id_ed25519 && chmod 600 /data/id_ed25519' < ~/.ssh/id_ed25519
  ```

- **IA local** (Ollama, LM Studio) en este ordenador: dirección `http://host.docker.internal:11434/v1` en
  Ajustes > Asistente. Guía: [docs/local-llm.es.md](docs/local-llm.es.md).

### Publicar una versión

Mismo número en `backend/pyproject.toml` y `frontend/package.json`, y luego `git tag vX.Y.Z && git push origin vX.Y.Z`.
El workflow [Image Docker](.github/workflows/docker.yml) publica la imagen (`X.Y.Z`, `X.Y`, `latest`, amd64 + arm64) y
una release de GitHub con `compose.yaml`. Cada push a `main` publica `edge`.

## Ejecutar desde el código fuente (macOS)

Para el desarrollo, o para usar la aplicación [desde el móvil](#desde-el-móvil-ngrok). Hace falta el Python 3.13
oficial de [python.org](https://www.python.org/downloads/macos/) (el Python de Homebrew lo bloquea el permiso «Red
local» de macOS y devuelve «No route to host») y Node 20 o superior (`brew install node`) para compilar la interfaz.

```bash
git clone https://github.com/RomKade/romkade-manager.git
cd romkade-manager
./run.sh
```

En el primer arranque, el script prepara el entorno de Python y compila la interfaz (`frontend/dist`); luego inicia el
servidor y abre http://127.0.0.1:8765 en el navegador. `Ctrl+C` detiene el servidor. Contraseñas y claves van al
llavero del sistema; los datos a `~/Library/Application Support/AnbernicGameManager` (`ROMKADE_DATA_DIR` para
cambiarlo; en Windows `%APPDATA%\AnbernicGameManager`, en Linux `~/.local/share/AnbernicGameManager`).

Instalación manual y pruebas:

```bash
cd romkade-manager/backend
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q               # pruebas contra un servidor SFTP simulado
```

## 1. Diagnóstico de la consola real (recomendado primero)

```bash
.venv/bin/python scripts/diagnose_device.py --host 192.168.86.242
```

El script muestra la huella de la clave de host, pide la contraseña (no se guarda) y luego comprueba SFTP, el espacio en disco y la estructura de carpetas. No escribe nada en la consola.

Para comparar la huella de forma independiente:

```bash
ssh-keyscan -p 22 192.168.86.242 2>/dev/null | ssh-keygen -lf -
```

## 2. Sincronizar el catálogo (fase 2)

```bash
.venv/bin/python scripts/catalog_report.py
```

En el primer arranque: confirmación de la clave de host, contraseña guardada en el llavero y ajustes
registrados. Después, ninguna pregunta. El script escanea la tarjeta en modo solo lectura, actualiza
`~/Library/Application Support/AnbernicGameManager/catalog.sqlite3` y muestra un informe
(juegos por plataforma, cambios, duplicados, imágenes sin emparejar).

## 3. Lanzar la aplicación

```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8765
```

Interfaz: http://127.0.0.1:8765. Documentación de la API: http://127.0.0.1:8765/docs

## Modificar la interfaz (Node 20 o superior: `brew install node`)

```bash
cd frontend
npm install
npm run dev          # http://127.0.0.1:5173, redirige /api al backend lanzado en 8765
npm test             # tests de Vitest
npm run build        # recompila frontend/dist, que luego sirve el backend
npm run gen:api      # regenera los tipos de TypeScript a partir del OpenAPI (con el backend lanzado)
```

## 4. Primera conexión mediante la API (innecesario si se ha lanzado catalog_report.py)

```bash
API=http://127.0.0.1:8765/api

# Ajustes (no sensibles, guardados en ~/Library/Application Support/AnbernicGameManager/)
curl -s -X PUT $API/settings -H 'Content-Type: application/json' \
  -d '{"host":"192.168.86.242","port":22,"username":"root","auth_method":"password","roms_root":"/mnt/mmc/Roms"}'

# Contraseña -> llavero de macOS (la API nunca la devuelve). read -s evita el historial del shell.
read -s PW && curl -s -X PUT $API/settings/password -H 'Content-Type: application/json' \
  -d "{\"password\":\"$PW\"}"; unset PW

# Clave de host: mostrar, comprobar y luego confirmar copiando la huella
curl -s $API/device/host-key
curl -s -X POST $API/device/host-key/trust -H 'Content-Type: application/json' \
  -d '{"fingerprint":"SHA256:...."}'
```

## 5. Uso

Catálogo (servido desde SQLite, incluso con la consola apagada):

```bash
curl -s -X POST $API/catalog/sync                       # lanza una sincronización (202 + id)
curl -s $API/catalog/sync/1                             # progreso: platforms_done / platforms_total
curl -s $API/catalog/status | python3 -m json.tool      # totales, última sincronización, espacio en la tarjeta
curl -s $API/platforms
curl -s "$API/games?q=mario&platform=SFC&sort=name&limit=20"
curl -s "$API/games?region=Europe&extension=chd&has_image=true"
curl -s $API/games/42                                   # ficha + duplicados + historial
open  http://127.0.0.1:8765/api/games/42/image          # imagen de Imgs (en caché local)
curl -s $API/catalog/changes                            # altas / cambios / desapariciones de la última sincronización
curl -s $API/catalog/duplicates
curl -s $API/catalog/unmatched-images
```

Acceso directo a la consola (diagnóstico):

```bash
curl -s -X POST $API/device/test-connection | python3 -m json.tool
curl -s $API/device/storage
curl -s "$API/device/inventory?include_files=true&platform=PS"
```

## Añadir juegos

Página **Añadir juegos** (antes «Transferencias», `/ajouter-des-jeux`): arrastra archivos o haz clic en «Elegir archivos».

1. Los archivos se copian primero a una zona de espera en el Mac (`~/Library/Application Support/AnbernicGameManager/staging`), calculando su huella SHA-256.
2. Para cada uno, la aplicación propone la consola de destino según el formato y avisa de: nombre no admitido por la tarjeta, formato poco habitual, archivo ya presente (sin distinguir mayúsculas), título ya presente, espacio insuficiente (margen mínimo de 256 MB).
3. «Copiar a la consola»: cada archivo se escribe con un nombre temporal oculto, se verifica (huella SHA-256 calculada en la consola o, si no, el tamaño) y luego se renombra. Después se vuelve a leer el catálogo de las consolas afectadas.
4. Un archivo ya presente nunca se sustituye sin confirmación. Si se sustituye, el antiguo se mueve a `/mnt/mmc/Roms/.agm-backups/<console>/` (misma tarjeta, sin consumir espacio). Puedes borrar esa carpeta a mano cuando ya no la necesites.
5. Cancelación o corte: el archivo temporal se elimina y no aparece nada en la tarjeta. Una transferencia fallida o cancelada se puede volver a lanzar mientras el archivo siga en la zona de espera.

## Garantías

- Lectura y escritura separadas: `ReadOnlyRemoteFS` para todo lo que lee, `RemoteWriter` solo para las copias. La escritura se limita a las carpetas de consolas existentes (nunca APPS, PORTS, un enlace simbólico o un archivo del sistema), y el único borrado posible afecta a los archivos temporales de la aplicación.
- El servidor rechaza las peticiones procedentes de otros sitios abiertos en el navegador (control de las cabeceras Origin y Host).
- Clave de host verificada, confirmación explícita en el primer contacto, bloqueo si cambia.
- Contraseña únicamente en el llavero de macOS.
- Rutas validadas y confinadas bajo la raíz; enlaces simbólicos señalados y nunca seguidos.
- Carpetas `Imgs` contadas aparte, nunca como juegos. De un archivo `candidate` no se afirma que sea jugable.
- Sincronización: un archivo desaparecido se marca con `deleted_at`, nunca se borra; una plataforma con error conserva sus archivos; raíz ausente o vacía: sincronización rechazada sin modificar nada.
- Roles: `candidate` (juego potencial), `component` (pista .bin de un .cue, disco de un .m3u), `auxiliary` (texto, partida guardada), `program` (APPS, PORTS).
- Servidor vinculado a 127.0.0.1.

## Géneros

La biblioteca filtra por género (Deportes, Disparos, Plataformas…). Los géneros proceden de una tabla integrada,
`backend/app/data/genres.json.gz`, emparejada por nombre de archivo: libretro-database para las consolas
(nombres No-Intro), catver.ini (progettoSNAPS) para el arcade (nombres cortos de MAME). Ningún acceso a la red durante el uso;
los géneros se recalculan en cada arranque y tras cada sincronización.
Segunda fuente: [OpenVGDB](https://github.com/OpenVGDB/OpenVGDB) (la base de OpenEmu), imprescindible para las
consolas de CD (PlayStation, Saturn, Mega-CD, PC Engine CD) ausentes de libretro. Los nombres de archivo
aproximados se emparejan por título compacto («Bomberman2»), quitando el prefijo («SS-Clockwork Knight»),
por inicio del título (nombre truncado) y, por último, por el mismo juego en otra consola o en arcade. Para actualizar la tabla:

```bash
cd backend && .venv/bin/python scripts/build_genres.py
```

Los juegos de arcade muestran su título completo («sf2.zip» → «Street Fighter II: The World Warrior»),
sacado de las listas MAME, FBNeo y HBMAME de libretro-database, en la misma tabla.

## Ilustraciones de las consolas

`frontend/public/consoles/*.webp`: tema XMB «systematic» de
[retroarch-assets](https://github.com/libretro/retroarch-assets) (CC-BY 4.0). Para añadir más:
`cd backend && .venv/bin/python scripts/build_console_icons.py` y luego recompilar la interfaz.

## Tráileres

El botón ▶ de una carátula busca un vídeo con la API oficial YouTube Data v3. Hace falta una clave de API
gratuita (Ajustes → Tráileres de YouTube), guardada en el llavero de macOS. Una búsqueda cuesta
100 unidades de una cuota de 10 000 al día, es decir, unos 100 juegos al día: la búsqueda se hace en el primer
clic y después el resultado (los 5 vídeos más relevantes) se guarda en caché en el catálogo. Sin clave,
el botón abre la búsqueda en youtube.com.

## Carátulas

Las imágenes de la carpeta `Imgs` de la tarjeta suelen ser montajes para el menú de la consola. La cuadrícula
muestra en su lugar la caja real del juego, sacada de [libretro-thumbnails](https://thumbnails.libretro.com)
(el banco de imágenes de RetroArch), por nombre No-Intro o, para el arcade, por título completo. Si falta el nombre
exacto, se busca el título más parecido en la lista de archivos del banco. Cada carátula se
descarga la primera vez que se muestra y luego se guarda en `cache/boxart` en el Mac; no se escribe nada en la
tarjeta. El selector «Carátulas / Imágenes de la tarjeta» de la biblioteca permite volver a las imágenes
de la tarjeta.

## Jugar en la consola desde la interfaz

En la ficha de un juego, «Jugar en la consola» cierra el menú (o el juego de RetroArch en curso, con su
guardado automático) y lanza el juego en la consola; el menú vuelve al salir del juego.
El recuadro de la consola, en la barra lateral, muestra el juego en curso y ofrece «Salir del juego».

Funciona con el firmware de Anbernic con el «Stock OS Mod» (`/mnt/mod/ctrl/RA_launch.sh`, núcleos de
`/mnt/mod/ctrl/configs/CORES.txt`). El script `backend/app/device/launch.sh` se envía por SSH y se ejecuta
en segundo plano: pausa el bucle del menú (`/mnt/vendor/ctrl/loadapp.sh`), cierra `dmenu.bin` limpiamente
(SIGINT), devuelve la pantalla a su modo de arranque (640×480, 32 bits, guardado por el mod en
`configs/fb.cfg`; sin esto RetroArch no puede mostrarse), lanza el juego igual que el mod y luego
libera el bucle al salir del juego. «Salir del juego» envía el comando de red `QUIT` de RetroArch
(UDP 55355). No se escribe ningún archivo en la tarjeta;
el registro está en `/tmp/agm-launch.log` en la consola.

## Idiomas

La interfaz está en francés, inglés y español (selector en la parte inferior de la barra lateral, elección guardada
en el navegador). Textos: `frontend/src/i18n/locales/*.ts`, un archivo por zona, con los tres idiomas
uno al lado del otro. El servidor responde en francés; la interfaz traduce sus errores a partir de su código.

## Partidas guardadas

Página «Partidas guardadas»: todas las partidas guardadas de la tarjeta, asociadas a su juego, leídas en modo solo lectura
en las carpetas del firmware (bajo `/mnt/mmc`):

| Carpeta | Contenido |
|---|---|
| `saves_RA/Roms/<CONSOLE>/<cœur>/` | guardados «en el juego» de RetroArch (`.srm`, `.save.zip`, `.nvmem`) |
| `states_RA/Roms/<CONSOLE>/<cœur>/` | estados guardados de RetroArch (`.state`, `.stateN`, `.state.auto`) |
| `save/Roms/<CONSOLE>/` | emuladores originales de Anbernic (`.stN`, `.mds.gz`, `.srm`) |
| `save_nds/` | DraStic (Nintendo DS) |
| `.config/ppsspp/PSP/SAVEDATA/` | PPSSPP (PSP), una carpeta por identificador de juego |
| `Roms/<CONSOLE>/*.sav` | partidas guardadas junto al juego |

- «Copiar todas las partidas guardadas al Mac» crea una carpeta con fecha en
  `~/Library/Application Support/AnbernicGameManager/save-backups/`, descargable en `.zip`.
- Restaurar un archivo de una copia, o eliminar una partida guardada de la tarjeta: no se permite mientras hay un juego en marcha,
  y siempre va precedido de una copia automática en el Mac del archivo sustituido o eliminado. Las escrituras pasan
  por `app/device/save_writer.py`, limitado a las ubicaciones de partidas guardadas.
- La guía «Cómo guardar» muestra los atajos de RetroArch realmente configurados en la consola.
- Panel: «Guardar ahora» envía el comando de red `SAVE_STATE` de RetroArch al juego en curso.

## Retomar una partida desde un guardado

En la página Partidas guardadas y en la ficha de un juego, cada partida guardada tiene un botón:
- «Continuar aquí» (estado guardado de RetroArch): lanza el juego en la consola y carga esa ranura en cuanto
  RetroArch está ejecutando el juego (comandos de red `GET_STATUS` y luego `LOAD_STATE_SLOT n`); el estado
  «auto» pasa por la opción `auto` de `RA_launch.sh`;
- «Jugar» (guardado en el juego): lanza el juego, que carga él mismo su partida guardada.

## Bluetooth

Página «Bluetooth»: estado del Bluetooth de la consola, dispositivos emparejados y al alcance (búsqueda de 12 s),
emparejar / conectar / desconectar / olvidar, y «Sonido de los juegos aquí» para un altavoz o unos auriculares.

- La consola tiene BlueZ y BlueALSA, pero nada arranca `bluealsa`: sin él, un altavoz se empareja sin
  recibir sonido. La aplicación lo lanza bajo demanda (`bluealsa -p a2dp-source`, proceso en segundo plano).
- «Sonido de los juegos aquí»: RetroArch es un programa de 32 bits, el plugin ALSA de BlueALSA solo existe en 64 bits,
  y RetroArch siempre abre la salida ALSA «default». Por eso la aplicación instala
  `/etc/alsa/conf.d/60-agm-bluetooth.conf` (salida `agm_bt`: el sonido se pasa a `aplay`, de 64 bits, hacia
  el altavoz; si no está, se descarta y el juego sigue sin sonido) y `/.asoundrc`
  (`pcm.!default agm_bt`, que leen los juegos lanzados desde Game Manager, que se ejecutan con `HOME=/`).
  El relé también copia el sonido a la salida HDMI (muda sin cable): le da a RetroArch un reloj
  en tiempo real; sin ella (salida «null»), el sonido llegaba entrecortado.
  «Devolver el sonido a la consola» elimina esos dos archivos. El menú de la consola, y los juegos lanzados
  desde él, siguen usando sus altavoces.
- Mandos recientes (Xbox, 8BitDo…): usan Bluetooth de bajo consumo y solo se emparejan durante
  una búsqueda activa. Por eso la conexión se hace en una sola sesión de `bluetoothctl` (agente, `scan on`, `pair`,
  `trust`, `connect`), con el registro en `/tmp/agm-bt-connect.log` en la consola. Si el dispositivo está emparejado pero no
  responde, hay que despertarlo (botón Xbox / Home) y volver a hacer clic en «Conectar».
- El firmware borra los emparejamientos en cada arranque (`/mnt/vendor/ctrl/loadapp.sh` vacía
  `/var/lib/bluetooth`), y `bluealsa` no se vuelve a lanzar: tras un reinicio, vuelve a conectar el dispositivo desde
  esta página.

## Mandos

Página «Mandos»: quién controla el juego. Mando de cada jugador en RetroArch (`input_playerN_joypad_index`,
números del controlador sdl2: 0 = botones de la consola, luego mandos USB / Bluetooth por orden de conexión).
RetroArch guarda su configuración al salir: un jugador 1 que se ha quedado en un mando antiguo ausente impide que la consola
controle el juego («Usar los botones de la consola» lo devuelve al jugador 1). La elección se guarda en
`/.config/agm-players` y se escribe de inmediato en `/.config/retroarch/retroarch.cfg` si no hay ningún juego en marcha o, si no,
`launch.sh` lo hace en el siguiente juego lanzado desde Game Manager (una vez cerrado RetroArch). Elegir un mando para un
jugador lo intercambia con el jugador que lo tenía.

RetroArch (controlador sdl2 con udev) no numera los mandos en el orden de `/proc/bus/input/devices` sino
por ruta sysfs: con un mando Xbox USB, `…/soc/5101000.ohci0…` va antes que los botones
`…/soc/soc@03000000:gpio_keys` (Xbox = 0, consola = 1), y «jugador 1 = mando n.º 1» le daba el control a la
consola. `/.config/agm-players` conserva los números de Game Manager; `players_apply.sh` (lanzado por Game Manager
sin juego en curso, y por `launch.sh` antes de cada juego, con los mandos conectados en ese momento) los traduce al
orden de RetroArch y además reserva el mando para el jugador (`input_playerN_reserved_device = "045e:0b12 Generic
X-Box pad"`, tipo 1 = preferido). Lo aplicado se copia en `/.config/agm-players.applied`; el
resultado se anota en `/tmp/agm-launch.log` («joueurs pour RetroArch : 0 045e:0b12 Generic X-Box pad 1 … »).

Con un mando conectado además de los botones de la consola, «Jugar en la consola» (ficha del juego) pregunta
primero «¿Quién juega?»: la elección pasa a ser el jugador 1 y luego se lanza el juego.

El botón de la cabecera se adapta a la situación: un cambio pendiente durante un juego de RetroArch conocido por la
biblioteca muestra «Relanzar el juego para aplicar»; un jugador 1 en un mando ausente muestra «Usar los
botones de la consola» (y luego la biblioteca si no hay juego en curso, o el relanzamiento del juego en curso); si no, sin juego
en curso, «Elegir un juego» abre la biblioteca. El relanzamiento vuelve a pasar por `launch.sh`: se sale del juego
limpiamente con su guardado automático, se escriben los mandos y luego se reanuda en `auto` si el sistema sabe
reanudar.

## Volumen

En el bloque «En curso» del panel, en la franja «En curso» de la ficha del juego y en la barra
superior cuando hay un juego en marcha: silenciar / reactivar el
sonido y control deslizante de volumen (1 a 100 % = -40 a 0 dB), válido tanto para los altavoces como para un altavoz
Bluetooth.

Lo que no funciona en esta consola, y de ahí esta elección:
- el mezclador del chip de sonido: durante un juego, sus ajustes están bloqueados (`amixer` no cambia nada, sin error);
- los comandos de red `VOLUME_UP` / `VOLUME_DOWN` de RetroArch: se ignoran (solo funciona `MUTE`).

Por eso Game Manager añade su propio volumen por software ALSA: `/.asoundrc` (que leen los juegos lanzados desde Game
Manager, `HOME=/`) hace pasar la salida «default» por dos `softvol` (volumen «Game Manager» y luego silencio),
antes de los altavoces o de la salida Bluetooth `agm_bt`. El control «Game Manager» se crea en la tarjeta 0 antes
del primer juego tras un arranque, con un segundo de silencio reproducido con `aplay` (ajustado entonces al 60 %):
creado por RetroArch, quedaba bloqueado por él durante toda esa partida (control deslizante y teclas Vol+/Vol- sin
efecto). Después se regula con `amixer`, incluso en plena partida. Al
lanzar, `launch.sh` pone el volumen propio de RetroArch (`audio_volume`, a menudo muy bajo) a 0 dB.
Un juego lanzado desde el menú de la consola no usa `/.asoundrc`: solo funciona el silencio (`MUTE`).

## Desde el móvil (ngrok)

```bash
./run.sh --telephone
```

Publica la interfaz en una dirección https de ngrok (cuenta de ngrok configurada una vez: `ngrok config add-authtoken …`)
y muestra la dirección, el usuario, la contraseña y un código QR. La aplicación no tiene cuentas: ngrok
pide el usuario y la contraseña **antes** de que la petición llegue al Mac (regla `basic-auth`,
`phone_policy.yml` en la carpeta de datos). La contraseña se crea en el primer arranque
(`phone_password`, legible solo por ti) y se conserva después. El servidor solo acepta, además de localhost,
la dirección de ngrok de ese arranque (`AGM_EXTRA_HOSTS`). `Ctrl+C` detiene el servidor y el acceso. Sin `--telephone`,
no se publica nada.

## Información sobre los juegos

Ficha del juego: género (pictograma), regiones (banderas), lanzamiento, editor, desarrollador, franquicia (enlaces
a Wikipedia en el idioma de la interfaz), resumen (en inglés) y ficha de GameFAQs. Tabla integrada
`backend/app/data/gameinfo.json.gz`, generada por `scripts/build_gameinfo.py` (libretro-database, OpenVGDB,
listas arcade MAME / FBNeo / HBMAME), emparejada por nombre de archivo como los géneros. La búsqueda también encuentra
el año, el editor, el desarrollador, la franquicia, y las regiones y géneros en francés, inglés y español
(«Japon», «Japan», «Japón»).

## Controles de los juegos

Sección «Controles» de la ficha: qué botón de la consola hace qué en ese juego («B: puñetazo»,
«A: disparo»), con algunos trucos. «Preguntar a Claude» hace una llamada (Opus 5.5, esfuerzo medio, unos
céntimos) con la correspondencia por defecto de los núcleos de RetroArch entre el mando original y los botones de la
consola (Mega Drive: A = Y, B = B, C = A; PlayStation: Cruz = B, Círculo = A…; arcade: botón 1 = B, 2 = A…,
moneda = Select). Respuesta en francés, inglés y español, guardada en la base (tabla `game_controls`, compartida por
las ediciones de un mismo juego). Juego poco conocido por el modelo: controles habituales de la consola, indicado como tal.
«Corregir» / «Introducir a mano» sustituye la lista por la tuya (mismo texto en los tres idiomas). La misma clave
de API de IA que las descripciones (Ajustes > Asistente).

## Conexión a una IA (LLM)

Ajustes > Asistente: la IA del [asistente de juego](#asistente-de-juego), que también sirve, bajo petición, para las
descripciones y los controles de los juegos, con un indicador de estado
(gris: ninguna, naranja: comprobando, verde: conectada, rojo: error). `backend/app/services/llm.py`:

| Opción | Clave | Notas |
|---|---|---|
| Claude (Anthropic) | `sk-ant-…` | Claude Opus 5.5 por defecto; descripciones por lotes (mitad de precio) |
| ChatGPT (OpenAI), Mistral, Gemini | clave del proveedor | protocolo OpenAI (chat completions) |
| Modelo local o servicio compatible con OpenAI | opcional | Ollama, LM Studio (Mac, Windows, Linux) o cualquier dirección `…/v1`; gratis y sin conexión en local |

- Servicio en línea: elegirlo y pegar la clave, nada más. El modelo se toma de la lista del proveedor
  (`suggest_model`, nunca un nombre inventado) y se puede cambiar; la conexión se comprueba sola (una petición real
  muy pequeña) y el resultado enciende el indicador (`last_test` en `llm.json`).
- Ninguna IA por defecto (una clave de Anthropic ya guardada mantiene Claude, como antes).
- Claves en el llavero del sistema (o `secrets.json` en Docker), una por proveedor, con un ojo para mostrarlas; si no,
  la variable de entorno del proveedor (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `MISTRAL_API_KEY`, `GEMINI_API_KEY`).
- Modelo local: direcciones listas Ollama, LM Studio y Ollama (Docker) (`host.docker.internal`, declarado en
  `compose.yaml` para Linux). Guía paso a paso: [docs/local-llm.es.md](docs/local-llm.es.md).
- Respuestas en JSON: salidas estructuradas (`json_schema`); si no, JSON simple con el esquema en la consigna
  (modelos locales que no las admiten).
- Descripciones sin Claude: juego a juego en segundo plano (se detiene tras 5 fallos seguidos, se puede reanudar).

## Asistente de juego

Una burbuja abajo a la derecha en todas las páginas: un asistente de IA para **tu biblioteca** (encontrar un juego,
comparar dos, usar la aplicación). En la ficha de un juego, o mientras un juego funciona en la consola, propone hablar
solo de **ese juego** (controles, objetivos, una parte difícil, secretos: primero una pista, la solución si se pide).
Usa la IA configurada en Ajustes > Asistente, en línea o local (Ollama, LM Studio; a los modelos de razonamiento se les pide
responder sin reflexión previa, lo que deja un modelo local de 12B en unos 10 s por respuesta). Cada pregunta pasa
por dos llamadas: una clasificación estructurada (dentro del tema o no, intención, género, consola) y luego la
respuesta en flujo, construida con la ficha del juego y los pasajes de **conocimientos**. Las preguntas fuera de tema,
las peticiones de ROM o BIOS y los intentos de cambiar sus instrucciones reciben el rechazo de la aplicación, nunca
el texto del modelo. Las conversaciones se quedan en el navegador.

**Conocimientos** (Ajustes > Conocimientos, sin IA): para cada juego, sus páginas de Wikipedia (en, fr, es) y su guía de
StrategyWiki, obtenidas sin IA mediante las API de MediaWiki una vez identificado el juego en Wikidata (videojuego +
consola correcta), divididas en pasajes con su fuente y su licencia (CC BY-SA 4.0, citada en las respuestas) e
indexadas en Typesense. Obtención para un juego (prueba, con una pregunta de prueba que muestra los pasajes
encontrados) o para todos; opción de obtención automática de los juegos nuevos tras cada sincronización. Diseño:
[docs/STRATEGIE-IA.md](docs/STRATEGIE-IA.md).

## Favoritos

«Añadir a favoritos» en la ficha de un juego (la edición abierta). Los favoritos aparecen en «Mis favoritos» del
panel (el último añadido primero, con «Volver a jugar») y en la biblioteca: botón «Favoritos» de los
filtros, o `/bibliotheque?fav=1` (enlace «Todos mis favoritos»). Guardados en la base del Mac (tabla `favorite`).

Los favoritos pertenecen a una consola: cada uno guarda la huella SHA-256 de la clave SSH aprobada de la consola
(estable, a diferencia de su dirección IP). Al conectar otra consola (la de un amigo, otro firmware) solo se muestran
sus propios favoritos, limitados a los juegos presentes en su tarjeta; los demás se quedan en la base y vuelven con su consola.

## Tiempo de juego

Página «Tiempo de juego»: tiempo del día, de los últimos 7 días y total, histograma de 14 días, tiempo por juego,
últimas partidas; tarjeta «Hoy» en el panel.

- **Seguimiento por Game Manager** (`app/services/playtime.py`): mientras el servidor está en marcha, mira cada
  30 s qué se está ejecutando en la consola y registra sesiones fechadas con el reloj del Mac (tabla
  `play_session`). Es lo que da el historial y el tiempo por día. `AGM_NO_TRACKER=1` lo desactiva.
- **Registros de RetroArch** (`/mnt/vendor/deep/retro/playlists/logs/<cœur>/<jeu>.lrtl`): tiempo total por juego,
  incluidas las partidas lanzadas desde el menú de la consola. Los totales por juego toman el mayor de los dos.
- **Alerta** (Ajustes → Tiempo de juego): al cabo de N horas de la partida en curso o del día, con
  recordatorio opcional. Se muestra como ventana emergente en Game Manager y, si está marcado, en la pantalla de la consola durante
  el juego (comando de red `SHOW_MSG` de RetroArch). Ajustes en `play_settings.json` de la carpeta de datos.


Filtro «Del … al …»: días, juegos y partidas de ese periodo. Solo cuentan las partidas seguidas por Game Manager:
los registros de RetroArch (`.lrtl`) solo dan un total por juego, sin fechas.

Borrar: la papelera de un juego (en «Por juego») o «Borrar todo», con confirmación. Las partidas de Game
Manager se eliminan; no se modifica nada en la consola: el total de los registros de RetroArch del juego en el momento del
borrado se guarda (tabla `play_reset`) y luego se resta, de modo que solo cuenta el tiempo jugado desde entonces. La
partida en curso, si está afectada, vuelve a empezar de cero.
## Panel

Por orden: el juego en curso, los juegos jugados recientemente (botón ▶ para relanzarlos en la consola;
historial de RetroArch de la consola completado con las partidas seguidas por Game Manager, `GET /api/play/recent`),
las últimas incorporaciones con un enlace «Añadir juegos», la tarjeta microSD y, por último, las consolas con más juegos y
la actividad (última partida, tiempo de juego del día, sincronización, juegos que se están añadiendo).

## Búsqueda (Typesense)

La barra de búsqueda superior, en todas las páginas, sugiere consolas, géneros y juegos mientras escribes (flechas +
Intro abren la ficha, «Ver los N resultados» abre la biblioteca). En la biblioteca, además filtra
la lista mostrada, combinada con los filtros (consola, género, formato, región) y las ordenaciones (entre ellas «Año de lanzamiento»:
del más antiguo al más reciente por defecto, juegos sin año conocido al final; el botón junto a la ordenación indica el orden
en claro, «Más antiguos primero», «A → Z»…, y lo invierte con un clic). Se toleran las erratas
(«castlvania», «zelad», «stret fihgter»), búsqueda por inicio de palabra («final fant»), relevancia primero
(título completo, luego nombre de archivo, consola y género).

Campo vacío: las 6 últimas búsquedas (Intro, elección de una sugerencia, «Ver los N resultados», o texto que ha
filtrado la biblioteca), para repetir con un clic y quitar una a una o todas. Guardadas en el navegador
(`localStorage`): el Mac y el móvil tienen cada uno su lista.

El motor es [Typesense](https://typesense.org): Game Manager arranca su propio contenedor Docker
`agm-typesense` (imagen `typesense/typesense:27.1`), accesible solo desde este Mac en `127.0.0.1:8118`,
con los datos y la clave de API en la carpeta de datos (`typesense/`, `typesense.key`). El índice se reconstruye al
arrancar y en cuanto cambia el catálogo (comprobado cada 2 s), sin cortes: «games» es un alias que se cambia
a la nueva colección una vez llena. Sin Docker, o mientras Typesense no está
listo, toma el relevo la búsqueda SQLite original (`GET /api/search/status` indica el motor usado).
Variables: `AGM_TYPESENSE_URL` y `AGM_TYPESENSE_KEY` para otro servidor, `AGM_TYPESENSE=0` para prescindir de él.
API: `GET /api/search?q=…` (búsqueda rápida), `GET /api/games?q=…` (biblioteca).

**Juegos añadidos sin Game Manager** (tarjeta leída en el Mac, otra herramienta): una vigilancia lee cada minuto la carpeta de
ROMs, en modo solo lectura, y vuelve a leer las carpetas de consolas cuya fecha ha cambiado; una consola que aparece o desaparece
lanza una sincronización completa. Al arrancar, recupera lo que haya cambiado desde la última lectura. Estas
relecturas aparecen en el historial de sincronizaciones con el desencadenante `watch`. Límite: un archivo
añadido en una subcarpeta (juego multidisco) solo aparece en la siguiente sincronización completa.
`AGM_NO_WATCH=1` desactiva la vigilancia.

## Conexión a la consola

Una sola conexión SSH, compartida y mantenida abierta 90 s después del último uso (`app/device/pool.py`), sirve
las carátulas, las partidas guardadas y todos los comandos (juego en curso, Bluetooth, tiempo de juego, lanzamiento):
abrir una conexión cuesta ~0,5 s en la consola, y un comando sobre la conexión abierta, de 0,02 a 0,15 s. Si la
consola no responde, las llamadas siguientes fallan de inmediato durante 15 s en lugar de esperar cada una el tiempo
de conexión. Las incorporaciones de juegos y la prueba de conexión de los Ajustes mantienen su propia conexión.

Ajustes > Conexión guía la puesta en marcha en tres pasos numerados y marcados: 1. la consola (dirección,
usuario, y contraseña o clave SSH según la autenticación elegida, en el mismo bloque); 2. identificar la consola
(comparar y aprobar la huella de su clave, una vez por consola); 3. probar la conexión.
Los campos secretos (contraseña, claves de API) tienen un ojo para mostrar u ocultar lo que se escribe. Ajustes >
Sistema muestra primero lo que la consola puede hacer con su sistema, por temas (juegos, sonido, mandos y Bluetooth,
tiempo de juego; lo que no es posible aparece tachado), luego la elección del sistema y luego la fecha y la hora.

## Otras consolas y sistemas

Game Manager reconoce el firmware de la consola por SSH (algunos `test -d`, solo lectura); también se puede
elegir en Ajustes → «Sistema de la consola». Cada perfil (`backend/app/device/systems.py`) indica dónde están
las ROMs y las partidas guardadas, cómo lanzar y salir de un juego, y qué está disponible; la interfaz oculta el resto
(`GET /api/device/system`, `GET /api/systems`, `POST /api/device/system/detect`).

| Perfil | Consolas | ROMs | Lanzar / salir desde el Mac | Estado |
|---|---|---|---|---|
| Anbernic + Stock OS Mod | RG35XX Pro/Plus/H/SP/2024, RG28XX, RG34XX, RG40XX, RG CubeXX | `/mnt/mmc/Roms` | sí, incluida la reanudación desde un guardado | probado |
| Anbernic original | las mismas consolas, sin el mod | `/mnt/mmc/Roms` | solo salir | experimental |
| Knulli, Batocera | H700, RK3566, Miyoo Flip, TrimUI, PC… | `/userdata/roms` | sí (servidor web de EmulationStation, puerto 1234) | experimental |
| ROCKNIX / JELOS | Anbernic, Powkiddy, Retroid, AYN | `/storage/roms` | salir; lanzar si responde el servidor web de ES | experimental |
| muOS | Anbernic, TrimUI | `/mnt/mmc/ROMS` | salir | experimental |
| ArkOS / dArkOS | R36S y clones, RG351, RG353 | `/roms` | salir | experimental |
| Onion OS | Miyoo Mini / Mini Plus | `/mnt/SDCARD/Roms` | sí (como el menú de Onion), salir | probado |
| spruce | Miyoo A30, Flip | `/mnt/SDCARD/Roms` | salir | experimental |
| MinUI / NextUI | Miyoo, TrimUI, Anbernic | `/mnt/SDCARD/Roms` | no | experimental |
| Android + RetroArch | Retroid Pocket, AYN Odin/Thor, Anbernic y Ayaneo con Android | `/storage/emulated/0/ROMs` | lanzar (en RetroArch); salir en la consola | experimental |
| Otro (Linux + SSH) | — | por configurar | salir (RetroArch) | experimental |

Nombres de carpetas: cada firmware tiene los suyos («snes», «SFC», «Super Nintendo Entertainment System (SFC)»,
nombres libres en muOS). `app.platforms.canonical` los reduce a un código común (`platform.code` en la API) para los
géneros, carátulas, tráileres e ilustraciones. Las carpetas de medios guardadas junto a las ROMs (`images`,
`videos`, `manuals`…) se ignoran. Salir de un juego fuera de Anbernic: comando de red `QUIT` de RetroArch
(bash o `nc`) y luego `SIGTERM` si RetroArch no lo escucha. Solo el perfil Anbernic + Stock OS Mod se ha probado
en una consola real; los demás siguen la documentación de su firmware.

Onion OS: el menú (MainUI) escribe el comando del juego en `/tmp/cmd_to_run.sh` y luego se cierra, y el bucle
`.tmp_update/runtime.sh` lanza el juego. `onion_launch.sh` (copiado en `/tmp`) hace lo mismo: comando en el formato
de MainUI (emulador de `Emu/<console>/config.json`) y luego cierre del menú (`SIGTERM`, `SIGKILL` como respaldo); primero se sale de un juego abierto
(`QUIT` de RetroArch) o se cierra una aplicación, el tiempo necesario para que vuelva el menú (registro `/tmp/agm-launch.log`). Onion
corta SSH al lanzar los juegos, salvo con «Keep services alive» (Tweaks > Network): el script lo activa
(`.tmp_update/config/.keepServicesAlive_` renombrado a `.keepServicesAlive`, como hace Tweaks), única escritura
en la tarjeta, para que la consola siga accesible durante la partida (juego en curso, Salir).

Android (Retroid, AYN…): Android no tiene servidor SSH; la aplicación gratuita **Termux** proporciona uno (SFTP
incluido) y la biblioteca, la copia de juegos y las partidas guardadas funcionan entonces como en Linux. En la consola,
una sola vez:

1. Instalar **Termux** (versión de F-Droid o GitHub, no la del Play Store, demasiado antigua) y **RetroArch**, y
   descargar los núcleos necesarios (RetroArch → Actualizador en línea → Descargar núcleos).
2. En Termux: `termux-setup-storage`, `pkg install openssh`, `passwd` (elegir una contraseña), `sshd`.
3. Ajustes de Android → Aplicaciones → Termux → permitir **«Mostrar sobre otras aplicaciones»** (sin ello, Android
   bloquea un juego lanzado desde el ordenador mientras Termux está en segundo plano).
4. En ROMKADE Manager: la dirección IP de la consola, el puerto **8022**, cualquier nombre de usuario y la contraseña
   de Termux.

Los juegos se lanzan con un intent de Android (`am start` hacia RetroArch, extras `ROM` y `LIBRETRO`; un núcleo por
consola, `ANDROID_CORES` en `launcher.py`, comprobado con la lista de núcleos Android de RetroArch). El juego en curso
no se puede leer ni cerrar desde el ordenador: RetroArch para Android se compila sin sus comandos de red (comprobado en
la 1.22.2) y Android oculta sus procesos a las demás aplicaciones. Tampoco disponible en Android: guardar ahora,
reanudar desde un guardado rápido, volumen, Bluetooth, mandos por jugador, hora de la consola (requiere root). Probado
en un emulador Android 14 (Termux 0.118.3, RetroArch 1.22.2): conexión, detección, sincronización y lanzamiento de un
juego con Termux en segundo plano. Las partidas se leen en
`RetroArch/saves` y `RetroArch/states`, junto a la carpeta de ROMs (carpetas por defecto de RetroArch en Android).

## Versión, condiciones de uso

- Un solo número de versión, en `backend/pyproject.toml` y `frontend/package.json` (comprobado por
  `backend/tests/test_version.py`), mostrado en la barra lateral y en Ajustes > Acerca de.
- Condiciones de uso en `/conditions` (enlace en la barra lateral): ROMKADE no proporciona juegos y no responde de lo
  que el usuario haga en la consola o su tarjeta de memoria (pérdida de datos, tarjeta corrupta, partidas perdidas).
  Un aviso las recuerda en el primer inicio, hasta «Entendido» (`romkade-terms-v1` en el navegador). Texto que debe
  revisar un jurista antes de una difusión pública.
- Logo e iconos de ROMKADE Manager (`frontend/src/assets/brand/`, `frontend/public/icon-*.png`), tomados de los
  archivos de marca del repositorio romkade-website.

## Fuentes y créditos

ROMKADE Manager no proporciona ningún juego. Lo que toma de otras fuentes se cita en la interfaz
(Ajustes > Acerca de, lista en `frontend/src/lib/credits.ts`, y bajo cada ficha de juego):

| Fuente | Uso | Licencia |
|---|---|---|
| [libretro-thumbnails](https://github.com/libretro-thumbnails/libretro-thumbnails) | Carátulas (imágenes © de sus editores) | — |
| [retroarch-assets](https://github.com/libretro/retroarch-assets) | Ilustraciones de las consolas | CC BY 4.0 |
| [libretro-database](https://github.com/libretro/libretro-database) | Géneros, lanzamiento, desarrollador, editor, franquicia, títulos arcade | — |
| [OpenVGDB](https://github.com/OpenVGDB/OpenVGDB) | Resúmenes, fechas, enlace a GameFAQs, géneros | MIT |
| [catver.ini (progettoSNAPS)](https://www.progettosnaps.net/catver/) | Categorías arcade | — |
| MAME, FBNeo, HBMAME | Títulos completos, año, fabricante (vía libretro-database) | — |
| Wikipedia, GameFAQs, YouTube, la IA elegida (Claude, ChatGPT, Mistral, Gemini, modelo local) | Enlaces, tráileres, descripciones y controles por IA (claves del usuario) | — |
| [Lucide](https://lucide.dev/), Archivo, Atkinson Hyperlegible Next | Pictogramas, tipografías | ISC, SIL OFL 1.1 |

Cualquier fuente nueva (script `backend/scripts/build_*.py`, servicio en línea, ilustración) se añade a
`CREDITS` en `frontend/src/lib/credits.ts`.

Si te gusta la herramienta, una estrella en [GitHub](https://github.com/RomKade/romkade-manager) ayuda al proyecto.

