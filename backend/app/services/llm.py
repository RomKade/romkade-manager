"""Connexion à un modèle de langage (LLM) : un seul réglage pour tout ce qui utilise l'IA (descriptions des jeux,
commandes des jeux).

Fournisseurs :
- Claude (Anthropic) : API Messages, sorties structurées, et lots à moitié prix pour les descriptions ;
- ChatGPT (OpenAI), Mistral, Gemini (Google), ou tout autre service compatible OpenAI (adresse au choix) ;
- un modèle local à poids ouverts (Ollama, LM Studio, sur cet ordinateur ou un autre du réseau) ou tout autre service
  compatible OpenAI, à l'adresse choisie (« local », clé facultative).
Tous sauf Claude passent par le protocole « chat completions » d'OpenAI (httpx, sans SDK de plus).

Les clés vont dans le trousseau du système (ou secrets.json dans Docker) ; le fournisseur, le modèle, l'adresse et le
dernier test dans llm.json (dossier de données). Le modèle n'est jamais inventé : à défaut de choix, il est pris dans
la liste renvoyée par le fournisseur (GET /models, suggest_model), sauf Claude Opus 5.5 par défaut pour Anthropic.
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
             r"[A-Za-z0-9_.\-]{20,}", "https://console.mistral.ai/api-keys", "MISTRAL_API_KEY"),
    Provider("gemini", "Gemini (Google)", "cloud", "openai", "https://generativelanguage.googleapis.com/v1beta/openai",
             "required", r"AIza[0-9A-Za-z_\-]{30,}", "https://aistudio.google.com/apikey", "GEMINI_API_KEY"),
    Provider("local", "Modèle local ou service compatible OpenAI", "local", "openai", "http://localhost:11434/v1",
             "optional"),
)}
# Adresses habituelles des serveurs locaux (protocole OpenAI). Dans Docker, « localhost » est le conteneur :
# host.docker.internal joint l'ordinateur hôte (Docker Desktop ; compose.yaml l'ajoute aussi sous Linux).
LOCAL_PRESETS = {"Ollama": "http://localhost:11434/v1", "LM Studio": "http://localhost:1234/v1",
                 "Ollama (Docker)": "http://host.docker.internal:11434/v1"}
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]", "host.docker.internal"}

# Modèle proposé quand l'utilisateur n'en choisit pas : premier motif qui correspond, version la plus récente.
SUGGEST: dict[str, list[str]] = {
    "openai": [r"gpt-\d+(\.\d+)?", r"gpt-\d+(\.\d+)?-mini", r"gpt-4o"],
    "mistral": [r"mistral-large-latest", r"mistral-medium-latest", r"mistral-small-latest"],
    "gemini": [r"gemini-\d+(\.\d+)?-pro", r"gemini-\d+(\.\d+)?-flash", r"gemini-[\w.-]*pro[\w.-]*",
               r"gemini-[\w.-]*flash[\w.-]*"],
}
_NOT_CHAT = re.compile(r"embed|whisper|tts|dall-e|image|audio|realtime|moderation|transcribe|search|vision-preview|"
                       r"rerank|ocr|guard", re.I)


def _version_key(model_id: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", model_id))


def suggest_model(provider_id: str, ids: list[str]) -> str | None:
    """Modèle à proposer parmi ceux du fournisseur : jamais un nom inventé, seulement un de la liste."""
    chat = [i for i in ids if not _NOT_CHAT.search(i)]
    for pattern in SUGGEST.get(provider_id, []):
        found = [i for i in chat if re.fullmatch(pattern, i)]
        if found:
            return max(found, key=_version_key)
    return chat[0] if chat and provider_id == "local" else None


def is_local_url(url: str | None) -> bool:
    from urllib.parse import urlparse

    host = (urlparse(url or "").hostname or "").lower()
    return host in _LOCAL_HOSTS or host.endswith(".local") or host.startswith("192.168.") or host.startswith("10.")


# Clé Anthropic : même entrée du trousseau qu'avant (ancien onglet Paramètres > Descriptions), pour ne rien perdre.
ANTHROPIC_KEY = ("api.anthropic.com", "game-descriptions")


class LlmTest(BaseModel):
    """Dernière vérification (bouton Vérifier, ou automatique après l'enregistrement), pour le voyant d'état."""
    provider: str
    model: str
    base_url: str
    ok: bool
    at: str
    error: str | None = None


class LlmConfig(BaseModel):
    provider: str | None = None  # None : aucune IA choisie
    model: str | None = None  # None : modèle par défaut du fournisseur, s'il en a un
    base_url: str | None = None  # None : adresse du fournisseur
    last_test: LlmTest | None = None


class LlmConfigStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> LlmConfig:
        try:
            cfg = LlmConfig.model_validate_json(self.path.read_text())
        except (OSError, ValueError):
            return LlmConfig()
        if cfg.provider == "custom":  # ancien choix « autre service compatible OpenAI », fusionné avec « local »
            cfg.provider = "local"
        return cfg if cfg.provider is None or cfg.provider in PROVIDERS else LlmConfig()

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

    @property
    def local(self) -> bool:
        return self.provider.id == "local" and is_local_url(self.base_url)

    def _client(self) -> httpx.Client:
        timeout = TIMEOUT_LOCAL if self.provider.id == "local" else TIMEOUT_CLOUD
        return httpx.Client(transport=self.transport, timeout=httpx.Timeout(timeout, connect=10.0))

    def anthropic_client(self):
        import anthropic

        kwargs = {"api_key": self.api_key} if self.api_key else {}
        if self.transport is not None:
            kwargs["http_client"] = httpx.Client(transport=self.transport)
        return anthropic.Anthropic(**kwargs)

    def complete_json(self, system: str, prompt: str, schema: dict, *, max_tokens: int,
                      effort: str | None = None, name: str = "answer", reasoning: str | None = None) -> dict | None:
        """Réponse JSON conforme à `schema`, ou None (refus, réponse tronquée ou illisible).
        Lève AppError (llm_unreachable, llm_rejected) si le fournisseur ne répond pas ou refuse la demande."""
        if self.provider.protocol == "anthropic":
            return self._anthropic_json(system, prompt, schema, max_tokens, effort)
        return self._openai_json(system, prompt, schema, max_tokens, name, reasoning)

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

    def _openai_json(self, system, prompt, schema, max_tokens, name, reasoning=None) -> dict | None:
        tokens = "max_completion_tokens" if self.provider.id == "openai" else "max_tokens"
        body = {"model": self.model, tokens: max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                "response_format": {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}}
        if reasoning:
            body["reasoning_effort"] = reasoning
        with self._client() as http:
            r = self._post(http, "/chat/completions", body)
            if r.status_code == 400 and "reasoning_effort" in body and re.search(r"reasoning", r.text, re.I):
                body.pop("reasoning_effort")  # serveur qui ne connaît pas ce réglage
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

    def stream_chat(self, system: str, messages: list[dict], *, max_tokens: int = 800, reasoning: str | None = None):
        """Réponse en texte libre, morceau par morceau (générateur). `messages` : [{role: user|assistant, content}].
        Serveur compatible OpenAI qui refuse le flux : une seule réponse entière. Lève AppError (llm_unreachable,
        llm_rejected) avant le premier morceau si le fournisseur ne répond pas ou refuse la demande.
        `reasoning` (compatible OpenAI) : « none » coupe la réflexion préalable des modèles à raisonnement (Gemma 4,
        Qwen 3… : sans lui, LM Studio peut épuiser les jetons à réfléchir et ne rien répondre) ; retiré si refusé."""
        if self.provider.protocol == "anthropic":
            yield from self._anthropic_stream(system, messages, max_tokens)
        else:
            yield from self._openai_stream(system, messages, max_tokens, reasoning)

    def _anthropic_stream(self, system, messages, max_tokens):
        import anthropic

        try:
            with self.anthropic_client().messages.stream(model=self.model, max_tokens=max_tokens, system=system,
                                                         messages=messages) as stream:
                yield from stream.text_stream
        except anthropic.APIConnectionError as exc:
            raise errors.AppError("llm_unreachable", f"Anthropic ne répond pas : {exc}", 502) from exc
        except anthropic.APIStatusError as exc:
            raise errors.AppError("llm_rejected", _status_message(self.provider, exc.status_code, str(exc)), 502,
                                  {"status": exc.status_code}) from exc

    def _openai_stream(self, system, messages, max_tokens, reasoning=None):
        tokens = "max_completion_tokens" if self.provider.id == "openai" else "max_tokens"
        body = {"model": self.model, tokens: max_tokens, "stream": True,
                "messages": [{"role": "system", "content": system}, *messages]}
        if reasoning:
            body["reasoning_effort"] = reasoning
        url = self.base_url.rstrip("/") + "/chat/completions"
        with self._client() as http:
            try:
                with http.stream("POST", url, json=body, headers=self._headers()) as r:
                    if r.status_code >= 400:
                        text = r.read().decode(errors="replace")
                        if r.status_code == 400 and reasoning and re.search(r"reasoning", text, re.I):
                            fallback = "no-reasoning"  # serveur qui ne connaît pas ce réglage : sans lui
                        elif r.status_code == 400 and re.search(r"stream", text, re.I):
                            fallback = True
                        else:
                            raise errors.AppError("llm_rejected", _status_message(self.provider, r.status_code, text),
                                                  502, {"status": r.status_code})
                    else:
                        fallback = False
                        for line in r.iter_lines():
                            if not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if data == "[DONE]":
                                break
                            try:
                                delta = json.loads(data)["choices"][0].get("delta") or {}
                            except (ValueError, KeyError, IndexError, TypeError):
                                continue
                            if delta.get("content"):
                                yield delta["content"]
            except httpx.HTTPError as exc:
                raise errors.AppError("llm_unreachable", _unreachable(self.provider, self.base_url, exc), 502) from exc
            if fallback == "no-reasoning":
                yield from self._openai_stream(system, messages, max_tokens, None)
                return
            if fallback:  # serveur sans flux : réponse entière
                body["stream"] = False
                r = self._post(http, "/chat/completions", body)
                if r.status_code >= 400:
                    raise errors.AppError("llm_rejected", _status_message(self.provider, r.status_code, r.text), 502,
                                          {"status": r.status_code})
                try:
                    yield r.json()["choices"][0]["message"].get("content") or ""
                except (ValueError, KeyError, IndexError, TypeError):
                    return

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
    if provider.id == "local":
        return (f"Aucun service ne répond sur {base_url} : lance Ollama ou LM Studio (serveur démarré) et vérifie "
                f"l'adresse (dans Docker, utilise http://host.docker.internal:11434/v1).")
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
    """JSON d'une réponse, y compris entouré de ```json … ``` ou précédé d'un raisonnement <think>…</think>
    (modèles locaux)."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
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


def effective_provider(cfg: LlmConfig, credentials) -> str | None:
    """Fournisseur choisi ; sans choix enregistré, Claude si une clé Anthropic existe déjà (réglage d'avant)."""
    if cfg.provider:
        return cfg.provider
    return "anthropic" if key_source(credentials, PROVIDERS["anthropic"]) else None


def build(cfg: LlmConfig, credentials, transport: httpx.BaseTransport | None = None, *,
          require_model: bool = True) -> LLM:
    """Modèle prêt à l'emploi d'après les réglages, ou AppError expliquant ce qui manque."""
    pid = effective_provider(cfg, credentials)
    if pid is None:
        raise errors.AppError("llm_none", "Aucune IA n'est connectée : choisis-en une dans Paramètres > Assistant.", 409)
    provider = PROVIDERS[pid]
    base_url = (cfg.base_url or provider.base_url or "").strip()
    if not base_url:
        raise errors.AppError("llm_no_url", "Indique l'adresse du service (Paramètres > Assistant).", 409)
    key = saved_key(credentials, provider) or (os.environ.get(provider.env) if provider.env else None)
    if provider.key == "required" and not key and not (provider.id == "anthropic" and key_source(credentials, provider)):
        raise errors.AppError("llm_key_missing", f"Ajoute d'abord une clé d'API {provider.label} (Paramètres > Assistant).",
                              409, {"provider": provider.id})
    model = (cfg.model or provider.default_model or "").strip()
    if require_model and not model:
        raise errors.AppError("llm_no_model", "Choisis un modèle (Paramètres > Assistant).", 409, {"provider": provider.id})
    return LLM(provider, model, base_url, key, transport)


def resolve(state) -> LLM:
    """Modèle configuré de l'application (app.state), ou AppError."""
    return build(state.llm_config.load(), state.credentials, getattr(state, "llm_transport", None))


def autofill_model(state) -> None:
    """Sans modèle choisi, prend celui que suggère la liste du fournisseur (si la clé ou l'adresse le permettent)."""
    store = state.llm_config
    cfg = store.load()
    pid = effective_provider(cfg, state.credentials)
    if pid is None or cfg.model or PROVIDERS[pid].default_model:
        return
    try:
        llm = build(cfg, state.credentials, getattr(state, "llm_transport", None), require_model=False)
        model = suggest_model(pid, llm.list_models())
    except errors.AppError:
        return
    if model:
        cfg.provider, cfg.model = pid, model
        store.save(cfg)


def record_test(state, llm: LLM, ok: bool, error: str | None = None) -> None:
    from datetime import UTC, datetime

    store = state.llm_config
    cfg = store.load()
    cfg.last_test = LlmTest(provider=llm.provider.id, model=llm.model, base_url=llm.base_url, ok=ok, error=error,
                            at=datetime.now(UTC).isoformat(timespec="seconds"))
    store.save(cfg)


def status(state) -> dict:
    """Réglages et état de la connexion, pour Paramètres > Assistant (sans jamais renvoyer de clé).

    `state` : none (aucune IA), incomplete (clé, modèle ou adresse manquants), untested (prête, pas encore vérifiée
    avec ces réglages), connected (dernière vérification réussie), error (dernière vérification en échec)."""
    cfg = state.llm_config.load()
    pid = effective_provider(cfg, state.credentials)
    llm = None
    try:
        llm = resolve(state)
        ready, problem, model, base_url = True, None, llm.model, llm.base_url
    except errors.AppError as exc:
        ready, problem = False, exc.code
        model = cfg.model or (PROVIDERS[pid].default_model if pid else None)
        base_url = cfg.base_url
    test = cfg.last_test
    same = bool(llm and test and (test.provider, test.model, test.base_url) == (llm.provider.id, llm.model, llm.base_url))
    conn = ("none" if pid is None else "incomplete" if not ready else
            ("connected" if test.ok else "error") if same else "untested")
    return {
        "provider": pid, "model": model, "base_url": cfg.base_url, "ready": ready, "problem": problem,
        "state": conn, "last_error": test.error if same and not test.ok else None,
        "tested_at": test.at if same else None, "local": bool(llm and llm.local) or (pid == "local" and is_local_url(base_url or PROVIDERS["local"].base_url)),
        "local_presets": LOCAL_PRESETS,
        "providers": [{"id": p.id, "label": p.label, "kind": p.kind, "key": p.key, "keys_url": p.keys_url,
                       "base_url": p.base_url, "default_model": p.default_model, "batch": p.batch,
                       "key_source": key_source(state.credentials, p) if p.key != "none" else None}
                      for p in PROVIDERS.values()],
    }
