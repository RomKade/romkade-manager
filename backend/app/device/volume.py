"""Volume des jeux lancés depuis Game Manager (firmware d'origine), réglable pendant le jeu.

Ce qui ne marche pas sur cette console :
- le mixeur de la puce son : pendant un jeu, ses réglages sont verrouillés (amixer ne change rien, sans erreur) ;
- les commandes réseau VOLUME_UP / VOLUME_DOWN de RetroArch : ignorées (son volume enregistré en quittant ne
  bouge pas). Seule MUTE marche.

On ajoute donc notre propre volume logiciel ALSA (`softvol`) devant la sortie des jeux. ASOUNDRC (/.asoundrc, lu
par les jeux lancés depuis Game Manager, qui tournent avec HOME=/) fait de « default » une chaîne
volume (CONTROL, -30 à +12 dB) -> coupure (interrupteur) -> sortie : haut-parleurs, ou enceinte Bluetooth
(agm_bt, voir bluetooth.py). Le réglage CONTROL apparaît sur la carte 0 quand un jeu ouvre la sortie et reste
jusqu'au redémarrage : amixer le lit et le règle à tout moment.
launch.sh met le volume de RetroArch (audio_volume) à 0 dB : c'est ce réglage-ci qui fait le volume.

Jeu lancé depuis le menu de la console :
- RetroArch n'utilise pas ASOUNDRC et verrouille le mixeur : seule la coupure marche (MUTE de RetroArch) ;
- un émulateur autonome du firmware (pcsx…) ne verrouille pas le mixeur : on règle « digital volume » (HW_ELEM).
"""

import re

from app import errors
from app.device.launcher import Runner
from app.device.ssh_client import DeviceClient

ASOUNDRC = "/.asoundrc"
CONTROL = "Game Manager"
# Haut du curseur : +12 dB, comme le maximum de RetroArch. Les jeux (PS1, arcade) sortent souvent bas : à 0 dB,
# même tout au maximum, le son restait faible sur les haut-parleurs.
MAX_DB = 12.0
VERSION = "agm-audio-3"  # change quand asoundrc() change : launcher réécrit alors /.asoundrc
SPEAKERS = "agm_speakers"  # défini dans ASOUNDRC (voir asoundrc)

# Ce que fait le « default » du firmware (/etc/asound.conf) à l'ouverture : ampli, sorties, mixeur à fond.
FIRMWARE_HOOKS = [("LINEOUT Switch", 1), ("SPK Switch", 1), ("OutputL Mixer DACL Switch", 1),
                  ("OutputR Mixer DACR Switch", 1), ("digital volume", 63)]


def asoundrc(slave: str = SPEAKERS) -> str:
    """/.asoundrc : sortie « default » des jeux lancés depuis Game Manager, avec notre volume devant `slave`.

    agm_speakers reproduit le « default » du firmware (mêmes hooks), en 16 bits imposés : sans cela, la chaîne
    de volume envoyait du 32 bits à la puce son, et le son sortait très faible.
    """
    hooks = "\n".join(f'            {{ name "{name}" preserve true lock true value {value} }}'
                       for name, value in FIRMWARE_HOOKS)
    return f"""# Game Manager : volume des jeux lancés depuis Game Manager (supprimable sans risque) {VERSION}
pcm.!default agm_vol
pcm.agm_vol {{
    type plug
    slave.pcm {{
        type softvol
        slave.pcm {{
            type softvol
            slave.pcm "{slave}"
            control {{ name "{CONTROL} Playback Switch"; card 0 }}
            resolution 2
        }}
        control {{ name "{CONTROL} Playback Volume"; card 0 }}
        min_dB -30.0
        max_dB {MAX_DB}
        resolution {round((MAX_DB + 30) * 2) + 1}
    }}
}}
pcm.agm_speakers {{
    type plug
    slave {{
        pcm {{
            type hooks
            slave.pcm "hw:audiocodec"
            hooks.0 {{
                type ctl_elems
                hook_args [
{hooks}
                ]
            }}
        }}
        format S16_LE
    }}
}}
"""


# Réglages lus et écrits par leur nom exact (cget / cset) : « amixer sset 'Game Manager' » mélangeait notre
# réglage avec tout autre élément au nom proche sur la carte (un reste d'essai, par exemple).
VOLUME_ELEM = f"name='{CONTROL} Playback Volume'"
SWITCH_ELEM = f"name='{CONTROL} Playback Switch'"
# Mixeur de la puce son : il règle les émulateurs autonomes du firmware (pcsx…), qui ne le verrouillent pas.
HW_ELEM = "name='digital volume'"
HW_SAVED = "/tmp/agm-volume"  # niveau d'avant la coupure (effacé au redémarrage)
HW_DEFAULT = 63


def _status_command() -> str:
    from app.device.launcher import GAME_PROCESSES  # launcher importe ce module pour /.asoundrc

    return (
        f"echo @@VOL; amixer -c 0 cget {VOLUME_ELEM} 2>/dev/null; "
        f"echo @@SW; amixer -c 0 cget {SWITCH_ELEM} 2>/dev/null; "
        f"echo @@HW; amixer -c 0 cget {HW_ELEM} 2>/dev/null; "
        f"echo @@SAVED; cat {HW_SAVED} 2>/dev/null; "
        # Jeu en cours : processus, et AGM_LAUNCH=1 s'il a été lancé par Game Manager (launch.sh).
        "echo @@GAME; for p in " + " ".join(GAME_PROCESSES) + "; do pid=$(pidof $p | awk '{print $1}'); "
        "if [ -n \"$pid\" ]; then echo \"$p\"; tr '\\0' '\\n' < /proc/$pid/environ | grep -q '^AGM_LAUNCH=1' && echo agm; "
        "break; fi; done; true"
    )


RA_MUTE = "echo -n MUTE > /dev/udp/127.0.0.1/55355"


def _mixer(text: str) -> tuple[int, int] | None:
    """(valeur, maximum) d'un `amixer cget` d'un réglage numérique."""
    top = re.search(r"\bmax=(\d+)", text)
    value = re.search(r"^\s*: values=(\d+)", text, re.M)
    return (int(value.group(1)), int(top.group(1))) if top and value and int(top.group(1)) > 0 else None


def parse_status(out: str) -> dict:
    """Réglage qui agit sur le jeu en cours (`mode`) :
    - « game_manager » : jeu lancé par Game Manager (RetroArch, notre volume logiciel) ;
    - « console » : émulateur autonome du firmware (pcsx…) : mixeur de la puce son ;
    - « retroarch » : RetroArch lancé depuis le menu de la console : mixeur verrouillé, seule la coupure marche.
    Sans jeu : notre volume s'il existe (prochain jeu lancé par Game Manager).
    """
    parts = dict((head.strip(), body) for head, _, body in
                 (sec.partition("\n") for sec in re.split(r"^@@", out, flags=re.M) if sec))
    game = parts.get("GAME", "").split()
    process, by_agm = (game[0] if game else None), "agm" in game[1:]
    soft = _mixer(parts.get("VOL", ""))
    if process is None or (process == "retroarch" and by_agm):
        mode = "game_manager" if soft else "none"
    elif process == "retroarch":
        mode = "retroarch"
    else:
        mode = "console"
    if mode == "game_manager":
        level, top = soft  # type: ignore[misc]
        switch = re.search(r"^\s*: values=(on|off)", parts.get("SW", ""), re.M)
        muted = bool(switch) and switch.group(1) == "off"
    elif mode == "console" and (hw := _mixer(parts.get("HW", ""))):
        level, top = hw
        muted = level == 0
    else:
        level, top, muted = 0, 0, False
    return {"mode": mode, "adjustable": top > 0, "percent": round(level * 100 / top) if top else 0, "muted": muted,
            "max": top, "level": level, "game_running": process is not None, "process": process,
            "restore": int(m.group()) if (m := re.search(r"\d+", parts.get("SAVED", ""))) else None}


async def status(run: Runner, client: DeviceClient) -> dict:
    _, out = await run(client, _status_command())
    return parse_status(out)


async def set_volume(run: Runner, client: DeviceClient, percent: int | None, muted: bool | None) -> dict:
    """Règle le volume (0-100 %), coupe ou rétablit le son du jeu en cours. Un volume donné rétablit le son."""
    if percent is not None and not 0 <= percent <= 100:
        raise errors.AppError("volume_invalid", "Le volume va de 0 à 100 %.", 422, {"percent": percent})
    st = await status(run, client)
    if percent is None and muted is None:
        return st
    if st["mode"] == "game_manager":
        if percent is not None:
            raw = round(percent * st["max"] / 100)
            sw = "off" if percent == 0 else "on"
            cmd = f"amixer -q -c 0 cset {VOLUME_ELEM} {raw},{raw} && amixer -q -c 0 cset {SWITCH_ELEM} {sw},{sw}"
        else:
            sw = "off" if muted else "on"
            cmd = f"amixer -q -c 0 cset {SWITCH_ELEM} {sw},{sw}"
    elif st["mode"] == "console" and st["adjustable"]:
        hw = f"amixer -q -c 0 cset {HW_ELEM}"
        if percent is not None:
            cmd = f"{hw} {round(percent * st['max'] / 100)}; rm -f {HW_SAVED}"
        elif muted:
            keep = f"echo {st['level']} > {HW_SAVED}; " if st["level"] > 0 else ""
            cmd = f"{keep}{hw} 0"
        else:
            cmd = f"{hw} {st['restore'] or (st['level'] if st['level'] > 0 else HW_DEFAULT)}; rm -f {HW_SAVED}"
    elif st["mode"] == "retroarch" and percent is None:
        cmd = RA_MUTE  # seule la coupure de RetroArch (bascule) marche
    else:
        raise errors.AppError("volume_not_ready", "Le volume de ce jeu se règle avec les touches de la console. "
                              "Lancé depuis Game Manager, il se règle aussi ici.", 409, {"mode": st["mode"]})
    code, out = await run(client, f"{{ {cmd}; }} 2>&1")
    if code != 0 and re.search(r"not permitted", out, re.I):
        # Réglage créé par le RetroArch en cours (premier jeu depuis le démarrage, avant que launch.sh ne le crée
        # lui-même) : verrouillé par lui jusqu'à la fin du jeu.
        raise errors.AppError("volume_locked", "Le jeu en cours a verrouillé le volume : quitte-le et relance-le "
                              "depuis Game Manager, le curseur répondra.", 409)
    st = await status(run, client)
    if cmd == RA_MUTE:
        st["muted"] = bool(muted)  # RetroArch ne dit pas s'il est coupé : on renvoie ce qu'on a demandé
    return st
