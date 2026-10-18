# Install a local LLM and connect it to ROMKADE Manager

<p align="center"><strong>English</strong> · <a href="local-llm.fr.md">Français</a> · <a href="local-llm.es.md">Español</a></p>

ROMKADE Manager uses an AI for **game descriptions** and **game controls** (which button does what). Instead of a paid
online service (Claude, ChatGPT, Mistral, Gemini), you can run an **open-weight** model on your computer, Mac,
Windows or Linux:

- **free**: no API key, no usage cost;
- **private**: nothing leaves your computer (or your network);
- **offline**, once the model is downloaded.

In exchange it is slower, and a small model makes more mistakes than a large online one: check the controls in game.

## What do you need?

| Model size | Recommended memory | For |
|---|---|---|
| 3 to 4 billion parameters (3B–4B) | 8 GB | trying it out; rough answers |
| 7 to 8 billion (7B–8B) | 16 GB | good balance |
| 12 to 14 billion (12B–14B) | 16 to 32 GB | best local results |

An Apple Silicon Mac or a PC with a recent graphics card answers in a few seconds; without a graphics card, expect
about a minute per answer.

Pick a model that handles **French and Spanish** well (texts are written in three languages), for example
`qwen2.5:7b`, `mistral-nemo` (12B) or `llama3.1:8b`.

## Option A: Ollama (simplest)

1. Download and install Ollama: <https://ollama.com/download> (macOS, Windows, Linux). On Linux:
   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   ```
2. Download a model, in a terminal:
   ```bash
   ollama pull qwen2.5:7b
   ```
3. Check that it is there:
   ```bash
   ollama list
   ```

Ollama starts its server by itself, at `http://localhost:11434/v1`.

## Option B: LM Studio (with a user interface)

1. Download and install LM Studio: <https://lmstudio.ai/>.
2. **Discover** tab: search for and download a model (for example Qwen2.5 7B Instruct).
3. **Developer** tab: load the model and click **Start Server**.

The server answers at `http://localhost:1234/v1`.

## Connect the model in ROMKADE Manager

1. Open **Settings > AI**.
2. Choose **Ollama, LM Studio, other…**.
3. Click the address: **Ollama** or **LM Studio** (or **Ollama (Docker)**, see below).
4. Click the model in the list.

The connection is checked automatically: the light turns **green** ("Connected"). The first try can take a minute
while the model loads into memory.

Descriptions are then generated **game by game**, in the background (Settings > Descriptions); controls are requested
from a game's page.

## ROMKADE Manager in Docker

Inside a container, `localhost` is the container itself, not your computer. Use the **Ollama (Docker)** address:
`http://host.docker.internal:11434/v1`.

- macOS and Windows (Docker Desktop): nothing else to do.
- Linux: the provided `compose.yaml` declares `host.docker.internal`. By default Ollama only listens on the machine
  itself: make it listen for containers too, then restart it:
  ```bash
  sudo systemctl edit ollama      # add:  [Service]  Environment="OLLAMA_HOST=0.0.0.0:11434"
  sudo systemctl restart ollama
  ```

## A model on another computer of the network

You can run the model on a more powerful machine at home. On that machine, make Ollama listen on the network
(`OLLAMA_HOST=0.0.0.0:11434`), then in ROMKADE Manager enter its address, for example `http://192.168.1.20:11434/v1`,
and click **Use this address**.

Ollama has no password: only open it on a trusted network, never on the Internet.

## Other OpenAI-compatible services

Any API speaking the OpenAI protocol (`/v1/chat/completions`) works: enter its address (usually ending in `/v1`) and,
if it asks for one, its API key under "Does the service need an API key?". For example OpenRouter
(`https://openrouter.ai/api/v1`) or Groq (`https://api.groq.com/openai/v1`). These services are online and billed under
their own terms.

## Troubleshooting

| Red light, message | Fix |
|---|---|
| "No service responds at …" | Ollama or LM Studio is not running, or the server is not started (LM Studio: Start Server). Check the address and port. |
| Same, with ROMKADE in Docker | Use `http://host.docker.internal:11434/v1`; on Linux, see above. |
| "No model found" | Download a model (`ollama pull …`), then reload the list. |
| "The model answers, but not in the expected format" | The model is too small to follow the instructions: use a 7B or larger. |
| Very slow answers | Normal on the first call (loading); otherwise use a smaller model. |

If the model stops answering during descriptions, generation stops after 5 failures in a row; start it again when the
model is back: games already described are kept.
