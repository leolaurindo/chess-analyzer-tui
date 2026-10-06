"""Read and parse chess positions and games from text, files, or the clipboard."""
from __future__ import annotations

import io
from pathlib import Path

import chess
import chess.pgn
import pyperclip


def player_name(value: str | None, fallback: str) -> str:
    name = (value or "").strip()
    return fallback if name in {"", "?"} else name


def parse_input(text: str) -> tuple[chess.Board, list[chess.Move] | None, str, str]:
    text = text.strip()
    try:
        return chess.Board(text), None, "White", "Black"
    except ValueError:
        pass
    game = chess.pgn.read_game(io.StringIO(text))
    if game is None:
        raise SystemExit("Input does not contain a FEN position or PGN game.")
    if game.errors:
        raise SystemExit(f"Could not parse PGN: {game.errors[0]}")
    moves = list(game.mainline_moves())
    if not moves:
        raise SystemExit("Input does not contain a valid FEN or PGN game with moves.")
    return (game.board(), moves,
            player_name(game.headers.get("White"), "White"),
            player_name(game.headers.get("Black"), "Black"))


def load_input(text: str | None = None, *, file: str | None = None,
               clipboard: bool = False) -> tuple[chess.Board, list[chess.Move] | None, str, str]:
    text = text if text is not None else chess.STARTING_FEN
    if file is not None:
        try:
            text = Path(file).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            raise SystemExit(f"Could not read file: {exc}") from exc
    elif clipboard:
        try:
            text = pyperclip.paste()
        except (pyperclip.PyperclipException, OSError) as exc:
            raise SystemExit(f"Could not read clipboard: {exc}") from exc
    return parse_input(text)
