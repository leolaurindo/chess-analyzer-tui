import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import chess

from chess_game import Analysis
from chess_input import parse_input
from chess_library import list_analyses, load_analysis, save_analysis


class LibraryTests(unittest.TestCase):
    def test_save_reopen_and_explicit_replace_preserve_tree_not_engine_results(self):
        analysis = Analysis.from_input(*parse_input('1. e4 {Pawn} e5 (1... c5 {Sicilian}) *'))
        analysis.root.comment = "Introduction"
        analysis.return_position = analysis.root.mainline_next
        analysis.current = analysis.return_position.children[chess.Move.from_uci("c7c5")]
        explored = analysis.current.child(chess.Move.from_uci("b1c3"))
        explored.comment = "My line"
        explored.analyzed = True
        analysis.flipped = True
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            first = save_analysis(analysis, "../Tal study", folder)
            self.assertEqual(first.path.parent, folder)
            self.assertEqual(list(folder.glob("*.json")), [first.path])
            restored = load_analysis(first.path)
            self.assertEqual(restored.root.comment, "Introduction")
            self.assertEqual(restored.current.comment, "Sicilian")
            self.assertEqual(restored.current.children[chess.Move.from_uci("b1c3")].comment, "My line")
            self.assertFalse(restored.current.children[chess.Move.from_uci("b1c3")].analyzed)
            self.assertTrue(restored.flipped)
            previous = first.path.read_bytes()
            analysis.current.comment = "Edited"
            with self.assertRaises(FileExistsError):
                save_analysis(analysis, first.title, folder)
            self.assertEqual(first.path.read_bytes(), previous)
            with patch("chess_session.os.replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    save_analysis(analysis, first.title, folder, overwrite=True)
            self.assertEqual(first.path.read_bytes(), previous)
            save_analysis(analysis, first.title, folder, overwrite=True)
            self.assertEqual(load_analysis(first.path).current.comment, "Edited")
            self.assertEqual(load_analysis(first.path).root.comment, "Introduction")

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
