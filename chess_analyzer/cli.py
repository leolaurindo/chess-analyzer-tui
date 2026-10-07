"""Command-line options and UCI engine startup."""
from __future__ import annotations

import argparse
import asyncio
import math
import os
import platform
import shutil
from importlib.metadata import version
from pathlib import Path

import chess
import chess.engine
import chess.pgn

from .input import load_input, player_name
from .game import Analysis
from .online import validate_username
from .session import load_session, save_session, session_path
from .tui import ChessAnalysisApp


def find_stockfish() -> str | None:
    local = Path(__file__).resolve().parent.parent / ("stockfish.exe" if os.name == "nt" else "stockfish")
    paths = [shutil.which("stockfish"), str(local), "/usr/games/stockfish",
             "/usr/bin/stockfish", "/usr/local/bin/stockfish"]
    return next((p for p in paths if p and os.path.isfile(p) and os.access(p, os.X_OK)), None)


def missing_engine_message() -> str:
    system = platform.system()
    label = "macOS" if system == "Darwin" else system
    suggestion = "Download an executable from https://stockfishchess.org/download/"
    if system == "Windows":
        suggestion = "winget install --id Stockfish.Stockfish --exact"
    elif system == "Darwin":
        suggestion = "brew install stockfish (requires Homebrew)"
    elif system == "Linux":
        try:
            release = platform.freedesktop_os_release()
        except OSError:
            release = {}
        if release.get("PRETTY_NAME"):
            label += f" ({release['PRETTY_NAME']})"
        families = {release.get("ID"), *release.get("ID_LIKE", "").split()}
        if families & {"debian", "ubuntu"}:
            suggestion = "sudo apt install stockfish"
        elif "arch" in families:
            suggestion = "sudo pacman -S stockfish"
        elif release.get("ID") == "fedora":
            suggestion = "sudo dnf install stockfish"
    executable = '"C:\\path\\to\\stockfish.exe"' if system == "Windows" else "/path/to/stockfish"
    return (
        "No engine detected on PATH or beside the application.\n"
        f"OS detection: {label}\n"
        f"Suggested Stockfish installation: {suggestion}\n"
        "After installation, make sure Stockfish is on PATH; restart your shell if needed.\n"
        f"Or pass any UCI engine: chess-analyzer --engine {executable}"
    )


async def run_app(args, board: chess.Board, engine_path: str, game: chess.pgn.Game | None,
                  white_name: str, black_name: str, *, session: Analysis | None = None) -> None:
    transport, engine = await chess.engine.popen_uci(engine_path)
    try:
        settings = {}
        for name, value in {"Threads": args.threads, "Hash": args.hash}.items():
            option = engine.options.get(name)
            if option and option.type == "spin":
                if option.min is not None:
                    value = max(value, option.min)
                if option.max is not None:
                    value = min(value, option.max)
                settings[name] = value
        await engine.configure(settings)
        multipv_option = engine.options.get("MultiPV")
        multipv = args.lines if multipv_option else 1
        if multipv_option:
            if multipv_option.min is not None:
                multipv = max(multipv, multipv_option.min)
            if multipv_option.max is not None:
                multipv = min(multipv, multipv_option.max)
        engine_name = engine.id.get("name") or Path(engine_path).name
        path = session_path()

        def persist(analysis: Analysis) -> None:
            try:
                save_session(analysis, path)
            except OSError as exc:
                app.notify(f"Could not save analysis: {exc}", severity="warning")

        app = ChessAnalysisApp(board, engine, args.time, multipv, args.ascii,
                               game=game, engine_name=engine_name,
                               white_name=white_name, black_name=black_name,
                               on_session_change=persist,
                               open_library=args.library,
                               browse_provider=args.browse, browse_user=args.user)
        if session is not None:
            app.analysis = session
        await app.run_async()
    finally:
        try:
            await asyncio.wait_for(engine.quit(), timeout=3)
        finally:
            transport.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="chess-analyzer", description="Interactive UCI chess engine analyzer.",
    )
    parser.add_argument("-v", "--version", action="version",
                        version=f"%(prog)s {version('chess-analyzer-tui')}")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("input", nargs="?", help="FEN, PGN text, or HTTPS game/study/PGN URL")
    source.add_argument("--file", help="Read FEN or PGN from a UTF-8 file")
    source.add_argument("--clip", action="store_true",
                        help="Analyze FEN or PGN from the clipboard")
    source.add_argument("-c", "--continue", dest="continue_session", action="store_true",
                        help="Restore the last analysis session")
    source.add_argument("--library", action="store_true", help="Browse saved local analyses")
    source.add_argument("--browse", choices=("chess.com", "lichess"), metavar="PROVIDER",
                        help="Browse public games from chess.com or lichess")
    parser.add_argument("--user", help="Public username to browse (requires --browse)")
    parser.add_argument("--white", help="White player's display name (overrides PGN header)")
    parser.add_argument("--black", help="Black player's display name (overrides PGN header)")
    parser.add_argument("-t", "--time", type=float, default=1.0, help="Thinking time per position")
    parser.add_argument("-n", "--lines", type=int, default=5, help="Number of engine continuations")
    parser.add_argument("--threads", type=int, default=2, help="Engine threads (if supported)")
    parser.add_argument("--hash", type=int, default=256, help="Engine hash size in MB (if supported)")
    parser.add_argument("--engine", help="Path to a UCI engine executable (default: Stockfish)")
    parser.add_argument("--ascii", action="store_true", help="Use letters instead of chess glyphs")
    args = parser.parse_args()
    if not math.isfinite(args.time) or args.time <= 0:
        parser.error("--time must be a positive, finite number")
    if min(args.lines, args.threads, args.hash) < 1:
        parser.error("--lines, --threads and --hash must be positive")
    if args.browse:
        if args.user is None:
            parser.error("--browse requires --user NAME")
        try:
            args.user = validate_username(args.user)
        except ValueError as exc:
            parser.error(str(exc))
    elif args.user is not None:
        parser.error("--user requires --browse chess.com or lichess")
    session = None
    if args.continue_session or ((args.library or args.browse) and session_path().exists()):
        try:
            session = load_session(session_path())
        except FileNotFoundError as exc:
            raise SystemExit("No saved analysis found. Start an analysis first.") from exc
        except (OSError, ValueError, UnicodeError) as exc:
            raise SystemExit(f"Could not restore saved analysis: {exc}") from exc
    if session is not None:
        board, game = session.root.board, None
        pgn_white, pgn_black = session.white_name, session.black_name
    else:
        board, game, pgn_white, pgn_black = load_input(args.input, file=args.file, clipboard=args.clip)
    white_name = player_name(args.white, pgn_white)
    black_name = player_name(args.black, pgn_black)
    if session is not None:
        session.white_name, session.black_name = white_name, black_name
    headers = session.headers if session is not None else game.headers if game is not None else None
    if headers is not None:
        for color, override, name in (("White", args.white, white_name),
                                      ("Black", args.black, black_name)):
            if override is not None and override.strip() not in {"", "?"}:
                headers[color] = name
    if not board.is_valid():
        raise SystemExit("The starting position is invalid.")
    engine_path = args.engine or find_stockfish()
    if not engine_path:
        raise SystemExit(missing_engine_message())
    try:
        asyncio.run(run_app(args, board, engine_path, game, white_name, black_name, session=session))
    except (OSError, chess.engine.EngineError, asyncio.TimeoutError) as exc:
        raise SystemExit(f"Engine error: {exc}") from exc


if __name__ == "__main__":
    main()
