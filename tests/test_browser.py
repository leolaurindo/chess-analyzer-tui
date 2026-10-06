import asyncio
import json
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import chess
import chess.engine
from textual.widgets import Input, Select

from chess_browser import GameBrowser
from chess_cli import find_stockfish
from chess_tui import ChessAnalysisApp


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
        async def ready():
            while not browser.games or browser.busy:
                await pilot.pause()
        await asyncio.wait_for(ready(), timeout=4)
        await pilot.pause()

    async def test_chesscom_month_selection_import_and_cancel_preserve_current_analysis(self):
        game = {"rules": "chess", "white": {"username": "Alice"}, "black": {"username": "Bob"},
                "end_time": 1700000000, "pgn": PGN, "url": "https://www.chess.com/game/live/1"}
        requested = []

        def fetch(url, **kwargs):
            requested.append(url)
            if url.endswith("archives"):
                return json.dumps({"archives": ["https://api.chess.com/pub/player/Alice/games/2024/01",
                                                "https://api.chess.com/pub/player/Alice/games/2023/12"]})
            return json.dumps({"games": [game]})

        app = ChessAnalysisApp(chess.Board(), self.engine, 0.05, 3)
        with patch("chess_online.fetch_text", side_effect=fetch):
            async with app.run_test(size=(80, 24)) as pilot:
                previous = app.analysis
                previous.current.comment = "Unsaved current note"
                await pilot.press("b", "escape")
                self.assertIs(app.analysis, previous)
                self.assertEqual(app.analysis.current.comment, "Unsaved current note")
                await pilot.press("b")
                browser = app.screen
                browser.query_one(Input).value = "Alice"
                await pilot.pause()
                browser.query_one(Input).focus()
                await pilot.press("enter")
                await self.wait_for_games(browser, pilot)
                self.assertEqual(browser.query_one("#month", Select).value, "2024-01")
                browser.query_one("#month", Select).value = "2023-12"
                browser.load_newest()
                await self.wait_for_games(browser, pilot)
                self.assertTrue(requested[-1].endswith("/2023/12"))
                await pilot.press("enter")
                self.assertIsNot(app.analysis, previous)
                self.assertEqual(app.analysis.root.comment, "Introduction")
                self.assertEqual((app.analysis.white_name, app.analysis.black_name), ("Alice", "Bob"))
                app.action_game_position(1)
                self.assertEqual(app.analysis.current.comment, "Pawn")
                self.assertIn(chess.Move.from_uci("c7c5"), app.move_choices(app.analysis.current))

    async def test_lichess_pagination_and_selected_pgn_use_public_endpoints(self):
        base = {"id": "game0000", "variant": "standard", "status": "mate", "createdAt": 2000,
                "speed": "blitz", "winner": "white",
                "players": {"white": {"user": {"name": "Alice"}},
                            "black": {"user": {"name": "Bob"}}}}
        first = [base | {"id": f"game{i:04}", "createdAt": 2000 - i,
                         "variant": "standard" if i == 0 else "atomic"} for i in range(50)]
        requests = []

        def fetch(url, **kwargs):
            requests.append(url)
            if "/game/export/" in url:
                return PGN
            if "until" in parse_qs(urlsplit(url).query):
                return json.dumps(base | {"id": "older001", "createdAt": 1800})
            return "\n".join(json.dumps(game) for game in first)

        app = ChessAnalysisApp(chess.Board(), self.engine, 0.05, 3, startup_menu="browser")
        with patch("chess_online.fetch_text", side_effect=fetch):
            async with app.run_test(size=(42, 28)) as pilot:
                browser = app.screen
                self.assertIsInstance(browser, GameBrowser)
                for selector in ("#load", "#older", "#newest"):
                    region = browser.query_one(selector).region
                    self.assertTrue(0 <= region.x < region.right <= 42)
                    self.assertTrue(0 <= region.y < region.bottom <= 28)
                browser.query_one("#provider", Select).value = "lichess"
                browser.query_one(Input).value = "Alice"
                await pilot.pause()
                browser.load_newest()
                await self.wait_for_games(browser, pilot)
                self.assertFalse(browser.query_one("#month").display)
                self.assertEqual(browser.until, 1950)
                browser.load_older()
                await self.wait_for_games(browser, pilot)
                self.assertEqual(parse_qs(urlsplit(requests[-1]).query)["until"], ["1950"])
                self.assertIsNone(browser.until)
                await pilot.press("enter")
                await pilot.pause()
                self.assertTrue(requests[-1].endswith("/game/export/older001"))
                self.assertEqual(app.analysis.root.comment, "Introduction")
                self.assertEqual(app.analysis.current.board.peek().uci(), "e7e5")

    async def test_listing_error_and_cancel_inflight_request_do_not_replace_analysis(self):
        started, release = threading.Event(), threading.Event()

        def blocked(username):
            started.set()
            release.wait(timeout=3)
            return []

        app = ChessAnalysisApp(chess.Board(), self.engine, 0.05, 3)
        async with app.run_test() as pilot:
            previous = app.analysis
            await pilot.press("b")
            browser = app.screen
            browser.query_one(Input).value = "Alice"
            await pilot.pause()
            with patch("chess_browser.chesscom_months", side_effect=ValueError("Rate limited")):
                browser.load_newest()
                async def failed():
                    while "Rate limited" not in browser.query_one("#browser-status").render().plain:
                        await pilot.pause()
                await asyncio.wait_for(failed(), timeout=3)
                self.assertIs(app.analysis, previous)
            with patch("chess_browser.chesscom_months", side_effect=blocked):
                browser.load_newest()
                self.assertTrue(await asyncio.to_thread(started.wait, 1))
                try:
                    await asyncio.wait_for(pilot.press("escape"), timeout=2)
                    self.assertIs(app.analysis, previous)
                    self.assertNotIsInstance(app.screen, GameBrowser)
                finally:
                    release.set()
                await pilot.pause()
                self.assertIs(app.analysis, previous)


if __name__ == "__main__":
    unittest.main()
