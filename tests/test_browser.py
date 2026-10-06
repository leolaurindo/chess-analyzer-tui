import asyncio
import threading
import unittest
from dataclasses import replace
from unittest.mock import patch

import chess
import chess.engine
from textual.widgets import OptionList

from chess_analyzer.browser import GameBrowser
from chess_analyzer.cli import find_stockfish
from chess_analyzer.online import GamePage, OnlineGame
from chess_analyzer.tui import ChessAnalysisApp


PGN = '[White "Alice"]\n[Black "Bob"]\n[Result "1-0"]\n\n{Introduction} 1. e4 {Pawn} e5 (1... c5 {Sicilian}) 1-0'


class BrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        path = find_stockfish()
        if not path:
            self.skipTest("Stockfish is required for browser integration tests")
        self.transport, self.engine = await chess.engine.popen_uci(path)
        await self.engine.configure({"Threads": 1, "Hash": 16})

    async def asyncTearDown(self):
        try:
            await asyncio.wait_for(self.engine.quit(), timeout=3)
        finally:
            self.transport.close()

    async def wait_for_games(self, browser, pilot):
        await pilot.pause()
        async def ready():
            while not browser.games or browser.busy:
                await pilot.pause()
        await asyncio.wait_for(ready(), timeout=4)

    async def test_provider_paging_keyboard_mouse_selection_and_reopening(self):
        games = [OnlineGame("older001", "Alice", "Bob", "", "1-0", "blitz", PGN),
                 OnlineGame("older002", "Alice", "Carol", "", "1-0", "blitz", PGN.replace("Bob", "Carol"))]
        for provider in ("chess.com", "lichess"):
            listed = games if provider == "chess.com" else [replace(game, pgn=None) for game in games]
            recent = [replace(listed[0], id="recent01")]
            app = ChessAnalysisApp(chess.Board(), self.engine, 0.05, 3,
                                   browse_provider=provider, browse_user="Alice")
            with (self.subTest(provider=provider),
                  patch("chess_analyzer.browser.chesscom_months", return_value=["2024-01", "2023-12"]),
                  patch("chess_analyzer.browser.chesscom_games", side_effect=lambda user, month:
                        recent if month == "2024-01" else listed) as monthly,
                  patch("chess_analyzer.browser.lichess_games", side_effect=lambda user, until:
                        GamePage(recent, 123) if until is None else GamePage(listed, None)) as paged,
                  patch("chess_analyzer.browser.lichess_pgn", return_value=games[1].pgn) as export):
                async with app.run_test(size=(40, 24)) as pilot:
                    previous = app.analysis
                    browser = app.screen
                    await self.wait_for_games(browser, pilot)
                    self.assertIs(app.focused, browser.query_one(OptionList))
                    for selector in ("#reload", "#older", "#newer", "#games"):
                        region = browser.query_one(selector).region
                        self.assertTrue(0 <= region.x < region.right <= 40)
                        self.assertTrue(0 <= region.y < region.bottom <= 24)
                    await pilot.press("right")
                    await self.wait_for_games(browser, pilot)
                    if provider == "chess.com":
                        monthly.assert_called_with("Alice", "2023-12")
                    else:
                        paged.assert_called_with("Alice", until=123)
                        self.assertTrue(browser.query_one("#older").disabled)
                    await pilot.press("left")
                    await self.wait_for_games(browser, pilot)
                    self.assertEqual(browser.query_one(OptionList).option_count, 1)
                    await pilot.click("#older")
                    await self.wait_for_games(browser, pilot)
                    self.assertIs(app.analysis, previous)
                    # Choosing games must work even after Tab moves focus to a button.
                    await pilot.press("tab", "down", "up", "down")
                    self.assertEqual(browser.query_one(OptionList).highlighted, 1)
                    if provider == "chess.com":
                        await pilot.click("#games", offset=(4, 2))
                        export.assert_not_called()
                    else:
                        await pilot.press("enter")
                        export.assert_called_once_with("older002")
                    self.assertEqual((app.analysis.white_name, app.analysis.black_name), ("Alice", "Carol"))
                    self.assertEqual(app.analysis.root.comment, "Introduction")
                    self.assertEqual(app.analysis.current.board.peek().uci(), "e7e5")
                    imported = app.analysis
                    await pilot.press("b", "escape")
                    self.assertIs(app.analysis, imported)

    async def test_error_retry_and_cancel_inflight_request_preserve_analysis(self):
        started, release = threading.Event(), threading.Event()

        def blocked(username):
            started.set()
            release.wait(timeout=3)
            return []

        app = ChessAnalysisApp(chess.Board(), self.engine, 0.05, 3,
                               browse_provider="chess.com", browse_user="Alice")
        with patch("chess_analyzer.browser.chesscom_months", side_effect=ValueError("Rate limited")):
            async with app.run_test() as pilot:
                previous = app.analysis
                previous.current.comment = "Unsaved note"
                browser = app.screen
                async def failed():
                    while "Rate limited" not in browser.query_one("#browser-status").render().plain:
                        await pilot.pause()
                await asyncio.wait_for(failed(), timeout=3)
                with patch("chess_analyzer.browser.chesscom_months", side_effect=blocked):
                    await pilot.press("r")
                    self.assertTrue(await asyncio.to_thread(started.wait, 1))
                    try:
                        await asyncio.wait_for(pilot.press("escape"), timeout=2)
                        self.assertNotIsInstance(app.screen, GameBrowser)
                    finally:
                        release.set()
                    await pilot.pause()
                self.assertIs(app.analysis, previous)
                self.assertEqual(app.analysis.current.comment, "Unsaved note")


if __name__ == "__main__":
    unittest.main()
