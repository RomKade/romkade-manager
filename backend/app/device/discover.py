"""Retrouver la console sur le réseau local, pour la proposer à la première connexion (l'utilisateur confirme).

1. Par son nom : la box enregistre le nom que la console donne en Wi-Fi (« anbernic » sur le firmware d'origine,
   « knulli », « rocknix »…) ; « anbernic » ou « anbernic.lan » répond alors tout de suite.
2. Sinon, le port SSH (22) de chaque adresse des réseaux domestiques courants, et du réseau de cet ordinateur quand
   il est visible (pas dans Docker Desktop : le conteneur ne voit que son réseau virtuel). Une adresse qui répond en
   SSH est proposée avec son nom (résolution inverse, quand la box la connaît) ; celles dont le nom ou la bannière
   ressemblent à une console passent devant (un Mac ou un NAS a aussi le SSH ouvert).

Rien n'est tenté au-delà de la bannière SSH : aucune authentification, aucun mot de passe essayé.
"""

import asyncio
import ipaddress
import re
import socket

PORT = 22
# Noms Wi-Fi des firmwares de consoles rétro, essayés tels quels puis avec le suffixe des box (« .lan », « .home »).
NAMES = ("anbernic", "knulli", "rocknix", "batocera", "muos", "arkos", "trimui", "miyoo", "powkiddy", "retroid")
SUFFIXES = ("", ".lan", ".home")
# Réseaux des box les plus courantes (Livebox, Freebox, Bbox, Google Wifi, Fritz!Box, Deco, Xiaomi, Asus…).
COMMON = ("192.168.1", "192.168.0", "192.168.86", "192.168.68", "192.168.2", "192.168.178", "192.168.50", "192.168.31",
          "192.168.10", "192.168.100", "10.0.0", "10.0.1")
LIKELY = re.compile(r"anbernic|rg\d{2,3}|knulli|rocknix|batocera|muos|arkos|trimui|miyoo|powkiddy|retroid|onion|garlic|minui",
                    re.I)
# Réseaux de Docker et de Docker Desktop : ceux du conteneur, pas celui de la maison.
_DOCKER = (ipaddress.ip_network("172.16.0.0/12"), ipaddress.ip_network("192.168.65.0/24"))

CONNECT_TIMEOUT = 0.6
BANNER_TIMEOUT = 1.5
CONCURRENCY = 256


async def _banner(host: str, timeout: float = CONNECT_TIMEOUT) -> str | None:
    """Bannière SSH de `host`, ou None s'il ne répond pas en SSH."""
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, PORT), timeout)
    except (OSError, asyncio.TimeoutError):
        return None
    try:
        line = (await asyncio.wait_for(reader.readline(), BANNER_TIMEOUT)).decode(errors="replace").strip()
    except (OSError, asyncio.TimeoutError):
        line = ""
    finally:
        writer.close()
    return line if line.startswith("SSH-") else None


async def _resolve(name: str) -> str | None:
    loop = asyncio.get_running_loop()
    try:
        infos = await asyncio.wait_for(loop.getaddrinfo(name, PORT, family=socket.AF_INET, type=socket.SOCK_STREAM), 1.5)
    except (OSError, asyncio.TimeoutError):
        return None
    ip = infos[0][4][0] if infos else None
    return ip if ip and ipaddress.ip_address(ip).is_private else None


async def _name_of(ip: str) -> str | None:
    loop = asyncio.get_running_loop()
    try:
        name = (await asyncio.wait_for(loop.run_in_executor(None, socket.gethostbyaddr, ip), 1.5))[0]
    except (OSError, asyncio.TimeoutError):
        return None
    return None if name == ip else name


def _own_subnets() -> list[str]:
    """Réseau /24 de cet ordinateur, s'il est visible (lancement direct ; pas dans un conteneur)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # aucun paquet envoyé : choisit seulement l'interface de sortie
            ip = ipaddress.ip_address(s.getsockname()[0])
    except OSError:
        return []
    if not ip.is_private or ip.is_loopback or any(ip in net for net in _DOCKER):
        return []
    return [str(ip).rsplit(".", 1)[0]]


def _candidate(host: str, name: str | None, banner: str) -> dict:
    return {"host": host, "name": name, "banner": banner, "likely": bool(LIKELY.search(f"{name or ''} {banner}"))}


async def by_name() -> list[dict]:
    """Consoles qui répondent à un nom de firmware connu (rapide : quelques résolutions DNS)."""
    names = [n + s for n in NAMES for s in SUFFIXES]
    ips = await asyncio.gather(*(_resolve(n) for n in names))
    found: dict[str, str] = {}
    for name, ip in zip(names, ips):
        if ip and ip not in found:
            found[ip] = name
    banners = await asyncio.gather(*(_banner(ip, 2.0) for ip in found))
    return [_candidate(ip, name, b) | {"likely": True} for (ip, name), b in zip(found.items(), banners) if b]


async def by_scan(subnets: list[str] | None = None) -> list[dict]:
    """Adresses des réseaux domestiques qui répondent en SSH, avec leur nom quand la box le connaît."""
    nets = list(dict.fromkeys([*(subnets or []), *_own_subnets(), *COMMON]))
    sem = asyncio.Semaphore(CONCURRENCY)

    async def probe(ip: str) -> tuple[str, str] | None:
        async with sem:
            b = await _banner(ip)
        return (ip, b) if b else None

    open_ = [x for x in await asyncio.gather(*(probe(f"{n}.{i}") for n in nets for i in range(1, 255))) if x]
    names = await asyncio.gather(*(_name_of(ip) for ip, _ in open_))
    return [_candidate(ip, name, b) for (ip, b), name in zip(open_, names)]


async def discover(scan: bool = False) -> dict:
    """Consoles probables d'abord. Le nom suffit le plus souvent ; le scan (quelques secondes) sinon, ou sur demande."""
    found = await by_name()
    scanned = False
    if scan or not found:
        known = {c["host"] for c in found}
        found += [c for c in await by_scan() if c["host"] not in known]
        scanned = True
    found.sort(key=lambda c: (not c["likely"], tuple(int(p) for p in c["host"].split("."))))
    return {"consoles": found, "scanned": scanned}
