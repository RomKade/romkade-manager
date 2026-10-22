"""Captures d'écran : prendre l'écran du jeu en cours, les retrouver par jeu (gardées sur le Mac)."""

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import errors
from app.api.play import _client, now_playing
from app.device import screen

router = APIRouter(prefix="/api", tags=["screenshots"])


class ShotOut(BaseModel):
    name: str
    taken_at: str
    size: int
    url: str


class GameShotsOut(BaseModel):
    game_id: int
    title: str
    platform_code: str | None = None
    platform_label: str | None = None
    shots: list[ShotOut]


class TakenOut(BaseModel):
    game_id: int
    title: str
    shot: ShotOut


@router.post("/device/screenshot", response_model=TakenOut)
async def take_screenshot(request: Request) -> dict:
    """Capture l'écran du jeu en cours sur la console et la range avec les captures de ce jeu."""
    profile = await request.app.state.system.ensure()
    if not profile.capabilities()["screenshot"]:
        raise errors.AppError("screenshot_unsupported", f"La capture d'écran n'est pas prise en charge sur "
                              f"{profile.label}.", 409, {"system": profile.id})
    now = await now_playing(request)
    if not now.playing:
        raise errors.AppError("no_game_running", "Aucun jeu en cours sur la console : lance un jeu pour en faire "
                              "une capture.", 409)
    if now.game is None:
        raise errors.AppError("screenshot_game_unknown", "Ce jeu n'est pas dans la bibliothèque : synchronise la "
                              "carte, puis refais la capture.", 409, {"rom_path": now.rom_path})
    png = await screen.grab(request.app.state.device_runner, _client(request))
    g = now.game
    shot = await asyncio.to_thread(request.app.state.screenshots.add, g.id, png,
                                   {"title": g.title, "platform_code": g.platform.code,
                                    "platform_label": g.platform.label})
    return {"game_id": g.id, "title": g.title, "shot": shot}


@router.get("/screenshots", response_model=list[GameShotsOut])
async def all_screenshots(request: Request) -> list[dict]:
    """Toutes les captures, par jeu (le jeu capturé le plus récemment d'abord)."""
    return await asyncio.to_thread(request.app.state.screenshots.all)


@router.get("/games/{game_id}/screenshots", response_model=list[ShotOut])
async def game_screenshots(game_id: int, request: Request) -> list[dict]:
    return await asyncio.to_thread(request.app.state.screenshots.for_game, game_id)


@router.get("/screenshots/{game_id}/{name}")
async def screenshot_file(game_id: int, name: str, request: Request) -> FileResponse:
    return FileResponse(request.app.state.screenshots.path(game_id, name), media_type="image/png",
                        headers={"Cache-Control": "private, max-age=31536000, immutable"})


@router.delete("/screenshots/{game_id}/{name}", status_code=204)
async def delete_screenshot(game_id: int, name: str, request: Request) -> None:
    await asyncio.to_thread(request.app.state.screenshots.delete, game_id, name)
