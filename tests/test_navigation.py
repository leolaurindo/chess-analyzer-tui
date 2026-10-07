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
from chess_analyzer.online import GamePage, OnlineGame
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

    def assert_navigation_footer(self, app):
        keys = list(app.screen.query_one(Footer).query("FooterKey"))
        rendered = "".join(str(key.render()) for key in keys)
        self.assertIn("Ctrl+H Home", rendered)
        self.assertIn("F1 Help", rendered)
        for key in keys:
            self.assertLessEqual(key.region.right, 40)

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
                self.assertIs(app.analysis.current, home.root)
                self.assertIsNone(app.analysis.return_position)
                self.assertEqual(app.analysis.current.board.fen(), chess.STARTING_FEN)
                self.assertIs(home.root.children[chess.Move.from_uci("d2d4")], home_node)
                app.show_position(home_node)
                home.return_position = home.root
                await pilot.press("h")
                self.assertIs(app.analysis.current, home.root)
                self.assertIsNone(home.return_position)
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
                        self.assert_navigation_footer(app)
                        if key == "c":
                            app.screen.query_one(TextArea).load_text("Discard this")
                        if key != "question_mark":
                            await pilot.press("f1")
                            self.assertIsInstance(app.screen, HelpDialog)
                            self.assertEqual(len(app.screen_stack), 3)
                            self.assert_navigation_footer(app)
                        await pilot.press("ctrl+h")
                        self.assertEqual(len(app.screen_stack), 1)
                        self.assertIs(app.analysis, home)
                        self.assertEqual(home.current.comment, "")
                self.assertEqual(list(Path(directory).iterdir()), [])
                self.assertIsNone(app.browse_user)
                await pilot.press("c")
                app.screen.query_one(TextArea).load_text("Discard on quit")
                await pilot.press("f1", "ctrl+q")
                self.assertEqual(len(app.screen_stack), 1)
                self.assertEqual(home.current.comment, "")

    async def test_text_keys_remain_typeable_and_f1_is_contextual(self):
        app = self.app()
        async with app.run_test(size=(40, 24)) as pilot:
            for key, widget, title in (("c", TextArea, "Comment help"),
                                       ("s", Input, "Save help"),
                                       ("b", Input, "Account help"),
                                       ("i", TextArea, "Import help")):
                with self.subTest(dialog=key):
                    await pilot.press(key)
                    dialog = app.screen
                    editor = dialog.query_one(widget)
                    editor.focus()
                    if widget is Input:
                        editor.value = ""
                    await pilot.press("h", "q", "question_mark")
                    self.assertEqual(editor.text if widget is TextArea else editor.value, "hq?")
                    await pilot.press("f1")
                    self.assertIsInstance(app.screen, HelpDialog)
                    self.assertEqual(app.screen.title, title)
                    self.assertNotIn("f: flip", app.screen.text)
                    self.assertEqual(len(app.screen_stack), 3)
                    self.assert_navigation_footer(app)
                    self.assert_fits(app, "#cancel")
                    for close_help in ("escape", "f1", "question_mark"):
                        await pilot.press(close_help)
                        self.assertIs(app.screen, dialog)
                        self.assertEqual(editor.text if widget is TextArea else editor.value, "hq?")
                        self.assertEqual(app.analysis.current.comment, "")
                        if close_help != "question_mark":
                            await pilot.press("f1")
                    if key == "c":
                        await pilot.press("ctrl+s")
                        self.assertEqual(app.analysis.current.comment, "hq?")
                        await pilot.press("c")
                        app.screen.query_one(TextArea).load_text("")
                        await pilot.press("ctrl+s")
                    else:
                        await pilot.press("escape")
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
                self.assert_navigation_footer(app)
                await pilot.press("f1")
                self.assertEqual(app.screen.title, "Browser help")
                self.assertIn("←/→: newer / older", app.screen.text)
                browser = app.screen_stack[-2]
                await pilot.press("escape")
                self.assertIs(app.screen, browser)
                await pilot.press("escape", "b")
                self.assertIsInstance(app.screen, GameBrowser)
                await pilot.press("ctrl+h")
                self.assertEqual(len(app.screen_stack), 1)
                await pilot.press("u")
                self.assertIsInstance(app.screen, AccountSelectionDialog)
                self.assertEqual(app.screen.query_one(Input).value, "Alice_1")
                self.assertEqual(app.screen.query_one(Select).value, "lichess")
                app.screen.query_one(Select).value = "chess.com"
                app.screen.query_one(Input).value = "Bob"
                with patch("chess_analyzer.browser.chesscom_months", return_value=[]):
                    await pilot.press("enter")
                    self.assertIsInstance(app.screen, GameBrowser)
                    self.assertEqual((app.browse_provider, app.browse_user), ("chess.com", "Bob"))
                    await pilot.press("escape", "u", "escape", "b")
                    self.assertIsInstance(app.screen, GameBrowser)
                    self.assertEqual(app.screen.username, "Bob")

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
            for cancel in ("escape", "ctrl+h", "ctrl+q"):
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

    async def test_help_cancels_inflight_import_but_keeps_text_and_allows_retry(self):
        started, release, completed = threading.Event(), threading.Event(), threading.Event()
        def blocked(url):
            started.set()
            release.wait(timeout=5)
            completed.set()
            return "1. d4 d5 *"

        app = self.app()
        with patch("chess_analyzer.input.load_url", side_effect=blocked):
            async with app.run_test(size=(40, 24)) as pilot:
                previous = app.analysis
                await pilot.press("i")
                dialog = app.screen
                url = "https://example.org/game.pgn"
                dialog.query_one(TextArea).load_text(url)
                await pilot.press("ctrl+s")
                self.assertTrue(await asyncio.to_thread(started.wait, 1))
                try:
                    await pilot.press("f1")
                    self.assertIsInstance(app.screen, HelpDialog)
                    release.set()
                    self.assertTrue(await asyncio.to_thread(completed.wait, 1))
                    await pilot.pause()
                    self.assertIsInstance(app.screen, HelpDialog)
                    self.assertIs(app.analysis, previous)
                    await pilot.press("escape")
                    self.assertIs(app.screen, dialog)
                    self.assertEqual(dialog.query_one(TextArea).text, url)
                    self.assertFalse(dialog.query_one(TextArea).disabled)
                    self.assertFalse(dialog.query_one("#load").disabled)
                    await pilot.press("ctrl+s")
                    self.assertEqual(app.analysis.current.board.peek().uci(), "d7d5")
                    self.assertEqual(len(app.screen_stack), 1)
                finally:
                    release.set()

    async def test_help_cancels_browser_loads_without_dismissing_underlying_dialog(self):
        game = OnlineGame("game0001", "Alice", "Bob", "", "1-0", "blitz")
        app = self.app()
        with patch("chess_analyzer.browser.lichess_games", return_value=GamePage([game], None)):
            async with app.run_test(size=(40, 24)) as pilot:
                app.browse_provider, app.browse_user = "lichess", "Alice"
                previous = app.analysis
                await pilot.press("b")
                browser = app.screen
                for operation, target, result in (
                        ("r", "lichess_games", GamePage([game], None)),
                        ("enter", "lichess_pgn", "1. e4 e5 1-0")):
                    started, release, completed = threading.Event(), threading.Event(), threading.Event()
                    def blocked(*args, **kwargs):
                        started.set()
                        release.wait(timeout=5)
                        completed.set()
                        return result
                    with self.subTest(operation=operation), patch(
                            "chess_analyzer.browser." + target, side_effect=blocked):
                        await pilot.press(operation)
                        self.assertTrue(await asyncio.to_thread(started.wait, 1))
                        try:
                            await pilot.press("question_mark")
                            self.assertIsInstance(app.screen, HelpDialog)
                            release.set()
                            self.assertTrue(await asyncio.to_thread(completed.wait, 1))
                            await pilot.pause()
                            self.assertIsInstance(app.screen, HelpDialog)
                            self.assertIs(app.analysis, previous)
                            await pilot.press("f1")
                            self.assertIs(app.screen, browser)
                            self.assertFalse(browser.busy)
                        finally:
                            release.set()
                    if operation == "r":
                        await pilot.press("r")
                        self.assertEqual(browser.games, [game])
                with patch("chess_analyzer.browser.lichess_pgn", return_value="1. e4 e5 1-0"):
                    await pilot.press("enter")
                    self.assertEqual(len(app.screen_stack), 1)
                    self.assertEqual(app.analysis.current.board.peek().uci(), "e7e5")


if __name__ == "__main__":
    unittest.main()
