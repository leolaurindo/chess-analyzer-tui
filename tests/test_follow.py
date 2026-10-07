import json
import threading
import unittest
from unittest.mock import patch

import chess

from chess_analyzer.follow import load_latest_game
from chess_analyzer.online import GamePage


PGN = '[White "Alice"]\n[Black "Bob"]\n[Result "1-0"]\n\n1. e4 e5 2. Nf3 1-0'
FINAL_FEN = "rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2"


def chesscom_record(game_id, end_time, pgn=PGN, rules="chess"):
    return {"url": f"https://www.chess.com/game/live/{game_id}", "end_time": end_time,
            "pgn": pgn, "rules": rules, "white": {"username": "Alice"},
            "black": {"username": "Bob"}, "time_class": "rapid"}


def lichess_record(game_id, created, variant="standard"):
    return {"id": game_id, "createdAt": created, "variant": variant, "status": "resign",
            "winner": "white", "players": {"white": {"user": {"name": "Alice"}},
                                           "black": {"user": {"name": "Bob"}}}}


class LatestGameTests(unittest.TestCase):
    def test_chesscom_falls_back_to_older_archive_and_selects_latest_completed_standard_game(self):
        prefix = "https://api.chess.com/pub/player/Alice/games/"
        responses = {
            prefix + "archives": json.dumps({"archives": [prefix + "2024/01", prefix + "2024/02"]}),
            prefix + "2024/02": json.dumps({"games": [
                chesscom_record(3, 300, rules="chess960"),
                chesscom_record(4, 400, pgn='[Result "*"]\n\n1. d4 *')]}),
            prefix + "2024/01": json.dumps({"games": [
                chesscom_record(1, 100, pgn='[Result "0-1"]\n\n1. d4 d5 0-1'),
                chesscom_record(2, 200)]}),
        }
        with patch("chess_analyzer.online.fetch_text", side_effect=lambda url, **kw: responses[url]):
            analysis = load_latest_game("chess.com", " Alice ")
        self.assertEqual(analysis.current.board.fen(), FINAL_FEN)
        self.assertEqual((analysis.white_name, analysis.black_name), ("Alice", "Bob"))
        self.assertTrue(analysis.has_pgn)
        self.assertEqual(analysis.root.board.fen(), chess.STARTING_FEN)

    def test_chesscom_stops_at_latest_available_archive(self):
        prefix = "https://api.chess.com/pub/player/Alice/games/"
        responses = {prefix + "archives": json.dumps({"archives": [prefix + "2024/01", prefix + "2024/02"]}),
                     prefix + "2024/02": json.dumps({"games": [chesscom_record(1, 200)]})}
        with patch("chess_analyzer.online.fetch_text", side_effect=lambda url, **kw: responses[url]):
            self.assertEqual(load_latest_game("chess.com", "Alice").current.board.fen(), FINAL_FEN)

    def test_lichess_traverses_empty_filtered_page_then_exports_latest_created_game(self):
        filtered = "\n".join(json.dumps(lichess_record(f"game{i:04d}", 1000 - i, "atomic"))
                             for i in range(50))
        older = "\n".join(json.dumps(record) for record in [
            lichess_record("older001", 900), lichess_record("older002", 800)])
        responses = {"https://lichess.org/game/export/older001": PGN}

        def fetch(url, **kwargs):
            if "/api/games/user/Alice?" in url:
                return older if "until=950" in url else filtered
            return responses[url]

        with patch("chess_analyzer.online.fetch_text", side_effect=fetch):
            analysis = load_latest_game("lichess", "Alice")
        self.assertEqual(analysis.current.board.fen(), FINAL_FEN)
        self.assertEqual(analysis.white_name, "Alice")

    def test_empty_accounts_return_none_without_exporting_a_game(self):
        for provider, response in (("chess.com", '{"archives": []}'), ("lichess", "")):
            with (self.subTest(provider=provider),
                  patch("chess_analyzer.online.fetch_text", return_value=response),
                  patch("chess_analyzer.follow.lichess_pgn") as export):
                self.assertIsNone(load_latest_game(provider, "Alice"))
                export.assert_not_called()
        with patch("chess_analyzer.online.fetch_text", side_effect=[
                '{"archives": ["https://api.chess.com/pub/player/Alice/games/2024/01"]}',
                '{"games": []}']):
            self.assertIsNone(load_latest_game("chess.com", "Alice"))

    def test_invalid_account_is_rejected_before_any_request(self):
        with patch("chess_analyzer.online.fetch_text") as fetch:
            for provider, username in (("other", "Alice"), ([], "Alice"), ("lichess", "../Alice"),
                                       ("lichess", ""), ("chess.com", None)):
                with self.subTest(provider=provider, username=username), self.assertRaises(ValueError):
                    load_latest_game(provider, username)
            fetch.assert_not_called()

    def test_provider_and_export_failures_are_propagated_without_retry(self):
        for response, requests in ((ValueError("Rate limited"), 1), ("not json", 1),
                                   (json.dumps(lichess_record("latest01", 1000)), 2)):
            with (self.subTest(response=response),
                  patch("chess_analyzer.online.fetch_text", side_effect=[response, ValueError("export failed")]) as fetch,
                  self.assertRaises(ValueError)):
                load_latest_game("lichess", "Alice")
            self.assertEqual(fetch.call_count, requests)
        archives = {"archives": ["https://api.chess.com/pub/player/Alice/games/2024/01",
                                 "https://api.chess.com/pub/player/Alice/games/2024/02"]}
        with (patch("chess_analyzer.online.fetch_text", side_effect=[
                json.dumps(archives), ValueError("archive failed")]) as fetch,
              self.assertRaisesRegex(ValueError, "archive failed")):
            load_latest_game("chess.com", "Alice")
        self.assertEqual(fetch.call_count, 2)

    def test_export_must_be_parseable_completed_standard_chess_with_valid_board(self):
        record = json.dumps(lichess_record("latest01", 1000))
        invalid = [("", "contain PGN"),
                   ('[Result "*"]\n\n1. e4 *', "not completed"),
                   ('[Variant "Atomic"]\n' + PGN, "not standard chess"),
                   ('[Variant "Chess960"]\n' + PGN, "not standard chess"),
                   ('[FEN "8/8/8/8/8/8/8/8 w - - 0 1"]\n[Result "1-0"]\n\n1-0', "invalid"),
                   ('[Result "1-0"]\n\n1. e5 1-0', "Could not parse")]
        for pgn, message in invalid:
            with (self.subTest(pgn=pgn),
                  patch("chess_analyzer.online.fetch_text", side_effect=[record, pgn]),
                  self.assertRaisesRegex(ValueError, message)):
                load_latest_game("lichess", "Alice")
        with patch("chess_analyzer.online.fetch_text", side_effect=[record, '[Result "1/2-1/2"]\n\n1/2-1/2']):
            self.assertEqual(load_latest_game("lichess", "Alice").current.board.fen(), chess.STARTING_FEN)

    def test_non_advancing_filtered_cursor_does_not_loop_forever(self):
        with (patch("chess_analyzer.follow.lichess_games", return_value=GamePage([], 100)),
              self.assertRaisesRegex(ValueError, "non-advancing")):
            load_latest_game("lichess", "Alice")

    def test_pre_cancelled_load_never_issues_a_request(self):
        cancelled = threading.Event()
        cancelled.set()
        with patch("chess_analyzer.online.fetch_text") as fetch:
            self.assertIsNone(load_latest_game("lichess", "Alice", cancelled=cancelled))
            fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
