"""Connexion à un modèle de langage (LLM) : un seul réglage pour tout ce qui utilise l'IA (descriptions des jeux,
commandes des jeux).

Fournisseurs :
- Claude (Anthropic) : API Messages, sorties structurées, et lots à moitié prix pour les descriptions ;
- ChatGPT (OpenAI), Mistral, Gemini (Google), ou tout autre service compatible OpenAI (adresse au choix) ;
- un modèle local à poids ouverts servi sur ce Mac par Ollama ou LM Studio (protocole OpenAI, sans clé ni coût).
Tous sauf Claude passent par le protocole « chat completions » d'OpenAI (httpx, sans SDK de plus).

Les clés vont dans le trousseau macOS ; le fournisseur, le modèle et l'adresse dans llm.json (dossier de données).
Le modèle n'est jamais deviné : il est choisi dans la liste renvoyée par le fournisseur (GET /models), sauf
Claude Opus 5.5 par défaut pour Anthropic (réglage historique des descriptions).
"""

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel

from app import errors

TIMEOUT_CLOUD = 120.0
TIMEOUT_LOCAL = 600.0  # un modèle local sur Mac peut mettre plusieurs minutes à répondre (premier chargement)
ANTHROPIC_VERSION = "2023-06-01"


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    kind: Literal["cloud", "local"]
    protocol: Literal["anthropic", "openai"]
    base_url: str | None
    key: Literal["required", "optional", "none"]
    key_re: str | None = None
    keys_url: str | None = None
    env: str | None = None  # variable d'environnement lue à défaut de clé dans le trousseau
    default_model: str | None = None
    batch: bool = False  # lots à moitié prix (descriptions)


PROVIDERS: dict[str, Provider] = {p.id: p for p in (
    Provider("anthropic", "Claude (Anthropic)", "cloud", "anthropic", "https://api.anthropic.com/v1", "required",
             r"sk-ant-[A-Za-z0-9_\-]{20,}", "https://console.anthropic.com/settings/keys", "ANTHROPIC_API_KEY",
             "claude-opus-5-5", batch=True),
    Provider("openai", "ChatGPT (OpenAI)", "cloud", "openai", "https://api.openai.com/v1", "required",
             r"sk-[A-Za-z0-9_\-]{20,}", "https://platform.openai.com/api-keys", "OPENAI_API_KEY"),
    Provider("mistral", "Mistral AI", "cloud", "openai", "https://api.mistral.ai/v1", "required",
             r"[A-Za-z0-9]{20,}", "https://console.mistral.ai/api-keys", "MISTRAL_API_KEY"),
    Provider("gemini", "Gemini (Google)", "cloud", "openai", "https://generativelanguage.googleapis.com/v1beta/openai",
             "required", r"AIza[0-9A-Za-z_\-]{30,}", "https://aistudio.google.com/apikey", "GEMINI_API_KEY"),
    Provider("local", "Modèle local (Ollama, LM Studio…)", "local", "openai", "http://localhost:11434/v1", "none"),
    Provider("custom", "Autre service compatible OpenAI", "cloud", "openai", None, "optional"),
)}
# Adresses habituelles des serveurs locaux (protocole OpenAI).
LOCAL_PRESETS = {"Ollama": "http://localhost:11434/v1", "LM Studio": "http://localhost:1234/v1"}

# Clé Anthropic : même entrée du trousseau qu'avant (Paramètres > Descriptions), pour ne rien perdre.
ANTHROPIC_KEY = ("api.anthropic.com", "game-descriptions")


class LlmConfig(BaseModel):
    provider: str = "anthropic"
    model: str | None = None  # None : modèle par défaut du fournisseur, s'il en a un
    base_url: str | None = None  # None : adresse du fournisseur (obligatoire pour « custom »)


class LlmConfigStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> LlmConfig:
        try:
            cfg = LlmConfig.model_validate_json(self.path.read_text())
        except (OSError, ValueError):
            return LlmConfig()
        return cfg if cfg.provider in PROVIDERS else LlmConfig()

    def save(self, cfg: LlmConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg.model_dump(), indent=2))
        tmp.replace(self.path)


def _key_entry(provider: Provider) -> tuple[str, str]:
    return ANTHROPIC_KEY if provider.id == "anthropic" else (f"llm:{provider.id}", "api-key")


def saved_key(credentials, provider: Provider) -> str | None:
    host, account = _key_entry(provider)
    return credentials.get_password(host, account) if credentials else None


def set_key(credentials, provider: Provider, key: str) -> None:
    key = key.strip()
    if provider.key == "none":
        raise errors.AppError("llm_key_unused", f"{provider.label} n'utilise pas de clé d'API.", 422)
    if provider.key_re and not re.fullmatch(provider.key_re, key):
        raise errors.AppError("llm_key_format", f"Ce n'est pas une clé d'API {provider.label}.", 422,
                              {"provider": provider.id})
    if not key or len(key) > 400:
        raise errors.AppError("llm_key_format", "Clé d'API vide ou trop longue.", 422, {"provider": provider.id})
    credentials.set_password(*_key_entry(provider), key)


def delete_key(credentials, provider: Provider) -> None:
    credentials.delete_password(*_key_entry(provider))


def _anthropic_profile() -> bool:
    creds = Path.home() / ".config" / "anthropic" / "credentials"
    return creds.is_dir() and any(creds.glob("*.json"))


def key_source(credentials, provider: Provider) -> Literal["keychain", "environment"] | None:
    if saved_key(credentials, provider):
        return "keychain"
    if provider.env and os.environ.get(provider.env):
        return "environment"
    if provider.id == "anthropic" and (os.environ.get("ANTHROPIC_AUTH_TOKEN") or _anthropic_profile()):
        return "environment"
    return None


@dataclass
class LLM:
    """Modèle prêt à l'emploi : fournisseur, modèle, adresse et clé résolus."""

    provider: Provider
    model: str
    base_url: str
    api_key: str | None
    transport: httpx.BaseTransport | None = None  # les tests y branchent un faux serveur (httpx.MockTransport)

    @property
    def label(self) -> str:
        return f"{self.provider.label} · {self.model}"

    def _client(self) -> httpx.Client:
        timeout = TIMEOUT_LOCAL if self.provider.kind == "local" else TIMEOUT_CLOUD
        return httpx.Client(transport=self.transport, timeout=httpx.Timeout(timeout, connect=10.0))

    def anthropic_client(self):
        import anthropic

        kwargs = {"api_key": self.api_key} if self.api_key else {}
        if self.transport is not None:
            kwargs["http_client"] = httpx.Client(transport=self.transport)
        return anthropic.Anthropic(**kwargs)

    def complete_json(self, system: str, prompt: str, schema: dict, *, max_tokens: int,
                      effort: str | None = None, name: str = "answer") -> dict | None:
        """Réponse JSON conforme à `schema`, ou None (refus, réponse tronquée ou illisible).
        Lève AppError (llm_unreachable, llm_rejected) si le fournisseur ne répond pas ou refuse la demande."""
        if self.provider.protocol == "anthropic":
            return self._anthropic_json(system, prompt, schema, max_tokens, effort)
        return self._openai_json(system, prompt, schema, max_tokens, name)

    def _anthropic_json(self, system, prompt, schema, max_tokens, effort) -> dict | None:
        import anthropic

        output = {"format": {"type": "json_schema", "schema": schema}}
        if effort:
            output["effort"] = effort
        try:
            message = self.anthropic_client().messages.create(
                model=self.model, max_tokens=max_tokens, system=system, output_config=output,
                messages=[{"role": "user", "content": prompt}])
        except anthropic.APIConnectionError as exc:
            raise errors.AppError("llm_unreachable", f"Anthropic ne répond pas : {exc}", 502) from exc
        except anthropic.APIStatusError as exc:
            raise errors.AppError("llm_rejected", _status_message(self.provider, exc.status_code, str(exc)), 502,
                                  {"status": exc.status_code}) from exc
        return parse_anthropic(message)

    def _openai_json(self, system, prompt, schema, max_tokens, name) -> dict | None:
        tokens = "max_completion_tokens" if self.provider.id == "openai" else "max_tokens"
        body = {"model": self.model, tokens: max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                "response_format": {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}}
        with self._client() as http:
            r = self._post(http, "/chat/completions", body)
            if r.status_code == 400 and re.search(r"response_format|json_schema|schema", r.text, re.I):
                # Modèle ou serveur sans sorties structurées : JSON simple, schéma donné dans la consigne.
                body["response_format"] = {"type": "json_object"}
                body["messages"][0]["content"] = (f"{system}\n\nAnswer with a single JSON object matching this JSON "
                                                  f"schema, and nothing else:\n{json.dumps(schema)}")
                r = self._post(http, "/chat/completions", body)
        if r.status_code >= 400:
            raise errors.AppError("llm_rejected", _status_message(self.provider, r.status_code, r.text), 502,
                                  {"status": r.status_code})
        try:
            choice = r.json()["choices"][0]
        except (ValueError, KeyError, IndexError, TypeError):
            return None
        msg = choice.get("message") or {}
        if choice.get("finish_reason") == "length" or msg.get("refusal"):
            return None
        return parse_json_text(msg.get("content") or "")

    def _headers(self) -> dict:
        if self.provider.protocol == "anthropic":
            return {"x-api-key": self.api_key or "", "anthropic-version": ANTHROPIC_VERSION}
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def _post(self, http: httpx.Client, path: str, body: dict) -> httpx.Response:
        try:
            return http.post(self.base_url.rstrip("/") + path, json=body, headers=self._headers())
        except httpx.HTTPError as exc:
            raise errors.AppError("llm_unreachable", _unreachable(self.provider, self.base_url, exc), 502) from exc

    def list_models(self) -> list[str]:
        """Modèles proposés par le fournisseur (GET /models), triés."""
        try:
            with self._client() as http:
                r = http.get(self.base_url.rstrip("/") + "/models", headers=self._headers(), params={"limit": 1000}
                             if self.provider.protocol == "anthropic" else None)
        except httpx.HTTPError as exc:
            raise errors.AppError("llm_unreachable", _unreachable(self.provider, self.base_url, exc), 502) from exc
        if r.status_code >= 400:
            raise errors.AppError("llm_rejected", _status_message(self.provider, r.status_code, r.text), 502,
                                  {"status": r.status_code})
        try:
            ids = [m["id"] for m in r.json().get("data", []) if isinstance(m, dict) and m.get("id")]
        except (ValueError, AttributeError):
            ids = []
        return sorted({i.removeprefix("models/") for i in ids})

    def test(self) -> dict:
        """Petite demande réelle : le modèle répond-il, et en JSON ? (quelques jetons, coût négligeable)."""
        start = time.monotonic()
        data = self.complete_json("You check that a connection works.", 'Reply with {"ok": true}.',
                                  {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"],
                                   "additionalProperties": False}, max_tokens=1000, name="check")
        return {"ok": bool(data and data.get("ok") is True), "model": self.model, "provider": self.provider.id,
                "seconds": round(time.monotonic() - start, 1)}


def _unreachable(provider: Provider, base_url: str, exc: Exception) -> str:
    if provider.kind == "local":
        return (f"Aucun modèle local ne répond sur {base_url} : lance Ollama ou LM Studio (serveur démarré) et "
                f"vérifie l'adresse.")
    return f"{provider.label} ne répond pas ({type(exc).__name__}) : vérifie la connexion à Internet et l'adresse."


def _status_message(provider: Provider, status: int, text: str) -> str:
    if status in (401, 403):
        return f"{provider.label} refuse la clé d'API (erreur {status}) : vérifie-la ou crée-en une nouvelle."
    if status == 404:
        return f"{provider.label} ne connaît pas ce modèle ou cette adresse (erreur 404)."
    if status == 429:
        return f"{provider.label} limite les demandes ou le crédit est épuisé (erreur 429)."
    return f"{provider.label} a refusé la demande (erreur {status}) : {text[:300]}"


def parse_json_text(text: str) -> dict | None:
    """JSON d'une réponse, y compris entouré de ```json … ``` (modèles locaux)."""
    text = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


def parse_anthropic(message) -> dict | None:
    """Champs JSON d'un message Anthropic, ou None (refus, réponse tronquée ou illisible)."""
    if message.stop_reason in ("refusal", "max_tokens"):
        return None
    return parse_json_text(next((b.text for b in message.content if b.type == "text"), ""))


def build(cfg: LlmConfig, credentials, transport: httpx.BaseTransport | None = None, *,
          require_model: bool = True) -> LLM:
    """Modèle prêt à l'emploi d'après les réglages, ou AppError expliquant ce qui manque."""
    provider = PROVIDERS[cfg.provider]
    base_url = (cfg.base_url or provider.base_url or "").strip()
    if not base_url:
        raise errors.AppError("llm_no_url", "Indique l'adresse du service (Paramètres > IA).", 409)
    key = saved_key(credentials, provider) or (os.environ.get(provider.env) if provider.env else None)
    if provider.key == "required" and not key and not (provider.id == "anthropic" and key_source(credentials, provider)):
        raise errors.AppError("llm_key_missing", f"Ajoute d'abord une clé d'API {provider.label} (Paramètres > IA).",
                              409, {"provider": provider.id})
    model = (cfg.model or provider.default_model or "").strip()
    if require_model and not model:
        raise errors.AppError("llm_no_model", "Choisis un modèle (Paramètres > IA).", 409, {"provider": provider.id})
    return LLM(provider, model, base_url, key, transport)


def resolve(state) -> LLM:
    """Modèle configuré de l'application (app.state), ou AppError."""
    return build(state.llm_config.load(), state.credentials, getattr(state, "llm_transport", None))


def status(state) -> dict:
    """Réglages et état de la connexion, pour Paramètres > IA (sans jamais renvoyer de clé)."""
    cfg = state.llm_config.load()
    try:
        llm = resolve(state)
        ready, problem, model = True, None, llm.model
    except errors.AppError as exc:
        ready, problem, model = False, exc.code, cfg.model or PROVIDERS[cfg.provider].default_model
    return {
        "provider": cfg.provider, "model": model, "base_url": cfg.base_url, "ready": ready, "problem": problem,
        "local_presets": LOCAL_PRESETS,
        "providers": [{"id": p.id, "label": p.label, "kind": p.kind, "key": p.key, "keys_url": p.keys_url,
                       "base_url": p.base_url, "default_model": p.default_model, "batch": p.batch,
                       "key_source": key_source(state.credentials, p) if p.key != "none" else None}
                      for p in PROVIDERS.values()],
    }
