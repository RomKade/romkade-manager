"""Sortie du son des jeux lancés depuis Game Manager : haut-parleurs de la console, TV (HDMI) ou enceinte Bluetooth.

Le choix est écrit dans les fichiers ALSA lus par ces jeux (voir volume.py et bluetooth.py), rien d'autre à garder :
- « tv » : /.asoundrc d'origine. Câble HDMI branché, le RetroArch du firmware ouvre « playback_hdmi » : le son va
  à la TV ; sans câble, il reste sur les haut-parleurs. C'est la sortie par défaut ;
- « speakers » : /.asoundrc qui redéfinit aussi « playback_hdmi » sur les haut-parleurs (même TV branchée) ;
- « bluetooth » : sortie agm_bt vers l'enceinte (bluetooth.set_audio_output).
Le menu de la console garde sa propre sortie. Le choix vaut à partir du prochain jeu lancé.
"""

import re
import shlex

from app import errors
from app.device import bluetooth as bt
from app.device.launcher import GAME_PROCESSES, Runner
from app.device.ssh_client import DeviceClient
from app.device.volume import ASOUNDRC, SPEAKERS, asoundrc, install_command

HDMI_STATE = "/sys/class/switch/hdmi/state"  # « HDMI=1 » câble branché (pilote sunxi)
HDMI_PCM = "plughw:ahubhdmi"

STATUS_COMMAND = (f"echo @@HDMI; cat {HDMI_STATE} 2>/dev/null; "
                  f"echo @@RC; grep -q playback_hdmi {ASOUNDRC} 2>/dev/null && echo speakers; true")


def parse(out: str, bt_status: dict) -> dict:
    hdmi = bool(re.search(r"HDMI=1", out))
    rc = out.split("@@RC", 1)[-1]
    address = bt_status["audio_output"]
    output = "bluetooth" if address else "speakers" if "speakers" in rc else "tv"
    devices = [d for d in bt_status["devices"] if d["kind"] == "audio" and (d["paired"] or d["connected"])]
    return {"output": output, "address": address, "hdmi": hdmi, "devices": devices}


async def status(run: Runner, client: DeviceClient) -> dict:
    _, out = await run(client, STATUS_COMMAND)
    return parse(out, await bt.status(run, client))


async def set_output(run: Runner, client: DeviceClient, output: str, address: str | None = None) -> dict:
    """Envoie le son des prochains jeux vers `output` ; une enceinte pas encore connectée est d'abord connectée."""
    if output == "bluetooth":
        if not address:
            raise errors.AppError("sound_no_device", "Choisis l'enceinte ou le casque Bluetooth.", 422)
        device = next((d for d in (await bt.status(run, client))["devices"] if d["address"] == bt.check_mac(address)), None)
        if not device or not device["connected"]:
            await bt.connect(run, client, address)
        await bt.set_audio_output(run, client, address)
    else:
        rc = shlex.quote(asoundrc(SPEAKERS, tv=output == "tv"))
        await run(client, f"rm -f {bt.ALSA_CONF}; printf %s {rc} > {ASOUNDRC}")
    return await status(run, client)


def test_command(output: str) -> str:
    """Joue le carillon de bluetooth.CHIME sur les haut-parleurs (sortie des jeux, avec ses réglages de la puce son)
    ou sur la TV. Sort « @@RESULT played|in_use|menu|absent|failed ». Sortie occupée : par un jeu en cours (in_use),
    sinon par le menu de la console (menu), qui garde la sortie TV ouverte ; les jeux lancés depuis Game Manager
    ferment le menu avant de démarrer (launch.sh), leur son passe donc quand même."""
    if output == "tv":
        check, device = f"grep -q HDMI=1 {HDMI_STATE} 2>/dev/null || {{ echo '@@RESULT absent'; exit 0; }}", HDMI_PCM
    else:
        check, device = install_command(), SPEAKERS
    aplay = f"HOME=/ LC_ALL=C env -u LD_LIBRARY_PATH timeout 15 aplay -q -t raw -f S16_LE -r 48000 -c 2 -D {device} -"
    return f"""{check}
if python3 -c {shlex.quote(bt.CHIME)} | {aplay} 2>/tmp/agm-sound-test.log; then echo '@@RESULT played'
elif grep -qi 'busy' /tmp/agm-sound-test.log; then
  if pidof {" ".join(GAME_PROCESSES)} >/dev/null; then echo '@@RESULT in_use'; else echo '@@RESULT menu'; fi
else echo '@@RESULT failed'; grep -m1 -a 'aplay: .*' /tmp/agm-sound-test.log; fi"""


async def sound_test(run: Runner, client: DeviceClient, output: str, address: str | None = None) -> str:
    """Test sonore de la sortie : « played », « in_use » si un jeu s'en sert déjà, « menu » si le menu de la console
    la garde ouverte. Erreur claire sinon."""
    if output == "bluetooth":
        if not address:
            raise errors.AppError("sound_no_device", "Choisis l'enceinte ou le casque Bluetooth.", 422)
        return await bt.sound_test(run, client, address)
    _, out = await run(client, test_command(output), timeout=30)
    result = re.search(r"@@RESULT (\w+)", out)
    state = result.group(1) if result else "failed"
    if state == "absent":
        raise errors.AppError("sound_no_tv", "La console n'est pas branchée à une TV : branche le câble HDMI, puis "
                              "refais le test.", 409)
    if state not in ("played", "in_use", "menu"):
        detail = out.split("@@RESULT", 1)[-1].split("\n", 1)[-1].strip()
        raise errors.AppError("sound_test_failed", "Le son n'a pas pu sortir. Quitte le jeu en cours s'il y en a un, "
                              "puis refais le test.", 502, {"detail": detail})
    return state
