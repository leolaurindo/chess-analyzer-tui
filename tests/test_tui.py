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

from chess_analyzer.cli import find_stockfish
from chess_analyzer.game import Analysis, Candidate
from chess_analyzer.input import parse_input
from chess_analyzer.library import list_analyses, load_analysis
from chess_analyzer.session import load_session, save_session
from chess_analyzer.tui import ChessAnalysisApp


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

    async def test_evaluation_bar_tracks_displayed_position_and_marks_unknown_scores(self):
        app = ChessAnalysisApp(chess.Board(), self.engine, 30, 3)
        app.analysis.root.candidates = [
            Candidate(chess.Move.from_uci("e2e4"), "+3.00", "1. e4"),
            Candidate(chess.Move.from_uci("d2d4"), "-3.00", "1. d4"),
        ]
        app.analysis.root.analyzed = True
        async with app.run_test(size=(120, 42)) as pilot:
            bar = app.query_one("#evaluation-bar")

            def colors():
                return [Style.parse(span.style).bgcolor.name for span in bar.render().spans]

            positive = colors()
            self.assertGreater(positive.count("#f0f0e8"), len(positive) / 2)
            await pilot.press("down")
            negative = colors()
            with self.subTest("candidate selection"):
                self.assertLess(negative.count("#f0f0e8"), len(negative) / 2)
            await pilot.press("right")
            self.assertEqual(app.analysis.current.candidates, [])
            self.assertFalse(app.analysis.current.analyzed)
            with self.subTest("pending analysis"):
                self.assertEqual(set(colors()), {"#59616d"})
            app.analysis.current.candidates = [
                Candidate(chess.Move.from_uci("d7d5"), "?", "1... d5")]
            app.refresh_board()
            self.assertEqual(set(colors()), {"#59616d"})
            app.analysis.current.candidates[0].score = "+0.00"
            app.refresh_board()
            even = colors()
            self.assertLessEqual(abs(even.count("#f0f0e8") - even.count("#30343b")), 1)
            app.analysis.current.candidates[0].score = "M3"
            app.refresh_board()
            self.assertEqual(set(colors()), {"#f0f0e8"})
            app.replace_analysis(Analysis.from_input(chess.Board("7k/5K2/6Q1/8/8/8/8/8 b - - 0 1")))
            drawn = colors()
            self.assertLessEqual(abs(drawn.count("#f0f0e8") - drawn.count("#30343b")), 1)

    async def test_original_move_best_label_and_current_position_bar(self):
        board, game, _, _ = parse_input("1. e4 *")
        app = ChessAnalysisApp(board, self.engine, 30, 1, game=game)
        node = app.analysis.root
        original = chess.Move.from_uci("e2e4")
        other = Candidate(chess.Move.from_uci("d2d4"), "-M2", "1. d4")
        node.candidates = [other]
        node.analyzed = True
        app.analysis.current = node
        async with app.run_test() as pilot:
            bar = app.query_one("#evaluation-bar")
            bar.white_share = 0.5
            bar.render()
            self.assertEqual(bar.white_share, 0)
            rows = app.query_one("#candidates").render().plain.splitlines()
            self.assertNotIn("BEST", next(row for row in rows if "Original" in row))
            self.assertIn("BEST", next(row for row in rows if "Engine" in row))

            node.candidates.insert(0, Candidate(original, "+1.00", "1. e4"))
            app.refresh_ui()
            await pilot.pause()
            rows = app.query_one("#candidates").render().plain.splitlines()
            original_row = next(row for row in rows if "Original" in row)
            self.assertIn("+1.00", original_row)
            self.assertIn("BEST", original_row)
            self.assertEqual(sum("BEST" in row for row in rows), 1)
            bar.render()
            self.assertGreater(bar.white_share, 0.5)

    async def test_original_move_outside_multipv_gets_score_and_continuation(self):
        board, game, _, _ = parse_input("1. e4 h5 *")
        app = ChessAnalysisApp(board, self.engine, 0.1, 1, game=game)
        app.analysis.current = app.analysis.root.mainline_next
        async with app.run_test() as pilot:
            await wait_for_analysis(app, pilot)
            node = app.analysis.current
            original = node.mainline_next.move_from_parent
            self.assertNotEqual(node.candidates[0].move, original)
            self.assertEqual(len(node.candidates), 2)
            candidate = next(c for c in node.candidates if c.move == original)
            self.assertNotEqual(candidate.score, "?")
            self.assertTrue(candidate.pv.startswith("1...h5"))
            rows = app.query_one("#candidates").render().plain.splitlines()
            original_row = next(row for row in rows if "Original" in row)
            self.assertIn(candidate.score, original_row)
            self.assertNotIn("BEST", original_row)
            self.assertIn(candidate.pv, app.query_one("#pv").render().plain)
            bar = app.query_one("#evaluation-bar")
            bar.render()
            self.assertGreater(bar.white_share, 0.5)

    async def test_navigation_cancels_original_move_search(self):
        board, game, _, _ = parse_input("1. e4 h5 *")
        app = ChessAnalysisApp(board, self.engine, 0.05, 1, game=game)
        app.analysis.current = app.analysis.root.mainline_next
        original_search_started = asyncio.Event()
        engine_analysis = self.engine.analysis

        async def slow_original_search(board, limit, **kwargs):
            if kwargs.get("root_moves") is not None:
                result = await engine_analysis(board, chess.engine.Limit(time=30), **kwargs)
                original_search_started.set()
                return result
            return await engine_analysis(board, limit, **kwargs)

        with patch.object(self.engine, "analysis", side_effect=slow_original_search):
            async with app.run_test() as pilot:
                await asyncio.wait_for(original_search_started.wait(), timeout=4)
                interrupted = app.analysis.current
                await asyncio.wait_for(pilot.press("right"), timeout=2)
                await wait_for_analysis(app, pilot)
                self.assertFalse(interrupted.analyzed)
                self.assertEqual(interrupted.candidates, [])
                self.assertIs(app.analysis.current, interrupted.mainline_next)
                self.assertTrue(app.analysis.current.candidates)

    async def test_move_17_game_scores_original_reply_and_mate_blunder(self):
        board, game, _, _ = parse_input(
            "1. e4 e5 2. Bc4 Nc6 3. Nf3 d6 4. Nc3 Bg4 5. h3 Bxf3 "
            "6. gxf3 Qg5 7. d4 Qg2 8. Rf1 Nxd4 9. Nd5 Nxf3+ "
            "10. Ke2 Nd4+ 11. Kd2 Qxe4 12. Nxc7+ Kd7 13. Nxa8 Nf3+ "
            "14. Kc3 d5 15. Bxd5 Bb4+ 16. Kb3 Nd4+ 17. Kxb4 Nxc2+ "
            "18. Kc5 Qb4# 0-1"
        )
        app = ChessAnalysisApp(board, self.engine, 0.5, 1, game=game)
        async with app.run_test() as pilot:
            for ply, san in ((32, "Kxb4"), (33, "Nxc2+"), (34, "Kc5")):
                app.action_game_position(ply)
                await wait_for_analysis(app, pilot)
                node = app.analysis.current
                original = node.mainline_next.move_from_parent
                candidate = next(c for c in node.candidates if c.move == original)
                self.assertEqual(node.board.san(original), san)
                self.assertNotEqual(candidate.score, "?")
                if san == "Kxb4":
                    self.assertEqual(node.candidates[0].move, original)
                    self.assertIn("BEST", next(
                        row for row in app.query_one("#candidates").render().plain.splitlines()
                        if "Original" in row))
                elif san == "Nxc2+":
                    self.assertNotEqual(node.candidates[0].move, original)
                    self.assertGreater(float(candidate.score), 0)
                else:
                    self.assertEqual(candidate.score, "-M1")
                    self.assertNotEqual(node.candidates[0].move, original)
                    bar = app.query_one("#evaluation-bar")
                    bar.render()
                    self.assertGreater(bar.white_share, 0.5)
                    # The original row shows the blunder's score, but the board/bar
                    # still show the position before White has played it.
                    self.assertEqual(app.displayed_position().board.fen(), node.board.fen())

    async def test_variation_preview_restores_original_without_committing(self):
        board, game, _, _ = parse_input("1. e4 h5 *")
        saves = []
        app = ChessAnalysisApp(board, self.engine, 30, 2, game=game,
                               on_session_change=lambda state: saves.append(state.current))
        node = app.analysis.root.mainline_next
        app.analysis.current = node
        e5, c5 = (chess.Move.from_uci(uci) for uci in ("e7e5", "c7c5"))
        node.candidates = [Candidate(e5, "+1.00", "1...e5"),
                           Candidate(c5, "-2.00", "1...c5")]
        node.analyzed = True
        async with app.run_test() as pilot:
            original_fen = node.board.fen()
            original_render = app.query_one("#board").render().plain
            children = dict(node.children)
            save_count = len(saves)
            for move in (e5, c5):
                await pilot.press("down")
                expected = node.board.copy()
                expected.push(move)
                self.assertIs(app.analysis.current, node)
                self.assertEqual(node.board.fen(), original_fen)
                self.assertEqual(app.displayed_position().board.fen(), expected.fen())
                self.assertEqual(app.query_one("#fen").render().plain, f"FEN  {expected.fen()}")
                self.assertIn("Preview", app.query_one("#position-info").render().plain)
                self.assertNotEqual(app.query_one("#board").render().plain, original_render)
                self.assertEqual(node.children, children)
                self.assertEqual(len(saves), save_count)
            bar = app.query_one("#evaluation-bar")
            bar.render()
            self.assertLess(bar.white_share, 0.5)
            app.action_export_analysis()
            self.assertEqual(app.screen.analysis.current.board.fen(),
                             app.displayed_position().board.fen())
            self.assertIs(app.screen.analysis.root, app.analysis.root)
            await pilot.press("escape")
            self.assertEqual(node.children, children)
            await pilot.press("down")  # Wrap back to Original.
            self.assertIsNone(app.preview_move())
            self.assertEqual(app.displayed_position().board.fen(), original_fen)
            self.assertEqual(app.query_one("#board").render().plain, original_render)
            bar.render()
            self.assertGreater(bar.white_share, 0.5)
            await pilot.press("down", "escape")
            self.assertIsNone(app.preview_move())
            self.assertIs(app.analysis.current, node)
            await pilot.press("down", "m")
            self.assertIsNone(app.preview_move())
            self.assertEqual(app.displayed_position().board.fen(), original_fen)
            await pilot.press("escape", "down")
            expected = app.displayed_position().board.fen()
            await pilot.press("enter")
            self.assertEqual(app.analysis.current.board.fen(), expected)
            self.assertIs(app.analysis.current.parent, node)
            self.assertIsNone(app.preview_move())
            self.assertIn(c5, node.children)
            await pilot.press("escape")
            self.assertIs(app.analysis.current, node)
            self.assertEqual(node.board.fen(), original_fen)

    async def test_preview_uses_terminal_result_without_a_candidate_score(self):
        board, game, _, _ = parse_input("1. f3 e5 2. g4 *")
        app = ChessAnalysisApp(board, self.engine, 30, 1, game=game)
        node = app.analysis.current
        mate = node.board.parse_san("Qh4#")
        node.candidates = [Candidate(mate, "?", "2...Qh4#")]
        node.analyzed = True
        async with app.run_test() as pilot:
            await pilot.press("down")  # Past End of original game.
            self.assertTrue(app.displayed_position().board.is_checkmate())
            self.assertIn("CHECKMATE", app.query_one("#position-info").render().plain)
            bar = app.query_one("#evaluation-bar")
            bar.render()
            self.assertEqual(bar.white_share, 0)
            self.assertFalse(node.board.is_checkmate())
            await pilot.press("up")
            self.assertEqual(app.displayed_position().board.fen(), node.board.fen())
            self.assertFalse(node.children)

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

    def assert_dialog_fits(self, app, selectors=("#save", "#cancel")):
        for selector in selectors:
            region = app.screen.query_one(selector).region
            self.assertTrue(0 <= region.x < region.right <= 40, selector)
            self.assertTrue(0 <= region.y < region.bottom <= 24, selector)

    async def test_edit_save_and_reopen_analysis_without_navigation_keys_leaking(self):
        board, game, white, black = parse_input('1. e4 {Imported} e5 *')
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "library"
            session = Path(directory) / "session.json"
            app = ChessAnalysisApp(board, self.engine, 0.05, 3, game=game,
                                   white_name=white, black_name=black,
                                   on_session_change=lambda state: save_session(state, session))
            with patch("chess_analyzer.tui.library_path", return_value=folder):
                async with app.run_test(size=(40, 24)) as pilot:
                    node = app.analysis.current
                    await pilot.press("c")
                    self.assert_dialog_fits(app)
                    editor = app.screen.query_one(TextArea)
                    editor.load_text("My [literal] comment")
                    await pilot.press("left", "q")
                    self.assertIs(app.analysis.current, node)
                    editor.load_text("My [literal] comment")
                    await pilot.press("ctrl+s")
                    self.assertEqual(node.comment, "My [literal] comment")
                    self.assertEqual(load_session(session).current.comment, node.comment)
                    for cancel in ("escape", "button"):
                        await pilot.press("c")
                        app.screen.query_one(TextArea).load_text("Canceled edit")
                        if cancel == "escape":
                            await pilot.press("escape")
                        else:
                            await pilot.click("#cancel")
                        self.assertEqual(node.comment, "My [literal] comment")
                    await pilot.press("s")
                    self.assert_dialog_fits(app)
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
                    self.assert_dialog_fits(app, ("#analyses",))
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

    async def test_original_move_label_reflects_engine_top_recommendation(self):
        board, game, _, _ = parse_input("1. e4 *")
        app = ChessAnalysisApp(board, self.engine, 0.05, 3, game=game)
        async with app.run_test(size=(120, 42)) as pilot:
            await wait_for_analysis(app, pilot)
            node = app.analysis.root
            app.analysis.current = node
            node.analyzed = True
            original = Candidate(chess.Move.from_uci("e2e4"), "+0.30", "1. e4")
            alternative = Candidate(chess.Move.from_uci("d2d4"), "+0.40", "1. d4")
            for candidates, annotation in [
                ([original, alternative], "  ← BEST"),
                ([alternative, original], ""),
                ([alternative], ""),
                ([], ""),
            ]:
                with self.subTest(annotation=annotation, candidates=candidates):
                    node.candidates = candidates
                    app.refresh_analysis_panel()
                    rows = app.query_one("#candidates").render().plain.splitlines()
                    score = "  +0.30" if original in candidates else ""
                    self.assertEqual(rows[1], f"▶ Original  e4{score}{annotation}")
                    self.assertEqual(sum("e4" in row for row in rows), 1)
                    self.assertEqual(sum("BEST" in row for row in rows),
                                     1 if candidates else 0)

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
            self.assertTrue(app.query_one("#top-player").render().plain.startswith("Black · Carlsen"))
            self.assertTrue(app.query_one("#bottom-player").render().plain.startswith("White · Supi"))
            await pilot.press("f")
            self.assertTrue(app.query_one("#top-player").render().plain.startswith("White · Supi"))
            self.assertTrue(app.query_one("#bottom-player").render().plain.startswith("Black · Carlsen"))
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
