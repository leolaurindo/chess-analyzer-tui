import asyncio
import json
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import chess
import chess.engine
from textual.widgets import OptionList

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
        await pilot.pause()
        async def ready():
            while not browser.games or browser.busy:
                await pilot.pause()
        await asyncio.wait_for(ready(), timeout=4)
        await pilot.pause()

    async def test_chesscom_autoload_keyboard_paging_selection_and_cancel(self):
        game = {"rules": "chess", "white": {"username": "Alice"}, "black": {"username": "Bob"},
                "end_time": 1700000000, "pgn": PGN, "url": "https://www.chess.com/game/live/1"}
        other = game | {"black": {"username": "Carol"}, "pgn": PGN.replace("Bob", "Carol"),
                        "url": "https://www.chess.com/game/live/2"}
        requested = []

        def fetch(url, **kwargs):
            requested.append(url)
            if url.endswith("archives"):
                return json.dumps({"archives": ["https://api.chess.com/pub/player/Alice/games/2024/01",
                                                "https://api.chess.com/pub/player/Alice/games/2023/12"]})
            return json.dumps({"games": [game, other]})

        app = ChessAnalysisApp(chess.Board(), self.engine, 0.05, 3,
                               browse_provider="chess.com", browse_user="Alice")
        with patch("chess_online.fetch_text", side_effect=fetch):
            async with app.run_test(size=(80, 24)) as pilot:
                previous = app.analysis
                previous.current.comment = "Unsaved current note"
                await pilot.press("b", "escape")
                self.assertIs(app.analysis, previous)
                self.assertEqual(app.analysis.current.comment, "Unsaved current note")
                await pilot.press("b")
                browser = app.screen
                await self.wait_for_games(browser, pilot)
                self.assertIn("2024-01", browser.query_one("#browser-status").render().plain)
                await pilot.press("right")
                await self.wait_for_games(browser, pilot)
                self.assertTrue(requested[-1].endswith("/2023/12"))
                await pilot.press("left")
                await self.wait_for_games(browser, pilot)
                self.assertTrue(requested[-1].endswith("/2024/01"))
                await pilot.press("right")
                await self.wait_for_games(browser, pilot)
                self.assertTrue(requested[-1].endswith("/2023/12"))
                # Arrow navigation must still choose games after focus moves to a button.
                await pilot.press("tab", "down", "up", "down")
                self.assertEqual(browser.query_one(OptionList).highlighted, 1)
                await pilot.press("enter")
                self.assertIsNot(app.analysis, previous)
                self.assertEqual(app.analysis.root.comment, "Introduction")
                self.assertEqual((app.analysis.white_name, app.analysis.black_name), ("Alice", "Carol"))
                app.action_game_position(1)
                self.assertEqual(app.analysis.current.comment, "Pawn")
                self.assertIn(chess.Move.from_uci("c7c5"), app.move_choices(app.analysis.current))

    async def test_lichess_autoload_paging_and_selected_pgn_use_public_endpoints(self):
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

        app = ChessAnalysisApp(chess.Board(), self.engine, 0.05, 3, startup_menu="browser",
                               browse_provider="lichess", browse_user="Alice")
        with patch("chess_online.fetch_text", side_effect=fetch):
            async with app.run_test(size=(40, 24)) as pilot:
                browser = app.screen
                self.assertIsInstance(browser, GameBrowser)
                await self.wait_for_games(browser, pilot)
                self.assertIs(app.focused, browser.query_one(OptionList))
                for selector in ("#reload", "#older", "#newer", "#games"):
                    region = browser.query_one(selector).region
                    self.assertTrue(0 <= region.x < region.right <= 40)
                    self.assertTrue(0 <= region.y < region.bottom <= 24)
                await pilot.press("right")
                await self.wait_for_games(browser, pilot)
                self.assertEqual(parse_qs(urlsplit(requests[-1]).query)["until"], ["1950"])
                self.assertTrue(browser.query_one("#older").disabled)
                await pilot.press("left")
                await self.wait_for_games(browser, pilot)
                self.assertNotIn("until", parse_qs(urlsplit(requests[-1]).query))
                await pilot.press("right")
                await self.wait_for_games(browser, pilot)
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

        app = ChessAnalysisApp(chess.Board(), self.engine, 0.05, 3,
                               browse_provider="chess.com", browse_user="Alice")
        async with app.run_test() as pilot:
            previous = app.analysis
            with patch("chess_browser.chesscom_months", side_effect=ValueError("Rate limited")):
                await pilot.press("b")
                browser = app.screen
                async def failed():
                    while "Rate limited" not in browser.query_one("#browser-status").render().plain:
                        await pilot.pause()
                await asyncio.wait_for(failed(), timeout=3)
                self.assertIs(app.analysis, previous)
            with patch("chess_browser.chesscom_months", side_effect=blocked):
                await pilot.press("r")
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
