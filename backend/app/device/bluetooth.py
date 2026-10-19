"""Bluetooth de la console : état, recherche, appairage, connexion, sortie son des jeux.

La console a BlueZ (bluetoothctl) et BlueALSA, mais rien ne démarre `bluealsa` : sans lui, une enceinte
s'appaire mais la connexion audio (A2DP) échoue. On le lance à la demande (processus détaché).

Son des jeux vers une enceinte : RetroArch est un programme 32 bits, le greffon ALSA de BlueALSA n'existe
qu'en 64 bits, et RetroArch (pilote alsathread) ouvre toujours la sortie « default ». On installe donc :
- ALSA_CONF : une sortie « agm_bt » qui envoie le son à `aplay` (64 bits) vers l'enceinte (voir alsa_conf) ;
- ASOUNDRC (/.asoundrc, voir volume.py) : « default » = notre volume, puis agm_bt, pour les programmes lancés avec
  HOME=/, c'est-à-dire les jeux lancés depuis Game Manager (app/device/launch.sh). Le menu de la console garde
  ses haut-parleurs.
« Remettre le son sur la console » supprime ALSA_CONF et remet ASOUNDRC vers les haut-parleurs.

Attention : au démarrage, le firmware efface les appairages (/mnt/vendor/ctrl/loadapp.sh vide
/var/lib/bluetooth). Il faut donc ré-appairer après chaque redémarrage de la console.
"""

import re
import shlex

from app import errors
from app.device.launcher import Runner
from app.device.ssh_client import DeviceClient
from app.device.volume import ASOUNDRC, SPEAKERS, asoundrc

MAC_RE = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$")
ALSA_CONF = "/etc/alsa/conf.d/60-agm-bluetooth.conf"
CLOCK_PCM = "plughw:ahubhdmi"
AUDIO_SINK = "0000110b"
HID = "00001124"
BLUEALSA_START = ("pidof bluealsa >/dev/null || { setsid nohup bluealsa -p a2dp-source > /tmp/agm-bluealsa.log 2>&1 "
                  "< /dev/null & sleep 1.5; }")

STATUS_COMMAND = (
    "echo @@SHOW; timeout 5 bluetoothctl show; "
    "for m in $(timeout 5 bluetoothctl devices | awk '/^Device/ {print $2}'); do echo \"@@DEV $m\"; timeout 5 bluetoothctl info $m; done; "
    "echo @@BLUEALSA; pidof bluealsa; "
    f"echo @@AUDIO; grep -q agm_bt {ASOUNDRC} 2>/dev/null && grep '^defaults.bluealsa.device' {ALSA_CONF} 2>/dev/null; true"
)


def check_mac(mac: str) -> str:
    mac = mac.upper()
    if not MAC_RE.fullmatch(mac):
        raise errors.AppError("bt_bad_address", "Adresse Bluetooth invalide", 422, {"address": mac})
    return mac


def _clean(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _fields(block: str) -> tuple[dict[str, str], list[str]]:
    fields, uuids = {}, []
    for line in block.splitlines():
        line = line.strip()
        if line.startswith("UUID:"):
            m = re.search(r"\(([0-9a-f]{8})-", line)
            if m:
                uuids.append(m.group(1))
        elif ":" in line:
            k, _, v = line.partition(":")
            fields.setdefault(k.strip(), v.strip())
    return fields, uuids


def device_kind(icon: str, uuids: list[str]) -> str:
    if AUDIO_SINK in uuids or icon.startswith("audio"):
        return "audio"
    if HID in uuids or icon.startswith("input"):
        return "controller" if "gaming" in icon or "joystick" in icon or icon == "input-gaming" else "input"
    return "other"


def _rssi(raw: str) -> int | None:
    """« -60 » ou « 0xffffffc4 (-60) » -> -60."""
    m = re.search(r"\((-?\d+)\)", raw) or re.match(r"(-?\d+)", raw)
    return int(m.group(1)) if m else None


def parse_status(out: str) -> dict:
    out = _clean(out)
    sections = re.split(r"^@@", out, flags=re.M)
    adapter: dict = {"present": False}
    devices = []
    bluealsa = False
    for sec in sections:
        head, _, body = sec.partition("\n")
        if head.startswith("SHOW"):
            f, _ = _fields(body)
            adapter = {"present": "Controller" in body, "powered": f.get("Powered") == "yes",
                       "discovering": f.get("Discovering") == "yes", "name": f.get("Alias") or f.get("Name")}
        elif head.startswith("DEV "):
            mac = head.split()[1]
            f, uuids = _fields(body)
            icon = f.get("Icon", "")
            devices.append({"address": mac, "name": f.get("Alias") or f.get("Name") or mac, "icon": icon,
                            "kind": device_kind(icon, uuids), "paired": f.get("Paired") == "yes",
                            "trusted": f.get("Trusted") == "yes", "connected": f.get("Connected") == "yes",
                            "rssi": _rssi(f.get("RSSI", ""))})
        elif head.startswith("BLUEALSA"):
            bluealsa = bool(body.strip())
    # Sortie choisie : nos deux fichiers sont en place (voir le docstring du module).
    m = re.search(r'defaults\.bluealsa\.device "([0-9A-F:]{17})"', out)
    devices.sort(key=lambda d: (not d["connected"], not d["paired"], d["name"].lower()))
    return {"adapter": adapter, "devices": devices, "bluealsa": bluealsa,
            "audio_output": m.group(1) if m else None}


async def status(run: Runner, client: DeviceClient) -> dict:
    _, out = await run(client, STATUS_COMMAND)
    return parse_status(out)


async def scan(run: Runner, client: DeviceClient, seconds: int = 12) -> dict:
    """Allume le Bluetooth, cherche les appareils à portée pendant `seconds` secondes, renvoie l'état."""
    await run(client, f"timeout 5 bluetoothctl power on; timeout {seconds + 5} bluetoothctl --timeout {seconds} scan on >/dev/null 2>&1; true",
              timeout=seconds + 20)
    return await status(run, client)


def connect_command(mac: str) -> str:
    """Une seule session bluetoothctl, comme à la main : agent, recherche active, appairage si besoin, confiance,
    connexion. Les manettes récentes (Xbox, 8BitDo…) sont en Bluetooth basse consommation : elles ne s'appairent
    que pendant une recherche active, ce que les commandes bluetoothctl séparées ne font pas. Chaque étape attend
    son résultat (`wait_for`) au lieu d'un délai fixe. Sort « @@RESULT connected|paired|absent ».
    """
    m = shlex.quote(mac)
    info = f"bluetoothctl info {m} 2>/dev/null"
    return f"""{BLUEALSA_START}
wait_for() {{ for _ in $(seq 1 "$2"); do {info} | grep -q "$1" && return 0; sleep 1; done; return 1; }}
{{
  echo 'power on'; echo 'agent NoInputNoOutput'; echo 'default-agent'; echo 'scan on'
  wait_for 'RSSI\\|Paired: yes' 8
  if ! {info} | grep -q 'Paired: yes'; then echo 'pair {mac}'; wait_for 'Paired: yes' 25; fi
  echo 'trust {mac}'; sleep 1
  echo 'connect {mac}'; wait_for 'Connected: yes' 20
  echo 'scan off'; sleep 1; echo 'quit'
}} | timeout 75 bluetoothctl > /tmp/agm-bt-connect.log 2>&1
if {info} | grep -q 'Connected: yes'; then echo '@@RESULT connected'
elif {info} | grep -q 'Paired: yes'; then echo '@@RESULT paired'
else echo '@@RESULT absent'; fi
grep -aoE 'Failed to [a-z]+: [A-Za-z.]+' /tmp/agm-bt-connect.log | tail -1"""


async def connect(run: Runner, client: DeviceClient, mac: str) -> dict:
    """Appaire si besoin, fait confiance et connecte. Démarre BlueALSA pour qu'une enceinte puisse recevoir le son."""
    mac = check_mac(mac)
    _, out = await run(client, connect_command(mac), timeout=100)
    result = re.search(r"@@RESULT (\w+)", out)
    detail = out.split("@@RESULT", 1)[-1].split("\n", 1)[-1].strip()
    state = result.group(1) if result else "absent"
    if state == "paired":
        raise errors.AppError("bt_paired_not_connected", "Appareil appairé, mais il ne répond pas. Réveille-le (bouton "
                              "Xbox / Home d'une manette, bouton marche d'une enceinte) puis clique sur « Connecter ».",
                              409, {"detail": detail})
    if state != "connected":
        raise errors.AppError("bt_connect_failed", "La connexion Bluetooth a échoué. Vérifie que l'appareil est allumé, "
                              "proche, et en mode appairage s'il n'a jamais été connecté.", 502, {"detail": detail})
    return await status(run, client)


async def disconnect(run: Runner, client: DeviceClient, mac: str) -> dict:
    mac = shlex.quote(check_mac(mac))
    await run(client, f"timeout 10 bluetoothctl disconnect {mac}; true")
    return await status(run, client)


async def forget(run: Runner, client: DeviceClient, mac: str) -> dict:
    mac = shlex.quote(check_mac(mac))
    await run(client, f"timeout 10 bluetoothctl remove {mac}; true")
    return await status(run, client)


def alsa_conf(mac: str) -> str:
    """Sortie ALSA « agm_bt » pour RetroArch.

    RetroArch est un programme 32 bits, et le greffon ALSA de BlueALSA n'existe qu'en 64 bits : RetroArch ne
    peut pas ouvrir « bluealsa » directement. Le greffon « file » (intégré à ALSA, donc aussi en 32 bits) envoie
    le son dans une commande : aplay (64 bits) le joue sur l'enceinte. Si l'enceinte n'est pas là (ou se
    déconnecte en plein jeu), un second aplay joue la suite sur les haut-parleurs de la console (SPEAKERS) ; en
    dernier recours, `cat` absorbe le son : le jeu tourne sans son au lieu de se bloquer.

    Le greffon « file » recopie le son vers une vraie sortie, CLOCK_PCM : la sortie HDMI, muette sans câble.
    Elle donne à RetroArch l'horloge temps réel dont sa synchronisation audio a besoin ; avec une sortie
    « null », sans horloge, le son arrivait par à-coups.
    """
    aplay = "env -u LD_LIBRARY_PATH aplay -q -t raw -f S16_LE -r 48000 -c 2 -D"
    play = f"{aplay} agm_bt_out - 2>/dev/null || {aplay} {SPEAKERS} - 2>/dev/null || exec cat > /dev/null"
    return f"""# Game Manager : son des jeux RetroArch vers l'enceinte Bluetooth {mac}. Supprimable sans risque.
defaults.bluealsa.device "{mac}"
defaults.bluealsa.profile "a2dp"
pcm.agm_bt_out {{
    type plug
    slave.pcm "bluealsa"
}}
pcm.agm_bt {{
    type plug
    slave {{
        pcm {{
            type file
            slave.pcm "{CLOCK_PCM}"
            file "|{play}"
            format "raw"
        }}
        format S16_LE
        rate 48000
        channels 2
    }}
}}
"""


async def set_audio_output(run: Runner, client: DeviceClient, mac: str | None) -> dict:
    """Son des jeux lancés depuis Game Manager : vers l'enceinte `mac`, ou None pour les haut-parleurs."""
    if mac:
        conf = shlex.quote(alsa_conf(check_mac(mac)))
        cmd = (f"{BLUEALSA_START}; printf %s {conf} > {ALSA_CONF} && "
               f"printf %s {shlex.quote(asoundrc('agm_bt'))} > {ASOUNDRC}")
    else:
        cmd = f"rm -f {ALSA_CONF}; printf %s {shlex.quote(asoundrc())} > {ASOUNDRC}"
    await run(client, cmd)
    return await status(run, client)


# Carillon du test sonore : une demi-seconde de silence (une enceinte qui se réveille avale le début du son), puis
# deux notes montantes adoucies, en 48 kHz stéréo 16 bits sur la sortie standard. Volume modéré (30 %).
CHIME = """import math, struct, sys
r = 48000
out = bytearray(4 * r // 2)
for f in (660, 880):
    n = int(r * 0.35)
    for i in range(n):
        v = int(9800 * math.sin(2 * math.pi * f * i / r) * min(1, i / 480) * (1 - i / n))
        out += struct.pack("<hh", v, v)
sys.stdout.buffer.write(bytes(out))
"""


def sound_test_command(mac: str) -> str:
    """Joue CHIME sur l'enceinte `mac` par BlueALSA, comme le son des jeux (aplay 64 bits, profil A2DP), sans
    passer par la sortie des jeux : on vérifie l'enceinte elle-même. Sort « @@RESULT played|in_use|absent|failed ».
    Un jeu qui envoie déjà son son à l'enceinte la garde pour lui : BlueALSA refuse un second flux (« busy »)."""
    m = shlex.quote(mac)
    aplay = f"env -u LD_LIBRARY_PATH timeout 15 aplay -q -t raw -f S16_LE -r 48000 -c 2 -D bluealsa:DEV={mac},PROFILE=a2dp -"
    return f"""{BLUEALSA_START}
timeout 5 bluetoothctl info {m} 2>/dev/null | grep -q 'Connected: yes' || {{ echo '@@RESULT absent'; exit 0; }}
if python3 -c {shlex.quote(CHIME)} | {aplay} 2>/tmp/agm-bt-test.log; then echo '@@RESULT played'
elif grep -q 'resource busy' /tmp/agm-bt-test.log; then echo '@@RESULT in_use'
else echo '@@RESULT failed'; grep -m1 -aoE "Couldn't [^:]+: .*|aplay: .*" /tmp/agm-bt-test.log; fi"""


async def sound_test(run: Runner, client: DeviceClient, mac: str) -> str:
    """Test sonore : un court carillon sur l'enceinte (« played »), ou « in_use » si un jeu y envoie déjà son son.
    Erreur claire si le son ne peut pas y aller."""
    mac = check_mac(mac)
    _, out = await run(client, sound_test_command(mac), timeout=30)
    result = re.search(r"@@RESULT (\w+)", out)
    state = result.group(1) if result else "failed"
    if state == "absent":
        raise errors.AppError("bt_test_not_connected", "L'appareil n'est pas connecté : connecte-le d'abord, puis "
                              "refais le test.", 409, {"address": mac})
    if state not in ("played", "in_use"):
        detail = out.split("@@RESULT", 1)[-1].split("\n", 1)[-1].strip()
        raise errors.AppError("bt_test_failed", "Le son n'a pas pu partir vers l'appareil. Éteins-le et rallume-le, "
                              "reconnecte-le, puis refais le test.", 502, {"detail": detail})
    return state
