"""Read and parse chess positions and games from text, files, or the clipboard."""
from __future__ import annotations

import io
import json
from pathlib import Path

import chess
import chess.pgn
import pyperclip


from chess_online import chesscom_game_id, load_url


def player_name(value: str | None, fallback: str) -> str:
    name = (value or "").strip()
    return fallback if name in {"", "?"} else name


def parse_input(text: str) -> tuple[chess.Board, chess.pgn.Game | None, str, str]:
    text = text.strip()
    try:
        return chess.Board(text), None, "White", "Black"
    except ValueError:
        pass
    game = chess.pgn.read_game(io.StringIO(text))
    if game is None:
        raise ValueError("Input does not contain a FEN position or PGN game.")
    if game.errors:
        raise ValueError(f"Could not parse PGN: {game.errors[0]}")
    if not game.variations:
        raise ValueError("Input does not contain a valid FEN or PGN game with moves.")
    return (game.board(), game,
            player_name(game.headers.get("White"), "White"),
            player_name(game.headers.get("Black"), "Black"))


def load_input(text: str | None = None, *, file: str | None = None,
               clipboard: bool = False, chesscom_user: str | None = None,
               chesscom_month: str | None = None) -> tuple[chess.Board, chess.pgn.Game | None, str, str]:
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
    if (chesscom_user or chesscom_month) and chesscom_game_id(text.strip()) is None:
        raise SystemExit("Chess.com archive flags apply only to a Chess.com game URL.")
    if text.strip().lower().startswith(("https://", "http://")):
        try:
            text = load_url(text.strip(), chesscom_user=chesscom_user, chesscom_month=chesscom_month)
        except (ValueError, json.JSONDecodeError) as exc:
            raise SystemExit(f"Could not load URL: {exc}") from exc
    try:
        return parse_input(text)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
