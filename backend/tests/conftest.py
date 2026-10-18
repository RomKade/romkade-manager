"""Serveur SSH/SFTP AsyncSSH en mémoire qui imite l'arborescence de la console.

Le serveur enregistre toute tentative d'écriture : les tests vérifient qu'il n'y en a aucune.
"""

import os
import tempfile
from pathlib import Path

os.environ.setdefault("ANBERNIC_DATA_DIR", tempfile.mkdtemp(prefix="agm-test-"))
os.environ.setdefault("AGM_EXTRA_HOSTS", "test,t")  # noms d'hôte des clients httpx de test

import asyncssh  # noqa: E402
import httpx  # noqa: E402
import pytest  # noqa: E402

from app.config import DeviceSettings, SettingsStore  # noqa: E402
from app.credentials import MemoryStore  # noqa: E402
from app.main import create_app  # noqa: E402

PASSWORD = "secret-test"
WRITE_FLAGS = asyncssh.FXF_WRITE | asyncssh.FXF_APPEND | asyncssh.FXF_CREAT | asyncssh.FXF_TRUNC


def build_card(root: Path) -> Path:
    roms = root / "mnt" / "mmc" / "Roms"
    files = {
        "PS/Ridge Racer (Europe).chd": 1200,
        "PS/Final Fantasy VII/FF7 (Disc 1).cue": 80,
        "PS/Final Fantasy VII/FF7 (Disc 1).bin": 5000,
        "PS/Imgs/Ridge Racer (Europe).png": 300,
        "SFC/Super Mario World (USA).smc": 512,
        "SFC/readme.txt": 10,
        "SFC/.DS_Store": 6,
        "SFC/._Super Mario World (USA).smc": 4,
        "SFC/a/b/c/d/too-deep.smc": 1,
        "ZZNEW/mystery.bin": 42,
        "PORTS/CaveStory.sh": 20,
        "PORTS/cavestory/data.pxm": 70,
        "APPS/tool.py": 15,
        "MD/Sonic The Hedgehog (Europe).md": 524288,
        "MD/Imgs/Sonic The Hedgehog (Europe).png": 64,
        "MD/Imgs/Orphan Game.png": 32,
        "MD/Imgs/Thumbs.db": 12,
    }
    for rel, size in files.items():
        p = roms / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\0" * size)
    # Sauvegardes, hors du dossier des ROMs comme sur la vraie console.
    card = roms.parent
    saves = {
        "saves_RA/Roms/SFC/Snes9x/Super Mario World (USA).srm": b"SRAM-MARIO",
        "states_RA/Roms/SFC/Snes9x/Super Mario World (USA).state1": b"STATE1",
        "states_RA/Roms/SFC/Snes9x/Super Mario World (USA).state.auto": b"AUTO",
        "states_RA/Roms/SFC/Snes9x/Super Mario World (USA).state1.png": b"PNG",
        "save/Roms/MD/Sonic The Hedgehog (Europe).md.st0": b"ST0",
        "save/Roms/MD/Sonic The Hedgehog (Europe).md.st0pic": b"PIC",
        "states_RA/Roms/MD/Genesis Plus GX/Unknown Game (USA).state": b"X",
    }
    for rel, data in saves.items():
        p = card / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    (roms / "SFC" / "Imgs").mkdir()
    (roms / "LINKED").symlink_to("/etc")
    (roms / "SFC" / "escape.smc").symlink_to("/etc/hostname")
    return roms


class RecordingSFTPServer(asyncssh.SFTPServer):
    """Enregistre toute écriture. Par défaut les refuse ; `allow_writes = True` les autorise (tests de transfert)."""

    write_attempts: list[str] = []
    statvfs_supported = True
    allow_writes = False
    free_bytes: int | None = None  # simule l'espace libre de la carte

    def __init__(self, chan):
        super().__init__(chan, chroot=self.chroot_dir)

    def _w(self, op, path, *more):
        p = path.decode() if isinstance(path, bytes) else path
        type(self).write_attempts.append(f"{op} {p}")
        if not self.allow_writes:
            raise asyncssh.SFTPPermissionDenied("write attempt recorded by test server")

    def open(self, path, pflags, attrs):
        if pflags & WRITE_FLAGS:
            self._w("open-write", path)
        return super().open(path, pflags, attrs)

    def remove(self, path):
        self._w("remove", path)
        return super().remove(path)

    def rename(self, oldpath, newpath):
        self._w("rename", oldpath)
        type(self).write_attempts.append(f"rename-to {newpath.decode() if isinstance(newpath, bytes) else newpath}")
        return super().rename(oldpath, newpath)

    def posix_rename(self, oldpath, newpath):
        self._w("posix_rename", oldpath)
        return super().posix_rename(oldpath, newpath)

    def mkdir(self, path, attrs):
        self._w("mkdir", path)
        return super().mkdir(path, attrs)

    def rmdir(self, path): self._w("rmdir", path); return super().rmdir(path)
    def setstat(self, path, attrs): self._w("setstat", path); return super().setstat(path, attrs)
    def symlink(self, oldpath, newpath): self._w("symlink", newpath); return super().symlink(oldpath, newpath)
    def link(self, oldpath, newpath): self._w("link", newpath); return super().link(oldpath, newpath)

    def statvfs(self, path):
        if not self.statvfs_supported:
            raise asyncssh.SFTPOpUnsupported("statvfs not supported")
        v = super().statvfs(path)  # os.statvfs_result
        if self.free_bytes is not None:
            free = self.free_bytes // (v.f_frsize or v.f_bsize)
            return asyncssh.SFTPVFSAttrs(v.f_bsize, v.f_frsize, v.f_blocks, free, free, v.f_files, v.f_ffree,
                                         v.f_favail, 0, 0, v.f_namemax)
        return v


class PasswordServer(asyncssh.SSHServer):
    connections = 0

    def connection_made(self, conn):
        type(self).connections += 1

    def begin_auth(self, username): return True
    def password_auth_supported(self): return True
    def validate_password(self, username, password): return username == "root" and password == PASSWORD


class ShellBehaviour:
    """Comportement des commandes simulées sur la console (sha256sum)."""
    sha256 = "ok"  # ok | missing | wrong
    chroot: str = ""


def df_process(process: asyncssh.SSHServerProcess) -> None:
    cmd = process.command or ""
    if cmd.startswith("sha256sum "):
        import hashlib
        import shlex
        if ShellBehaviour.sha256 == "missing":
            process.stderr.write("sh: sha256sum: not found\n")
            process.exit(127)
            return
        path = shlex.split(cmd)[1]
        data = open(ShellBehaviour.chroot + path, "rb").read()
        digest = hashlib.sha256(data + (b"x" if ShellBehaviour.sha256 == "wrong" else b"")).hexdigest()
        process.stdout.write(f"{digest}  {path}\n")
        process.exit(0)
        return
    if cmd.startswith("df -kP"):
        process.stdout.write("Filesystem 1024-blocks Used Available Capacity Mounted on\n"
                             "/dev/mmcblk1p1 62000000 12000000 50000000 20% /mnt/mmc\n")
        process.exit(0)
    else:
        process.stderr.write("refused\n")
        process.exit(1)


@pytest.fixture
def card(tmp_path):
    chroot = tmp_path / "card"
    build_card(chroot)
    return chroot


@pytest.fixture
async def ssh_server(card):
    host_key = asyncssh.generate_private_key("ssh-ed25519")

    class Factory(RecordingSFTPServer):
        chroot_dir = str(card)
        write_attempts: list[str] = []
        statvfs_supported = True
        allow_writes = False
        free_bytes = None

    ShellBehaviour.sha256 = "ok"
    ShellBehaviour.chroot = str(card)

    server = await asyncssh.create_server(
        PasswordServer, "127.0.0.1", 0, server_host_keys=[host_key],
        sftp_factory=Factory, process_factory=df_process,
    )
    port = server.sockets[0].getsockname()[1]
    yield {"port": port, "host_key": host_key, "sftp": Factory, "chroot": card}
    server.close()
    await server.wait_closed()


@pytest.fixture
async def app_factory(tmp_path, ssh_server):
    created = []

    def make(password: str | None = PASSWORD, trust: bool = True, **overrides):
        store = SettingsStore(tmp_path / "settings.json")
        params = {"host": "127.0.0.1", "port": ssh_server["port"], "username": "root",
                  "roms_root": "/mnt/mmc/Roms", "connect_timeout": 5, "system": "anbernic-stock-mod",
                  **overrides}
        store.save(DeviceSettings(**params))
        creds = MemoryStore()
        if password:
            creds.set_password("127.0.0.1", "root", password)
        app = create_app(store, creds, tmp_path / "known_hosts", db_path=tmp_path / "catalog.sqlite3",
                         cache_dir=tmp_path / "cache", staging_dir=tmp_path / "staging")
        if trust:
            app.state.host_keys.trust("127.0.0.1", ssh_server["port"], ssh_server["host_key"])
        # Jamais Wikidata / Wikipédia / StrategyWiki pendant les tests : ceux qui en ont besoin posent leur faux serveur.
        app.state.knowledge.fetcher.transport = httpx.MockTransport(lambda request: httpx.Response(503))
        created.append(app)
        return app
    yield make
    for app in created:  # ferme les connexions SSH avant d'arrêter le serveur simulé
        await app.state.transfers.close()
        await app.state.pool.close()


@pytest.fixture
async def client(app_factory):
    app = app_factory()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def no_llm_env(monkeypatch):
    """Ni clé d'API dans l'environnement ni profil Anthropic du Mac : seules comptent celles du test."""
    from app.services import llm

    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "MISTRAL_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(llm, "_anthropic_profile", lambda: False)

