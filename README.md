# Chess analyzer

Terminal Stockfish analysis, with piece rendering adapted from
[Thomas Mauran's chess-tui](https://github.com/thomas-mauran/chess-tui).
Full renderer credits and license information are below.

## Install and run

Requires Python 3.11+; no terminal image support is needed. From this checkout:

```sh
uv tool install .      # or: pipx install .
chess-analyzer
chess-analyzer --pgn game.pgn
```

The command works from any directory. If it isn't on PATH, use
`uv tool update-shell` (or `pipx ensurepath`) and restart your shell.
For development without a tool install: `uv run chess-analyzer`.

Alternatively pass a quoted FEN. Options: `--ascii`, `--time 0.5`, `--lines 3`,
`--threads 2`, `--hash 256`, and `--engine /path/to/stockfish`.

## Stockfish

The engine is installed separately. If none is found, the app detects your OS
(and Linux distribution) and suggests an installation command:

| Platform | Command |
| --- | --- |
| Debian/Ubuntu and derivatives (e.g. Linux Mint) | `sudo apt install stockfish` |
| Arch and derivatives (e.g. Manjaro) | `sudo pacman -S stockfish` |
| Fedora | `sudo dnf install stockfish` |
| macOS (Homebrew) | `brew install stockfish` |
| Windows (WinGet) | `winget install --id Stockfish.Stockfish --exact` |

Linux detection uses the distribution’s `ID` and `ID_LIKE` from `os-release`;
Fedora is matched by `ID` only. Other distros/platforms get the
[official download link](https://stockfishchess.org/download/).

After installation, make sure `stockfish` (`stockfish.exe` on Windows) is on
PATH: add the executable’s directory to PATH and restart your shell if needed.
Alternatively, pass an executable with `chess-analyzer --engine /path/to/stockfish`
(on Windows: `chess-analyzer --engine "C:\path\to\stockfish.exe"`).

Stockfish is found on PATH or beside the application module as `stockfish`
(`stockfish.exe` on Windows). Engine binaries aren't bundled or downloaded
automatically; installing the app through uv tool or pipx only installs its
Python dependencies.

## Navigation

PGNs open at the final position. **↑/↓** choose an original move or Stockfish
alternative; **→/Enter** follow it; **←** steps back; **Esc** returns from an
explored line to its game position. Moves and the return link are clickable.
**f** flips, **r** reanalyzes, **q** quits. Original-game history supports clicking
any move or Start; branches are retained, and navigation never waits for analysis.

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
