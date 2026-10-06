import unittest

import chess

from chess_analyzer.openings import opening_label


class OpeningTests(unittest.TestCase):
    def test_names_variations_and_transpositions_ignore_move_counters(self):
        for moves in ("e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6",
                      "Nf3 c5 e4 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6"):
            with self.subTest(moves=moves):
                board = chess.Board()
                for move in moves.split():
                    board.push_san(move)
                self.assertEqual(opening_label(board),
                                 "B90 · Sicilian Defense: Najdorf Variation")
                # No history is needed when the FEN itself is a named position.
                fen = board.fen().rsplit(" ", 2)[0] + " 99 80"
                self.assertEqual(opening_label(chess.Board(fen)),
                                 "B90 · Sicilian Defense: Najdorf Variation")

    def test_latest_known_position_follows_only_this_line_without_mutating_board(self):
        board = chess.Board()
        for move in "e4 c5 Ba6".split():
            board.push_san(move)
        before = (board.fen(), list(board.move_stack))
        self.assertEqual(opening_label(board), "B20 · Sicilian Defense")
        self.assertEqual((board.fen(), board.move_stack), before)
        self.assertIsNone(opening_label(chess.Board(board.fen())))
        board.pop()
        board.pop()
        board.push_san("e6")
        self.assertEqual(opening_label(board), "C00 · French Defense")
        self.assertIsNone(opening_label(chess.Board()))


if __name__ == "__main__":
    unittest.main()
