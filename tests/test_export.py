import io
import tempfile
import unittest
from pathlib import Path

import chess
import chess.pgn

from chess_analyzer.game import Analysis, Candidate
from chess_analyzer.input import parse_input
from chess_analyzer.library import load_analysis, save_analysis
from chess_analyzer.session import load_session, save_session


ANNOTATED_PGN = '''[Event "Study"]
[Site "https://example.org/study"]
[Date "2024.02.03"]
[Round "7"]
[White "Alice"]
[Black "Bob"]
[Result "1-0"]
[Annotator "Carol"]
[Variant "Standard"]

{Introduction} 1. e4 {King pawn} e5
({Sicilian introduction} 1... c5 {Sicilian} 2. Nf3 (2. Nc3 {Nested}) d6)
2. Nf3 {Main line} 1-0
'''


class ExportTests(unittest.TestCase):
    def test_full_tree_exports_comments_mainline_and_only_retained_moves(self):
        analysis = Analysis.from_input(*parse_input(ANNOTATED_PGN))
        anchor = analysis.root.mainline_next
        explored = anchor.child(chess.Move.from_uci("e7e6"))
        explored.comment = "Explored French"
        explored.child(chess.Move.from_uci("d2d4")).comment = "Center"
        analysis.current = explored
        analysis.return_position = anchor
        anchor.candidates = [Candidate(chess.Move.from_uci("d7d5"), "0.00", "1... d5")]
        explored.candidates = [Candidate(chess.Move.from_uci("b1c3"), "0.00", "2. Nc3")]

        exported = chess.pgn.read_game(io.StringIO(analysis.to_pgn()))
        self.assertEqual(exported.errors, [])
        self.assertEqual([move.uci() for move in exported.mainline_moves()],
                         ["e2e4", "e7e5", "g1f3"])
        self.assertEqual(exported.headers["Result"], "1-0")
        self.assertEqual(exported.comment, "Introduction")
        e4 = exported.variations[0]
        self.assertEqual(e4.comment, "King pawn")
        self.assertEqual([node.move.uci() for node in e4.variations],
                         ["e7e5", "c7c5", "e7e6"])
        self.assertEqual(e4.variations[0].variations[0].comment, "Main line")
        sicilian = e4.variations[1]
        self.assertEqual(sicilian.starting_comment, "Sicilian introduction")
        self.assertEqual(sicilian.comment, "Sicilian")
        self.assertEqual([node.move.uci() for node in sicilian.variations], ["g1f3", "b1c3"])
        self.assertEqual(sicilian.variations[1].comment, "Nested")
        french = e4.variations[2]
        self.assertEqual(french.comment, "Explored French")
        self.assertEqual([node.move.uci() for node in french.variations], ["d2d4"])
        self.assertEqual(french.variations[0].comment, "Center")
        self.assertIs(analysis.current, explored)
        self.assertIs(analysis.return_position, anchor)

    def test_headers_survive_session_and_named_save_before_export(self):
        board, original, white, black = parse_input(ANNOTATED_PGN)
        analysis = Analysis.from_input(board, original, white, black)
        analysis.white_name = "Override"
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            session = folder / "session.json"
            save_session(analysis, session)
            entry = save_analysis(analysis, "Study", folder / "library")
            for owner, restored in (("session", load_session(session)),
                                    ("library", load_analysis(entry.path))):
                with self.subTest(owner=owner):
                    self.assertEqual(restored.headers, dict(original.headers))
                    self.assertEqual(restored.white_name, "Override")
                    exported = chess.pgn.read_game(io.StringIO(restored.to_pgn()))
                    self.assertEqual(dict(exported.headers), dict(original.headers) | {"White": "Override"})
                    self.assertEqual(exported.comment, "Introduction")
                    self.assertEqual(exported.variations[0].variations[1].starting_comment,
                                     "Sicilian introduction")

    def test_nonstandard_start_round_trips_with_and_without_explored_moves(self):
        for fen, moves in (("4k3/8/8/8/8/8/4P3/4K3 w - - 0 17", ("e2e4", "e8d7")),
                           ("4k3/8/8/8/8/8/4P3/4K3 b - - 5 17", ("e8d7", "e2e4"))):
            for explore in (False, True):
                with self.subTest(fen=fen, explore=explore):
                    analysis = Analysis.from_input(chess.Board(fen))
                    if explore:
                        for uci in moves:
                            analysis.current = analysis.current.child(chess.Move.from_uci(uci))
                    board, game, _, _ = parse_input(analysis.to_pgn())
                    self.assertEqual(board.fen(), fen)
                    self.assertEqual(game.headers["SetUp"], "1")
                    self.assertEqual(game.headers["FEN"], fen)
                    self.assertEqual(game.errors, [])
                    self.assertEqual([move.uci() for move in game.mainline_moves()],
                                     list(moves) if explore else [])
                    self.assertEqual(game.end().board().fen(), analysis.current.board.fen())

    def test_initial_position_without_moves_exports_reopenable_pgn(self):
        analysis = Analysis.from_input(chess.Board())
        analysis.root.comment = "Before the first move"
        board, game, white, black = parse_input(analysis.to_pgn())
        self.assertEqual(board.fen(), chess.STARTING_FEN)
        self.assertEqual(game.variations, [])
        self.assertEqual(game.comment, "Before the first move")
        self.assertEqual((white, black), ("White", "Black"))

    def test_unoverridden_player_headers_are_not_replaced_by_display_fallbacks(self):
        analysis = Analysis.from_input(*parse_input('[White "?"]\n[Black " Bob "]\n\n1. e4 *'))
        game = chess.pgn.read_game(io.StringIO(analysis.to_pgn()))
        self.assertEqual(game.headers["White"], "?")
        self.assertEqual(game.headers["Black"], " Bob ")


if __name__ == "__main__":
    unittest.main()
