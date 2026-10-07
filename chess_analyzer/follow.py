"""One-time latest available game loading, without changing config or sessions."""
from __future__ import annotations

import io

import chess
import chess.pgn

from .config import Account
from .game import Analysis
from .input import player_name
from .online import chesscom_games, chesscom_months, lichess_games, lichess_pgn


def load_latest_game(provider: str, username: str) -> Analysis | None:
    """Return a new analysis at the game's end, or None for an empty account.

    Requests are synchronous and bounded by the provider transport. UI callers
    should run this off-thread and discard the result if their load is cancelled.
    """
    account = Account(provider, username)
    latest = None
    if account.provider == "chess.com":
        for month in chesscom_months(account.username):
            games = chesscom_games(account.username, month)
            if games:
                latest = games[0]
                break
    else:
        until = None
        while True:
            page = lichess_games(account.username, until=until)
            if page.games:
                latest = page.games[0]
                break
            if page.until is None:
                break
            if until is not None and page.until >= until:
                raise ValueError("Lichess returned a non-advancing page cursor.")
            until = page.until
    if latest is None:
        return None
    pgn = latest.pgn if latest.pgn is not None else lichess_pgn(latest.id)
    game = chess.pgn.read_game(io.StringIO(pgn))
    if game is None:
        raise ValueError("The latest game does not contain PGN.")
    if game.errors:
        raise ValueError(f"Could not parse the latest game: {game.errors[0]}")
    if game.headers.get("Result") not in {"1-0", "0-1", "1/2-1/2"}:
        raise ValueError("The latest game is not completed.")
    board = game.board()
    if type(board) is not chess.Board or board.chess960:
        raise ValueError("The latest game is not standard chess.")
    return Analysis.from_input(board, game,
                               player_name(game.headers.get("White"), "White"),
                               player_name(game.headers.get("Black"), "Black"))
