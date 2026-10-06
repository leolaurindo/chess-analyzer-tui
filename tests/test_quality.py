import unittest

import chess
import chess.engine

from chess_game import Candidate, Node, quality_label, winning_chances


class QualityTests(unittest.TestCase):
    def test_loss_bands_include_the_lower_boundary(self):
        cases = [(0, "Excellent"), (1.99, "Excellent"), (2, "Good"), (4.99, "Good"),
                 (5, "Inaccuracy"), (9.99, "Inaccuracy"), (10, "Mistake"),
                 (19.99, "Mistake"), (20, "Blunder"), (100, "Blunder")]
        for loss, expected in cases:
            with self.subTest(loss=loss):
                self.assertEqual(quality_label(loss), expected)

    def test_chances_handle_centipawns_extremes_and_mates(self):
        cases = [(chess.engine.Cp(0), 50), (chess.engine.Cp(200), 67.62),
                 (chess.engine.Cp(-200), 32.38), (chess.engine.Cp(10**9), 100),
                 (chess.engine.Cp(-10**9), 0), (chess.engine.Mate(3), 100),
                 (chess.engine.Mate(-3), 0), (chess.engine.Mate(0), 0),
                 (chess.engine.MateGiven, 100)]
        for score, expected in cases:
            with self.subTest(score=score):
                self.assertAlmostEqual(winning_chances(score), expected, places=2)

    def test_move_labels_use_the_mover_perspective_and_require_analyzed_scores(self):
        for color in (chess.WHITE, chess.BLACK):
            board = chess.Board()
            board.turn = color
            node = Node(board)
            moves = list(board.legal_moves)
            scores = [0, 0, -30, -75, -150, -300, 20]
            node.candidates = [Candidate(move, chess.engine.Cp(cp if color else -cp), "")
                               for move, cp in zip(moves, scores)]
            self.assertIsNone(node.quality(moves[0]))
            node.analyzed = True
            for move, expected in zip(moves, ("Best", "Excellent", "Good", "Inaccuracy",
                                             "Mistake", "Blunder", "Excellent")):
                with self.subTest(color=color, label=expected):
                    self.assertEqual(node.quality(move), expected)
            self.assertIsNone(node.quality(moves[-1]))
            # A large pawn loss in an already won position is not automatically a blunder.
            node.candidates = [Candidate(moves[0], chess.engine.Cp(1000 if color else -1000), ""),
                               Candidate(moves[1], chess.engine.Cp(700 if color else -700), "")]
            self.assertEqual(node.quality(moves[1]), "Good")
            node.candidates = [Candidate(moves[0], chess.engine.Mate(2 if color else -2), ""),
                               Candidate(moves[1], chess.engine.Cp(0), "")]
            self.assertEqual(node.quality(moves[1]), "Blunder")


if __name__ == "__main__":
    unittest.main()
