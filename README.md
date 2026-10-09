# Chess Analyzer TUI

Interactive terminal chess analysis

Initialize analysis from FEN or PGN text, files, your clipboard, directly from URLs or public apis from `chess.com` and `lichess.org`. Stockfish is the default engine, but also supports other UCI engines.

- Piece rendering adapted from [Thomas Mauran's chess-tui](https://github.com/thomas-mauran/chess-tui). Full renderer credits and license information are below.
- Opening information extracted from [lichess's github repository](#opening-data-credits).

![Chess Analyzer TUI demo](demos/showcase.gif)

**Convenient ways to jump straight into the analysis**:
- Jump into your latest game: Save a public Chess.com or Lichess account once, then run `chess-analyzer -f` to analyze its latest available completed game. Or press **Ctrl+L** from Home or analysis. See [Latest available game](#latest-available-game) for setup details.
- Start an analysis from your clipboard with `chess-analyzer --clip`: it can be FEN position, PGN and even chess.com or lichess url.
- Browse games from public accounts with `chess-analyzer --browse lichess --user <user>`

## Install and run

Requires Python 3.11+.

Installation options:
```sh
brew install leolaurindo/tap/chess-analyzer-tui
uv tool install chess-analyzer-tui
pipx install  chess-analyzer-tui
```


All options provide the `chess-analyzer` command.
The Homebrew formula also installs Stockfish and the Python runtime.
Otherwise, see [how to install stockfish for your machine here](#stockfish).


**Common entry points**:

```sh
chess-analyzer # Home: analyze the initial position
chess-analyzer "1. e4 e5 2. Nf3 Nc6 *"
chess-analyzer https://lichess.org/nrmBGiQF
chess-analyzer https://lichess.org/study/r072zv4F/R33cxdop
chess-analyzer https://www.chess.com/game/live/4912555148
chess-analyzer --file game.pgn
chess-analyzer --file position.fen
chess-analyzer --clip
chess-analyzer --continue          # or: chess-analyzer -c
chess-analyzer --library           # choose a saved analysis
chess-analyzer --follow            # or -f; first save an account with u in the app
chess-analyzer --browse chess.com --user leolaurindo
chess-analyzer --browse lichess --user leolaurindo
chess-analyzer --white "Supi" --black "Carlsen" "2kr2nr/1pp2ppp/3b4/1P3q2/2Pp1B2/5Q1P/RP3PP1/R5K1 w - - 0 1"
```

Run `chess-analyzer` from any directory. If the command isn't on your `PATH`, run
`uv tool update-shell` (or `pipx ensurepath`) and restart your shell.

**Input:** Provide one source: quoted FEN or PGN text, a Chess.com game URL, a
Lichess game or study URL, an HTTPS URL serving plain-text PGN, `--file PATH` for
a UTF-8 file, or `--clip` for clipboard contents. The format is detected
automatically. With no input, analysis starts from the initial position.

A game URL works directly for Chess.com and Lichess; no username, month, or API
key is needed. To browse a user's public games instead, use
`--browse chess.com --user NAME` or `--browse lichess --user NAME`. Chess.com
game URLs are resolved through an undocumented callback and downloaded from a
public monthly archive. If the callback stops working, use `--browse`, which
uses documented APIs only.

URL loads are restricted to public HTTPS hosts and time out after 10 seconds per
request. Generic downloads are limited to 4 MiB; Chess.com monthly archives are
limited to 16 MiB.

Options:

- `--file PATH` — load FEN or PGN from a file
- `--clip` — load FEN or PGN from the clipboard
- `--continue` / `-c` — restore the last analysis session
- `--library` — interactively reopen a named local analysis
- `--follow` / `-f` — load the default account’s latest available completed standard game
- `--browse PROVIDER --user NAME` — browse public games; provider is `chess.com` or `lichess`
- `--ascii` — use ASCII pieces
- `--time 0.5` / `-t 0.5` — set analysis time
- `--lines 3` — show multiple lines
- `--threads 2` — set engine threads, if supported
- `--hash 256` — set engine hash size, if supported
- `--engine /path/to/engine` — choose a UCI engine executable
- `--white "Supi"` / `--black "Carlsen"` — label the players (override PGN names)

Copy a FEN position or PGN game and run `chess-analyzer --clip`.
On Linux, install `wl-clipboard` for Wayland, or `xclip` / `xsel` for X11;
a graphical session is required. The active Wayland/X11 clipboard is preferred
on Linux, including WSL, rather than silently choosing a different host clipboard.
macOS and Windows use their built-in clipboard support.

## File export

Press **e** from analysis or Home to open export. Choose **FEN** for the displayed
position or **PGN** for the full analysis: original mainline, imported/explored
variations, and comments. Unfollowed engine suggestions are excluded.

Type a file name or a full destination path. A file name alone uses the global
application data folder's `exports` directory:

- Linux: `$XDG_DATA_HOME/chess-analyzer/exports`, or `~/.local/share/chess-analyzer/exports`
- macOS: `~/Library/Application Support/chess-analyzer/exports`
- Windows: `%LOCALAPPDATA%\chess-analyzer\exports`

The dialog prints the default folder and resolved destination before writing.
**Export** or Enter confirms the write; an existing file requires explicit
replacement permission. After success, the full saved path stays in the dialog
until you press **Done**, Close, or Esc. Canceling before Export creates no file.
Errors leave the analysis and existing destination unchanged; writes are atomic.

Original PGN headers survive sessions and named saves; player display overrides
are reflected in the exported PGN. Nonstandard starting positions include
SetUp/FEN headers, including analyses with no moves yet.

Ctrl+F / Ctrl+P clipboard export has been removed. Clipboard input via `--clip`
is still available.

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
- **Delete** in the library removes the selected named save after confirmation.
  Cancel is focused by default. Deleting a save does not change the currently
  opened analysis or its automatic continue snapshot.

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

Press **b** from analysis or Home to browse. Without an account selected, choose
Chess.com or Lichess and enter a public username; Enter or Save & browse saves
the default and opens its games.
The selection is saved as your one default account. **u** changes it, with the
current values prefilled. CLI accounts open directly but do not change the saved
default merely by browsing.
Games load automatically; months/pages are selected with the paging keys.
No login, token storage, or play-token reuse is needed.

- **↑/↓** chooses a game; **Enter** opens it for analysis, preserving its PGN
  comments and variations. Only completed standard-chess games are listed.
- **←/→** browses newer/older games. Chess.com uses archive months, newest first;
  Lichess uses pages of 50 games. Public Chess.com archives can lag due to caching.
- **r** reloads the current month/page, including after a loading error.
- **Esc** cancels without changing your analysis, including during a request.
- After opening a game, **b** returns to this provider/username’s browser. This
  shortcut also works after selecting an account in the app.
- Press **s** during analysis if you want to keep a named local copy.

Requests are sequential, run off the UI thread, and have time/size limits. Rate
limits are shown without automatic retries; wait at least a minute before retrying.
Canceling discards a pending result; the underlying HTTP request can run until its
timeout. Starting the browser automatically requests the latest games.

`--browse`, `--library`, and `--follow` restore the last session behind their dialogs when one
exists, so canceling does not replace your continue snapshot with a new game.
These startup menus cannot be combined with another input source.

Provider references: [Chess.com Published Data API](https://support.chess.com/en/articles/9650547-published-data-api)
and [Lichess game export API](https://lichess.org/api#tag/Games/operation/apiGamesUser).

## Latest available game

1. Run `chess-analyzer`, press **u**, choose Chess.com or Lichess, and enter a
   public username. ↑/↓ changes provider, including while typing the username.
   Enter or **Save & browse** persists that single default.
2. Run `chess-analyzer -f` / `--follow`, or press **Ctrl+L** from Home/analysis,
   to load its latest available completed standard-chess game at the final position.
   **b** browses that account's other games; **u** changes the default.

Plain startup never fetches online games, even with a saved account. Follow is
one explicit, one-time fetch—not polling or live monitoring. It cannot be
combined with text, `--file`, `--clip`, `--continue`, `--library`, or `--browse`.
`-t` remains engine thinking time. `--white` / `--black` also override the
follow-loaded game's labels and exported PGN headers.

Missing follow configuration reports how to set it up before starting the engine.
Malformed configuration is reported; ordinary startup still lets you repair it
with **u**. Only a successful latest-game load replaces the analysis/session.
Loading, empty-account, and error states remain in a cancellable dialog; **r**
retries explicitly. **Esc**, Home, or quit cancel. Help cancels the download but
keeps the dialog retryable underneath. Cancellation discards the result and stops
further archive/page/export requests after the current bounded HTTP request finishes.
There is no authentication, token storage, or automatic retry.

Chess.com searches archive months newest first, falling back to older archives
when no completed standard games are available. Public archives can lag, so the
result is described as **latest available**. Lichess traverses filtered empty
pages using its API's newest-created ordering.

The account is stored atomically as provider/username JSON in `config.json`,
separately from analysis snapshots:

- Linux: `$XDG_CONFIG_HOME/chess-analyzer`, or `~/.config/chess-analyzer`
- macOS: `~/Library/Application Support/chess-analyzer`
- Windows: `%LOCALAPPDATA%\chess-analyzer`

A failed account save is shown and leaves the previous account/config unchanged.

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

## Home and help

Plain startup opens **Home**, the initial-position chess analysis, without any
network request. Explicit inputs and startup library/browser options still open
what you requested.

- **h** goes Home outside text fields; **F2** works on every screen, including
  dialogs. Ctrl+H is not used because terminals interpret it as Backspace.
  Home always shows the initial chess position, retaining the scratch tree,
  and cancels pending edits/downloads without applying them.
- **PgUp** rewinds the current game to its own starting position; **PgDown** goes
  to its last original position, never to an explored engine/side variation.
  For FEN input, both return to the imported FEN, even after exploring moves.
  Neither replaces the current game or its tree. The Home key is not bound.
- **g** on Home returns to the preserved game with its exact position, comments,
  branches, and orientation. Home's own analysis is retained separately. While
  a game is preserved, Home edits/navigation do not replace its `--continue`
  snapshot. Opening another game replaces the preserved game.
- **b** opens the current account’s browser; **u** chooses or changes the provider
  and public username, even when already configured. **Ctrl+L** loads the latest
  available completed game. **l** opens the library;
  **i** imports pasted FEN, PGN, or an HTTPS URL. **Ctrl+S** imports; **Esc**
  cancels. Downloads run off the UI thread, using the same bounded URL loader
  as CLI input.
- **?** shows contextual help outside text fields; **F1** works everywhere.
  Help is an overlay: Esc or repeated F1/`?` closes only help and returns to the
  underlying dialog with unsubmitted fields intact. Active import/browser/latest
  downloads are canceled without closing their dialog; Ctrl+S (import) or
  **r** (browser/latest) retries after closing help. Help scrolls on small terminals.
- **q** quits outside text fields; **Ctrl+Q** quits everywhere, canceling pending
  dialogs. Plain `h`, `q`, and `?` remain typeable in inputs and text areas.

Only help, Home, and quit are global. Analysis commands do not leak into dialogs.
**e** exports the current FEN or full analysis PGN to a file.

## Navigation

PGNs open at the final position and use their `White`/`Black` headers for player labels
when present. Use `--white` and `--black` to set or override names, including for FENs.
When original player names or provider profile URLs identify the saved account,
newly opened games put that player at the bottom (Black automatically flips).
This applies to follow, browser, imported games, and library loads. Display-name
overrides do not replace original player identity. **f** still flips manually;
`--continue` preserves the saved orientation instead of forcing it again.

PGN comments (including Lichess study annotations) appear at their own positions.
Imported `[%clk ...]` clock annotations are hidden from display/comment editing,
but remain in saved analyses and PGN exports, even if you clear the prose comment.
Imported side variations are listed alongside engine moves; follow them with the
same keys or mouse clicks. Comments stay attached to that game's move tree, not
other games or engine-generated positions.

Opening labels show the ECO code and opening/variation name for the latest known
position on the current line. Transpositions are recognized; stepping back or
exploring another line updates the label. For FEN-only input, only the supplied
position (and subsequent moves) can be matched. Labels work offline.

- **↑/↓** — choose an original move, retained variation, or engine alternative
- **→/Enter** — follow the selected move; **←** — step back
- **Esc** — return from an explored line to its game position; shown as **Back to game**
  in the command bar only while exploring a variation
- **f** — flip board; **r** — reanalyze; **q** — quit

Moves, the return link, and any original-game move (or Start) are clickable.
Branches are retained, and navigation never waits for analysis.

Use at least 40×24 terminal cells. Larger boards use multiline pieces; smaller
ones use chess glyphs. Narrow layouts stack the panels; scroll with the mouse
wheel. PgUp/PgDown navigate the game's boundaries on the analysis screen, and
scroll within help/dialogs. Blue highlights the selected move, yellow the previous
move, and red a checked king.

The evaluation bar follows the selected engine alternative's score and keeps its
last value while Stockfish is thinking; it does not reset to the middle.

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

## Release notes

See [CHANGELOG.md](CHANGELOG.md). Version 0.2.0 requires snapshot v3; older v2
sessions/library saves must be recreated from their original FEN/PGN.

## Development

Application modules live in `chess_analyzer/`: `cli.py`, `tui.py`, `input.py`,
`game.py`, `session.py`, `library.py`, `online.py`, `browser.py`, `follow.py`,
`config.py`, `clipboard.py` (input only), `export.py`, and `dialogs.py`.
Piece artwork and the bundled opening dataset are also inside this package.
Run from the checkout with `uv run chess-analyzer` or
`uv run python -m chess_analyzer.cli`.

## Verify

With Stockfish installed: `uv run python -m unittest discover -s tests -v`.
