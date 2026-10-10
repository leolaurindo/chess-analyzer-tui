import unittest

import chess

from chess_analyzer.game import Analysis
from chess_analyzer.tui import captured_material, side_label


class CapturedMaterialTests(unittest.TestCase):
    def test_counts_captures_and_net_points_on_the_selected_line(self):
        board = chess.Board("r6k/8/8/8/8/8/8/R6K w - - 0 1")
        analysis = Analysis.from_input(board)
        node = analysis.root.child(chess.Move.from_uci("a1a8"))

        captured, material = captured_material(node)

        self.assertEqual(captured[chess.WHITE], {chess.ROOK: 1})
        self.assertEqual(captured[chess.BLACK], {})
        self.assertEqual(material[chess.WHITE] - material[chess.BLACK], 5)
        self.assertEqual(material[chess.BLACK] - material[chess.WHITE], -5)
        self.assertEqual(side_label("White", "Alice", sorted(captured[chess.WHITE].items()), 5),
                         "White · Alice   ♜ +5")
        self.assertEqual(side_label("White", "Alice", [(chess.PAWN, 3)], 3),
                         "White · Alice   ♟ ♟ ♟ +3")

    def test_counts_en_passant_as_a_pawn(self):
        board = chess.Board("7k/8/8/3pP3/8/8/8/7K w - d6 0 2")
        analysis = Analysis.from_input(board)
        node = analysis.root.child(chess.Move.from_uci("e5d6"))

        captured, material = captured_material(node)

        self.assertEqual(captured[chess.WHITE], {chess.PAWN: 1})
        self.assertEqual(material[chess.WHITE], 1)


if __name__ == "__main__":
    unittest.main()
