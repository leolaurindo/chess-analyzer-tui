import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import chess

from chess_analyzer.game import Analysis
from chess_analyzer.library import analysis_path, list_analyses, load_analysis, save_analysis
from chess_analyzer.session import write_json


class LibraryTests(unittest.TestCase):
    def test_named_save_reopen_and_explicit_replace(self):
        analysis = Analysis.from_input(chess.Board())
        analysis.current.comment = "Saved"
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            first = save_analysis(analysis, "../Tal study", folder)
            self.assertEqual(first.path.parent, folder)
            self.assertEqual(list(folder.glob("*.json")), [first.path])
            self.assertEqual(load_analysis(first.path).current.comment, "Saved")
            previous = first.path.read_bytes()
            analysis.current.comment = "Edited"
            with self.assertRaises(FileExistsError):
                save_analysis(analysis, first.title, folder)
            self.assertEqual(first.path.read_bytes(), previous)
            save_analysis(analysis, first.title, folder, overwrite=True)
            self.assertEqual(load_analysis(first.path).current.comment, "Edited")

    def test_concurrent_name_creation_is_not_overwritten_without_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            path = analysis_path(folder, "Race")
            previous = b"Another process's saved data"

            def competing_save(path, data, **kwargs):
                path.write_bytes(previous)
                write_json(path, data, **kwargs)

            with patch("chess_analyzer.library.write_json", side_effect=competing_save):
                with self.assertRaises(FileExistsError):
                    save_analysis(Analysis.from_input(chess.Board()), "Race", folder)
            self.assertEqual(path.read_bytes(), previous)
            self.assertEqual(list(folder.iterdir()), [path])

    def test_empty_library_bad_files_and_invalid_names_do_not_lose_good_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "library"
            self.assertEqual(list_analyses(folder), ([], []))
            entry = save_analysis(Analysis.from_input(chess.Board()), "Good", folder)
            (folder / "broken.json").write_text("not json", encoding="utf-8")
            entries, warnings = list_analyses(folder)
            self.assertEqual([item.title for item in entries], ["Good"])
            self.assertIn("broken.json", warnings[0])
            data = json.loads(entry.path.read_text())
            data["analysis"]["current"] = -1
            entry.path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "invalid saved position"):
                load_analysis(entry.path)
            for name in ("", "\n", "x" * 121):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    save_analysis(Analysis.from_input(chess.Board()), name, folder)


if __name__ == "__main__":
    unittest.main()
