"""Statistiques d'usage du serveur MCP (PostHog MCP Analytics, Cloud EU, même projet que romkade.com et le Manager).

Ce qui part : nom de l'outil appelé, durée, erreur ou non, client (ChatGPT, Claude…), identifiant de session,
liste des outils, exceptions du serveur. Ce qui ne part jamais : les arguments et les réponses des outils (titres
de jeux, recherches, code d'appairage, noms des consoles), l'intention de l'utilisateur ni l'identifiant de la
conversation (règle des annuaires : rien de la conversation au-delà de ce que l'outil demande). Aucun
paramètre « context » n'est ajouté aux outils : ChatGPT et Claude voient exactement les mêmes outils qu'avant.

Clé absente (POSTHOG_PROJECT_TOKEN) : rien n'est envoyé, le serveur fonctionne pareil.
"""

import asyncio
import logging
import os

log = logging.getLogger("romkade.cloud")

# Contenu des appels : jamais envoyé.
PRIVATE = ("$mcp_parameters", "$mcp_response", "$mcp_intent", "$mcp_intent_source")


def strip_private(event):
    """Retire le contenu des appels de chaque événement, juste avant l'envoi à PostHog."""
    for key in PRIVATE:
        (event.get("properties") or {}).pop(key, None)
    return event


class Analytics:
    """Branche PostHog sur le serveur MCP ; `close()` envoie les derniers événements à l'arrêt."""

    def __init__(self, mcp):
        self.client = self.handle = None
        token = os.environ.get("POSTHOG_PROJECT_TOKEN", "").strip()
        if not token:
            log.info("POSTHOG_PROJECT_TOKEN absent : statistiques MCP désactivées")
            return
        from posthog import Posthog
        from posthog.mcp import instrument
        from posthog.mcp.types import MCPAnalyticsOptions

        self.client = Posthog(token, host=os.environ.get("POSTHOG_HOST", "").strip() or "https://eu.i.posthog.com")
        self.handle = instrument(mcp, self.client, MCPAnalyticsOptions(
            context=False, enable_conversation_id=False, before_send=strip_private, logger=log.warning))

    async def close(self):
        if self.handle is not None:
            await self.handle.flush()
            await asyncio.to_thread(self.client.shutdown)
