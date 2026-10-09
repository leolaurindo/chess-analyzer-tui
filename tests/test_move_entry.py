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
