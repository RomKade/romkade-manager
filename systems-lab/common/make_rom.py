"""ROM Game Boy de test (32 Ko) : une boucle infinie, en-tête valide. Faite ici pour n'utiliser aucun jeu protégé."""
import sys

LOGO = bytes.fromhex("CEED6666CC0D000B03730083000C000D0008111F8889000EDCCC6EE6DDDDD999BBBB67636E0EECCCDDDC999FBBB9333E")
rom = bytearray(32 * 1024)
rom[0x100:0x104] = bytes([0x00, 0xC3, 0x50, 0x01])        # nop ; jp $0150
rom[0x104:0x134] = LOGO
rom[0x134:0x13F] = b"AGM LAB".ljust(11, b"\0")
rom[0x150:0x153] = bytes([0x18, 0xFE, 0x00])              # jr -2 (boucle)
rom[0x14D] = (-sum(rom[0x134:0x14D]) - 25) & 0xFF        # somme de contrôle de l'en-tête
open(sys.argv[1], "wb").write(rom)
