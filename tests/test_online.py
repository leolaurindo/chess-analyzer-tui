import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from chess_analyzer.online import chesscom_games, chesscom_months, fetch_text, lichess_games, load_url


class ProviderTests(unittest.TestCase):
    def test_archive_months_are_sorted_and_foreign_archive_urls_are_rejected(self):
        prefix = "https://api.chess.com/pub/player/Player/games/"
        with patch("chess_analyzer.online.fetch_text", return_value=json.dumps(
                {"archives": [prefix + "2020/01", prefix + "2024/12"]})):
            self.assertEqual(chesscom_months("Player"), ["2024-12", "2020-01"])
        with (patch("chess_analyzer.online.fetch_text", return_value=json.dumps(
                {"archives": ["https://private.test/games/2020/01"]})),
              self.assertRaisesRegex(ValueError, "archive URL")):
            chesscom_months("Player")

    def test_chesscom_lists_only_finished_standard_games_newest_first(self):
        base = {"rules": "chess", "white": {"username": "Alice"},
                "black": {"username": "Bob"}, "time_class": "rapid"}
        games = [base | {"url": "https://www.chess.com/game/live/1", "end_time": 100,
                         "pgn": '[Result "1-0"]\n\n1. e4 e5 1-0'},
                 base | {"url": "https://www.chess.com/game/daily/2", "end_time": 200,
                         "pgn": '[Result "1/2-1/2"]\n\n1. e4 e5 1/2-1/2'},
                 base | {"url": "https://www.chess.com/game/live/3", "end_time": 300,
                         "pgn": '[Result "*"]\n\n1. e4 *'},
                 base | {"rules": "chess960", "end_time": 400}]
        with patch("chess_analyzer.online.fetch_text", return_value=json.dumps({"games": games})):
            listed = chesscom_games("Alice", "2024-01")
        self.assertEqual([game.id for game in listed], ["2", "1"])
        self.assertEqual(listed[0].result, "1/2-1/2")
        self.assertEqual((listed[0].white, listed[0].black), ("Alice", "Bob"))
        self.assertIn("1. e4", listed[0].pgn)

    def test_lichess_page_excludes_ongoing_and_variant_games_and_advances_raw_cursor(self):
        base = {"id": "aabbcc01", "variant": "standard", "status": "mate", "createdAt": 300,
                "speed": "blitz", "winner": "black",
                "players": {"white": {"user": {"name": "Alice"}},
                            "black": {"user": {"name": "Bob"}}}}
        records = [base, base | {"id": "aabbcc02", "status": "started", "createdAt": 200},
                   base | {"id": "aabbcc03", "variant": "atomic", "createdAt": 100},
                   base | {"id": "aabbcc04", "createdAt": 50}]  # Server returned more than requested.
        text = "\n".join(json.dumps(game) for game in records)
        with patch("chess_analyzer.online.fetch_text", return_value=text) as fetch:
            page = lichess_games("Alice", until=400, limit=3)
        self.assertEqual([game.id for game in page.games], ["aabbcc01"])
        self.assertEqual(page.games[0].result, "0-1")
        self.assertEqual(page.until, 99)
        query = parse_qs(urlsplit(fetch.call_args.args[0]).query)
        self.assertEqual(query["ongoing"], ["false"])
        self.assertEqual(query["until"], ["400"])
        self.assertEqual(query["max"], ["3"])
        self.assertEqual(fetch.call_args.kwargs["accept"], "application/x-ndjson")
        with patch("chess_analyzer.online.fetch_text", return_value=""):
            self.assertIsNone(lichess_games("Alice", until=99).until)

    def test_invalid_parameters_do_not_issue_requests_and_not_found_is_explicit(self):
        with patch("chess_analyzer.online.fetch_text") as fetch:
            for load in (lambda: chesscom_months("../Alice"),
                         lambda: chesscom_games("Alice", "2024-99"),
                         lambda: lichess_games("Alice", limit=1000)):
                with self.assertRaises(ValueError):
                    load()
            fetch.assert_not_called()
        with (patch("chess_analyzer.online._validate_url"),
              patch("chess_analyzer.online.fetch_text", side_effect=[
                  json.dumps({"game": {"pgnHeaders": {"Date": "2024.01.01", "White": "Alice"}}}), ""]),
              self.assertRaisesRegex(ValueError, "Game not found")):
            load_url("https://www.chess.com/game/live/1")

    def test_rate_limit_is_reported_without_automatic_retry(self):
        error = HTTPError("https://lichess.org", 429, "Too many requests", {}, None)
        with (patch("chess_analyzer.online._validate_url"),
              patch("chess_analyzer.online.build_opener") as opener,
              self.assertRaisesRegex(ValueError, "Wait at least one minute")):
            opener.return_value.open.side_effect = error
            fetch_text("https://lichess.org/api/games/user/Alice")
        opener.return_value.open.assert_called_once()


if __name__ == "__main__":
    unittest.main()
