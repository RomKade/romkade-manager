"""Remplace la façade SFTP du Manager sur la console : services/saves.py n'en prend que le nom (annotation), l'agent
lui passe son propre lecteur de fichiers locaux (romkade_agent.LocalFS)."""


class ReadOnlyRemoteFS:
    pass
