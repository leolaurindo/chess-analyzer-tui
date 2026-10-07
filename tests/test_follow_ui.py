import asyncio
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import chess
import chess.engine
import chess.pgn
from textual.widgets import Input, Select

from chess_analyzer.browser import GameBrowser
from chess_analyzer.cli import find_stockfish, main
from chess_analyzer.config import Account, load_account, save_account
from chess_analyzer.dialogs import AccountSelectionDialog, HelpDialog, LatestGameDialog
from chess_analyzer.follow import load_latest_game
from chess_analyzer.game import Analysis
from chess_analyzer.input import parse_input
from chess_analyzer.online import GamePage
from chess_analyzer.session import load_session, save_session
from chess_analyzer.tui import ChessAnalysisApp


PGN = ('[Event "Public game"]\n[Site "https://lichess.org/latest01"]\n'
       '[Date "2025.06.01"]\n[White "?"]\n[Black "Bob"]\n[Result "1-0"]\n\n'
       '{Introduction} 1. e4 {Pawn} e5 (1... c5 {Sicilian}) 2. Nf3 1-0')
FINAL_FEN = "rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2"
RECORD = {"id": "latest01", "createdAt": 1000, "variant": "standard", "status": "resign",
          "players": {"white": {"user": {"name": "Alice"}},
                      "black": {"user": {"name": "Bob"}}}, "winner": "white"}


class FollowUiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.config, self.session = self.root / "config.json", self.root / "session.json"
        for target in ("chess_analyzer.config.user_config_path", "chess_analyzer.session.user_state_path"):
            location = patch(target, return_value=self.root)
            location.start()
            self.addCleanup(location.stop)
        path = find_stockfish()
        if not path:
            self.skipTest("Stockfish is required for follow integration tests")
        self.engine_path = path
        self.transport, self.engine = await chess.engine.popen_uci(path)
        await self.engine.configure({"Threads": 1, "Hash": 16})

    async def asyncTearDown(self):
        try:
            await asyncio.wait_for(self.engine.quit(), timeout=3)
        finally:
            self.transport.close()

    def app(self, **kwargs):
        board, game, white, black = parse_input('[White "Prior"]\n[Black "Game"]\n\n1. d4 {Keep} d5 *')
        return ChessAnalysisApp(board, self.engine, 0.05, 3, game=game,
                                white_name=white, black_name=black,
                                on_session_change=lambda state: save_session(state, self.session), **kwargs)

    async def wait_for(self, pilot, predicate):
        async def ready():
            while not predicate():
                await pilot.pause()
        await asyncio.wait_for(ready(), timeout=4)

    async def test_plain_startup_uses_default_account_only_on_explicit_b_or_latest(self):
        save_account(Account("lichess", "Alice"), self.config)
        snapshot = self.config.read_bytes()
        async def run(app):
            self.assertEqual((app.browse_provider, app.browse_user), ("lichess", "Alice"))
            async with app.run_test(size=(40, 24)) as pilot:
                prior = app.analysis
                self.assertEqual(prior.current.board.fen(), chess.STARTING_FEN)
                self.assertEqual(len(app.screen_stack), 1)
                fetch.assert_not_called()
                await pilot.press("u")
                self.assertIsInstance(app.screen, AccountSelectionDialog)
                self.assertEqual(app.screen.query_one(Input).value, "Alice")
                self.assertEqual(app.screen.query_one(Select).value, "lichess")
                await pilot.press("escape", "question_mark")
                self.assertIn("Ctrl+L: latest available", app.screen.text)
                await pilot.press("escape", "b")
                self.assertIsInstance(app.screen, GameBrowser)
                self.assertEqual(app.screen.username, "Alice")
                await pilot.press("escape", "ctrl+l")
                self.assertIsInstance(app.screen, LatestGameDialog)
                await self.wait_for(pilot, lambda: not app.screen.query_one("#load").disabled)
                self.assertIn("No completed standard games", app.screen.query_one("#latest-status").render().plain)
                await pilot.press("escape")
                self.assertIs(app.analysis, prior)

        with (patch("sys.argv", ["chess-analyzer", "--engine", self.engine_path,
                                 "-t", "0.05", "--threads", "1", "--hash", "16"]),
              patch("chess_analyzer.online.fetch_text", return_value="") as fetch,
              patch.object(ChessAnalysisApp, "run_async", run)):
            await asyncio.to_thread(main)
        self.assertEqual(self.config.read_bytes(), snapshot)

        async def browse(app):
            async with app.run_test(size=(40, 24)) as pilot:
                self.assertIsInstance(app.screen, GameBrowser)
                self.assertEqual((app.screen.provider, app.screen.username), ("chess.com", "CliUser"))
                await pilot.press("escape")

        with (patch("sys.argv", ["chess-analyzer", "--browse", "chess.com", "--user", "CliUser",
                                 "--engine", self.engine_path, "-t", "0.05", "--threads", "1", "--hash", "16"]),
              patch("chess_analyzer.browser.chesscom_months", return_value=[]),
              patch.object(ChessAnalysisApp, "run_async", browse)):
            await asyncio.to_thread(main)
        self.assertEqual(self.config.read_bytes(), snapshot)

    async def test_account_selection_saves_changes_and_failed_save_preserves_account_and_analysis(self):
        app = self.app()
        with (patch("chess_analyzer.browser.lichess_games", return_value=GamePage([], None)),
              patch("chess_analyzer.browser.chesscom_months", return_value=[])):
            async with app.run_test(size=(40, 24)) as pilot:
                prior = app.analysis
                await pilot.press("ctrl+l")
                self.assertEqual(len(app.screen_stack), 1)
                await pilot.press("u")
                app.screen.query_one(Select).value = "lichess"
                app.screen.query_one(Input).value = " Alice "
                await pilot.press("enter")
                self.assertEqual(load_account(), Account("lichess", "Alice"))
                self.assertIsInstance(app.screen, GameBrowser)
                await pilot.press("escape", "u")
                self.assertEqual(app.screen.query_one(Input).value, "Alice")
                self.assertEqual(app.screen.query_one(Select).value, "lichess")
                app.screen.query_one(Select).value = "chess.com"
                app.screen.query_one(Input).value = "Bob"
                await pilot.press("enter", "escape")
                self.assertEqual(load_account(), Account("chess.com", "Bob"))
                snapshot = self.config.read_bytes()
                await pilot.press("u")
                app.screen.query_one(Input).value = "Carol"
                with (patch("chess_analyzer.session.os.replace", side_effect=OSError("disk failure")),
                      patch.object(app, "notify") as notify):
                    await pilot.press("enter")
                notify.assert_called_once()
                self.assertIn("account unchanged", notify.call_args.args[0])
                self.assertEqual((app.browse_provider, app.browse_user), ("chess.com", "Bob"))
                self.assertIs(app.analysis, prior)
                self.assertEqual(len(app.screen_stack), 1)
                self.assertEqual(self.config.read_bytes(), snapshot)

    async def test_latest_failure_empty_and_retry_preserve_session_until_success(self):
        app = self.app(browse_provider="lichess", browse_user="Alice", open_latest=True)
        save_session(app.analysis, self.session)
        previous = self.session.read_bytes()
        with patch("chess_analyzer.online.fetch_text", side_effect=ValueError("Rate limited")):
            async with app.run_test(size=(40, 24)) as pilot:
                prior = app.analysis
                dialog = app.screen
                await self.wait_for(pilot, lambda: not dialog.query_one("#load").disabled)
                self.assertIn("Rate limited", dialog.query_one("#latest-status").render().plain)
                self.assertIs(app.analysis, prior)
                self.assertEqual(self.session.read_bytes(), previous)
                with patch("chess_analyzer.online.fetch_text", return_value=""):
                    await pilot.press("r")
                    await self.wait_for(pilot, lambda: not dialog.query_one("#load").disabled)
                self.assertIn("No completed standard games", dialog.query_one("#latest-status").render().plain)
                self.assertEqual(self.session.read_bytes(), previous)
                with patch("chess_analyzer.online.fetch_text", side_effect=[json.dumps(RECORD), PGN]):
                    await pilot.press("r")
                    await self.wait_for(pilot, lambda: len(app.screen_stack) == 1)
                self.assertEqual(app.analysis.current.board.fen(), FINAL_FEN)
                self.assertEqual(load_session(self.session).headers["Event"], "Public game")
                self.assertIsNot(app.analysis, prior)

    async def test_cancellation_stops_requests_and_help_keeps_latest_dialog_retryable(self):
        cases = [("chess.com", "archives", "escape"), ("chess.com", "month", "f2"),
                 ("lichess", "filtered", "question_mark"), ("lichess", "listing", "ctrl+q"),
                 ("lichess", "export", "escape")]
        for provider, stage, cancel in cases:
            with self.subTest(provider=provider, stage=stage, cancel=cancel):
                started, release, completed = threading.Event(), threading.Event(), threading.Event()
                calls = []
                prefix = "https://api.chess.com/pub/player/Alice/games/"
                filtered = "\n".join(json.dumps(RECORD | {"createdAt": 1000 - i, "variant": "atomic"})
                                     for i in range(50))

                def fetch(url, **kwargs):
                    calls.append(url)
                    blocked = ((stage == "archives" and url.endswith("archives"))
                               or (stage == "month" and url.endswith("2025/06"))
                               or (stage in {"filtered", "listing"} and "api/games/user" in url)
                               or (stage == "export" and "game/export" in url))
                    if blocked and not release.is_set():
                        started.set()
                        if not release.wait(5):
                            raise TimeoutError("test did not release request")
                    if provider == "chess.com":
                        if url.endswith("archives"):
                            return json.dumps({"archives": [prefix + "2025/05", prefix + "2025/06"]})
                        return '{"games": []}'
                    if "api/games/user" in url:
                        return filtered if stage == "filtered" and "until=" not in url else json.dumps(RECORD)
                    return PGN

                def load(*args, **kwargs):
                    try:
                        return load_latest_game(*args, **kwargs)
                    finally:
                        completed.set()

                save_account(Account(provider, "Alice"), self.config)
                config_before = self.config.read_bytes()
                app = self.app(browse_provider=provider, browse_user="Alice", open_latest=True)
                save_session(app.analysis, self.session)
                before = self.session.read_bytes()
                with (patch("chess_analyzer.online.fetch_text", side_effect=fetch),
                      patch("chess_analyzer.dialogs.load_latest_game", side_effect=load)):
                    async with app.run_test(size=(40, 24)) as pilot:
                        prior, dialog = app.analysis, app.screen
                        self.assertTrue(await asyncio.to_thread(started.wait, 2))
                        try:
                            for selector in ("#load", "#cancel"):
                                region = dialog.query_one(selector).region
                                self.assertTrue(0 <= region.x < region.right <= 40)
                                self.assertTrue(0 <= region.y < region.bottom <= 24)
                            in_flight = list(calls)
                            await asyncio.wait_for(pilot.press(cancel), timeout=2)
                            self.assertTrue(dialog.cancelled.is_set())
                            release.set()
                            self.assertTrue(await asyncio.to_thread(completed.wait, 2))
                            await pilot.pause()
                            self.assertEqual(calls, in_flight)
                            self.assertEqual(self.session.read_bytes(), before)
                            self.assertEqual(self.config.read_bytes(), config_before)
                            if cancel == "f2":
                                self.assertIs(app.preserved_analysis[0], prior)
                                await pilot.press("g")
                            elif cancel == "question_mark":
                                self.assertIsInstance(app.screen, HelpDialog)
                                self.assertEqual(app.screen.title, "Latest game help")
                                await pilot.press("escape")
                                self.assertIs(app.screen, dialog)
                                self.assertFalse(dialog.query_one("#load").disabled)
                                await pilot.press("r")
                                await self.wait_for(pilot, lambda: len(app.screen_stack) == 1)
                                self.assertEqual(app.analysis.current.board.fen(), FINAL_FEN)
                                continue
                            self.assertIs(app.analysis, prior)
                        finally:
                            release.set()

    async def test_cli_follow_restores_prior_session_and_applies_overrides_to_metadata(self):
        prior = Analysis.from_input(*parse_input('[White "Prior"]\n[Black "Game"]\n\n1. d4 {Keep} d5 *'))
        prior.flipped = True
        save_session(prior, self.session)
        before = self.session.read_bytes()
        save_account(Account("lichess", "Bob"), self.config)

        async def run(app):
            self.assertEqual((app.analysis.white_name, app.analysis.black_name), ("Prior", "Game"))
            async with app.run_test(size=(40, 24)) as pilot:
                await self.wait_for(pilot, lambda: app.analysis.current.board.fen() == FINAL_FEN)
                self.assertEqual(len(app.screen_stack), 1)
                self.assertEqual(app.analysis.current.board.fen(), FINAL_FEN)
                exported = chess.pgn.read_game(io.StringIO(app.analysis.to_pgn()))
                expected = {"White": "White", "Black": "Changed Black", "Event": "Public game",
                            "Site": "https://lichess.org/latest01", "Date": "2025.06.01", "Result": "1-0"}
                for header, value in expected.items():
                    self.assertEqual(exported.headers[header], value)
                    if header not in {"White", "Black"}:
                        self.assertEqual(load_session(self.session).headers[header], value)
                restored = load_session(self.session)
                self.assertEqual((restored.white_name, restored.black_name), ("White", "Changed Black"))
                self.assertEqual((restored.headers["White"], restored.headers["Black"]), ("?", "Bob"))
                self.assertEqual(app.analysis.root.comment, "Introduction")
                self.assertTrue(app.analysis.flipped)
                self.assertEqual(app.query_one("#bottom-player").render().plain, "Black · Changed Black")
                self.assertEqual(app.think_time, 0.05)

        for flag in ("-f", "--follow"):
            self.session.write_bytes(before)
            with (self.subTest(flag=flag),
                  patch("sys.argv", ["chess-analyzer", flag, "--white", "White", "--black", "Changed Black",
                                     "--engine", self.engine_path, "-t", "0.05", "--threads", "1", "--hash", "16"]),
                  patch("chess_analyzer.online.fetch_text", side_effect=[json.dumps(RECORD), PGN]),
                  patch.object(ChessAnalysisApp, "run_async", run)):
                await asyncio.to_thread(main)


if __name__ == "__main__":
    unittest.main()
