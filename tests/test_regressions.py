import asyncio
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import chess
import chess.engine
import chess.pgn
from textual.widgets import Input, Select, TextArea

from chess_analyzer.cli import find_stockfish
from chess_analyzer.config import Account
from chess_analyzer.game import Analysis
from chess_analyzer.input import parse_input
from chess_analyzer.library import load_analysis, save_analysis
from chess_analyzer.session import load_session, save_session
from chess_analyzer.tui import ChessAnalysisApp


class ManualRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        engine = find_stockfish()
        if engine is None:
            self.skipTest("Stockfish required")
        self.transport, self.engine = await chess.engine.popen_uci(engine)
        await self.engine.configure({"Threads": 1, "Hash": 16})

    async def asyncTearDown(self):
        try:
            await asyncio.wait_for(self.engine.quit(), 3)
        finally:
            self.transport.close()

    def app(self, pgn=None, **kwargs):
        parsed = parse_input(pgn) if pgn else (chess.Board(), None, "White", "Black")
        board, game, white, black = parsed
        return ChessAnalysisApp(board, self.engine, 0.05, 3, game=game,
                                white_name=white, black_name=black, **kwargs)

    async def test_account_arrows_change_provider_and_f2_leaves_without_stealing_backspace(self):
        app = self.app()
        async with app.run_test(size=(40, 24)) as pilot:
            await pilot.press("u")
            dialog = app.screen
            self.assertIsInstance(app.focused, Input)
            await pilot.press("down")
            self.assertEqual(dialog.query_one(Select).value, "lichess")
            await pilot.press("up")
            self.assertEqual(dialog.query_one(Select).value, "chess.com")
            dialog.query_one(Select).focus()
            await pilot.press("down")
            self.assertEqual(dialog.query_one(Select).value, "lichess")
            editor = dialog.query_one(Input)
            editor.focus()
            editor.value = "Alice"
            await pilot.press("end", "backspace")
            self.assertEqual(editor.value, "Alic")
            self.assertIs(app.screen, dialog)
            await pilot.press("f2")
            self.assertEqual(len(app.screen_stack), 1)
            self.assertEqual(app.analysis.current.board.fen(), chess.STARTING_FEN)
            self.assertIsNone(app.browse_user)

    async def test_clock_tags_are_hidden_from_comments_but_survive_edits_and_export(self):
        app = self.app('1. e4 {Good [%clk 0:00:20]} e5 {[%clk 0:00:17.1]} *')
        async with app.run_test() as pilot:
            node = app.analysis.current
            self.assertFalse(app.query_one("#comments").display)
            await pilot.press("c")
            self.assertEqual(app.screen.query_one(TextArea).text, "")
            app.screen.query_one(TextArea).load_text("My note")
            await pilot.press("ctrl+s")
            self.assertEqual(app.query_one("#comments").render().plain, "My note")
            exported = chess.pgn.read_game(io.StringIO(app.analysis.to_pgn()))
            self.assertEqual(exported.end().clock(), 17.1)
            self.assertIn("My note", exported.end().comment)
            self.assertEqual(exported.variations[0].clock(), 20)
            await pilot.press("c")
            self.assertEqual(app.screen.query_one(TextArea).text, "My note")
            app.screen.query_one(TextArea).load_text("")
            await pilot.press("ctrl+s")
            self.assertFalse(app.query_one("#comments").display)
            self.assertEqual(node.comment, "[%clk 0:00:17.1]")

    async def test_page_keys_jump_to_original_game_boundaries_not_explored_positions(self):
        pgn = ('[FEN "4k3/8/8/8/8/8/4P3/4K3 w - - 0 17"]\n'
               '[SetUp "1"]\n\n17. e4 Kd7 *')
        app = self.app(pgn)
        async with app.run_test() as pilot:
            game = app.analysis
            end = game.current
            explored = end.child(chess.Move.from_uci("e1f2"))
            game.return_position = end
            app.show_position(explored)
            await pilot.press("pageup")
            self.assertIs(app.analysis, game)
            self.assertIs(game.current, game.root)
            self.assertIsNone(game.return_position)
            self.assertEqual(game.current.board.fen(), "4k3/8/8/8/8/8/4P3/4K3 w - - 0 17")
            await pilot.press("pagedown")
            self.assertIs(game.current, end)
            self.assertIs(end.children[chess.Move.from_uci("e1f2")], explored)
            await pilot.press("home")  # No longer a game-rewind shortcut.
            self.assertIs(game.current, end)
            await pilot.press("h")
            self.assertIsNot(app.analysis, game)
            self.assertEqual(app.analysis.current.board.fen(), chess.STARTING_FEN)
            await pilot.press("g")
            self.assertIs(app.analysis, game)
            self.assertIs(game.current, end)

    async def test_fen_pageup_and_pagedown_coincide_even_after_exploration(self):
        fen = "4k3/8/8/8/8/8/4P3/4K3 w - - 0 17"
        app = self.app(fen)
        async with app.run_test() as pilot:
            game = app.analysis
            explored = game.root.child(chess.Move.from_uci("e2e4"))
            for key in ("pageup", "pagedown"):
                app.show_position(explored)
                await pilot.press(key)
                self.assertIs(app.analysis, game)
                self.assertIs(game.current, game.root)
                self.assertEqual(game.current.board.fen(), fen)
                self.assertIs(game.root.children[chess.Move.from_uci("e2e4")], explored)

    async def test_library_delete_requires_confirmation_and_preserves_analysis_and_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library, session = root / "library", root / "session.json"
            app = self.app('1. e4 {Keep note} e5 *',
                           on_session_change=lambda state: save_session(state, session))
            entry = save_analysis(app.analysis, "My notes", library)
            with patch("chess_analyzer.tui.library_path", return_value=library):
                async with app.run_test(size=(40, 24)) as pilot:
                    current = app.analysis
                    before = session.read_bytes()
                    await pilot.press("l", "delete")
                    self.assertEqual(app.screen.__class__.__name__, "DeleteAnalysisDialog")
                    for selector in ("#delete", "#cancel"):
                        region = app.screen.query_one(selector).region
                        self.assertTrue(0 <= region.x < region.right <= 40)
                        self.assertTrue(0 <= region.y < region.bottom <= 24)
                    await pilot.press("enter")  # Cancel is focused, never delete by accident.
                    self.assertTrue(entry.path.exists())
                    await pilot.press("delete")
                    with patch("chess_analyzer.dialogs.delete_analysis", side_effect=OSError("disk failure")):
                        await pilot.click("#delete")
                    self.assertTrue(entry.path.exists())
                    self.assertIn("disk failure", app.screen.query_one("#error").render().plain)
                    await pilot.press("delete")
                    await pilot.click("#delete")
                    self.assertFalse(entry.path.exists())
                    self.assertEqual(app.screen.entries, [])
                    self.assertIn("No saved analyses", app.screen.query_one("#error").render().plain)
                    self.assertIs(app.analysis, current)
                    self.assertEqual(session.read_bytes(), before)
                    await pilot.press("escape")
                    self.assertIs(app.analysis, current)

    async def test_account_pov_uses_original_metadata_for_initial_import_and_library_load(self):
        board, game, _, _ = parse_input('[White "Opponent"]\n[Black "aLiCe"]\n\n1. e4 e5 *')
        app = ChessAnalysisApp(board, self.engine, 0.05, 3, game=game,
                               black_name="My display alias", account=Account("chess.com", "ALICE"))
        async with app.run_test() as pilot:
            self.assertTrue(app.analysis.flipped)
            self.assertTrue(app.query_one("#bottom-player").render().plain.startswith("Black · My display alias"))
            await pilot.press("f")
            self.assertFalse(app.analysis.flipped)  # Navigation must not fight a manual flip.
            with tempfile.TemporaryDirectory() as directory:
                entry = save_analysis(app.analysis, "Saved game", Path(directory))
                app.replace_analysis(load_analysis(entry.path))
            self.assertTrue(app.analysis.flipped)
            white = Analysis.from_input(*parse_input('[White "alice"]\n[Black "Other"]\n\n1. d4 *'))
            white.flipped = True
            app.replace_analysis(white)
            self.assertFalse(app.analysis.flipped)
            self.assertTrue(app.query_one("#bottom-player").render().plain.startswith("White · alice"))
            unrelated = Analysis.from_input(*parse_input('[White "Other"]\n[Black "Unknown"]\n\n1. d4 *'))
            unrelated.flipped = True
            app.replace_analysis(unrelated)
            self.assertTrue(app.analysis.flipped)
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "session.json"
                white.flipped = True
                save_session(white, path)
                app.analysis = load_session(path)  # Continue restores the saved manual orientation.
                app.show_position(app.analysis.current)
                self.assertTrue(app.analysis.flipped)


class PlayerMetadataTests(unittest.TestCase):
    def test_profile_urls_identify_user_without_overridden_display_names(self):
        for provider, url in (("chess.com", "https://www.chess.com/member/aLiCe"),
                              ("lichess", "https://lichess.org/@/Alice")):
            with self.subTest(provider=provider):
                analysis = Analysis.from_input(chess.Board())
                analysis.headers = {"White": "Someone", "Black": "Display alias", "BlackUrl": url}
                analysis.orient_for(provider, "alice")
                self.assertTrue(analysis.flipped)
                analysis.headers["BlackUrl"] = "https://example.org/member/alice"
                analysis.flipped = False
                analysis.orient_for(provider, "alice")
                self.assertFalse(analysis.flipped)
                analysis.headers["BlackUrl"] = "https://[broken"
                analysis.headers["Black"] = "Alice"
                analysis.orient_for(provider, "alice")
                self.assertTrue(analysis.flipped)


if __name__ == "__main__":
    unittest.main()
