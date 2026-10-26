<p align="center">
  <img src="frontend/src/assets/brand/romkade-manager-logo-480.webp" alt="ROMKADE Manager" width="380">
</p>

<h3 align="center">Your retro handheld, finally organized.<br>Manage it from your computer, and just ask ChatGPT or Claude to play.</h3>

<p align="center">
  <b><a href="https://romkade.com/en/">romkade.com</a></b> &nbsp;·&nbsp; <b>English</b> · <a href="README.fr.md">Français</a> · <a href="README.es.md">Español</a>
</p>

<p align="center">
  <a href="https://romkade.com/video/hero-en.mp4"><img src="docs/readme/presentation-en.jpg" alt="Watch the presentation video" width="760"></a>
  <br><sub>▶ Watch the 50-second presentation</sub>
</p>

---

**ROMKADE Manager** turns your retro handheld (Anbernic, Miyoo, TrimUI…) into a console you control from your
computer. Your whole microSD card becomes a beautiful library with box art and game pages, and **Duke**, your AI
assistant, knows every game on it. No cable, no pulling out the card: everything happens over Wi-Fi.

## ✨ What you can do

- 📚 **See your whole collection.** Every game on the card, with box art, summary, trailer and genre. Search finds it even with a typo.
- 🤖 **Ask Duke.** “A two-player game?”, “How do I beat this level?”: the AI assistant knows your library and launches games for you.
- 💬 **Talk to your console from ChatGPT, Claude or Google Home.** “Launch Tetris”, “Set the volume to 40%”, from your phone or your computer.
- 🎮 **Play from your computer.** Launch a game, quit it, resume from a save, change the volume.
- ➕ **Add games by drag and drop.** Over Wi-Fi, straight into the right folder, checked before anything is copied.
- 💾 **Keep your saves safe.** Copy them all to your computer in one click, restore one when you need it.
- 🕹️ **Controllers and Bluetooth sound.** Choose who plays with which controller, send the sound to a Bluetooth speaker.
- ⏳ **Playtime.** See how long you play, with optional reminders.

<table>
  <tr>
    <td width="50%"><img src="docs/readme/assistant-duke.webp" alt="Duke, the AI assistant"><p align="center"><sub>Duke knows your games</sub></p></td>
    <td width="50%"><img src="docs/readme/bibliotheque-consoles.webp" alt="The library, by console"><p align="center"><sub>Your library, console by console</sub></p></td>
  </tr>
  <tr>
    <td width="50%"><img src="docs/readme/manettes.webp" alt="Controllers"><p align="center"><sub>Who plays with which controller</sub></p></td>
    <td width="50%"><img src="docs/readme/bluetooth-enceinte.webp" alt="Bluetooth speaker"><p align="center"><sub>Game sound on a speaker</sub></p></td>
  </tr>
</table>

## 🎮 Works with your console

| | Consoles and systems |
|---|---|
| ✅ **Verified** | Anbernic RG35XX (Pro, Plus, H, SP, 2024), RG28XX, RG34XX, RG40XX, RG CubeXX with Stock OS Mod · Miyoo Mini and Mini Plus with Onion OS |
| 🧪 **Experimental** | Knulli, Batocera, ROCKNIX, muOS, ArkOS, spruce, MinUI / NextUI, Android with RetroArch |

All your console needs is to be on the same Wi-Fi as your computer.

## 🚀 Get started in 3 steps

1. **Install Docker Desktop**, free on macOS, Windows and Linux.
2. **Start ROMKADE Manager.** In a terminal, in an empty folder:

   ```bash
   curl -fsSLO https://github.com/RomKade/romkade-manager/releases/latest/download/compose.yaml
   docker compose up -d
   ```

   On Windows, type `curl.exe` instead of `curl`.
3. **Open http://localhost:8765**, create your ROMKADE account and follow the guided setup: ROMKADE Manager finds your
   console on the network for you.

Step-by-step guide with screenshots: **[romkade.com/en/installation](https://romkade.com/en/installation/)**.
Coming soon: install in one click from Docker Desktop's Extensions.

## 🔒 Your games, your console

- **No games provided.** ROMKADE Manager organizes the files you already own.
- **Your data stays at home.** Library, saves and settings live on your computer.
- **Nothing changes without you.** The console is only modified when you ask: adding games, restoring a save, controller or Bluetooth settings.
- **Private by design.** The interface only opens on your computer, never on the Internet.

## 🛠️ Under the hood

Python (FastAPI) and SQLite on the server side, a React interface, Typesense for search, all packaged with Docker for
Intel/AMD and ARM. ROMKADE Manager reaches the console over SSH on your local network; ROMKADE Cloud, an MCP server,
connects ChatGPT, Claude and Google Home to it. Installation from source, development and every feature in detail:
[technical reference](docs/reference.md).

## License

© 2026 ROMKADE. The code is published for reading and evaluation; any other use needs ROMKADE's written permission
(see [LICENSE](LICENSE)). ROMKADE is not affiliated with any console maker; trademarks belong to their owners.
