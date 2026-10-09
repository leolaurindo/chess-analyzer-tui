import asyncio
import tempfile
import unittest
from pathlib import Path

import chess
import chess.engine

from chess_analyzer.cli import find_stockfish
from chess_analyzer.input import parse_input
from chess_analyzer.session import load_session, save_session
from chess_analyzer.tui import ChessAnalysisApp
from textual.widgets import Input


class MoveEntryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        path = find_stockfish()
        if not path:
            self.skipTest("Stockfish is required for move-entry integration tests")
        self.transport, self.engine = await chess.engine.popen_uci(path)
        await self.engine.configure({"Threads": 1, "Hash": 16})

    async def asyncTearDown(self):
        if hasattr(self, "engine"):
            try:
                await asyncio.wait_for(self.engine.quit(), timeout=3)
            finally:
                self.transport.close()

    async def wait_for_analysis(self, app, pilot):
        async def ready():
            while not app.analysis.current.analyzed:
                await asyncio.sleep(0.01)
            await pilot.pause()
        await asyncio.wait_for(ready(), timeout=4)

    async def test_notation_modes_keep_engine_running_and_escape_returns_in_two_steps(self):
        board, game, _, _ = parse_input("1. e4 e5 *")
        app = ChessAnalysisApp(board, self.engine, 0.05, 3, game=game)
        async with app.run_test(size=(100, 34)) as pilot:
            app.action_game_position(0)
            anchor = app.analysis.current
            await pilot.press("m", "h", "4", "enter")
            branch = app.analysis.current
            self.assertEqual(branch.board.peek().uci(), "h2h4")
            self.assertIsNone(app.move_entry)
            self.assertIs(app.analysis.return_position, anchor)
            await self.wait_for_analysis(app, pilot)
            self.assertTrue(branch.candidates)
            await pilot.press("M", "e", "7", "e", "5", "enter")
            self.assertTrue(app.move_entry.persistent)
            self.assertEqual(app.analysis.current.board.peek().uci(), "e7e5")
            await self.wait_for_analysis(app, pilot)
            self.assertTrue(app.analysis.current.candidates)
            await pilot.press("N", "f", "3", "enter")
            position = app.analysis.current
            self.assertEqual(position.board.peek().uci(), "g1f3")
            self.assertTrue(app.move_entry.persistent)
            self.assertIs(app.analysis.return_position, anchor)
            await pilot.press("escape")
            self.assertIsNone(app.move_entry)
            self.assertIs(app.analysis.current, position)
            await pilot.press("escape")
            self.assertIs(app.analysis.current, anchor)
            self.assertIs(anchor.children[chess.Move.from_uci("h2h4")], branch)
            self.assertEqual([move.uci() for move in game.mainline_moves()], ["e2e4", "e7e5"])

    async def test_bad_notation_preserves_single_move_mode_and_tree(self):
        app = ChessAnalysisApp(chess.Board(), self.engine, 0.05, 3)
        async with app.run_test() as pilot:
            root = app.analysis.root
            await pilot.press("m")
            notation = app.query_one("#move-notation", Input)
            for text in ("e5", "--", "N", "junk"):
                with self.subTest(text=text):
                    notation.value = text
                    await pilot.pause()
                    await pilot.press("enter")
                    self.assertIs(app.analysis.current, root)
                    self.assertEqual(root.children, {})
                    self.assertIsNotNone(app.move_entry)
                    self.assertIn("legal", app.query_one("#move-entry-hint").render().plain)
            notation.value = "e2e4"
            await pilot.press("enter")
            self.assertEqual(app.analysis.current.board.peek().uci(), "e2e4")
            self.assertIsNone(app.move_entry)

    async def test_arrows_and_both_selection_keys_follow_legal_moves(self):
        app = ChessAnalysisApp(chess.Board(), self.engine, 0.05, 3)
        async with app.run_test() as pilot:
            await pilot.press("M", "up", "space")
            self.assertEqual(app.move_entry.source, chess.E2)
            board_text = app.query_one("#board").render()
            self.assertTrue(any("#397a50" in str(span.style) for span in board_text.spans))
            await pilot.press("up", "up", "enter")
            self.assertEqual(app.analysis.current.board.peek().uci(), "e2e4")
            self.assertIsNotNone(app.move_entry)
            await pilot.press("down", "enter", "down", "down", "space")
            self.assertEqual(app.analysis.current.board.peek().uci(), "e7e5")
            self.assertIsNotNone(app.move_entry)

    async def test_source_reselection_invalid_destination_and_flipped_cursor(self):
        app = ChessAnalysisApp(chess.Board(), self.engine, 0.05, 3)
        async with app.run_test() as pilot:
            await pilot.press("f", "m", "down", "space")
            self.assertEqual(app.move_entry.source, chess.E2)
            await pilot.press("left", "space")
            self.assertEqual(app.move_entry.source, chess.F2)
            await pilot.press("left", "space", "space")
            self.assertIsNone(app.move_entry.source)
            await pilot.press("right", "space", "down", "left", "enter")
            self.assertIs(app.analysis.current, app.analysis.root)
            self.assertIn("Not a legal", app.move_entry.error)
            await pilot.press("backspace")
            self.assertIsNone(app.move_entry.source)
            await pilot.press("escape")
            self.assertIsNone(app.move_entry)
            self.assertEqual(app.analysis.root.children, {})

    async def test_board_promotion_supports_underpromotion(self):
        app = ChessAnalysisApp(chess.Board("7k/P7/8/8/8/8/8/7K w - - 0 1"), self.engine, 0.05, 3)
        async with app.run_test() as pilot:
            await pilot.press("m", *(["left"] * 7), *(["up"] * 6), "space", "up", "enter")
            self.assertEqual(len(app.move_entry.promotions), 4)
            self.assertIs(app.analysis.current, app.analysis.root)
            await pilot.press("n", "enter")
            self.assertEqual(app.analysis.current.board.piece_at(chess.A8), chess.Piece(chess.KNIGHT, chess.WHITE))
            self.assertEqual(app.analysis.current.board.peek().uci(), "a7a8n")
            self.assertIsNone(app.move_entry)

    async def test_shared_follow_preserves_original_game_and_reuses_branches(self):
        board, game, _, _ = parse_input("1. e4 e5 *")
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory) / "session.json"
            app = ChessAnalysisApp(board, self.engine, 0.05, 3, game=game,
                                   on_session_change=lambda state: save_session(state, session))
            async with app.run_test() as pilot:
                app.action_game_position(1)
                anchor = app.analysis.current
                original = anchor.mainline_next
                app.follow_move(chess.Move.from_uci("e7e5"))
                self.assertIs(app.analysis.current, original)
                self.assertIsNone(app.analysis.return_position)
                await pilot.press("left")
                app.follow_move(chess.Move.from_uci("c7c5"))
                branch = app.analysis.current
                app.follow_move(chess.Move.from_uci("g1f3"))
                self.assertIs(app.analysis.return_position, anchor)
                restored = load_session(session)
                self.assertEqual(restored.current.board.peek().uci(), "g1f3")
                self.assertEqual(restored.return_position.board.peek().uci(), "e2e4")
                await pilot.press("escape")
                self.assertIs(app.analysis.current, anchor)
                app.follow_move(chess.Move.from_uci("c7c5"))
                self.assertIs(app.analysis.current, branch)
                self.assertIs(anchor.mainline_next, original)
                await pilot.press("escape", "enter")
                self.assertIs(app.analysis.current, original)

    async def test_shared_follow_rejects_illegal_and_null_moves_without_changes(self):
        app = ChessAnalysisApp(chess.Board(), self.engine, 0.05, 3)
        async with app.run_test():
            root = app.analysis.root
            for move in (chess.Move.from_uci("e2e5"), chess.Move.null()):
                with self.subTest(move=move):
                    with self.assertRaisesRegex(ValueError, "not legal"):
                        app.follow_move(move)
                    self.assertIs(app.analysis.current, root)
                    self.assertEqual(root.children, {})
                    self.assertIsNone(app.analysis.return_position)
                    self.assertEqual(root.board.fen(), chess.STARTING_FEN)


if __name__ == "__main__":
    unittest.main()
