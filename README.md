# Chess analyzer

Terminal chess analysis, with Stockfish as the default engine.

Piece rendering adapted from [Thomas Mauran's chess-tui](https://github.com/thomas-mauran/chess-tui).
Full renderer credits and license information are below.

## Install and run

Requires Python 3.11+.

```sh
uv tool install .      # or: pipx install .
chess-analyzer
chess-analyzer --pgn game.pgn
chess-analyzer "2kr2nr/1pp2ppp/3b4/1P3q2/2Pp1B2/5Q1P/RP3PP1/R5K1 w - - 0 1"  # Supi–Carlsen position
```

The command works from any directory. If it isn't on PATH, use
`uv tool update-shell` (or `pipx ensurepath`) and restart your shell.
For development without a tool install: `uv run chess-analyzer`.

Alternatively, pass a quoted FEN.

Options:

- `--ascii` — use ASCII pieces
- `--time 0.5` — set analysis time
- `--lines 3` — show multiple lines
- `--threads 2` — set engine threads, if supported
- `--hash 256` — set engine hash size, if supported
- `--engine /path/to/engine` — choose a UCI engine executable

## Stockfish

Stockfish is the default engine and is installed separately. If it isn't found,
the app detects your OS (and Linux distribution) and suggests an installation command:

| Platform | Command |
| --- | --- |
| Debian/Ubuntu and derivatives (e.g. Linux Mint) | `sudo apt install stockfish` |
| Arch and derivatives (e.g. Manjaro) | `sudo pacman -S stockfish` |
| Fedora | `sudo dnf install stockfish` |
| macOS (Homebrew) | `brew install stockfish` |
| Windows (WinGet) | `winget install --id Stockfish.Stockfish --exact` |

Other distros/platforms get the [official download link](https://stockfishchess.org/download/).

After installation, make sure `stockfish` (`stockfish.exe` on Windows) is on
PATH: add the executable’s directory to PATH and restart your shell if needed.
Alternatively, pass an executable with `chess-analyzer --engine /path/to/stockfish`
(on Windows: `chess-analyzer --engine "C:\path\to\stockfish.exe"`).

Stockfish is found on PATH or beside the application module as `stockfish`
(`stockfish.exe` on Windows). Other UCI engines can be selected with
`--engine /path/to/engine`; engine-specific files and settings (such as Leela's
network weights and backend) must be configured separately. The app applies
thread, hash, and multiple-line settings only when the engine supports them.

## Navigation

PGNs open at the final position.

- **↑/↓** — choose an original move or engine alternative
- **→/Enter** — follow the selected move; **←** — step back
- **Esc** — return from an explored line to its game position
- **f** — flip board; **r** — reanalyze; **q** — quit

Moves, the return link, and any original-game move (or Start) are clickable.
Branches are retained, and navigation never waits for analysis.

Use at least 40×24 terminal cells. Larger boards use multiline pieces; smaller
ones use chess glyphs. Narrow layouts stack the panels; scroll with the mouse
wheel or Page Up/Down. Blue highlights the selected move, yellow the previous
move, and red a checked king.

## Renderer credits

The multiline piece artwork and size-adaptive rendering approach are adapted
from [Thomas Mauran's chess-tui](https://github.com/thomas-mauran/chess-tui),
using its [native piece designs](https://github.com/thomas-mauran/chess-tui/tree/fc1d4841532bf72f5a25c5cb45abe82ec25e056b/src/pieces).
Thank you to Thomas Mauran and the chess-tui contributors.

The artwork is used under the MIT License; its copyright and full license notice
are preserved in [licenses/chess-tui-MIT.txt](licenses/chess-tui-MIT.txt). We
adapted the art to Python/Textual, centered it within our board cells, reduced
the large king's outer padding, and aligned the large pawn's head and base. Our
Stockfish analysis, PGN navigation, and branch management remain independent of
the upstream Rust application.

## Verify

With Stockfish installed: `uv run python -m unittest discover -s tests -v`.
