import json
import unittest
from unittest.mock import patch

import chess_input
import chess_online


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
        with (patch("chess_online._validate_url"),
              patch("chess_online.fetch_text", return_value=LICHESS_PGN) as fetch):
            board, moves, white, black = chess_input.load_input("https://lichess.org/nrmBGiQF")
        fetch.assert_called_once_with("https://lichess.org/game/export/nrmBGiQF")
        self.assertEqual((white, black), ("DrNykterstein", "PseudoBenko"))
        self.assertEqual([move.uci() for move in moves.mainline_moves()], ["c2c4", "g8f6", "g2g3", "e7e6"])
        self.assertEqual(board.fen(), chess_input.chess.STARTING_FEN)

    def test_chesscom_url_looks_up_exact_game_in_specified_public_archive(self):
        data = {"games": [{"rules": "chess", "url": "https://www.chess.com/game/live/4912555148",
                           "end_time": 1590550000, "white": {"username": "LPSupi"},
                           "black": {"username": "MenuGarden"}, "pgn": CHESSCOM_PGN}]}
        with (patch("chess_online._validate_url"),
              patch("chess_online.fetch_text", return_value=json.dumps(data)) as fetch):
            board, moves, white, black = chess_input.load_input(
                "https://www.chess.com/game/live/4912555148",
                chesscom_user="LPSupi", chesscom_month="2020-05",
            )
        self.assertEqual(fetch.call_args.args[0],
                         "https://api.chess.com/pub/player/LPSupi/games/2020/05")
        self.assertEqual((white, black), ("LPSupi", "MenuGarden"))
        self.assertEqual([move.uci() for move in moves.mainline_moves()],
                         ["e2e4", "d7d5", "e4d5", "d8d5"])
        self.assertEqual(board.fen(), chess_input.chess.STARTING_FEN)

    def test_chesscom_url_without_context_explains_browser_without_fetching_game(self):
        with (patch("chess_online._validate_url"),
              patch("chess_online.fetch_text") as fetch,
              self.assertRaisesRegex(SystemExit, "--chesscom-user")):
            chess_input.load_input("https://www.chess.com/game/live/4912555148")
        fetch.assert_not_called()

    def test_lichess_study_chapter_url_uses_pgn_export(self):
        url = "https://lichess.org/study/r072zv4F/R33cxdop"
        with (patch("chess_online._validate_url"),
              patch("chess_online.fetch_text", return_value=LICHESS_STUDY_PGN) as fetch):
            _, moves, white, black = chess_input.load_input(url)
        fetch.assert_called_once_with(
            "https://lichess.org/study/r072zv4F/R33cxdop.pgn"
        )
        self.assertEqual((white, black), ("Mikhail Tal", "Andres Vooremaa"))
        self.assertEqual(len(list(moves.mainline_moves())), 6)

    def test_plain_text_pgn_url_is_loaded_directly(self):
        url = "https://example.org/games/latest.pgn"
        with (patch("chess_online._validate_url"),
              patch("chess_online.fetch_text", return_value=LICHESS_PGN) as fetch):
            _, moves, _, _ = chess_input.load_input(url)
        fetch.assert_called_once_with(url)
        self.assertEqual(len(list(moves.mainline_moves())), 4)

    def test_non_https_url_is_rejected_before_network_access(self):
        with self.assertRaises(SystemExit) as error:
            chess_input.load_input("http://example.org/game.pgn")
        self.assertIn("Only public HTTPS URLs", str(error.exception))

    def test_private_network_hosts_are_rejected(self):
        private_address = (2, 1, 6, "", ("10.0.0.1", 443))
        with (
            patch("chess_online.socket.getaddrinfo", return_value=[private_address]),
            patch("chess_online.build_opener") as opener,
            self.assertRaises(ValueError) as error,
        ):
            chess_online.fetch_text("https://private.test/game.pgn")
        self.assertIn("public IP", str(error.exception))
        opener.assert_not_called()


if __name__ == "__main__":
    unittest.main()
