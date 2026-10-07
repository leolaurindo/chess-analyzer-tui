# Chess Analyzer TUI

Interactive terminal chess analysis

Initialize analysis from FEN or PGN text, files, your clipboard, directly from URLs or public apis from `chess.com` and `lichess.org`. Stockfish is the default engine, but also supports other UCI engines.

- Piece rendering adapted from [Thomas Mauran's chess-tui](https://github.com/thomas-mauran/chess-tui). Full renderer credits and license information are below.
- Opening information extracted from [lichess's github repository](#opening-data-credits).

![Chess Analyzer TUI demo](demos/showcase.gif)

## Install and run

Requires Python 3.11+.

Once published on PyPI, install the `chess-analyzer-tui` package with either tool
manager. Both install the `chess-analyzer` command (the command name is not a
separate PyPI package):

```sh
uv tool install chess-analyzer-tui   # or: pipx install chess-analyzer-tui
chess-analyzer # opens a new game
chess-analyzer "1. e4 e5 2. Nf3 Nc6 *"
chess-analyzer https://lichess.org/nrmBGiQF
chess-analyzer https://lichess.org/study/r072zv4F/R33cxdop
chess-analyzer https://www.chess.com/game/live/4912555148
chess-analyzer --file game.pgn
chess-analyzer --file position.fen
chess-analyzer --clip
chess-analyzer --continue          # or: chess-analyzer -c
chess-analyzer --library           # choose a saved analysis
chess-analyzer --browse chess.com --user leolaurindo
chess-analyzer --browse lichess --user leolaurindo
chess-analyzer --white "Supi" --black "Carlsen" "2kr2nr/1pp2ppp/3b4/1P3q2/2Pp1B2/5Q1P/RP3PP1/R5K1 w - - 0 1"
```

The command works from any directory. If it isn't on PATH, use
`uv tool update-shell` (or `pipx ensurepath`) and restart your shell.

Pass quoted FEN or PGN text, a Chess.com game URL, a Lichess game or study URL, or
an HTTPS URL that serves plain-text PGN. The examples include a Lichess study of
Mikhail Tal and a regular Lichess game by Magnus Carlsen, plus a public Chess.com
game by GM LPSupi. A game URL is sufficient for either provider; no username,
month, or API key is required. Without a game link, use
`--browse chess.com --user NAME` or `--browse lichess --user NAME` instead. Chess.com URL-only lookup uses an undocumented callback to
resolve archive details, then downloads the PGN from a public monthly archive;
if that callback becomes unavailable, use the browser, which uses documented
APIs only. Use `--file`
to read a UTF-8 file or `--clip` to read the clipboard. Choose one input source;
the format is detected automatically. URL loads
are limited to public HTTPS hosts and a 10-second timeout per request. Generic
downloads are capped at 4 MiB; Chess.com monthly archives at 16 MiB. Without
input, analysis starts from the initial position.

Options:

- `--file PATH` — load FEN or PGN from a file
- `--clip` — load FEN or PGN from the clipboard
- `--continue` / `-c` — restore the last analysis session
- `--library` — interactively reopen a named local analysis
- `--browse PROVIDER --user NAME` — browse public games; provider is `chess.com` or `lichess`
- `--ascii` — use ASCII pieces
- `--time 0.5` — set analysis time
- `--lines 3` — show multiple lines
- `--threads 2` — set engine threads, if supported
- `--hash 256` — set engine hash size, if supported
- `--engine /path/to/engine` — choose a UCI engine executable
- `--white "Supi"` / `--black "Carlsen"` — label the players (override PGN names)

Copy a FEN position or PGN game and run `chess-analyzer --clip`.
On Linux, install `wl-clipboard` for Wayland, or `xclip` / `xsel` for X11;
a graphical session is required. macOS and Windows use their built-in clipboard
support.

## Clipboard export

- **Ctrl+F** copies the current displayed position as FEN.
- **Ctrl+P** copies the full analysis as PGN: the original mainline first, imported
  and explored variations, position comments, and variation starting comments.
  Engine suggestions are included only after you follow them.

Original PGN headers (including Result, Date, Event, and Site) survive sessions
and named saves. `--white` / `--black` overrides are reflected in exported PGN.
Nonstandard starting positions include SetUp/FEN headers so they reopen correctly,
including analyses with no moves yet.
Clipboard failures are shown without changing the analysis. These shortcuts are
available on the analysis screen, not inside dialogs. Clipboard export uses the
same platform support described above; there is no file-export dialog.

## Continue an analysis

Run `chess-analyzer --continue` (or `-c`) to restore the last game, explored
branches, original PGN headers, imported comments and side variations, current
position, player names, and board orientation. Engine analysis
is recalculated using the current command-line settings.

The session saves automatically as you navigate or flip the board. Starting a
new analysis replaces the previous session. One small `session.json` file is
stored locally:

- Linux: `$XDG_STATE_HOME/chess-analyzer`, or `~/.local/state/chess-analyzer`
- macOS: `~/Library/Application Support/chess-analyzer`
- Windows: `%LOCALAPPDATA%\\chess-analyzer`

`--continue` cannot be combined with text, `--file`, or `--clip`.

**Breaking save-format change:** Sessions and named library saves now use snapshot
version 3 with required PGN headers. Older version 2 saves are unsupported; there
is no migration. Reimport the original FEN/PGN and save a new analysis.

## Local analysis library

- **c** opens the current position’s comment editor; **Ctrl+S** or Save applies
  the edit, and Esc cancels. An empty comment removes it. Imported comments can
  be edited, and explored positions can have their own comments.
- **s** saves the entire analysis under a name: comments, imported and explored
  variations, original PGN headers, current position, player names, and orientation.
  Existing names require explicit replacement confirmation. Engine evaluations are recalculated.
- **l** opens the library; choose with ↑/↓ and Enter. Esc leaves the current
  analysis unchanged. You can also start with `chess-analyzer --library`.

Named saves are independent of the automatic `--continue` snapshot. Further
edits require **s** to update the named save; changing games does not change it.
The library stores one JSON file per named analysis in:

- Linux: `$XDG_DATA_HOME/chess-analyzer/analyses`, or `~/.local/share/chess-analyzer/analyses`
- macOS: `~/Library/Application Support/chess-analyzer/analyses`
- Windows: `%LOCALAPPDATA%\\chess-analyzer\\analyses`

## Online game browser

Choose the provider and public username on the command line:

```sh
chess-analyzer --browse chess.com --user leolaurindo
chess-analyzer --browse lichess --user leolaurindo
```

Games load automatically; there are no provider, username, or month selectors.
No login, token storage, or play-token reuse is needed.

- **↑/↓** chooses a game; **Enter** opens it for analysis, preserving its PGN
  comments and variations. Only completed standard-chess games are listed.
- **←/→** browses newer/older games. Chess.com uses archive months, newest first;
  Lichess uses pages of 50 games. Public Chess.com archives can lag due to caching.
- **r** reloads the current month/page, including after a loading error.
- **Esc** cancels without changing your analysis, including during a request.
- After opening a game, **b** returns to this provider/username’s browser. This
  shortcut is available only when the app was started with `--browse`.
- Press **s** during analysis if you want to keep a named local copy.

Requests are sequential, run off the UI thread, and have time/size limits. Rate
limits are shown without automatic retries; wait at least a minute before retrying.
Canceling discards a pending result; the underlying HTTP request can run until its
timeout. Starting the browser automatically requests the latest games.

`--browse` and `--library` restore the last session behind their menus when one
exists, so canceling does not replace your continue snapshot with a new game.
These startup menus cannot be combined with another input source.

Provider references: [Chess.com Published Data API](https://support.chess.com/en/articles/9650547-published-data-api)
and [Lichess game export API](https://lichess.org/api#tag/Games/operation/apiGamesUser).

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

Stockfish is found on PATH or alongside the application package as `stockfish`
(`stockfish.exe` on Windows). Other UCI engines can be selected with
`--engine /path/to/engine`—for example, Leela Chess Zero (Lc0) with
`--engine /path/to/lc0`. Configure engine-specific files and settings, such as
Lc0's network weights and backend, separately. The app applies thread, hash,
and multiple-line settings only when the engine supports them.

## Navigation

PGNs open at the final position and use their `White`/`Black` headers for player labels
when present. Use `--white` and `--black` to set or override names, including for FENs.
PGN comments (including Lichess study annotations) appear at their own positions.
Imported side variations are listed alongside engine moves; follow them with the
same keys or mouse clicks. Comments stay attached to that game's move tree, not
other games or engine-generated positions.

Opening labels show the ECO code and opening/variation name for the latest known
position on the current line. Transpositions are recognized; stepping back or
exploring another line updates the label. For FEN-only input, only the supplied
position (and subsequent moves) can be matched. Labels work offline.

- **↑/↓** — choose an original move, retained variation, or engine alternative
- **→/Enter** — follow the selected move; **←** — step back
- **Esc** — return from an explored line to its game position
- **f** — flip board; **r** — reanalyze; **q** — quit

Moves, the return link, and any original-game move (or Start) are clickable.
Branches are retained, and navigation never waits for analysis.

Use at least 40×24 terminal cells. Larger boards use multiline pieces; smaller
ones use chess glyphs. Narrow layouts stack the panels; scroll with the mouse
wheel or Page Up/Down. Blue highlights the selected move, yellow the previous
move, and red a checked king.

## Opening data credits

Opening names and variations come from Lichess’s
[`chess-openings`](https://github.com/lichess-org/chess-openings) dataset, released
under the [CC0 Public Domain Dedication](https://creativecommons.org/publicdomain/zero/1.0/).
The bundled position index uses revision
[`65bb03f`](https://github.com/lichess-org/chess-openings/tree/65bb03f76c7f077984db01a2f2d0534e4181ddfe)
and can be regenerated with `uv run python scripts/build_openings.py`.
No opening descriptions are included.

## Renderer credits

The piece artwork and size-adaptive rendering approach are adapted from
[Thomas Mauran's chess-tui](https://github.com/thomas-mauran/chess-tui), using its
[piece designs](https://github.com/thomas-mauran/chess-tui/tree/fc1d4841532bf72f5a25c5cb45abe82ec25e056b/src/pieces).
The artwork is used under the MIT License; the full notice is preserved in
[licenses/chess-tui-MIT.txt](licenses/chess-tui-MIT.txt). The rest of this project
is released under [MIT](LICENSE).

## Development

Application modules live in `chess_analyzer/`: `cli.py`, `tui.py`, `input.py`,
`game.py`, `session.py`, `library.py`, `online.py`, `browser.py`, and `dialogs.py`.
Piece artwork and the bundled opening dataset are also inside this package.
Run from the checkout with `uv run chess-analyzer` or
`uv run python -m chess_analyzer.cli`.

## Verify

With Stockfish installed: `uv run python -m unittest discover -s tests -v`.
