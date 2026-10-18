# Instalar un LLM local y conectarlo a ROMKADE Manager

<p align="center"><a href="local-llm.md">English</a> · <a href="local-llm.fr.md">Français</a> · <strong>Español</strong></p>

ROMKADE Manager usa una IA para las **descripciones de los juegos** y los **controles de los juegos** (qué botón hace
qué). En lugar de un servicio en línea de pago (Claude, ChatGPT, Mistral, Gemini), puedes ejecutar un modelo **de pesos
abiertos** en tu ordenador, Mac, Windows o Linux:

- **gratis**: sin clave de API ni coste por uso;
- **privado**: nada sale de tu ordenador (o de tu red);
- **sin conexión**, una vez descargado el modelo.

A cambio es más lento, y un modelo pequeño se equivoca más que uno grande en línea: comprueba los controles en el juego.

## ¿Qué necesitas?

| Tamaño del modelo | Memoria recomendada | Para |
|---|---|---|
| 3 a 4 mil millones de parámetros (3B–4B) | 8 GB | probar; respuestas aproximadas |
| 7 a 8 mil millones (7B–8B) | 16 GB | buen equilibrio |
| 12 a 14 mil millones (12B–14B) | 16 a 32 GB | mejores resultados en local |

Un Mac con Apple Silicon o un PC con una tarjeta gráfica reciente responde en unos segundos; sin tarjeta gráfica,
cuenta con un minuto por respuesta.

Elige un modelo que maneje bien el **francés y el español** (los textos se redactan en tres idiomas), por ejemplo
`qwen2.5:7b`, `mistral-nemo` (12B) o `llama3.1:8b`.

## Opción A: Ollama (lo más sencillo)

1. Descarga e instala Ollama: <https://ollama.com/download> (macOS, Windows, Linux). En Linux:
   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   ```
2. Descarga un modelo, en un terminal:
   ```bash
   ollama pull qwen2.5:7b
   ```
3. Comprueba que está:
   ```bash
   ollama list
   ```

Ollama inicia su servidor solo, en la dirección `http://localhost:11434/v1`.

## Opción B: LM Studio (con interfaz)

1. Descarga e instala LM Studio: <https://lmstudio.ai/>.
2. Pestaña **Discover**: busca y descarga un modelo (por ejemplo Qwen2.5 7B Instruct).
3. Pestaña **Developer**: carga el modelo y haz clic en **Start Server**.

El servidor responde en la dirección `http://localhost:1234/v1`.

## Conectar el modelo en ROMKADE Manager

1. Abre **Ajustes > Asistente**.
2. Elige **Ollama, LM Studio, otro…**.
3. Haz clic en la dirección: **Ollama** o **LM Studio** (u **Ollama (Docker)**, ver más abajo).
4. Haz clic en el modelo de la lista.

La conexión se comprueba sola: el indicador se pone **verde** («Conectada»). El primer intento puede tardar un minuto,
mientras el modelo se carga en memoria.

Las descripciones se generan después **juego a juego**, en segundo plano (al final de Ajustes > Asistente); los controles se
piden desde la ficha de un juego.

## ROMKADE Manager en Docker

Dentro de un contenedor, `localhost` es el propio contenedor, no tu ordenador. Usa la dirección **Ollama (Docker)**:
`http://host.docker.internal:11434/v1`.

- macOS y Windows (Docker Desktop): no hay que hacer nada más.
- Linux: el `compose.yaml` incluido declara `host.docker.internal`. Por defecto Ollama solo escucha en la propia
  máquina: haz que escuche también para los contenedores y reinícialo:
  ```bash
  sudo systemctl edit ollama      # añade:  [Service]  Environment="OLLAMA_HOST=0.0.0.0:11434"
  sudo systemctl restart ollama
  ```

## Un modelo en otro ordenador de la red

Puedes ejecutar el modelo en una máquina más potente de casa. En esa máquina, haz que Ollama escuche en la red
(`OLLAMA_HOST=0.0.0.0:11434`) y en ROMKADE Manager escribe su dirección, por ejemplo `http://192.168.1.20:11434/v1`,
y haz clic en **Usar esta dirección**.

Ollama no tiene contraseña: ábrelo solo en una red de confianza, nunca en Internet.

## Otros servicios compatibles con OpenAI

Cualquier API que hable el protocolo de OpenAI (`/v1/chat/completions`) funciona: escribe su dirección (normalmente
terminada en `/v1`) y, si la pide, su clave de API en «¿El servicio pide una clave de API?». Por ejemplo OpenRouter
(`https://openrouter.ai/api/v1`) o Groq (`https://api.groq.com/openai/v1`). Estos servicios son en línea y se facturan
según sus propias condiciones.

## Si algo falla

| Indicador rojo, mensaje | Solución |
|---|---|
| «Ningún servicio responde en …» | Ollama o LM Studio no está abierto, o el servidor no está iniciado (LM Studio: Start Server). Revisa la dirección y el puerto. |
| Lo mismo, con ROMKADE en Docker | Usa `http://host.docker.internal:11434/v1`; en Linux, ver más arriba. |
| «No se encontró ningún modelo» | Descarga un modelo (`ollama pull …`) y recarga la lista. |
| «El modelo responde, pero no en el formato esperado» | El modelo es demasiado pequeño para seguir la consigna: usa uno de 7B o más. |
| Respuestas muy lentas | Normal en la primera llamada (carga); si no, usa un modelo más pequeño. |

Si el modelo deja de responder durante las descripciones, la generación se detiene tras 5 fallos seguidos; vuelve a
lanzarla cuando el modelo esté disponible: los juegos ya descritos se conservan.
