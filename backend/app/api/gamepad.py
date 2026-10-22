"""Manette de l'ordinateur : WebSocket qui relaie une manette du navigateur vers la console (app/device/gamepad.py).

Paramètre `token` : identifiant du relais (4 à 16 caractères a-z0-9), qui ressort dans le champ `remote` de la
manette virtuelle (GET /api/players) : l'interface sait ainsi quelle manette de la console attribuer au joueur.

Messages du navigateur (JSON) : {"b": [valeurs des boutons, 0 à 1], "a": [axes, -1 à 1]} à chaque changement,
{"release": true} pour tout relâcher. Réponses : {"ready": true} quand la manette existe sur la console,
{"error": {...}} si elle n'a pas pu être créée (la connexion se ferme alors).
"""

import json

import asyncssh
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app import errors
from app.device.gamepad import Relay
from app.device.ssh_client import DeviceClient

router = APIRouter(prefix="/api/gamepad", tags=["gamepad"])
MAX_RELAYS = 4  # une manette virtuelle par joueur de RetroArch, au plus
_active: set[WebSocket] = set()


def _numbers(value, size: int) -> list[float]:
    if not isinstance(value, list):
        return []
    return [float(v) for v in value[:size] if isinstance(v, (int, float)) and not isinstance(v, bool)]


@router.websocket("/ws")
async def gamepad_ws(ws: WebSocket, token: str = "") -> None:
    await ws.accept()
    st = ws.app.state
    try:
        p = st.system.profile()
        if not p.capabilities()["players"]:
            raise errors.AppError("gamepad_unsupported", f"La manette de l'ordinateur n'est pas prise en charge sur {p.label}.",
                                  409, {"system": p.id})
        if len(_active) >= MAX_RELAYS:
            raise errors.AppError("gamepad_too_many", f"Déjà {MAX_RELAYS} manettes relayées vers la console.", 409)
        _active.add(ws)
        async with Relay(DeviceClient(st.settings_store.load(), st.credentials, st.host_keys), token) as relay:
            await ws.send_json({"ready": True})
            try:
                while True:
                    try:
                        msg = json.loads(await ws.receive_text())
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(msg, dict) or msg.get("release"):
                        relay.release()
                    else:
                        relay.send(_numbers(msg.get("b"), 32), _numbers(msg.get("a"), 8))
            except (BrokenPipeError, asyncssh.Error) as exc:
                raise errors.AppError("gamepad_relay_lost", "Connexion à la console perdue.", 502,
                                      {"reason": str(exc)}) from exc
    except WebSocketDisconnect:
        pass
    except errors.AppError as exc:
        exc = st.presence.explain(exc, st.settings_store.load().host)
        try:
            await ws.send_json(exc.to_dict())
            await ws.close()
        except (RuntimeError, WebSocketDisconnect):
            pass
    finally:
        _active.discard(ws)
