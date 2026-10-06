import asyncio
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import chess
import chess.engine

from chess_tui import ChessAnalysisApp, find_stockfish, parse_input


def screen_text(app):
    svg = ET.fromstring(app.export_screenshot())
    return "".join("".join(e.itertext()) for e in svg.iter("{http://www.w3.org/2000/svg}text"))


async def wait_for_analysis(app, pilot):
    async def ready():
        while not app.current.analyzed:
            await asyncio.sleep(0.01)
        await pilot.pause()

    await asyncio.wait_for(ready(), timeout=4)


class ChessTuiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        path = find_stockfish()
        if not path:
            self.skipTest("Stockfish is required for TUI integration tests")
        self.transport, self.engine = await chess.engine.popen_uci(path)
        await self.engine.configure({"Threads": 1, "Hash": 16})

    async def asyncTearDown(self):
        try:
            await asyncio.wait_for(self.engine.quit(), timeout=3)
        finally:
            self.transport.close()

    async def test_board_fits_and_large_pawns_stay_straight(self):
        app = ChessAnalysisApp(chess.Board(), self.engine, 0.05, 3)
        async with app.run_test(size=(80, 24)) as pilot:
            await wait_for_analysis(app, pilot)
            for width, height in [(80, 24), (42, 28), (160, 50), (144, 50)]:
                with self.subTest(size=(width, height)):
                    await pilot.resize_terminal(width, height)
                    await pilot.pause()
                    for selector in ("#board", "#analysis-side"):
                        region = app.query_one(selector).region
                        self.assertTrue(0 <= region.x < region.right <= width)
                        self.assertTrue(1 <= region.y < region.bottom <= height - 1)
                    visible = "".join(screen_text(app).split())
                    self.assertIn("abcdefgh", visible)
                    if width < 144:
                        self.assertIn("♜♞♝♛♚♝♞♜", visible)
                        self.assertIn("♖♘♗♕♔♗♘♖", visible)
                        continue
                    rows = app.query_one("#board").render().plain.splitlines()
                    heads = [row for row in rows if "▄▇▄" in row]
                    necks = [row for row in rows if "▜█▛" in row]
                    bases = [row for row in rows if "▄███▄" in row]
                    self.assertEqual((len(heads), len(necks), len(bases)), (2, 2, 2))
                    for head, neck, base in zip(heads, necks, bases):
                        centers = [i for i, char in enumerate(head) if char == "▇"]
                        self.assertEqual(len(centers), 8)
                        for center in centers:
                            self.assertEqual(neck[center], "█")
                            self.assertEqual(base[center - 2:center + 3], "▄███▄")

    async def test_ascii_and_flip_work_even_with_room_for_art(self):
        app = ChessAnalysisApp(chess.Board(), self.engine, 0.05, 3, ascii_pieces=True)
        async with app.run_test(size=(160, 50)) as pilot:
            await wait_for_analysis(app, pilot)
            await pilot.pause()
            visible = "".join(screen_text(app).split())
            self.assertIn("8rnbqkbnr", visible)
            self.assertIn("1RNBQKBNR", visible)
            self.assertNotIn("╋", visible)
            await pilot.press("f")
            visible = "".join(screen_text(app).split())
            self.assertIn("1RNBKQBNR", visible)
            self.assertIn("hgfedcba", visible)

    async def test_rapid_navigation_during_analysis_keeps_engine_usable(self):
        moves = [chess.Move.from_uci(move) for move in
                 ("e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "g8f6")]
        app = ChessAnalysisApp(chess.Board(), self.engine, 30, 5, moves=moves)
        async with app.run_test(size=(80, 24)) as pilot:
            for _ in range(12):
                await asyncio.wait_for(pilot.press("left", "right"), timeout=2)
            app.think_time = 0.05
            await asyncio.wait_for(pilot.press("left"), timeout=2)
            await wait_for_analysis(app, pilot)
            self.assertTrue(app.current.candidates)
            await asyncio.wait_for(pilot.press("right"), timeout=2)
            await wait_for_analysis(app, pilot)
            self.assertTrue(app.current.candidates)

    async def test_pgn_navigation_and_exploration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "game.pgn"
            path.write_text('[Event "Test"]\n[White "Supi"]\n[Black "Carlsen"]\n\n1. e4 h5 *\n', encoding="utf-8")
            board, moves, white_name, black_name = parse_input(path.read_text(encoding="utf-8"))
        final = board.copy()
        for move in moves:
            final.push(move)
        app = ChessAnalysisApp(board, self.engine, 0.05, 3, moves=moves,
                               white_name=white_name, black_name=black_name)
        async with app.run_test(size=(120, 42)) as pilot:
            await wait_for_analysis(app, pilot)
            self.assertEqual(app.query_one("#top-player").render().plain, "Black · Carlsen")
            self.assertEqual(app.query_one("#bottom-player").render().plain, "White · Supi")
            await pilot.press("f")
            self.assertEqual(app.query_one("#top-player").render().plain, "White · Supi")
            self.assertEqual(app.query_one("#bottom-player").render().plain, "Black · Carlsen")
            await pilot.press("f")
            await pilot.press("right", "enter")
            self.assertEqual(app.current.board.fen(), final.fen())  # Stop at the PGN's end.
            app.think_time = 30
            await pilot.press("left")
            anchor = app.current.board.fen()
            self.assertIn("Original", str(app.query_one("#candidates").render()))
            await asyncio.wait_for(pilot.press("enter"), timeout=2)
            self.assertEqual(app.current.board.fen(), final.fen())
            app.think_time = 0.05
            await pilot.press("left")
            await wait_for_analysis(app, pilot)
            await pilot.press("down", "right")
            branch = app.current.board.fen()
            self.assertFalse(app.current.is_mainline)
            await wait_for_analysis(app, pilot)
            self.assertIn("1...", str(app.query_one("#position-info").render()))
            await pilot.press("right", "escape")
            self.assertEqual(app.current.board.fen(), anchor)
            await pilot.press("down", "right")
            self.assertEqual(app.current.board.fen(), branch)
            await pilot.click("#return-game")
            self.assertEqual(app.current.board.fen(), anchor)
            await pilot.press("enter")
            self.assertEqual(app.current.board.fen(), final.fen())
            await pilot.press("left")
            await pilot.pause()
            await pilot.click("#candidates", offset=(4, 2))
            self.assertFalse(app.current.is_mainline)
            await pilot.pause()
            await pilot.click("#history", offset=(2, 3))
            self.assertEqual(app.current.board.fen(), chess.STARTING_FEN)


if __name__ == "__main__":
    unittest.main()
