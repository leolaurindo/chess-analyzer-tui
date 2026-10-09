import asyncio
import io
import tempfile
import unittest
from pathlib import Path

import chess
import chess.engine
from rich.console import Console
from textual.widgets import Input

from chess_analyzer.cli import find_stockfish
from chess_analyzer.input import parse_input
from chess_analyzer.dialogs import HelpDialog
from chess_analyzer.game import Analysis, Candidate
from chess_analyzer.library import load_analysis, save_analysis
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

    async def wait_for_analysis(self, app, pilot):
        async def ready():
            while not app.analysis.current.analyzed:
                await asyncio.sleep(0.01)
            await pilot.pause()
        await asyncio.wait_for(ready(), timeout=4)

    async def test_notation_modes_keep_engine_running_and_escape_returns_in_two_steps(self):
        board, game, _, _ = parse_input("1. e4 e5 *")
        app = ChessAnalysisApp(board, self.engine, 0.05, 3, game=game)
        app.analysis.root.analyzed = True
        app.analysis.root.candidates = [Candidate(chess.Move.from_uci("e2e4"), "0.00", "1. e4")]
        async with app.run_test(size=(100, 34)) as pilot:
            app.action_game_position(0)
            anchor = app.analysis.current
            await pilot.press("m", "h", "4", "enter")
            branch = app.analysis.current
            self.assertEqual(branch.board.peek().uci(), "h2h4")
            self.assertIsNone(app.move_entry)
            self.assertIs(app.analysis.return_position, anchor)
            await self.wait_for_analysis(app, pilot)
            self.assertTrue(branch.candidates)
            await pilot.press("M", "e", "7", "e", "5", "enter")
            self.assertTrue(app.move_entry.persistent)
            self.assertEqual(app.analysis.current.board.peek().uci(), "e7e5")
            await self.wait_for_analysis(app, pilot)
            self.assertTrue(app.analysis.current.candidates)
            await pilot.press("N", "f", "3", "enter")
            position = app.analysis.current
            self.assertEqual(position.board.peek().uci(), "g1f3")
            self.assertTrue(app.move_entry.persistent)
            self.assertIs(app.analysis.return_position, anchor)
            await pilot.press("escape")
            self.assertIsNone(app.move_entry)
            self.assertIs(app.analysis.current, position)
            await pilot.press("escape")
            self.assertIs(app.analysis.current, anchor)
            self.assertIs(anchor.children[chess.Move.from_uci("h2h4")], branch)
            self.assertEqual([move.uci() for move in game.mainline_moves()], ["e2e4", "e7e5"])

    async def test_bad_notation_preserves_single_move_mode_and_tree(self):
        app = ChessAnalysisApp(chess.Board(), self.engine, 0.05, 3)
        async with app.run_test() as pilot:
            root = app.analysis.root
            await pilot.press("m")
            notation = app.query_one("#move-notation", Input)
            for text in ("e5", "--", "N", "junk"):
                with self.subTest(text=text):
                    notation.value = text
                    await pilot.pause()
                    await pilot.press("enter")
                    self.assertIs(app.analysis.current, root)
                    self.assertEqual(root.children, {})
                    self.assertIsNotNone(app.move_entry)
                    self.assertIn("legal", app.query_one("#move-entry-hint").render().plain)
            notation.value = "e2e4"
            await pilot.press("enter")
            self.assertEqual(app.analysis.current.board.peek().uci(), "e2e4")
            self.assertIsNone(app.move_entry)

    async def test_arrows_and_both_selection_keys_follow_legal_moves(self):
        app = ChessAnalysisApp(chess.Board(), self.engine, 0.05, 3)
        async with app.run_test() as pilot:
            await pilot.press("M", "up")
            await pilot.click("#candidates", offset=(4, 0))
            await pilot.press("space")
            self.assertEqual(app.move_entry.source, chess.E2)
            board_text = app.query_one("#board").render()
            rows = board_text.plain.splitlines(keepends=True)

            def square_content(file, rank):
                row_index = next(index for index, row in enumerate(rows) if row.startswith(f"{rank}  "))
                offset = sum(len(row) for row in rows[:row_index]) + rows[-1].index(file)
                return board_text.plain[offset]

            self.assertEqual(square_content("e", 3), "●")
            self.assertEqual(square_content("e", 4), "●")
            self.assertNotEqual(square_content("d", 3), "●")
            self.assertNotEqual(square_content("e", 5), "●")
            await pilot.press("up", "up", "enter")
            self.assertEqual(app.analysis.current.board.peek().uci(), "e2e4")
            self.assertIsNotNone(app.move_entry)
            await pilot.press("down", "enter", "down", "down", "space")
            self.assertEqual(app.analysis.current.board.peek().uci(), "e7e5")
            self.assertIsNotNone(app.move_entry)

    async def test_legal_circles_preserve_capture_art_and_square_backgrounds(self):
        app = ChessAnalysisApp(chess.Board("7k/8/8/2p5/3P4/8/8/7K w - - 0 1"), self.engine, 0.05, 3)
        async with app.run_test() as pilot:
            await pilot.press("M")
            for size in ((40, 24), (160, 50)):
                with self.subTest(size=size):
                    await pilot.resize_terminal(*size)
                    app.move_entry.source = None
                    unmarked = app.query_one("#board").render()
                    app.move_entry.source = chess.D4
                    marked = app.query_one("#board").render()
                    self.assertEqual(marked.plain.count("●"), 1)
                    self.assertEqual(marked.plain.count("○"), 1)
                    self.assertEqual(marked.plain.replace("●", " ").replace("○", " "), unmarked.plain)
                    for marker in ("●", "○"):
                        offset = marked.plain.index(marker)
                        marker_style = marked.get_style_at_offset(Console(), offset)
                        original_style = unmarked.get_style_at_offset(Console(), offset)
                        self.assertEqual(marker_style.bgcolor, original_style.bgcolor)
                        self.assertNotEqual(marker_style.color, original_style.color)
                    self.assertFalse(any(marked.get_style_at_offset(Console(), span.start).underline
                                         for span in marked.spans))

    async def test_entry_uses_colors_without_last_move_or_check_stripes(self):
        app = ChessAnalysisApp(chess.Board(), self.engine, 0.05, 3)
        async with app.run_test() as pilot:
            await pilot.press("M", "e", "4", "enter")
            last_move = app.query_one("#board").render()
            self.assertTrue(any(last_move.get_style_at_offset(Console(), span.start).bgcolor.name == "#898e3c"
                                for span in last_move.spans))
            self.assertFalse(any(last_move.get_style_at_offset(Console(), span.start).underline
                                 for span in last_move.spans))
            app.replace_analysis(Analysis.from_input(chess.Board("4r2k/8/8/8/8/8/8/4K3 w - - 0 1")))
            await pilot.press("M")
            checked = app.query_one("#board").render()
            self.assertTrue(any(checked.get_style_at_offset(Console(), span.start).bgcolor.name == "#ad4b4b"
                                for span in checked.spans))
            self.assertFalse(any(checked.get_style_at_offset(Console(), span.start).underline
                                 for span in checked.spans))

    async def test_source_reselection_invalid_destination_and_flipped_cursor(self):
        app = ChessAnalysisApp(chess.Board(), self.engine, 0.05, 3)
        async with app.run_test() as pilot:
            await pilot.press("f", "m", "down", "space")
            self.assertEqual(app.move_entry.source, chess.E2)
            await pilot.press("left", "space")
            self.assertEqual(app.move_entry.source, chess.F2)
            await pilot.press("left", "space", "space")
            self.assertIsNone(app.move_entry.source)
            await pilot.press("right", "space", "down", "left", "enter")
            self.assertIs(app.analysis.current, app.analysis.root)
            self.assertIn("Not a legal", app.move_entry.error)
            await pilot.press("backspace")
            self.assertIsNone(app.move_entry.source)
            await pilot.press("escape")
            self.assertIsNone(app.move_entry)
            self.assertEqual(app.analysis.root.children, {})

    async def test_board_promotion_supports_underpromotion(self):
        app = ChessAnalysisApp(chess.Board("7k/P7/8/8/8/8/8/7K w - - 0 1"), self.engine, 0.05, 3)
        async with app.run_test() as pilot:
            await pilot.press("m", *(["left"] * 7), *(["up"] * 6), "space", "up", "enter")
            self.assertEqual(len(app.move_entry.promotions), 4)
            self.assertIs(app.analysis.current, app.analysis.root)
            await pilot.press("n", "enter")
            self.assertEqual(app.analysis.current.board.piece_at(chess.A8), chess.Piece(chess.KNIGHT, chess.WHITE))
            self.assertEqual(app.analysis.current.board.peek().uci(), "a7a8n")
            self.assertIsNone(app.move_entry)

    async def test_special_notation_moves_and_king_safety(self):
        cases = (
            ("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", "O-O", "e1g1"),
            ("7k/8/8/3pP3/8/8/8/7K w - d6 0 1", "exd6", "e5d6"),
            ("7k/P7/8/8/8/8/8/7K w - - 0 1", "a8=N", "a7a8n"),
            ("4r2k/8/8/8/8/8/4R3/4K3 w - - 0 1", "Rd2", None),
            ("7k/8/8/8/8/8/8/1N1N3K w - - 0 1", "Nc3", None),
            ("7k/P7/8/8/8/8/8/7K w - - 0 1", "a8", None),
        )
        for fen, text, expected in cases:
            with self.subTest(text=text):
                app = ChessAnalysisApp(chess.Board(fen), self.engine, 0.05, 3)
                async with app.run_test() as pilot:
                    await pilot.press("m", *text, "enter")
                    if expected:
                        self.assertEqual(app.analysis.current.board.peek().uci(), expected)
                        self.assertIsNone(app.move_entry)
                        if expected == "e1g1":
                            self.assertEqual(app.analysis.current.board.piece_at(chess.F1),
                                             chess.Piece(chess.ROOK, chess.WHITE))
                        elif expected == "e5d6":
                            self.assertIsNone(app.analysis.current.board.piece_at(chess.D5))
                    else:
                        self.assertIs(app.analysis.current, app.analysis.root)
                        self.assertEqual(app.analysis.root.children, {})
                        self.assertIsNotNone(app.move_entry)

    async def test_board_castling_en_passant_and_default_queen_promotion(self):
        cases = (
            ("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1",
             ("space", "right", "right", "enter"), "e1g1"),
            ("7k/8/8/3pP3/8/8/8/7K w - d6 0 1",
             (*(["left"] * 3), *(["up"] * 4), "enter", "up", "left", "space"), "e5d6"),
            ("7k/P7/8/8/8/8/8/7K w - - 0 1",
             (*(["left"] * 7), *(["up"] * 6), "space", "up", "enter", "enter"), "a7a8q"),
        )
        for fen, keys, expected in cases:
            with self.subTest(move=expected):
                app = ChessAnalysisApp(chess.Board(fen), self.engine, 0.05, 3)
                async with app.run_test() as pilot:
                    await pilot.press("m", *keys)
                    self.assertEqual(app.analysis.current.board.peek().uci(), expected)
                    self.assertIsNone(app.move_entry)

    async def test_help_preserves_draft_home_and_game_replacement_clear_entry(self):
        board, game, _, _ = parse_input("1. e4 e5 *")
        app = ChessAnalysisApp(board, self.engine, 0.05, 3, game=game)
        async with app.run_test() as pilot:
            anchor = app.analysis.current
            await pilot.press("M", "N", "f", "f1")
            self.assertIsInstance(app.screen, HelpDialog)
            await pilot.press("escape")
            self.assertTrue(app.move_entry.persistent)
            self.assertEqual(app.query_one("#move-notation", Input).value, "Nf")
            await pilot.press("f1", "question_mark", "3", "enter")
            branch = app.analysis.current
            self.assertEqual(branch.board.peek().uci(), "g1f3")
            await pilot.press("f2")
            self.assertIsNone(app.move_entry)
            self.assertIs(app.analysis, app.home_analysis)
            await pilot.press("g")
            self.assertIs(app.analysis.current, branch)
            self.assertIs(app.analysis.return_position, anchor)
            await pilot.press("M", "e")
            app.replace_analysis(Analysis.from_input(chess.Board()))
            self.assertIsNone(app.move_entry)
            self.assertEqual(app.query_one("#move-notation", Input).value, "")
            self.assertEqual(app.analysis.current.board.fen(), chess.STARTING_FEN)

    async def test_entry_blocks_game_jumps_and_dialog_shortcuts_but_suggestions_are_clickable(self):
        app = ChessAnalysisApp(chess.Board(), self.engine, 0.05, 3)
        async with app.run_test(size=(120, 42)) as pilot:
            await self.wait_for_analysis(app, pilot)
            move = app.analysis.root.candidates[0].move
            await pilot.press("M", "pageup", "pagedown", "ctrl+s", "ctrl+l")
            self.assertIs(app.analysis.current, app.analysis.root)
            self.assertTrue(app.move_entry.persistent)
            # Existing candidate rows stay actionable, even with a notation draft.
            await pilot.press("h")
            await pilot.click("#history")
            await pilot.press("tab", "4")
            self.assertEqual(app.query_one("#move-notation", Input).value, "h4")
            self.assertEqual(app.analysis.root.children, {})
            await pilot.click("#candidates", offset=(4, 1))
            self.assertEqual(app.analysis.current.board.peek(), move)
            self.assertTrue(app.move_entry.persistent)
            self.assertEqual(app.query_one("#move-notation", Input).value, "")
            await self.wait_for_analysis(app, pilot)
            self.assertTrue(app.analysis.current.candidates)

    async def test_entry_fits_small_terminal_and_text_does_not_move_board_cursor(self):
        app = ChessAnalysisApp(chess.Board(), self.engine, 0.05, 3)
        async with app.run_test(size=(40, 24)) as pilot:
            await pilot.press("M", "h", "4", "left", "space")
            self.assertEqual(app.query_one("#move-notation", Input).value, "h4")
            self.assertEqual(app.move_entry.cursor, chess.E1)
            self.assertIsNone(app.move_entry.source)
            for selector in ("#board", "#move-entry-panel", "#move-notation"):
                region = app.query_one(selector).region
                self.assertTrue(0 <= region.x < region.right <= 40, selector)
                self.assertTrue(1 <= region.y < region.bottom <= 23, selector)
            await pilot.press("backspace", "backspace", "up", "space")
            self.assertEqual(app.move_entry.source, chess.E2)
            await pilot.press("escape")
            self.assertEqual(app.analysis.root.children, {})

    async def test_entered_endpoint_branch_round_trips_through_library_session_and_pgn(self):
        board, game, _, _ = parse_input('[White "Alice"]\n\n1. e4 e5 *')
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            session = folder / "session.json"
            app = ChessAnalysisApp(board, self.engine, 0.05, 3, game=game,
                                   on_session_change=lambda state: save_session(state, session))
            async with app.run_test() as pilot:
                anchor = app.analysis.current
                await pilot.press("M", "B", "c", "4", "enter", "N", "f", "6", "enter")
                fen = app.analysis.current.board.fen()
                saved = save_analysis(app.analysis, "User branch", folder / "library")
                for restored in (load_session(session), load_analysis(saved.path)):
                    self.assertEqual(restored.current.board.fen(), fen)
                    self.assertEqual(restored.return_position.board.fen(), anchor.board.fen())
                    exported = chess.pgn.read_game(io.StringIO(restored.to_pgn()))
                    self.assertEqual([move.uci() for move in exported.mainline_moves()],
                                     ["e2e4", "e7e5", "f1c4", "g8f6"])
                    # Reimporting PGN promotes an endpoint extension to its mainline;
                    # saved analysis still keeps the original game endpoint distinct.
                    self.assertIsNone(restored.return_position.mainline_next)
                await pilot.press("escape", "escape")
                self.assertIs(app.analysis.current, anchor)
                self.assertIsNone(anchor.mainline_next)
                await pilot.press("down", "enter")
                self.assertEqual(app.analysis.current.board.peek().uci(), "f1c4")

    async def test_rapid_manual_moves_interrupt_analysis_without_leaving_persistent_mode(self):
        app = ChessAnalysisApp(chess.Board(), self.engine, 30, 3)
        async with app.run_test() as pilot:
            await pilot.press("M")
            for text in ("e4", "e5", "Nf3", "Nc6"):
                await asyncio.wait_for(pilot.press(*text, "enter"), timeout=3)
                self.assertTrue(app.move_entry.persistent)
            app.think_time = 0.05
            await pilot.press("B", "b", "5", "enter")
            await self.wait_for_analysis(app, pilot)
            self.assertEqual(app.analysis.current.board.peek().uci(), "f1b5")
            self.assertTrue(app.analysis.current.candidates)
            self.assertTrue(app.move_entry.persistent)

    async def test_fen_boundaries_keep_entered_tree_and_terminal_position_refuses_entry(self):
        app = ChessAnalysisApp(chess.Board(), self.engine, 0.05, 3)
        async with app.run_test() as pilot:
            await pilot.press("m", "e", "4", "enter", "pagedown")
            self.assertIs(app.analysis.current, app.analysis.root)
            self.assertIsNone(app.analysis.return_position)
            self.assertIn(chess.Move.from_uci("e2e4"), app.analysis.root.children)
            app.replace_analysis(Analysis.from_input(chess.Board("7k/6Q1/5K2/8/8/8/8/8 b - - 0 1")))
            await pilot.press("M")
            self.assertIsNone(app.move_entry)
            self.assertEqual(app.analysis.root.children, {})

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
                exported = chess.pgn.read_game(io.StringIO(restored.to_pgn()))
                self.assertEqual([move.uci() for move in exported.mainline_moves()], ["e2e4", "e7e5"])
                self.assertEqual(exported.variations[0].variations[1].move.uci(), "c7c5")
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
