import contextlib
import io
import json
import tempfile
import unittest
from itertools import product
from pathlib import Path
from unittest.mock import AsyncMock, patch

import chess
import pyperclip

from chess_analyzer.cli import main
from chess_analyzer.config import Account, save_account
from chess_analyzer.game import Analysis
from chess_analyzer.input import parse_input
from chess_analyzer.session import save_session


class CliTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.config = Path(directory.name) / "config.json"
        config = patch("chess_analyzer.config.user_config_path", return_value=self.config.parent)
        config.start()
        self.addCleanup(config.stop)

    def test_version_aliases_print_version_without_starting_analysis(self):
        for flag in ("--version", "-v"):
            output = io.StringIO()
            with (
                self.subTest(flag=flag),
                patch("sys.argv", ["chess-analyzer", flag]),
                patch("chess_analyzer.cli.find_stockfish") as find_engine,
                patch("chess_analyzer.input.paste_text") as paste,
                contextlib.redirect_stdout(output),
                self.assertRaises(SystemExit) as error,
            ):
                main()
            self.assertEqual(error.exception.code, 0)
            self.assertRegex(output.getvalue(), r"^chess-analyzer \d+\.\d+\.\d+\n$")
            find_engine.assert_not_called()
            paste.assert_not_called()

    def test_all_sources_load_fen_and_pgn(self):
        pgn = '[White "Supi"]\n[Black "Carlsen"]\n\n1. e4 e5 *\n'
        fen = "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1"
        cases = [
            (pgn, chess.STARTING_FEN, ["e2e4", "e7e5"], ("Supi", "Carlsen")),
            (f"\n {fen} \n", fen, None, ("White", "Black")),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "position.txt"
            for case, source in product(cases, ("text", "file", "--clip")):
                contents, expected_fen, expected_moves, names = case
                path.write_text(contents, encoding="utf-8-sig")
                argv = {"text": [contents], "file": ["--file", str(path)]}.get(source, [source])
                with (
                    self.subTest(source=source, contents=contents),
                    patch("sys.argv", ["chess-analyzer", *argv, "--engine", "stockfish"]),
                    patch("chess_analyzer.input.paste_text", return_value=contents),
                    patch("chess_analyzer.cli.run_app", new_callable=AsyncMock) as run,
                ):
                    main()
                    _, board, _, moves, white, black = run.call_args.args
                    actual_moves = None if moves is None else [move.uci() for move in moves.mainline_moves()]
                    self.assertEqual(board.fen(), expected_fen)
                    self.assertEqual(actual_moves, expected_moves)
                    self.assertEqual((white, black), names)

    def test_engine_config_defaults_and_cli_overrides(self):
        self.config.write_text(json.dumps({"engine": {
            "time": 5, "lines": 3, "threads": 4, "hash": 512,
        }}))
        for options, expected in (
            ([], (5.0, 3, 4, 512)),
            (["--time", "7", "--lines", "2", "--threads", "1", "--hash", "128"],
             (7.0, 2, 1, 128)),
        ):
            with (
                self.subTest(options=options),
                patch("sys.argv", ["chess-analyzer", "--engine", "stockfish", *options]),
                patch("chess_analyzer.cli.run_app", new_callable=AsyncMock) as run,
            ):
                main()
                args = run.call_args.args[0]
                self.assertEqual((args.time, args.lines, args.threads, args.hash), expected)

    def test_clipboard_is_not_read_without_opt_in(self):
        with (
            patch("sys.argv", ["chess-analyzer", "--engine", "stockfish"]),
            patch("chess_analyzer.input.paste_text") as paste,
            patch("chess_analyzer.cli.run_app", new_callable=AsyncMock),
        ):
            main()
            paste.assert_not_called()

    def test_clipboard_rejects_unavailable_empty_and_invalid_games(self):
        cases = [
            (pyperclip.PyperclipException("No clipboard backend"), "Could not read clipboard"),
            ("", "does not contain a FEN position or PGN game"),
            ("not a chess game", "does not contain a valid FEN or PGN game with moves"),
            ("[not a PGN header]\n\n*", "does not contain a valid FEN or PGN game with moves"),
            ("1. e4 e5 2. Bh6 *", "Could not parse PGN"),
            ("8/8/8/8/8/8/8/8 w - - 0 1", "starting position is invalid"),
        ]
        for contents, message in cases:
            with (
                self.subTest(contents=contents),
                patch("sys.argv", ["chess-analyzer", "--clip"]),
                patch("chess_analyzer.input.paste_text", side_effect=[contents]),
                patch("chess_analyzer.cli.run_app", new_callable=AsyncMock) as run,
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as error,
            ):
                main()
            self.assertIn(message, str(error.exception))
            run.assert_not_called()

    def test_input_sources_are_mutually_exclusive(self):
        for sources in (["--clip", chess.STARTING_FEN], ["--clip", "--file", "game.pgn"],
                        ["--file", "game.pgn", chess.STARTING_FEN], ["-c", "--clip"],
                        ["--continue", "--file", "game.pgn"], ["-c", chess.STARTING_FEN],
                        ["--library", "--clip"], ["--library", "--continue"],
                        ["--browse", "lichess", "--user", "Alice", "--library"],
                        ["--browse", "lichess", "--user", "Alice", "--continue"],
                        ["--browse", "lichess", "--user", "Alice", chess.STARTING_FEN],
                        ["--follow", chess.STARTING_FEN], ["-f", "--file", "game.pgn"],
                        ["--follow", "--clip"], ["-f", "--continue"], ["-f", "--library"],
                        ["--follow", "--browse", "lichess", "--user", "Alice"]):
            with (
                self.subTest(sources=sources),
                patch("sys.argv", ["chess-analyzer", *sources]),
                patch("chess_analyzer.input.paste_text") as paste,
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as error,
            ):
                main()
            self.assertEqual(error.exception.code, 2)
            paste.assert_not_called()

    def test_startup_menus_restore_existing_analysis_before_opening(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.json"
            analysis = Analysis.from_input(chess.Board(), white_name="Alice", black_name="Bob")
            analysis.current.comment = "Keep my note"
            save_session(analysis, path)
            previous = path.read_bytes()
            for flag, source in (("--library", ["--library"]),
                                 ("--browse", ["--browse", "lichess", "--user", "Alice"])):
                with (self.subTest(flag=flag),
                      patch("sys.argv", ["chess-analyzer", *source, "--engine", "stockfish"]),
                      patch("chess_analyzer.cli.session_path", return_value=path),
                      patch("chess_analyzer.cli.run_app", new_callable=AsyncMock) as run):
                    main()
                self.assertEqual(run.call_args.kwargs["session"].current.comment, "Keep my note")
                self.assertTrue(getattr(run.call_args.args[0], flag[2:]))
                self.assertEqual(path.read_bytes(), previous)

    def test_chesscom_url_needs_no_extra_flags_and_browse_needs_no_link(self):
        url = "https://www.chess.com/game/live/4912555148"
        loaded = parse_input('[White "LPSupi"]\n[Black "MenuGarden"]\n\n1. e4 d5 *')
        with (patch("sys.argv", ["chess-analyzer", url, "--engine", "stockfish"]),
              patch("chess_analyzer.cli.load_input", return_value=loaded) as load,
              patch("chess_analyzer.cli.run_app", new_callable=AsyncMock) as run):
            main()
        load.assert_called_once_with(url, file=None, clipboard=False)
        self.assertEqual(run.call_args.args[4:], ("LPSupi", "MenuGarden"))
        self.assertEqual([move.uci() for move in run.call_args.args[3].mainline_moves()],
                         ["e2e4", "d7d5"])
        with tempfile.TemporaryDirectory() as directory:
            with (patch("sys.argv", ["chess-analyzer", "--browse", "chess.com", "--user", "Alice",
                                     "--engine", "stockfish"]),
                  patch("chess_analyzer.cli.session_path", return_value=Path(directory) / "absent.json"),
                  patch("chess_analyzer.online.fetch_text") as fetch,
                  patch("chess_analyzer.cli.run_app", new_callable=AsyncMock) as run):
                main()
            self.assertEqual(run.call_args.args[0].browse, "chess.com")
            self.assertEqual(run.call_args.args[0].user, "Alice")
            self.assertIsNone(run.call_args.args[3])
            fetch.assert_not_called()

    def test_browse_requires_provider_and_username_before_loading(self):
        for flags in (["--browse"], ["--browse", "lichess"], ["--user", "Alice"],
                      ["--browse", "other", "--user", "Alice"],
                      ["--browse", "chess.com", "--user", "../Alice"],
                      ["--browse", "lichess", "--user", ""]):
            with (self.subTest(flags=flags), patch("sys.argv", ["chess-analyzer", *flags]),
                  patch("chess_analyzer.cli.load_input") as load,
                  patch("chess_analyzer.cli.find_stockfish") as engine,
                  contextlib.redirect_stderr(io.StringIO()),
                  self.assertRaises(SystemExit) as error):
                main()
            self.assertEqual(error.exception.code, 2)
            load.assert_not_called()
            engine.assert_not_called()

    def test_player_overrides_export_on_import_and_continue_even_when_matching_fallback(self):
        loaded = parse_input('[White "?"]\n[Black "Bob"]\n\n1. e4 *')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.json"
            save_session(Analysis.from_input(*loaded), path)
            for source in (["--clip"], ["--continue"]):
                with (self.subTest(source=source),
                      patch("sys.argv", ["chess-analyzer", *source, "--white", "White",
                                         "--black", "New Black", "--engine", "stockfish"]),
                      patch("chess_analyzer.input.paste_text", return_value='[White "?"]\n[Black "Bob"]\n\n1. e4 *'),
                      patch("chess_analyzer.cli.session_path", return_value=path),
                      patch("chess_analyzer.cli.run_app", new_callable=AsyncMock) as run):
                    main()
                session = run.call_args.kwargs["session"]
                analysis = session if session is not None else Analysis.from_input(
                    run.call_args.args[1], run.call_args.args[3], *run.call_args.args[4:])
                _, game, white, black = parse_input(analysis.to_pgn())
                self.assertEqual((white, black), ("White", "New Black"))
                self.assertEqual(game.headers["White"], "White")
                self.assertEqual(game.headers["Black"], "New Black")

    def test_continue_reports_missing_or_corrupt_session(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.json"
            for flag, contents, message in (
                ("-c", None, "No saved analysis found"),
                ("--continue", "not json", "Could not restore saved analysis"),
            ):
                if contents is not None:
                    path.write_text(contents, encoding="utf-8")
                with (
                    self.subTest(flag=flag),
                    patch("sys.argv", ["chess-analyzer", flag]),
                    patch("chess_analyzer.cli.session_path", return_value=path),
                    patch("chess_analyzer.input.paste_text") as paste,
                    self.assertRaises(SystemExit) as error,
                ):
                    main()
                self.assertIn(message, str(error.exception))
                paste.assert_not_called()
                if contents is not None:
                    self.assertEqual(path.read_text(encoding="utf-8"), contents)

    def test_follow_requires_valid_configuration_before_engine_or_input_loading(self):
        for content, message in ((None, "No default account configured"),
                                 ("{broken", "Invalid account configuration")):
            if content is not None:
                self.config.write_text(content)
            with (self.subTest(content=content), patch("sys.argv", ["chess-analyzer", "-f"]),
                  patch("chess_analyzer.cli.find_stockfish") as engine,
                  patch("chess_analyzer.cli.load_input") as load,
                  patch("chess_analyzer.online.fetch_text") as fetch,
                  self.assertRaises(SystemExit) as error):
                main()
            self.assertIn(message, str(error.exception))
            self.assertIn("press u", str(error.exception))
            engine.assert_not_called()
            load.assert_not_called()
            fetch.assert_not_called()

    def test_saved_account_does_not_turn_plain_or_explicit_input_into_online_startup(self):
        save_account(Account("chess.com", "SavedUser"), self.config)
        previous = self.config.read_bytes()
        for source in ([], ["1. e4 e5 *"], ["--browse", "lichess", "--user", "CliUser"]):
            with (self.subTest(source=source),
                  patch("sys.argv", ["chess-analyzer", *source, "--engine", "stockfish"]),
                  patch("chess_analyzer.cli.session_path", return_value=self.config.parent / "session.json"),
                  patch("chess_analyzer.cli.run_app", new_callable=AsyncMock) as run,
                  patch("chess_analyzer.online.fetch_text") as fetch):
                main()
            args = run.call_args.args[0]
            self.assertEqual(args.account, Account("chess.com", "SavedUser"))
            self.assertFalse(args.follow)
            self.assertEqual(args.browse, "lichess" if "--browse" in source else None)
            self.assertEqual(self.config.read_bytes(), previous)
            fetch.assert_not_called()
        self.config.write_text("{broken")
        with (patch("sys.argv", ["chess-analyzer", "1. e4 *", "--engine", "stockfish"]),
              patch("chess_analyzer.cli.run_app", new_callable=AsyncMock) as run,
              patch("chess_analyzer.online.fetch_text") as fetch):
            main()
        self.assertIn("Invalid account configuration", run.call_args.args[0].account_error)
        self.assertIsNotNone(run.call_args.args[3])
        fetch.assert_not_called()

    def test_unreadable_file_reports_an_error(self):
        with tempfile.TemporaryDirectory() as directory:
            for path in (Path(directory) / "missing", Path(directory) / "invalid"):
                if path.name == "invalid":
                    path.write_bytes(b"\xff")
                with (
                    self.subTest(path=path),
                    patch("sys.argv", ["chess-analyzer", "--file", str(path)]),
                    self.assertRaises(SystemExit) as error,
                ):
                    main()
                self.assertIn("Could not read file", str(error.exception))

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
            with (
                self.subTest(system=system, release=release),
                patch("sys.argv", ["chess-analyzer"]),
                patch("chess_analyzer.cli.find_stockfish", return_value=None),
                patch("platform.system", return_value=system),
                patch("platform.freedesktop_os_release", side_effect=[release]),
                self.assertRaises(SystemExit) as error,
            ):
                main()
            message = str(error.exception)
            for expected in ("No engine detected", f"OS detection: {label}", suggestion,
                             "make sure Stockfish is on PATH", "chess-analyzer --engine"):
                self.assertIn(expected, message)


if __name__ == "__main__":
    unittest.main()
