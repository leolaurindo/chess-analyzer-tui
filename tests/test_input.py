import json
import unittest
from unittest.mock import patch

import chess

from chess_analyzer.input import load_input
from chess_analyzer.online import fetch_text


LICHESS_PGN = '''[Event "rated bullet game"]
[Site "https://lichess.org/nrmBGiQF"]
[White "DrNykterstein"]
[Black "PseudoBenko"]
[Result "1-0"]
[WhiteTitle "GM"]
[BlackTitle "IM"]

1. c4 Nf6 2. g3 e6 1-0
'''

LICHESS_STUDY_PGN = '''[Event "Mikhail Tal - Andres Vooremaa"]
[White "Mikhail Tal"]
[Black "Andres Vooremaa"]
[Result "1-0"]

1. e4 c5 2. Nf3 e6 3. d4 cxd4 1-0
'''

CHESSCOM_PGN = '''[Event "Live Chess"]
[Date "2020.05.27"]
[White "LPSupi"]
[Black "MenuGarden"]
[Result "1-0"]
[Link "https://www.chess.com/game/live/4912555148"]

1. e4 d5 2. exd5 Qxd5 1-0
'''


class UrlInputTests(unittest.TestCase):
    def test_lichess_game_url_uses_public_pgn_export(self):
        with (patch("chess_analyzer.online._validate_url"),
              patch("chess_analyzer.online.fetch_text", return_value=LICHESS_PGN) as fetch):
            board, moves, white, black = load_input("https://lichess.org/nrmBGiQF")
        fetch.assert_called_once_with("https://lichess.org/game/export/nrmBGiQF")
        self.assertEqual((white, black), ("DrNykterstein", "PseudoBenko"))
        self.assertEqual([move.uci() for move in moves.mainline_moves()], ["c2c4", "g8f6", "g2g3", "e7e6"])
        self.assertEqual(board.fen(), chess.STARTING_FEN)

    def test_chesscom_url_alone_resolves_details_and_imports_exact_game(self):
        callback = json.dumps({"game": {"pgnHeaders": {
            "Date": "2020.05.27", "White": "LPSupi", "Black": "MenuGarden"}}})
        other_game = CHESSCOM_PGN.replace("4912555148", "49125551480")
        with (patch("chess_analyzer.online._validate_url"),
              patch("chess_analyzer.online.fetch_text", side_effect=[callback, other_game + "\n" + CHESSCOM_PGN]) as fetch):
            board, moves, white, black = load_input(
                "https://www.chess.com/game/live/4912555148"
            )
        self.assertEqual(fetch.call_args_list[0].args[0],
                         "https://www.chess.com/callback/live/game/4912555148")
        self.assertEqual(fetch.call_args_list[1].args[0],
                         "https://api.chess.com/pub/player/LPSupi/games/2020/05/pgn")
        self.assertEqual((white, black), ("LPSupi", "MenuGarden"))
        self.assertEqual(moves.headers["Link"], "https://www.chess.com/game/live/4912555148")
        self.assertEqual([move.uci() for move in moves.mainline_moves()],
                         ["e2e4", "d7d5", "e4d5", "d8d5"])
        self.assertEqual(board.fen(), chess.STARTING_FEN)

    def test_chesscom_url_tries_other_players_archive_when_first_has_no_match(self):
        callback = json.dumps({"game": {"pgnHeaders": {
            "Date": "2020.05.27", "White": "LPSupi", "Black": "MenuGarden"}}})
        with (patch("chess_analyzer.online._validate_url"),
              patch("chess_analyzer.online.fetch_text", side_effect=[callback, "", CHESSCOM_PGN]) as fetch):
            _, game, _, _ = load_input("https://www.chess.com/live/game/4912555148")
        self.assertEqual(game.headers["Link"], "https://www.chess.com/game/live/4912555148")
        self.assertEqual(fetch.call_args_list[-1].args[0],
                         "https://api.chess.com/pub/player/MenuGarden/games/2020/05/pgn")

    def test_chesscom_callback_failures_explain_username_browsing_fallback(self):
        for response in ({}, {"game": {"pgnHeaders": {"Date": "bad", "White": "Alice"}}},
                         {"game": {"pgnHeaders": {"Date": "2024.01.01"}}}):
            with (self.subTest(response=response), patch("chess_analyzer.online._validate_url"),
                  patch("chess_analyzer.online.fetch_text", return_value=json.dumps(response)) as fetch,
                  self.assertRaisesRegex(SystemExit, "Try --browse chess.com --user NAME")):
                load_input("https://www.chess.com/game/live/1")
            self.assertEqual(fetch.call_count, 1)  # No archive search without valid details.
        with (patch("chess_analyzer.online._validate_url"),
              patch("chess_analyzer.online.fetch_text", side_effect=ValueError("Rate limited")),
              self.assertRaisesRegex(SystemExit, "Rate limited.*Try --browse")):
            load_input("https://www.chess.com/game/live/1")

    def test_lichess_study_chapter_url_uses_pgn_export(self):
        url = "https://lichess.org/study/r072zv4F/R33cxdop"
        with (patch("chess_analyzer.online._validate_url"),
              patch("chess_analyzer.online.fetch_text", return_value=LICHESS_STUDY_PGN) as fetch):
            _, moves, white, black = load_input(url)
        fetch.assert_called_once_with(
            "https://lichess.org/study/r072zv4F/R33cxdop.pgn"
        )
        self.assertEqual((white, black), ("Mikhail Tal", "Andres Vooremaa"))
        self.assertEqual(len(list(moves.mainline_moves())), 6)

    def test_plain_text_pgn_url_is_loaded_directly(self):
        url = "https://example.org/games/latest.pgn"
        with (patch("chess_analyzer.online._validate_url"),
              patch("chess_analyzer.online.fetch_text", return_value=LICHESS_PGN) as fetch):
            _, moves, _, _ = load_input(url)
        fetch.assert_called_once_with(url)
        self.assertEqual(len(list(moves.mainline_moves())), 4)

    def test_non_https_url_is_rejected_before_network_access(self):
        with self.assertRaises(SystemExit) as error:
            load_input("http://example.org/game.pgn")
        self.assertIn("Only public HTTPS URLs", str(error.exception))

    def test_private_network_hosts_are_rejected(self):
        private_address = (2, 1, 6, "", ("10.0.0.1", 443))
        with (
            patch("chess_analyzer.online.socket.getaddrinfo", return_value=[private_address]),
            patch("chess_analyzer.online.build_opener") as opener,
            self.assertRaises(ValueError) as error,
        ):
            fetch_text("https://private.test/game.pgn")
        self.assertIn("public IP", str(error.exception))
        opener.assert_not_called()


if __name__ == "__main__":
    unittest.main()
