"""Captures d'écran des jeux, gardées sur le Mac : un dossier par jeu.

<données>/screenshots/<id du jeu>/<AAAAMMJJ-HHMMSS>.png   + game.json (titre et console au moment de la capture,
pour retrouver les captures d'un jeu sorti du catalogue).
"""

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from app import errors

NAME_RE = re.compile(r"^\d{8}-\d{6}(-\d+)?\.png$")


class ScreenshotStore:
    def __init__(self, root: Path):
        self.root = root

    def _game_dir(self, game_id: int) -> Path:
        return self.root / str(int(game_id))

    def path(self, game_id: int, name: str) -> Path:
        p = self._game_dir(game_id) / name
        if not NAME_RE.fullmatch(name) or not p.is_file():
            raise errors.AppError("screenshot_not_found", "Capture introuvable", 404, {"game_id": game_id, "name": name})
        return p

    def add(self, game_id: int, png: bytes, game: dict) -> dict:
        """Range une capture ; `game` : titre et console, gardés à côté."""
        d = self._game_dir(game_id)
        d.mkdir(parents=True, exist_ok=True)
        stamp, n = datetime.now(UTC).strftime("%Y%m%d-%H%M%S"), 1
        name = f"{stamp}.png"
        while (d / name).exists():
            n += 1
            name = f"{stamp}-{n}.png"
        (d / name).write_bytes(png)
        (d / "game.json").write_text(json.dumps(game, ensure_ascii=False))
        return self._shot(game_id, d / name)

    def delete(self, game_id: int, name: str) -> None:
        p = self.path(game_id, name)
        p.unlink()
        d = p.parent
        if not any(d.glob("*.png")):  # plus aucune capture : le dossier du jeu part aussi
            (d / "game.json").unlink(missing_ok=True)
            d.rmdir()

    @staticmethod
    def _shot(game_id: int, p: Path) -> dict:
        taken = datetime.strptime(p.stem[:15], "%Y%m%d-%H%M%S").replace(tzinfo=UTC)
        return {"name": p.name, "taken_at": taken.isoformat(), "size": p.stat().st_size,
                "url": f"/api/screenshots/{game_id}/{p.name}"}

    def for_game(self, game_id: int) -> list[dict]:
        """Captures d'un jeu, la plus récente d'abord."""
        d = self._game_dir(game_id)
        return [self._shot(game_id, p) for p in sorted(d.glob("*.png"), reverse=True) if NAME_RE.fullmatch(p.name)]

    def all(self) -> list[dict]:
        """Jeux qui ont des captures, du plus récemment capturé au plus ancien."""
        out = []
        if not self.root.is_dir():
            return out
        for d in self.root.iterdir():
            if not d.name.isdigit() or not d.is_dir():
                continue
            shots = self.for_game(int(d.name))
            if not shots:
                continue
            try:
                game = json.loads((d / "game.json").read_text())
            except (OSError, ValueError):
                game = {}
            out.append({"game_id": int(d.name), "title": game.get("title") or f"#{d.name}",
                        "platform_code": game.get("platform_code"), "platform_label": game.get("platform_label"),
                        "shots": shots})
        out.sort(key=lambda g: g["shots"][0]["name"], reverse=True)
        return out
