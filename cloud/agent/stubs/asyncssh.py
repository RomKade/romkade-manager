"""Remplace asyncssh sur la console : l'agent exécute les commandes sur place, sans SSH.

launcher.py l'importe pour ssh_run (jamais appelé par l'agent) ; seuls les noms utilisés doivent exister.
"""


class TimeoutError(Exception):  # noqa: A001
    pass


class SSHKey:
    pass
