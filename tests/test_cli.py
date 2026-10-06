import contextlib
import io
import unittest
from unittest.mock import AsyncMock, patch

import chess
import pyperclip

from chess_tui import main


class CliTests(unittest.TestCase):
    def test_clipboard_aliases_load_fen_and_pgn(self):
        pgn = '[White "Supi"]\n[Black "Carlsen"]\n\n1. e4 e5 *\n'
        fen = "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1"
        cases = [
            (pgn, chess.STARTING_FEN, ["e2e4", "e7e5"], ("Supi", "Carlsen")),
            (f"\n {fen} \n", fen, [], ("White", "Black")),
        ]
        for flag in ("--clip", "-c"):
            for contents, expected_fen, expected_moves, names in cases:
                with (
                    self.subTest(flag=flag, contents=contents),
                    patch("sys.argv", ["chess-analyzer", flag, "--engine", "stockfish"]),
                    patch("pyperclip.paste", return_value=contents),
                    patch("chess_tui.run_app", new_callable=AsyncMock) as run,
                ):
                    main()
                    args, board, engine, moves, white, black = run.call_args.args
                    self.assertEqual(board.fen(), expected_fen)
                    self.assertEqual([move.uci() for move in moves], expected_moves)
                    self.assertEqual((white, black), names)

    def test_clipboard_is_not_read_without_opt_in(self):
        with (
            patch("sys.argv", ["chess-analyzer", "--engine", "stockfish"]),
            patch("pyperclip.paste") as paste,
            patch("chess_tui.run_app", new_callable=AsyncMock),
        ):
            main()
            paste.assert_not_called()

    def test_clipboard_rejects_unavailable_empty_and_invalid_games(self):
        cases = [
            (pyperclip.PyperclipException("No clipboard backend"), "Could not read clipboard"),
            ("", "does not contain a game"),
            ("not a chess game", "does not contain a valid FEN or PGN game with moves"),
            ('[Event "No moves"]\n\n*', "does not contain a valid FEN or PGN game with moves"),
            ("1. e4 e5 2. Bh6 *", "Could not parse PGN"),
            ("8/8/8/8/8/8/8/8 w - - 0 1", "starting position is invalid"),
        ]
        for contents, message in cases:
            with (
                self.subTest(contents=contents),
                patch("sys.argv", ["chess-analyzer", "-c"]),
                patch("pyperclip.paste", side_effect=[contents]),
                patch("chess_tui.run_app", new_callable=AsyncMock) as run,
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as error,
            ):
                main()
            self.assertIn(message, str(error.exception))
            run.assert_not_called()

    def test_clipboard_cannot_be_combined_with_other_sources(self):
        for other in ([chess.STARTING_FEN], ["--pgn", "game.pgn"]):
            with (
                self.subTest(other=other),
                patch("sys.argv", ["chess-analyzer", "-c", *other]),
                patch("pyperclip.paste") as paste,
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as error,
            ):
                main()
            self.assertEqual(error.exception.code, 2)
            paste.assert_not_called()

    def test_missing_engine_explains_installation_for_the_detected_os(self):
        cases = [
            ("Windows", {}, "Windows", "winget install --id Stockfish.Stockfish --exact"),
            ("Darwin", {}, "macOS", "brew install stockfish"),
            ("Linux", {"ID": "ubuntu"}, "Linux", "sudo apt install stockfish"),
            ("Linux", {"ID": "linuxmint", "ID_LIKE": "ubuntu debian", "PRETTY_NAME": "Linux Mint"},
             "Linux (Linux Mint)", "sudo apt install stockfish"),
            ("Linux", {"ID": "manjaro", "ID_LIKE": "arch"}, "Linux", "sudo pacman -S stockfish"),
            ("Linux", {"ID": "fedora"}, "Linux", "sudo dnf install stockfish"),
            ("Linux", {"ID": "unknown"}, "Linux", "https://stockfishchess.org/download/"),
            ("Linux", OSError("No os-release file"), "Linux", "https://stockfishchess.org/download/"),
            ("FreeBSD", {}, "FreeBSD", "https://stockfishchess.org/download/"),
        ]
        for system, release, label, suggestion in cases:
            with self.subTest(system=system, release=release):
                with (
                    patch("sys.argv", ["chess-analyzer"]),
                    patch("chess_tui.find_stockfish", return_value=None),
                    patch("platform.system", return_value=system),
                    patch("platform.freedesktop_os_release", side_effect=[release]),
                    self.assertRaises(SystemExit) as error,
                ):
                    main()
                message = str(error.exception)
                self.assertIn("No engine detected", message)
                self.assertIn(f"OS detection: {label}", message)
                self.assertIn(suggestion, message)
                self.assertIn("make sure Stockfish is on PATH", message)
                self.assertIn("chess-analyzer --engine", message)


if __name__ == "__main__":
    unittest.main()
