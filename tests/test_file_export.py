import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import chess
import chess.engine
from textual.widgets import Button, Checkbox, Input, Select

from chess_analyzer.cli import find_stockfish
from chess_analyzer.dialogs import ExportDialog, HelpDialog
from chess_analyzer.input import parse_input
from chess_analyzer.session import analysis_to_data
from chess_analyzer.tui import ChessAnalysisApp


class FileExportDialogTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        engine = find_stockfish()
        if engine is None:
            self.skipTest("Stockfish required")
        self.transport, self.engine = await chess.engine.popen_uci(engine)
        await self.engine.configure({"Threads": 1, "Hash": 16})
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.directory = Path(folder.name) / "exports"
        location = patch("chess_analyzer.tui.export_directory", return_value=self.directory)
        location.start()
        self.addCleanup(location.stop)

    async def asyncTearDown(self):
        try:
            await asyncio.wait_for(self.engine.quit(), 3)
        finally:
            self.transport.close()

    def app(self):
        board, game, white, black = parse_input('1. e4 {Note} e5 (1... c5 {Variation}) *')
        return ChessAnalysisApp(board, self.engine, 0.05, 3, game=game,
                                white_name=white, black_name=black)

    async def test_fen_export_shows_destination_waits_for_confirmation_and_saved_path_acknowledgement(self):
        app = self.app()
        async with app.run_test(size=(40, 24)) as pilot:
            before = analysis_to_data(app.analysis)
            await pilot.press("ctrl+f", "ctrl+p")
            self.assertEqual(len(app.screen_stack), 1)
            self.assertFalse(self.directory.exists())
            await pilot.press("e")
            dialog = app.screen
            self.assertIsInstance(dialog, ExportDialog)
            self.assertEqual(dialog.query_one("#export-path", Input).value,
                             str(self.directory / "analysis.pgn"))
            self.assertIn(str(self.directory), dialog.query_one("#export-folder").render().plain)
            self.assertFalse(self.directory.exists())
            dialog.query_one(Select).value = "fen"
            await pilot.pause()
            self.assertEqual(dialog.query_one(Input).value, str(self.directory / "analysis.fen"))
            dialog.query_one(Input).value = "my-position.fen"
            await pilot.pause()
            destination = self.directory / "my-position.fen"
            self.assertIn(str(destination), dialog.query_one("#export-status").render().plain)
            await pilot.press("pageup", "pagedown")
            self.assertEqual(analysis_to_data(app.analysis), before)
            for selector in ("#export", "#cancel"):
                region = dialog.query_one(selector).region
                self.assertTrue(0 <= region.x < region.right <= 40)
                self.assertTrue(0 <= region.y < region.bottom <= 24)
            await pilot.click("#export")
            self.assertEqual(destination.read_text(encoding="utf-8").strip(),
                             "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2")
            self.assertIs(app.screen, dialog)
            self.assertIn(str(destination), dialog.query_one("#export-status").render().plain)
            self.assertEqual(str(dialog.query_one("#export", Button).label), "Done")
            await pilot.pause(0.3)  # Let the button's click debounce expire before acknowledgement.
            await pilot.press("enter")
            self.assertEqual(len(app.screen_stack), 1)
            self.assertEqual(analysis_to_data(app.analysis), before)

    async def test_overwrite_permission_errors_and_pgn_round_trip_do_not_change_analysis(self):
        app = self.app()
        async with app.run_test(size=(40, 24)) as pilot:
            before = analysis_to_data(app.analysis)
            await pilot.press("e")
            dialog = app.screen
            dialog.query_one(Input).value = ""
            await pilot.click("#export")
            self.assertIn("Enter a file name", dialog.query_one("#export-status").render().plain)
            self.assertFalse(self.directory.exists())
            await pilot.pause(0.3)
            path = self.directory / "notes.pgn"
            path.parent.mkdir()
            path.write_bytes(b"Do not replace without permission")
            dialog.query_one(Input).value = str(path)
            await pilot.click("#export")
            self.assertIn("File exists", dialog.query_one("#export-status").render().plain)
            self.assertEqual(path.read_bytes(), b"Do not replace without permission")
            await pilot.pause(0.3)
            dialog.query_one(Checkbox).value = True
            with patch("chess_analyzer.export.os.replace", side_effect=OSError("disk failure")):
                await pilot.click("#export")
            self.assertIn("disk failure", dialog.query_one("#export-status").render().plain)
            self.assertEqual(path.read_bytes(), b"Do not replace without permission")
            self.assertEqual(list(self.directory.iterdir()), [path])
            await pilot.pause(0.3)
            await pilot.click("#export")
            _, exported, _, _ = parse_input(path.read_text(encoding="utf-8"))
            self.assertEqual(exported.variations[0].comment, "Note")
            self.assertEqual(exported.variations[0].variations[1].comment, "Variation")
            self.assertIs(app.screen, dialog)
            await pilot.press("escape")
            self.assertEqual(analysis_to_data(app.analysis), before)

    async def test_help_and_cancel_keep_path_draft_without_writing_and_home_cancels_safely(self):
        app = self.app()
        async with app.run_test(size=(40, 24)) as pilot:
            game = app.analysis
            before = analysis_to_data(game)
            for cancel in ("escape", "f2"):
                await pilot.press("e")
                dialog = app.screen
                dialog.query_one(Input).value = "custom.pgn"
                await pilot.press("f1")
                self.assertIsInstance(app.screen, HelpDialog)
                self.assertEqual(app.screen.title, "Export help")
                await pilot.press("escape")
                self.assertIs(app.screen, dialog)
                self.assertEqual(dialog.query_one(Input).value, "custom.pgn")
                await pilot.press(cancel)
                self.assertFalse(self.directory.exists())
                self.assertEqual(len(app.screen_stack), 1)
                if cancel == "f2":
                    await pilot.press("g")
                self.assertIs(app.analysis, game)
                self.assertEqual(analysis_to_data(game), before)


if __name__ == "__main__":
    unittest.main()
