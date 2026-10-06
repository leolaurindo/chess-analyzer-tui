import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET

import chess
import chess.engine
from rich.style import Style
from textual.widgets import Checkbox, Input, TextArea

from chess_cli import find_stockfish
from chess_game import Analysis
from chess_input import parse_input
from chess_library import list_analyses, load_analysis
from chess_session import load_session, save_session
from chess_tui import ChessAnalysisApp


def screen_text(app):
    svg = ET.fromstring(app.export_screenshot())
    return "".join("".join(e.itertext()) for e in svg.iter("{http://www.w3.org/2000/svg}text"))


async def wait_for_analysis(app, pilot):
    async def ready():
        while not app.analysis.current.analyzed:
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
        board = chess.Board()
        for move in moves:
            board.push(move)
        app = ChessAnalysisApp(chess.Board(), self.engine, 30, 5,
                               game=chess.pgn.Game.from_board(board))
        async with app.run_test(size=(80, 24)) as pilot:
            for _ in range(12):
                await asyncio.wait_for(pilot.press("left", "right"), timeout=2)
            app.think_time = 0.05
            await asyncio.wait_for(pilot.press("left"), timeout=2)
            await wait_for_analysis(app, pilot)
            self.assertTrue(app.analysis.current.candidates)
            await asyncio.wait_for(pilot.press("right"), timeout=2)
            await wait_for_analysis(app, pilot)
            self.assertTrue(app.analysis.current.candidates)

    async def test_evaluation_bar_uses_terminal_game_result(self):
        white_mate = chess.Board("7k/6Q1/5K2/8/8/8/8/8 b - - 0 1")
        black_mate = chess.Board()
        for move in ("f3", "e5", "g4", "Qh4#"):
            black_mate.push_san(move)
        stalemate = chess.Board("7k/5K2/6Q1/8/8/8/8/8 b - - 0 1")
        cases = (
            (white_mate, {"#f0f0e8"}),
            (black_mate, {"#30343b"}),
            (stalemate, {"#f0f0e8", "#30343b"}),
        )

        for board, expected_colors in cases:
            with self.subTest(outcome=board.outcome()):
                app = ChessAnalysisApp(board, self.engine, 0.05, 3)
                async with app.run_test(size=(120, 42)) as pilot:
                    await pilot.pause()
                    bar = app.query_one("#evaluation-bar").render()
                    colors = [Style.parse(span.style).bgcolor.name for span in bar.spans]
                    self.assertTrue(colors)
                    self.assertEqual(set(colors), expected_colors)
                    if len(expected_colors) == 2:
                        self.assertLessEqual(abs(colors.count("#f0f0e8") -
                                                 colors.count("#30343b")), 1)

    async def test_edit_save_and_reopen_analysis_without_navigation_keys_leaking(self):
        board, game, white, black = parse_input('1. e4 {Imported} e5 *')
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "library"
            session = Path(directory) / "session.json"
            app = ChessAnalysisApp(board, self.engine, 0.05, 3, game=game,
                                   white_name=white, black_name=black,
                                   on_session_change=lambda state: save_session(state, session))
            with patch("chess_tui.library_path", return_value=folder):
                async with app.run_test() as pilot:
                    node = app.analysis.current
                    await pilot.press("c")
                    editor = app.screen.query_one(TextArea)
                    editor.load_text("My [literal] comment")
                    await pilot.press("left", "q")
                    self.assertIs(app.analysis.current, node)
                    editor.load_text("My [literal] comment")
                    await pilot.press("ctrl+s")
                    self.assertEqual(node.comment, "My [literal] comment")
                    self.assertEqual(load_session(session).current.comment, node.comment)
                    await pilot.press("c")
                    app.screen.query_one(TextArea).load_text("Canceled edit")
                    await pilot.press("escape")
                    self.assertEqual(node.comment, "My [literal] comment")
                    await pilot.press("s")
                    app.screen.query_one(Input).value = "Tal notes"
                    await pilot.click("#save")
                    entries, _ = list_analyses(folder)
                    self.assertEqual([entry.title for entry in entries], ["Tal notes"])
                    node.comment = "Replacement"
                    await pilot.press("s")
                    await pilot.click("#save")
                    self.assertIn("already exists", app.screen.query_one("#error").render().plain)
                    self.assertEqual(load_analysis(entries[0].path).current.comment, "My [literal] comment")
                    app.screen.query_one(Checkbox).value = True
                    await pilot.press("ctrl+s")
                    self.assertEqual(load_analysis(entries[0].path).current.comment, "Replacement")
                    app.replace_analysis(Analysis.from_input(chess.Board()))
                    self.assertEqual(app.analysis.current.comment, "")
                    await pilot.press("l")
                    await pilot.pause()
                    await pilot.press("enter")
                    self.assertEqual(app.analysis.current.comment, "Replacement")
                    self.assertEqual(load_session(session).current.comment, "Replacement")
                    await pilot.press("c")
                    app.screen.query_one(TextArea).load_text("")
                    await pilot.press("ctrl+s")
                    self.assertFalse(app.query_one("#comments").display)

    async def test_opening_label_tracks_navigation_and_imported_variations(self):
        board, game, _, _ = parse_input(
            "1. e4 c5 (1... e6) 2. Nf3 d6 3. d4 cxd4 4. Nxd4 Nf6 5. Nc3 a6 *"
        )
        app = ChessAnalysisApp(board, self.engine, 0.05, 3, game=game)
        async with app.run_test() as pilot:
            self.assertEqual(app.query_one("#opening").render().plain,
                             "B90 · Sicilian Defense: Najdorf Variation")
            app.action_game_position(1)
            choices = app.move_choices(app.analysis.current)
            app.action_follow_choice(choices.index(chess.Move.from_uci("e7e6")))
            self.assertEqual(app.query_one("#opening").render().plain, "C00 · French Defense")
            await pilot.press("escape", "enter")
            self.assertEqual(app.query_one("#opening").render().plain, "B20 · Sicilian Defense")
            app.action_game_position(0)
            self.assertFalse(app.query_one("#opening").display)

    async def test_pgn_navigation_and_exploration(self):
        board, moves, white_name, black_name = parse_input(
            '[White "Supi"]\n[Black "Carlsen"]\n\n1. e4 h5 *\n'
        )
        final = board.copy()
        for move in moves.mainline_moves():
            final.push(move)
        app = ChessAnalysisApp(board, self.engine, 0.05, 3, game=moves,
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
            self.assertEqual(app.analysis.current.board.fen(), final.fen())  # Stop at the PGN's end.
            app.think_time = 30
            await pilot.press("left")
            anchor = app.analysis.current.board.fen()
            self.assertIn("Original", str(app.query_one("#candidates").render()))
            await asyncio.wait_for(pilot.press("enter"), timeout=2)
            self.assertEqual(app.analysis.current.board.fen(), final.fen())
            app.think_time = 0.05
            await pilot.press("left")
            await wait_for_analysis(app, pilot)
            await pilot.press("down", "right")
            branch = app.analysis.current.board.fen()
            self.assertFalse(app.analysis.current.is_mainline)
            await wait_for_analysis(app, pilot)
            self.assertIn("1...", str(app.query_one("#position-info").render()))
            await pilot.press("right", "escape")
            self.assertEqual(app.analysis.current.board.fen(), anchor)
            await pilot.press("down", "right")
            self.assertEqual(app.analysis.current.board.fen(), branch)
            await pilot.click("#return-game")
            self.assertEqual(app.analysis.current.board.fen(), anchor)
            await pilot.press("enter")
            self.assertEqual(app.analysis.current.board.fen(), final.fen())
            await pilot.press("left")
            await pilot.pause()
            await pilot.click("#candidates", offset=(4, 2))
            self.assertFalse(app.analysis.current.is_mainline)
            await pilot.pause()
            await pilot.click("#history", offset=(2, 3))
            self.assertEqual(app.analysis.current.board.fen(), chess.STARTING_FEN)


if __name__ == "__main__":
    unittest.main()
