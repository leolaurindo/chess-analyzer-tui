# Changelog

## 0.2.1

### Added

- Configurable global ensine defaults in `config.json` for analysis time, lines, threads and hash size. Command-line options override these defaults.
- Enter legal moves with `m` (one move) or `M` (persistent entry), using SAN/UCI notation or board navigation. Legal destinations and promotion choices are shown. Engine analysis remains available.

### Changed

- Updated the README and showcase demo with the latest controls and behavior.

### Compatibility

- Move entry preserves existing branches and does not change the session/save format.


## 0.2.0

### Added

- Initial-position Home with preserved game/scratch analyses, keyboard navigation, contextual help, and import/account dialogs.
- Saved provider/account configuration; explicit `-f` / `--follow` startup and Ctrl+L load the latest public game from Chess.com or Lichess. Plain startup never fetches games.
- File export with `e`: displayed FEN or full retained PGN tree, comments, and headers. Editable destination defaults to the global application data folder's `exports` directory. Writes are atomic; overwrites require permission; the saved path remains visible until acknowledged.
- Confirmed deletion of named library analyses.

### Changed

- PgUp jumps to the current game's starting position; PgDown returns to its last original position, not explored continuations. Both return to the imported position for FEN input.
- h / F2 opens Home; g restores the parked game. F2 replaces Ctrl+H, which terminals interpret as Backspace.
- The evaluation bar retains its last known value while analysis is pending and follows the selected engine alternative's score.
- Esc returns to the original branch point; the command bar shows this shortcut only while exploring a variation.
- New games use the configured account's point of view when original player metadata identifies it. Restored sessions retain manual orientation.
- Imported clock annotations are hidden from comment display/editing but preserved in saves and PGN export.
- Linux clipboard input prefers the active Wayland/X11 desktop, including WSL.

### Breaking changes

- Sessions and library saves now require snapshot version 3 with PGN headers. Version 2 saves are unsupported and are not migrated. Reimport the original FEN/PGN and save a new analysis; retain any old files as backups.
- Ctrl+F / Ctrl+P clipboard export and Home-key rewind are removed. Use e for file export and PgUp for rewind.

### Deferred

- Experimental move-quality grading is not included in this release.
