import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import chess

from chess_analyzer.cli import find_stockfish, main
from chess_analyzer.game import Analysis
from chess_analyzer.session import load_session, save_session
from chess_analyzer.tui import ChessAnalysisApp


class SessionTests(unittest.TestCase):
    def test_fen_history_round_trip_and_failed_write_preserves_previous_session(self):
        analysis = Analysis.from_input(chess.Board("4k3/8/8/8/8/8/4P3/4K3 w - - 0 1"))
        analysis.current = analysis.root.child(chess.Move.from_uci("e2e4"))
        analysis.current.analyzed = True
        analysis.flipped = True
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state" / "session.json"
            save_session(analysis, path)
            restored = load_session(path)
            self.assertEqual(restored.current.board.fen(), "4k3/8/8/8/4P3/8/8/4K3 b - - 0 1")
            self.assertEqual(restored.current.board.peek().uci(), "e2e4")
            self.assertFalse(restored.root.is_mainline)
            self.assertTrue(restored.flipped)
            self.assertFalse(restored.current.analyzed)
            # Existing v2 snapshots lack headers and must still reopen.
            legacy = json.loads(path.read_text(encoding="utf-8"))
            del legacy["headers"]
            path.write_text(json.dumps(legacy), encoding="utf-8")
            self.assertEqual(load_session(path).headers, {})
            previous = path.read_bytes()
            analysis.flipped = False
            with patch("chess_analyzer.session.os.replace", side_effect=OSError("disk failure")):
                with self.assertRaises(OSError):
                    save_session(analysis, path)
            self.assertEqual(path.read_bytes(), previous)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_invalid_snapshot_is_rejected_without_overwriting_it(self):
        analysis = Analysis.from_input(chess.Board())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.json"
            save_session(analysis, path)
            original = json.loads(path.read_text(encoding="utf-8"))
            for change in ({"version": 99}, {"current": -1}, {"fen": "bad fen"},
                           {"nodes": [[0, "e2e5", False, False, "", ""]]},
                           {"nodes": [[4, "e2e4", False, False, "", ""]]},
                           {"nodes": [[0, "e2e4", False, True, 42, ""]]},
                           {"headers": []}, {"headers": {"Result": 42}}):
                with self.subTest(change=change):
                    path.write_text(json.dumps(original | change), encoding="utf-8")
                    previous = path.read_bytes()
                    with self.assertRaisesRegex(ValueError, "Invalid analysis snapshot"):
                        load_session(path)
                    self.assertEqual(path.read_bytes(), previous)

    def test_study_comments_variations_continue_and_new_game_isolation(self):
        engine = find_stockfish()
        if engine is None:
            self.skipTest("Stockfish is required for session integration tests")
        pgn = ('{Study introduction} 1. e4 {King pawn} e5 '
               '({Sicilian introduction} 1... c5 {Sicilian [literal]} '
               '2. Nf3 (2. Nc3 {Nested variation}) d6) 2. Nf3 {Main line} *')

        async def explore(app):
            async with app.run_test() as pilot:
                self.assertEqual(app.analysis.current.comment, "Main line")
                app.action_game_position(1)
                choices = app.move_choices(app.analysis.current)
                self.assertIn(chess.Move.from_uci("c7c5"), choices)
                app.action_follow_choice(choices.index(chess.Move.from_uci("c7c5")))
                self.assertEqual(app.analysis.return_position.comment, "King pawn")
                self.assertIn("Sicilian [literal]", app.query_one("#comments").render().plain)
                self.assertIn("Sicilian introduction", app.query_one("#comments").render().plain)
                choices = app.move_choices(app.analysis.current)
                app.action_follow_choice(choices.index(chess.Move.from_uci("b1c3")))
                self.assertEqual(app.analysis.current.comment, "Nested variation")
                await pilot.pause()

        async def resume(app):
            async with app.run_test() as pilot:
                self.assertEqual(app.query_one("#comments").render().plain, "Nested variation")
                self.assertEqual(app.analysis.root.comment, "Study introduction")
                await pilot.press("escape")
                self.assertEqual(app.analysis.current.comment, "King pawn")
                self.assertIn("Variation", app.query_one("#candidates").render().plain)
                await pilot.press("enter")
                self.assertEqual(app.analysis.current.board.peek().uci(), "e7e5")
                self.assertFalse(app.query_one("#comments").display)

        async def fresh(app):
            async with app.run_test():
                self.assertEqual(app.analysis.root.comment, "")
                self.assertEqual(app.analysis.current.comment, "")
                self.assertFalse(app.query_one("#comments").display)
                self.assertNotIn(chess.Move.from_uci("c7c5"), app.analysis.root.mainline_next.children)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.json"
            for source, run in ((["https://lichess.org/study/r072zv4F/R33cxdop"], explore),
                                (["--continue"], resume), (["1. e4 e5 *"], fresh)):
                with (
                    self.subTest(source=source),
                    patch("sys.argv", ["chess-analyzer", *source, "--engine", engine,
                                       "--time", "0.05", "--threads", "1", "--hash", "16"]),
                    patch("chess_analyzer.online._validate_url"),
                    patch("chess_analyzer.online.fetch_text", return_value=pgn),
                    patch("chess_analyzer.cli.session_path", return_value=path),
                    patch.object(ChessAnalysisApp, "run_async", run),
                ):
                    main()

    def test_cli_restores_branches_names_orientation_and_reanalyzes(self):
        engine = find_stockfish()
        if engine is None:
            self.skipTest("Stockfish is required for session integration tests")
        pgn = '[White "Supi"]\n[Black "Carlsen"]\n\n1. e4 h5 *'
        saved_position = None

        async def wait_for_analysis(app, pilot):
            async def ready():
                while not app.analysis.current.analyzed:
                    await asyncio.sleep(0.01)
                await pilot.pause()
            await asyncio.wait_for(ready(), timeout=4)

        async def explore(app):
            nonlocal saved_position
            async with app.run_test() as pilot:
                await pilot.press("left")
                await wait_for_analysis(app, pilot)
                await pilot.press("down", "right", "f")
                self.assertFalse(app.analysis.current.is_mainline)
                self.assertEqual(app.analysis.return_position.board.peek().uci(), "e2e4")
                saved_position = app.analysis.current.board.fen()

        async def resume(app):
            self.assertFalse(app.analysis.current.analyzed)
            self.assertEqual(app.analysis.current.candidates, [])
            async with app.run_test() as pilot:
                self.assertEqual(app.analysis.current.board.fen(), saved_position)
                self.assertTrue(app.analysis.flipped)
                self.assertIn("Supi", app.query_one("#top-player").render().plain)
                self.assertIn("Carlsen", app.query_one("#bottom-player").render().plain)
                await wait_for_analysis(app, pilot)
                self.assertTrue(app.analysis.current.candidates)
                await pilot.press("escape")
                self.assertEqual(app.analysis.current.board.peek().uci(), "e2e4")
                self.assertTrue(any(child.board.fen() == saved_position
                                    for child in app.analysis.current.children.values()))
                await pilot.press("enter")
                self.assertEqual(app.analysis.current.board.peek().uci(), "h7h5")
                # Leave the saved session at the explored branch for the next alias.
                branch = next(child for child in app.analysis.current.parent.children.values()
                              if child.board.fen() == saved_position)
                app.analysis.return_position = app.analysis.current.parent
                app.show_position(branch)

        async def fresh(app):
            async with app.run_test():
                self.assertEqual(app.analysis.current.board.fen(), chess.STARTING_FEN)
                self.assertFalse(app.analysis.has_pgn)
                self.assertFalse(app.analysis.flipped)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.json"
            for source, run in (([pgn], explore), (["-c"], resume),
                                (["--continue"], resume), ([], fresh)):
                with (
                    self.subTest(source=source),
                    patch("sys.argv", ["chess-analyzer", *source, "--engine", engine,
                                       "--time", "0.05", "--threads", "1", "--hash", "16"]),
                    patch("chess_analyzer.cli.session_path", return_value=path),
                    patch.object(ChessAnalysisApp, "run_async", run),
                ):
                    main()
                self.assertTrue(path.is_file())


if __name__ == "__main__":
    unittest.main()
