import asyncio
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import chess
import chess.engine
from textual.containers import VerticalScroll
from textual.widgets import Footer, Input, Select, TextArea

from chess_analyzer.browser import GameBrowser
from chess_analyzer.cli import find_stockfish
from chess_analyzer.dialogs import AccountSelectionDialog, HelpDialog, ImportDialog
from chess_analyzer.input import parse_input
from chess_analyzer.online import GamePage
from chess_analyzer.session import load_session, save_session
from chess_analyzer.tui import ChessAnalysisApp


class NavigationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        path = find_stockfish()
        if not path:
            self.skipTest("Stockfish is required for navigation integration tests")
        self.transport, self.engine = await chess.engine.popen_uci(path)
        await self.engine.configure({"Threads": 1, "Hash": 16})

    async def asyncTearDown(self):
        try:
            await asyncio.wait_for(self.engine.quit(), timeout=3)
        finally:
            self.transport.close()

    def app(self, **kwargs):
        return ChessAnalysisApp(chess.Board(), self.engine, 0.05, 3, **kwargs)

    def assert_fits(self, app, *selectors):
        for selector in selectors:
            region = app.screen.query_one(selector).region
            self.assertTrue(0 <= region.x < region.right <= 40, selector)
            self.assertTrue(0 <= region.y < region.bottom <= 24, selector)

    async def test_home_retains_both_trees_without_clobbering_continue(self):
        board, game, white, black = parse_input(
            '[White "Alice"]\n\n1. e4 {Pawn} e5 (1... c5 {Sicilian}) *')
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory) / "session.json"
            app = ChessAnalysisApp(board, self.engine, 0.05, 3, game=game,
                                   white_name=white, black_name=black,
                                   on_session_change=lambda state: save_session(state, session))
            async with app.run_test(size=(40, 24)) as pilot:
                app.action_game_position(1)
                app.action_follow_choice(app.move_choices(app.analysis.current).index(
                    chess.Move.from_uci("c7c5")))
                await pilot.press("f")
                game_state, node, anchor = app.analysis, app.analysis.current, app.analysis.return_position
                snapshot = session.read_bytes()
                await pilot.press("h")
                home = app.analysis
                self.assertEqual(home.current.board.fen(), chess.STARTING_FEN)
                self.assertIsNot(home, game_state)
                await pilot.press("question_mark")
                self.assertIn("g: return to preserved game", app.screen.text)
                await pilot.press("escape")
                # Explore a separate Home branch and edit it; the parked game remains the session.
                home.current.selected = 0
                app.show_position(home.current.child(chess.Move.from_uci("d2d4")))
                await pilot.press("c")
                app.screen.query_one(TextArea).load_text("Home notes")
                await pilot.press("ctrl+s", "f")
                home_node = home.current
                self.assertEqual(session.read_bytes(), snapshot)
                self.assertEqual(load_session(session).current.comment, "Sicilian")
                await pilot.press("g")
                self.assertIs(app.analysis, game_state)
                self.assertIs(app.analysis.current, node)
                self.assertIs(app.analysis.return_position, anchor)
                self.assertTrue(app.analysis.flipped)
                self.assertEqual(node.comment, "Sicilian")
                self.assertEqual(session.read_bytes(), snapshot)
                await pilot.press("h")
                self.assertIs(app.analysis.current, home_node)
                self.assertEqual(home_node.comment, "Home notes")
                self.assertTrue(app.analysis.flipped)
                await pilot.press("g", "escape")
                self.assertIs(app.analysis.current, anchor)
                self.assertIn(chess.Move.from_uci("c7c5"), anchor.children)

    async def test_global_home_cancels_each_dialog_without_applying(self):
        with tempfile.TemporaryDirectory() as directory, patch(
                "chess_analyzer.tui.library_path", return_value=Path(directory)):
            app = self.app()
            async with app.run_test(size=(40, 24)) as pilot:
                home = app.analysis
                await pilot.pause()
                help_key = next(key for key in app.query_one(Footer).query("FooterKey")
                                if "Help" in str(key.render()))
                self.assertLessEqual(help_key.region.right, 40)
                for key, selectors in (("c", ("#save", "#cancel")),
                                       ("s", ("#save", "#cancel")),
                                       ("l", ("#analyses",)),
                                       ("b", ("#browse", "#cancel")),
                                       ("i", ("#load", "#cancel")),
                                       ("question_mark", ("#cancel",))):
                    with self.subTest(dialog=key):
                        await pilot.press(key)
                        self.assert_fits(app, *selectors)
                        if key == "c":
                            app.screen.query_one(TextArea).load_text("Discard this")
                        await pilot.press("ctrl+h")
                        self.assertEqual(len(app.screen_stack), 1)
                        self.assertIs(app.analysis, home)
                        self.assertEqual(home.current.comment, "")
                self.assertEqual(list(Path(directory).iterdir()), [])
                self.assertIsNone(app.browse_user)

    async def test_text_keys_remain_typeable_and_f1_is_contextual(self):
        app = self.app()
        async with app.run_test(size=(40, 24)) as pilot:
            for key, widget, title in (("c", TextArea, "Comment help"),
                                       ("s", Input, "Save help"),
                                       ("b", Input, "Account help"),
                                       ("i", TextArea, "Import help")):
                with self.subTest(dialog=key):
                    await pilot.press(key)
                    editor = app.screen.query_one(widget)
                    editor.focus()
                    if widget is Input:
                        editor.value = ""
                    await pilot.press("h", "q", "question_mark")
                    self.assertEqual(editor.text if widget is TextArea else editor.value, "hq?")
                    await pilot.press("f1")
                    self.assertIsInstance(app.screen, HelpDialog)
                    self.assertEqual(app.screen.title, title)
                    self.assertNotIn("f: flip", app.screen.text)
                    self.assertEqual(len(app.screen_stack), 2)  # Help canceled the entry dialog.
                    self.assert_fits(app, "#cancel")
                    await pilot.press("escape")
                    self.assertEqual(app.analysis.current.comment, "")
            await pilot.press("question_mark")
            self.assertEqual(app.screen.title, "Home help")
            self.assertIn("f: flip", app.screen.text)
            self.assertNotIn("g: return", app.screen.text)
            help_scroll = app.screen.query_one(VerticalScroll)
            help_scroll.focus()
            await pilot.press("pagedown")
            self.assertGreater(help_scroll.scroll_y, 0)
            with tempfile.TemporaryDirectory() as directory, patch(
                    "chess_analyzer.tui.library_path", return_value=Path(directory)):
                await pilot.press("escape", "l", "question_mark")
            self.assertEqual(app.screen.title, "Library help")
            self.assertIn("Enter: open selected analysis", app.screen.text)
            self.assertNotIn("f: flip", app.screen.text)

    async def test_account_validation_provider_selection_and_browser_reuse(self):
        app = self.app()
        with patch("chess_analyzer.browser.lichess_games") as games:
            games.return_value = GamePage([], None)
            async with app.run_test(size=(40, 24)) as pilot:
                await pilot.press("b")
                self.assertIsInstance(app.screen, AccountSelectionDialog)
                app.screen.query_one(Input).value = "bad/name"
                await pilot.press("enter")
                self.assertIn("Enter a username", app.screen.query_one("#error").render().plain)
                self.assert_fits(app, "#browse", "#cancel")
                games.assert_not_called()
                app.screen.query_one(Select).value = "lichess"
                app.screen.query_one(Input).value = " Alice_1 "
                await pilot.press("enter")
                self.assertIsInstance(app.screen, GameBrowser)
                self.assertEqual((app.browse_provider, app.browse_user), ("lichess", "Alice_1"))
                await pilot.pause()
                help_key = next(key for key in app.screen.query_one(Footer).query("FooterKey")
                                if "Help" in str(key.render()))
                self.assertLessEqual(help_key.region.right, 40)
                await pilot.press("f1")
                self.assertEqual(app.screen.title, "Browser help")
                self.assertIn("←/→: newer / older", app.screen.text)
                await pilot.press("escape", "b")
                self.assertIsInstance(app.screen, GameBrowser)
                await pilot.press("ctrl+h")
                self.assertEqual(len(app.screen_stack), 1)

    async def test_import_success_failure_and_canceled_download(self):
        app = self.app()
        async with app.run_test(size=(40, 24)) as pilot:
            await pilot.press("i")
            app.screen.query_one(TextArea).load_text("not a game")
            await pilot.press("ctrl+s")
            self.assertIsInstance(app.screen, ImportDialog)
            self.assertIn("valid FEN", app.screen.query_one("#error").render().plain)
            self.assert_fits(app, "#load", "#cancel")
            app.screen.query_one(TextArea).load_text("1. e4 {Imported} e5 *")
            await pilot.press("ctrl+s")
            self.assertEqual(app.analysis.current.board.peek().uci(), "e7e5")
            self.assertEqual(app.analysis.root.mainline_next.comment, "Imported")
            game = app.analysis
            for cancel in ("escape", "ctrl+h", "f1", "ctrl+q"):
                started, release = threading.Event(), threading.Event()
                def blocked(url):
                    started.set()
                    release.wait(timeout=3)
                    return "1. d4 d5 *"
                with self.subTest(cancel=cancel), patch("chess_analyzer.input.load_url", side_effect=blocked):
                    await pilot.press("i")
                    app.screen.query_one(TextArea).load_text("https://example.org/game.pgn")
                    await pilot.press("ctrl+s")
                    self.assertTrue(await asyncio.to_thread(started.wait, 1))
                    try:
                        await asyncio.wait_for(pilot.press(cancel), timeout=2)
                    finally:
                        release.set()
                    await pilot.pause()
                    if cancel == "ctrl+h":
                        self.assertIs(app.preserved_analysis[0], game)
                        await pilot.press("g")
                    self.assertIs(app.analysis, game)
                    self.assertEqual(game.current.board.peek().uci(), "e7e5")
                    if cancel == "f1":
                        self.assertIsInstance(app.screen, HelpDialog)
                        await pilot.press("escape")


if __name__ == "__main__":
    unittest.main()
