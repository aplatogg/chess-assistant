# ♟ Chess.com Assistant

A real-time Chess.com assistant powered by **Stockfish** and **Playwright**.  
Reads the live board state via browser CDP, analyzes with Stockfish, and shows a floating overlay with top moves, evaluation bar, and principal variation — with optional auto-play.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![License](https://img.shields.io/badge/License-MIT-green)

---

## Features

- **Live board reading** — grabs FEN directly from the Chess.com game object (no screen capture)
- **Stockfish analysis** — top 5 moves with scores, depth, and full principal variation
- **Floating overlay UI** — always-on-top panel with eval bar, win%, opening name, clock
- **Auto-play** — two modes:
  - `NAT` — human-like timing (2–5s think time, ~80% best move rate)
  - `BOT` — engine-like speed (~0.2–0.9s, ~93% best move rate)
- **Opening book** — recognizes 60+ openings and displays the name live
- **Time management** — auto-reduces analysis depth when clock is low
- **Anti-throttle** — injects silent Web Audio to prevent background-tab slowdowns
- **Brave / Firefox support** — connects to existing browser via CDP or launches fresh

---

## Requirements

- Python 3.10+
- [Stockfish](https://stockfishchess.org/download/) — place `stockfish.exe` in the same folder as the script
- Brave Browser (recommended) or Firefox

---

## Installation

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_USERNAME/chess-assistant.git
cd chess-assistant

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Install Playwright browsers
playwright install chromium

# 4. Download Stockfish
# https://stockfishchess.org/download/
# Place stockfish.exe in this folder
```

---

## Usage

### Step 1 — Launch Brave with remote debugging

```bash
"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe" --remote-debugging-port=9222
```

### Step 2 — Open Chess.com and start a game

Go to [chess.com/play/online](https://www.chess.com/play/online) and start a game.

### Step 3 — Run the assistant

```bash
# Connect to running Brave (recommended)
python chess_assistant.py --browser brave

# With auto-play enabled from the start
python chess_assistant.py --browser brave --auto-play

# Custom analysis depth (default: 18)
python chess_assistant.py --depth 20

# Launch a new browser window instead of connecting
python chess_assistant.py --launch
```

---

## Overlay UI

```
┌─────────────────────────────────────┐
│ ♟ Chess.com Assistant            ● │
├─────────────────────────────────────┤
│ [========== eval bar ===========]  │
│           +1.45  62%               │
│        Sicilian: Najdorf           │
│ Best: Kuda e4->f6    [AUTO: ON][NAT]│
│ ⏱ 4:32                             │
│ Top moves:                          │
│   1. Kuda e4->f6      +1.45  d18   │
│   2. Benteng d1->e1   +1.12  d18   │
│   3. Bidak d4->d5     +0.98  d18   │
│   4. Gajah c1->e3     +0.87  d18   │
│   5. Raja g1->h1      +0.71  d18   │
├─────────────────────────────────────┤
│ Principal variation:                │
│   Nf6 d5 Nxd5 Nxd5 Qxd5 Nc6 ...  │
├─────────────────────────────────────┤
│ Depth: [18▲▼]  d18 · Putih jalan  │
└─────────────────────────────────────┘
```

| Button | Action |
|--------|--------|
| `AUTO: ON/OFF` | Toggle auto-play |
| `NAT / BOT` | Switch between human-like and engine-like play style |
| `Depth spinner` | Adjust Stockfish analysis depth (5–30) |

---

## Auto-play Modes

| Mode | Think time | Best move % | Use case |
|------|-----------|-------------|---------|
| **NAT** | 2–5 seconds | ~80% | Looks human, avoids detection |
| **BOT** | 0.2–0.9 seconds | ~93% | Fastest, engine-like |

Both modes automatically play faster when clock is below 30 seconds.

---

## Stockfish Path

The script searches for `stockfish.exe` in this order:

1. `F:\Claude Normal\File\stockfish.exe` (default output dir)
2. `C:\tools\stockfish.exe`
3. `stockfish.exe` (current directory)
4. System PATH

To use a custom path, edit `STOCKFISH_CANDIDATES` at the top of `chess_assistant.py`.

---

## CLI Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--browser` | `brave` | `brave` or `firefox` |
| `--launch` | off | Launch new browser instead of connecting to existing |
| `--port` | `9222` | CDP remote debugging port |
| `--depth` | `18` | Stockfish analysis depth |
| `--auto-play` | off | Enable auto-play on startup |

---

## How It Works

1. **Board reading** — Connects to Brave/Chrome via Chrome DevTools Protocol (CDP). Reads the FEN position directly from the Chess.com JavaScript game object (`board.game.getFEN()`), falling back to DOM piece parsing if the API is unavailable.

2. **Engine analysis** — Sends the FEN to Stockfish via UCI protocol using `python-chess`. Requests `MultiPV 5` (top 5 moves) with configurable depth.

3. **Overlay** — A `tkinter` window rendered on a separate thread, always on top. Updates every ~0.7 seconds via a thread-safe queue.

4. **Auto-play** — On our turn, waits for the configured think delay, verifies the position hasn't changed (opponent didn't premove), then simulates mouse clicks on the board squares using CDP mouse events with a Bezier curve movement path.

---

## Disclaimer

This tool is for **educational and research purposes** only.  
Using third-party assistance tools during rated Chess.com games violates their [Terms of Service](https://www.chess.com/legal/user-agreement).  
Use only in unrated games, puzzles, or analysis mode.

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

<div align="center">
  Made by <a href="https://github.com/aplatogg">@aplatogg</a>
</div>
